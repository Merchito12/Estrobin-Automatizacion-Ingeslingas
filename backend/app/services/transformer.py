"""Extracción y normalización de registros a partir de una hoja de origen.

El archivo de entrada es solo una FUENTE DE DATOS: aquí se leen sus valores, se
normalizan y se derivan los campos fijos (tipo, país, plazo, vencimiento). La
salida jamás hereda estructura ni formato del archivo de entrada.
"""
from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from datetime import date, timedelta
from typing import Any

from ..models import EMPTY, INVALID, OK, WARNING, Issue, Record
from ..profile import Profile
from ..utils.nit import NitError, normalize_nit
from ..utils.parsing import (
    AmountError,
    DateParseError,
    parse_amount_ex,
    parse_date_ex,
    parse_int_ex,
)
from ..utils.text import MONTHS_ES, clean_name, is_blank, to_text
from .file_reader import SourceSheet
from .mapping import MappingResult

EXAMPLE_ROWS = 3


@dataclass
class ExtractionStats:
    scanned_rows: int = 0
    empty_rows: int = 0
    total_rows: int = 0


@dataclass
class ExtractionResult:
    records: list[Record] = field(default_factory=list)
    warnings: list[Issue] = field(default_factory=list)
    stats: ExtractionStats = field(default_factory=ExtractionStats)


def _cell(row: list[Any], index: int | None) -> Any:
    if index is None or index >= len(row):
        return None
    return row[index]


def _optional_text(value: Any) -> str | None:
    text = to_text(value).strip()
    return text or None


def _examples(rows: list[int]) -> str:
    shown = ", ".join(str(r) for r in rows[:EXAMPLE_ROWS])
    return shown + ("…" if len(rows) > EXAMPLE_ROWS else "")


def extract_records(sheet: SourceSheet, mapping: MappingResult, profile: Profile) -> ExtractionResult:
    result = ExtractionResult()
    idx = {key: mapping.source_index(key) for key in mapping.matches}
    nit_match = mapping.matches.get("nit")
    nit_spec = profile.column("nit")
    assume_dv = True if nit_match and _norm_header(nit_match.source_header) in nit_spec.assume_dv_headers else None

    offset = timedelta(days=int(profile.rules["due_offset_days"]))
    term_days = int(profile.constants["term_days"])
    due_mismatch_rows: list[int] = []
    term_mismatch_rows: list[int] = []
    # Claves que cuentan para decidir si una fila está vacía o es de totales.
    content_keys = ("nit", "name", "invoice", "issue_date", "amount", "solunion_code",
                    "debtor_reference", "payment_condition")

    for position in range(mapping.header_index + 1, len(sheet.rows)):
        row = sheet.rows[position]
        result.stats.scanned_rows += 1
        excel_row = position + 1

        values = {key: _cell(row, idx.get(key)) for key in content_keys if key in idx}
        if all(is_blank(v) for v in values.values()):
            result.stats.empty_rows += 1
            continue
        identity = ("nit", "name", "invoice", "issue_date")
        if all(is_blank(values.get(key)) for key in identity) and not is_blank(values.get("amount")):
            result.stats.total_rows += 1   # fila de totales/subtotales de HELISA
            continue

        record = Record(source_row=excel_row, raw=dict(values))
        record.document_type = str(profile.constants["document_type"])
        record.country = str(profile.constants["country"])
        record.term = term_days

        _parse_nit(record, values.get("nit"), assume_dv, result)
        _parse_name_invoice(record, values)
        _parse_issue_date(record, values.get("issue_date"), result)
        _parse_amount(record, values.get("amount"), result)
        record.solunion_code = _optional_text(values.get("solunion_code"))
        record.debtor_reference = _optional_text(values.get("debtor_reference"))
        record.payment_condition = _optional_text(values.get("payment_condition"))

        if record.issue_date is not None:
            record.due_date = record.issue_date + offset
            source_due = _cell(row, idx.get("due_date"))
            if not is_blank(source_due):
                try:
                    if parse_date_ex(source_due)[0] != record.due_date:
                        due_mismatch_rows.append(excel_row)
                except DateParseError:
                    due_mismatch_rows.append(excel_row)
        source_term = _cell(row, idx.get("term"))
        if not is_blank(source_term):
            try:
                if parse_int_ex(source_term) != term_days:
                    term_mismatch_rows.append(excel_row)
            except ValueError:
                term_mismatch_rows.append(excel_row)

        result.records.append(record)

    if due_mismatch_rows:
        result.warnings.append(Issue(
            WARNING, "due_date_replaced",
            f"En {len(due_mismatch_rows)} fila(s) el vencimiento del archivo de origen no era "
            f"emisión + {offset.days} días; se reemplazó por la regla (filas {_examples(due_mismatch_rows)}).",
            column=profile.column("due_date").public_name,
        ))
    if term_mismatch_rows:
        result.warnings.append(Issue(
            WARNING, "term_replaced",
            f"En {len(term_mismatch_rows)} fila(s) el plazo del archivo de origen era distinto de "
            f"{term_days}; se reemplazó por {term_days} (filas {_examples(term_mismatch_rows)}).",
            column=profile.column("term").public_name,
        ))
    return result


def _norm_header(text: str) -> str:
    from ..utils.text import normalize_header
    return normalize_header(text)


def _parse_nit(record: Record, raw: Any, assume_dv: bool | None, result: ExtractionResult) -> None:
    if is_blank(raw):
        record.status["nit"] = EMPTY
        return
    try:
        nit = normalize_nit(raw, assume_dv)
    except NitError as exc:
        record.status["nit"] = INVALID
        record.detail["nit"] = exc.message
        return
    record.nit = nit
    record.status["nit"] = OK
    if nit.dv_corrected:
        result.warnings.append(Issue(
            WARNING, "nit_dv_corrected",
            f"El dígito de verificación del NIT {nit.base} no era correcto; se reemplazó por {nit.dv}.",
            row=record.source_row, column="CÓDIGO DOCUMENTO",
        ))


def _parse_name_invoice(record: Record, values: dict[str, Any]) -> None:
    name = clean_name(to_text(values.get("name")))
    record.name = name
    record.status["name"] = OK if name else EMPTY

    invoice = to_text(values.get("invoice")).strip()
    record.invoice = invoice
    record.status["invoice"] = OK if invoice else EMPTY


def _parse_issue_date(record: Record, raw: Any, result: ExtractionResult) -> None:
    if is_blank(raw):
        record.status["issue_date"] = EMPTY
        return
    try:
        parsed, note = parse_date_ex(raw)
    except DateParseError as exc:
        record.status["issue_date"] = INVALID
        record.detail["issue_date"] = str(exc)
        return
    record.issue_date = parsed
    record.status["issue_date"] = OK
    if note:
        result.warnings.append(Issue(
            WARNING, "date_ambiguous", note[0].upper() + note[1:] + ".",
            row=record.source_row, column="FECHA EMISIÓN",
        ))


def _parse_amount(record: Record, raw: Any, result: ExtractionResult) -> None:
    if is_blank(raw):
        record.status["amount"] = EMPTY
        return
    try:
        amount, note = parse_amount_ex(raw)
    except AmountError as exc:
        record.status["amount"] = INVALID
        record.detail["amount"] = str(exc)
        return
    record.amount = amount
    record.status["amount"] = OK
    if note:
        result.warnings.append(Issue(
            WARNING, "amount_ambiguous", note[0].upper() + note[1:] + ".",
            row=record.source_row, column="VALOR DE LA FACTURA",
        ))


# --------------------------------------------------------------------------- #
# Periodo y nombre del archivo
# --------------------------------------------------------------------------- #
def dominant_period(records: list[Record]) -> tuple[int, int, Counter] | None:
    """(año, mes, conteo por periodo) del mes dominante entre fechas de emisión."""
    counts: Counter = Counter(
        (r.issue_date.year, r.issue_date.month) for r in records if r.issue_date is not None
    )
    if not counts:
        return None
    # Mayor frecuencia; ante empate, el periodo más reciente.
    (year, month), _ = max(counts.items(), key=lambda item: (item[1], item[0]))
    return year, month, counts


def output_filename(records: list[Record], profile: Profile) -> str:
    period = dominant_period(records)
    if period is None:
        return profile.fallback_output_name
    year, month, _ = period
    return f"{profile.output_name_prefix} {MONTHS_ES[month - 1]} {year}.xlsx"


def format_date(value: date | None) -> str:
    return value.strftime("%d/%m/%Y") if value else ""

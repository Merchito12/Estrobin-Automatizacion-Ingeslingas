"""Orquestación: leer → mapear → extraer → validar → reconstruir → verificar."""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field
from decimal import Decimal
from typing import Any

from ..models import ERROR, WARNING, Issue, Record
from ..profile import Profile
from . import changes as changes_service
from . import error_interpreter, excel_writer, mapping, transformer, validator
from .file_reader import FileReadError, read_source
from .jobs import JobStore
from .postprocess import use_shared_strings

logger = logging.getLogger("ingeslingas.pipeline")


@dataclass
class ProcessResult:
    ok: bool
    payload: dict[str, Any]
    http_status: int = 200


def _issue_dicts(issues: list[Issue], limit: int) -> list[dict[str, Any]]:
    return [i.to_dict() for i in issues[:limit]]


def _mapping_public(result: mapping.MappingResult, profile: Profile) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for column in profile.columns:
        match = result.matches.get(column.key)
        if column.role == "constant":
            rows.append({
                "key": column.key, "source": None, "target": column.public_name,
                "confidence": 1.0, "method": "constante", "value": str(column.constant),
            })
        elif column.key == "due_date":
            rows.append({
                "key": column.key, "source": match.source_header if match else None,
                "target": column.public_name, "confidence": 1.0,
                "method": "regla", "value": f"emisión + {profile.rules['due_offset_days']} días",
            })
        elif column.key == "term":
            rows.append({
                "key": column.key, "source": match.source_header if match else None,
                "target": column.public_name, "confidence": 1.0,
                "method": "regla", "value": str(profile.constants["term_days"]),
            })
        elif match:
            rows.append({
                "key": column.key, "source": match.source_header or "(sin encabezado)",
                "sourceColumn": _column_letter(match.source_index),
                "target": column.public_name, "confidence": match.confidence, "method": match.method,
            })
    return rows


def _column_letter(index: int) -> str:
    letters, number = "", index + 1
    while number:
        number, remainder = divmod(number - 1, 26)
        letters = chr(65 + remainder) + letters
    return letters


def _failure(profile: Profile, issues: list[Issue], *, found: int = 0, valid: int = 0,
             mapping_rows: list[dict[str, Any]] | None = None, warnings: list[Issue] | None = None,
             hints: list[dict[str, Any]] | None = None, status: int = 200,
             extra: dict[str, Any] | None = None) -> ProcessResult:
    limit = int(profile.rules["max_issues_returned"])
    errors = [i for i in issues if i.severity == ERROR]
    warns = list(warnings or []) + [i for i in issues if i.severity == WARNING]
    payload: dict[str, Any] = {
        "ok": False,
        "recordsFound": found,
        "validRecords": valid,
        "errors": _issue_dicts(errors, limit),
        "errorCount": len(errors),
        "warnings": _issue_dicts(warns, limit),
        "warningCount": len(warns),
        "mapping": mapping_rows or [],
        "portalErrorHints": hints or [],
    }
    if extra:
        payload.update(extra)
    return ProcessResult(False, payload, status)


def process_upload(data: bytes, extension: str, portal_error: str | None,
                   profile: Profile, store: JobStore) -> ProcessResult:
    started = time.perf_counter()
    hints = error_interpreter.interpret(portal_error, profile)

    try:
        source = read_source(data, extension)
    except FileReadError as exc:
        return _failure(profile, [Issue(ERROR, exc.code, exc.message)], hints=hints, status=422)

    try:
        sheet, header_index = mapping.select_sheet(source.sheets, profile)
    except mapping.MappingError as exc:
        return _failure(profile, [Issue(ERROR, exc.code, exc.message)], hints=hints, status=422)

    column_map = mapping.map_columns(sheet, header_index, profile)
    mapping_rows = _mapping_public(column_map, profile)
    base_extra = {"stats": {"sheet": sheet.name, "headerRow": header_index + 1, "format": source.fmt}}

    if column_map.missing_required:
        missing = [Issue(ERROR, "column_not_found",
                         f"No fue posible identificar automáticamente la columna {name}.", column=name)
                   for name in column_map.missing_required]
        shown = [h for h in column_map.headers if h]
        base_extra["detectedHeaders"] = shown[:40]
        return _failure(profile, missing, mapping_rows=mapping_rows, hints=hints, status=200, extra=base_extra)

    extraction = transformer.extract_records(sheet, column_map, profile)
    records = extraction.records
    base_extra["stats"].update({
        "skippedEmptyRows": extraction.stats.empty_rows,
        "skippedTotalRows": extraction.stats.total_rows,
    })

    issues = validator.validate_data(records, profile) + validator.validate_rules(records, profile)
    all_warnings = extraction.warnings + [i for i in issues if i.severity == WARNING]
    errors = [i for i in issues if i.severity == ERROR]
    bad_rows = {i.row for i in errors if i.row is not None}
    valid_records = [r for r in records if r.source_row not in bad_rows]

    if not records:
        return _failure(profile, [Issue(ERROR, "no_records",
                                        "No se encontraron facturas para procesar en el archivo.")],
                        mapping_rows=mapping_rows, hints=hints, extra=base_extra)

    if errors:
        return _failure(profile, errors, found=len(records), valid=len(valid_records),
                        mapping_rows=mapping_rows, warnings=extraction.warnings
                        + [i for i in issues if i.severity == WARNING],
                        hints=hints, extra=base_extra)

    # Periodo dominante, nombre y totales (Decimal exacto).
    total = sum((r.amount for r in records if r.amount is not None), Decimal(0))
    dates = [r.issue_date for r in records if r.issue_date is not None]
    period = transformer.dominant_period(records)
    if period and len(period[2]) > 1:
        names = ", ".join(f"{transformer.MONTHS_ES[m - 1].title()} {y} ({n})"
                          for (y, m), n in sorted(period[2].items()))
        all_warnings.append(Issue(
            WARNING, "multiple_periods",
            f"Las fechas de emisión abarcan varios periodos: {names}. "
            f"El nombre del archivo usa el periodo dominante."))
    output_name = transformer.output_filename(records, profile)

    job = store.create()
    try:
        excel_writer.build_workbook(records, profile, job.output_path)
        use_shared_strings(job.output_path)
        problems = validator.verify_workbook(job.output_path, records, profile, total)
    except excel_writer.TemplateError as exc:
        store.delete(job.job_id)
        logger.error("Plantilla inválida: %s", exc)
        return _failure(profile, [Issue(ERROR, "template", f"Error interno de plantilla: {exc}")],
                        found=len(records), valid=len(records), mapping_rows=mapping_rows,
                        hints=hints, status=500, extra=base_extra)
    except Exception:
        store.delete(job.job_id)
        logger.exception("Fallo inesperado al construir el Excel")
        return _failure(profile, [Issue(ERROR, "build_failed",
                                        "Ocurrió un error interno al generar el archivo. Intenta nuevamente.")],
                        found=len(records), valid=len(records), mapping_rows=mapping_rows,
                        hints=hints, status=500, extra=base_extra)

    if problems:
        store.delete(job.job_id)
        logger.error("Validación del workbook final falló con %d problema(s): %s", len(problems), problems[:3])
        detail = [Issue(ERROR, "workbook_validation", f"Validación interna del archivo final: {p}") for p in problems]
        return _failure(profile, detail, found=len(records), valid=len(records),
                        mapping_rows=mapping_rows, hints=hints, status=500, extra=base_extra)

    store.commit(job, output_name)
    limit = int(profile.rules["max_issues_returned"])
    preview_n = int(profile.rules["preview_rows"])
    logger.info("Procesado OK: registros=%d periodo=%s duración=%.2fs job=%s",
                len(records), output_name, time.perf_counter() - started, job.job_id)

    payload = {
        "ok": True,
        "jobId": job.job_id,
        "outputFilename": output_name,
        "recordsFound": len(records),
        "validRecords": len(valid_records),
        "warnings": _issue_dicts(all_warnings, limit),
        "warningCount": len(all_warnings),
        "errors": [],
        "errorCount": 0,
        "mapping": mapping_rows,
        "portalErrorHints": hints,
        "changes": changes_service.summarize_changes(records, extraction.stats, profile),
        "summary": {
            "totalValue": float(total),
            "totalValueText": format(total, "f"),
            "minDate": transformer.format_date(min(dates)) if dates else None,
            "maxDate": transformer.format_date(max(dates)) if dates else None,
            "period": _period_label(period),
        },
        "preview": [_preview_row(r) for r in records[:preview_n]],
        "expiresInMinutes": store.ttl_seconds // 60,
        **base_extra,
    }
    return ProcessResult(True, payload)


def _period_label(period: tuple[int, int, Any] | None) -> str | None:
    if period is None:
        return None
    year, month, _ = period
    return f"{transformer.MONTHS_ES[month - 1]} {year}"


def _preview_row(record: Record) -> dict[str, Any]:
    return {
        "factura": record.invoice,
        "cliente": record.name,
        "nit": record.nit.full if record.nit else "",
        "emision": transformer.format_date(record.issue_date),
        "vencimiento": transformer.format_date(record.due_date),
        "plazo": record.term,
        "valor": float(record.amount) if record.amount is not None else None,
    }


__all__ = ["ProcessResult", "process_upload"]

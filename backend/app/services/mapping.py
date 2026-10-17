"""Detección de la fila de encabezados y mapeo automático de columnas.

Estrategia (determinística, sin LLM):
  1. Normalización de encabezados (minúsculas, sin acentos, solo [a-z0-9]).
  2. Alias conocidos del perfil (coincidencia exacta o por tokens).
  3. Similitud de texto (difflib) como respaldo.
  4. Inferencia por contenido SOLO para fechas de emisión sin encabezado
     (p. ej. HELISA entrega esa columna sin título).
"""
from __future__ import annotations

from dataclasses import dataclass, field
from difflib import SequenceMatcher
from statistics import mean
from typing import Any

from ..profile import ColumnSpec, Profile
from ..utils.parsing import DateParseError, looks_like_date_text, parse_date_ex
from ..utils.text import is_blank, normalize_header
from .file_reader import SourceSheet

FUZZY_MIN_RATIO = 0.88
CONTENT_SAMPLE_ROWS = 500


class MappingError(Exception):
    """No fue posible ubicar encabezados o columnas obligatorias."""

    def __init__(self, message: str, code: str = "mapping") -> None:
        super().__init__(message)
        self.message = message
        self.code = code


@dataclass
class ColumnMatch:
    key: str
    target: str                  # nombre público de la columna de destino
    source_index: int            # índice 0-based de la columna de origen
    source_header: str           # texto original del encabezado ("" si no tenía)
    confidence: float            # 0..1
    method: str                  # alias | similitud | contenido


@dataclass
class MappingResult:
    sheet_name: str
    header_index: int            # índice 0-based de la fila de encabezados
    headers: list[str]
    matches: dict[str, ColumnMatch] = field(default_factory=dict)
    missing_required: list[str] = field(default_factory=list)

    def source_index(self, key: str) -> int | None:
        match = self.matches.get(key)
        return match.source_index if match else None


# --------------------------------------------------------------------------- #
# Puntuación de encabezados
# --------------------------------------------------------------------------- #
@dataclass(frozen=True)
class HeaderScore:
    rank: float          # puntaje con desempate por prioridad de alias
    confidence: float    # confianza mostrada al usuario (0..1)
    kind: str            # alias | similitud
    alias_index: int


NO_MATCH = HeaderScore(0.0, 0.0, "", -1)


def score_header(header_norm: str, column: ColumnSpec) -> HeaderScore:
    """Mejor coincidencia de ``header_norm`` contra los alias de ``column``.

    El desempate por prioridad de alias evita ambigüedades entre alias equivalentes
    (p. ej. "Vr Neto" frente a "Valor").
    """
    if not header_norm:
        return NO_MATCH
    header_tokens = header_norm.split()
    header_set = set(header_tokens)
    best = NO_MATCH
    for idx, alias in enumerate(column.aliases):
        alias_tokens = alias.split()
        alias_set = set(alias_tokens)
        if header_norm == alias:
            confidence, kind = 1.0, "alias"
        elif len(alias_tokens) >= 2 and alias_set <= header_set \
                and len(header_tokens) <= len(alias_tokens) + 2:
            confidence, kind = 0.9, "alias"
        elif len(header_tokens) >= 2 and header_set <= alias_set \
                and len(alias_tokens) <= len(header_tokens) + 2:
            confidence, kind = 0.88, "alias"
        else:
            ratio = SequenceMatcher(None, header_norm, alias).ratio()
            if ratio < FUZZY_MIN_RATIO:
                continue
            confidence, kind = round(ratio, 2), "similitud"
        rank = confidence - idx * 0.0005
        if rank > best.rank:
            best = HeaderScore(rank, confidence, kind, idx)
    return best


def _targets(profile: Profile) -> list[ColumnSpec]:
    return [c for c in profile.columns if c.maps_from_source]


# --------------------------------------------------------------------------- #
# Fila de encabezados
# --------------------------------------------------------------------------- #
def _row_score(row: list[Any], profile: Profile) -> tuple[float, int]:
    """(puntaje, columnas obligatorias distintas) de una fila candidata a encabezado."""
    threshold = float(profile.rules["alias_accept_threshold"])
    cells = [(i, normalize_header(v)) for i, v in enumerate(row) if not is_blank(v)]
    candidates: list[tuple[float, str, int]] = []
    for column in _targets(profile):
        for idx, norm in cells:
            found = score_header(norm, column)
            if found.confidence >= threshold:
                candidates.append((found.rank, column.key, idx))
    candidates.sort(reverse=True)
    used_cells: set[int] = set()
    used_keys: set[str] = set()
    total, required = 0.0, 0
    for score, key, idx in candidates:
        if key in used_keys or idx in used_cells:
            continue
        used_keys.add(key)
        used_cells.add(idx)
        if profile.column(key).required:
            required += 1
            total += 1.0
        else:
            total += 0.25
    return total, required


def detect_header_row(rows: list[list[Any]], profile: Profile) -> tuple[int, float]:
    """Índice 0-based de la mejor fila de encabezados y su puntaje, o MappingError."""
    scan = int(profile.rules["header_scan_rows"])
    minimum = int(profile.rules["min_required_in_header"])
    best_index, best_score, best_required = -1, 0.0, 0
    for index, row in enumerate(rows[:scan]):
        if not row:
            continue
        score, required = _row_score(row, profile)
        if score > best_score:
            best_index, best_score, best_required = index, score, required
    if best_index < 0 or best_required < minimum:
        raise MappingError(
            "No fue posible ubicar la fila de encabezados en las primeras "
            f"{scan} filas del archivo. Verifica que incluya columnas como NIT/identificación, "
            "nombre del cliente, número de factura, fecha y valor."
        )
    return best_index, best_score


def select_sheet(sheets: list[SourceSheet], profile: Profile) -> tuple[SourceSheet, int]:
    """Elige la hoja (y su fila de encabezados) con mayor coincidencia con el perfil."""
    best: tuple[float, int, SourceSheet] | None = None
    for sheet in sheets:
        if not sheet.rows:
            continue
        try:
            index, score = detect_header_row(sheet.rows, profile)
        except MappingError:
            continue
        rank = (score, len(sheet.rows))
        if best is None or rank > (best[0], len(best[2].rows)):
            best = (score, index, sheet)
    if best is None:
        raise MappingError(
            "No se encontró ninguna hoja con encabezados reconocibles. Se esperan columnas como "
            "NIT/identificación, cliente, número de factura, fecha y valor."
        )
    return best[2], best[1]


# --------------------------------------------------------------------------- #
# Mapeo de columnas
# --------------------------------------------------------------------------- #
def map_columns(sheet: SourceSheet, header_index: int, profile: Profile) -> MappingResult:
    header_row = sheet.rows[header_index]
    width = max((len(r) for r in sheet.rows[header_index:]), default=len(header_row))
    headers = [("" if i >= len(header_row) or header_row[i] is None else str(header_row[i]).strip())
               for i in range(width)]
    result = MappingResult(sheet.name, header_index, headers)

    threshold = float(profile.rules["alias_accept_threshold"])
    scored: list[tuple[HeaderScore, str, int]] = []
    for column in _targets(profile):
        for idx, header in enumerate(headers):
            found = score_header(normalize_header(header), column)
            if found.confidence >= threshold:
                scored.append((found, column.key, idx))
    scored.sort(key=lambda item: (-item[0].rank, item[2]))

    used_cols: set[int] = set()
    for found, key, idx in scored:
        if key in result.matches or idx in used_cols:
            continue
        column = profile.column(key)
        result.matches[key] = ColumnMatch(
            key=key,
            target=column.public_name,
            source_index=idx,
            source_header=headers[idx],
            confidence=found.confidence,
            method=found.kind,
        )
        used_cols.add(idx)

    _reject_issue_date_without_dates(sheet, result, used_cols)
    _infer_issue_date_by_content(sheet, result, profile, used_cols)

    result.missing_required = [
        profile.column(key).public_name
        for key in profile.required_keys
        if key not in result.matches
    ]
    return result


def _plausible_date_cell(value: Any) -> bool:
    """Fecha explícita o serial de Excel plausible (años ~1982-2064)."""
    if looks_like_date_text(value):
        return True
    return (isinstance(value, (int, float)) and not isinstance(value, bool)
            and 30000 <= float(value) <= 60000)


def _reject_issue_date_without_dates(sheet: SourceSheet, result: MappingResult, used_cols: set[int]) -> None:
    """Descarta la columna de fecha elegida por encabezado si su contenido no son fechas.

    Caso real: HELISA deja el encabezado "Fecha" sobre la columna marcadora ("+") y las
    fechas quedan en la columna siguiente, sin título. Así se libera la columna para que
    la inferencia por contenido encuentre la correcta.
    """
    match = result.matches.get("issue_date")
    if match is None or match.method == "contenido":
        return
    body = sheet.rows[result.header_index + 1: result.header_index + 1 + CONTENT_SAMPLE_ROWS]
    values = [row[match.source_index] for row in body
              if match.source_index < len(row) and not is_blank(row[match.source_index])]
    if not values:
        return
    valid = sum(1 for v in values if _plausible_date_cell(v))
    if valid / len(values) < 0.5:
        del result.matches["issue_date"]
        used_cols.discard(match.source_index)


def _infer_issue_date_by_content(
    sheet: SourceSheet, result: MappingResult, profile: Profile, used_cols: set[int]
) -> None:
    """HELISA entrega la fecha de la factura en una columna sin encabezado."""
    key = "issue_date"
    if key in result.matches:
        return
    body = sheet.rows[result.header_index + 1: result.header_index + 1 + CONTENT_SAMPLE_ROWS]
    width = len(result.headers)
    candidates: list[tuple[float, int, float]] = []   # (fracción, columna, promedio ordinal)
    for col in range(width):
        if col in used_cols:
            continue
        values = [row[col] for row in body if col < len(row) and not is_blank(row[col])]
        if not values:
            continue
        valid = [v for v in values if looks_like_date_text(v)]
        fraction = len(valid) / len(values)
        if fraction >= 0.8:
            ordinals: list[int] = []
            for v in valid:
                try:
                    ordinals.append(parse_date_ex(v)[0].toordinal())
                except DateParseError:
                    continue
            if ordinals:
                candidates.append((fraction, col, mean(ordinals)))
    if not candidates:
        return

    min_confidence = float(profile.rules["content_accept_threshold"])
    if len(candidates) == 1:
        fraction, col, _ = candidates[0]
        confidence = min(0.9, 0.5 + 0.4 * fraction)
    else:
        # Varias columnas de fecha sin encabezado: la emisión es la más antigua.
        fraction, col, _ = min(candidates, key=lambda c: c[2])
        confidence = 0.6
    if confidence < min_confidence:
        return
    column = profile.column(key)
    result.matches[key] = ColumnMatch(
        key=key,
        target=column.public_name,
        source_index=col,
        source_header=result.headers[col] if col < len(result.headers) else "",
        confidence=round(confidence, 2),
        method="contenido",
    )
    used_cols.add(col)

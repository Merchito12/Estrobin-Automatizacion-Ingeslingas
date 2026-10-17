"""Parseo robusto de importes y fechas (formato colombiano por defecto)."""
from __future__ import annotations

import math
import re
from datetime import date, datetime, timedelta
from decimal import Decimal, InvalidOperation
from typing import Any

from .text import MONTH_LOOKUP, strip_accents

MIN_YEAR = 2000
MAX_YEAR = 2100
_EXCEL_EPOCH = date(1899, 12, 30)
# Rango de seriales Excel razonable para MIN_YEAR..MAX_YEAR.
_SERIAL_MIN = (date(MIN_YEAR, 1, 1) - _EXCEL_EPOCH).days
_SERIAL_MAX = (date(MAX_YEAR, 12, 31) - _EXCEL_EPOCH).days


class AmountError(ValueError):
    pass


class DateParseError(ValueError):
    pass


# --------------------------------------------------------------------------- #
# Importes
# --------------------------------------------------------------------------- #
_CURRENCY_TOKENS = re.compile(r"(?i)(?:col\$|m/?cte|pesos?|cop)|[$€£]")
_WHITESPACE = re.compile(r"[\s  ]+")
_SCIENTIFIC = re.compile(r"[0-9]+(?:\.[0-9]+)?[eE][+-]?[0-9]+")
_AMOUNT_CHARS = re.compile(r"[0-9.,]+")


def _group_ok(int_part: str, sep: str) -> bool:
    groups = int_part.split(sep)
    if not groups[0] or not groups[0].isascii() or not groups[0].isdigit() or len(groups[0]) > 3:
        return False
    return all(len(g) == 3 and g.isascii() and g.isdigit() for g in groups[1:])


def parse_amount_ex(value: Any) -> tuple[Decimal, str | None]:
    """Convierte ``value`` en Decimal exacto. Devuelve (importe, nota|None).

    Formatos soportados: ``1234567.89``, ``1,234,567.89``, ``1.234.567,89``,
    ``$ 1.234.567,89``, ``(1.234,56)``, ``-1.234,56``, ``1.2E+7``, enteros y floats
    de Excel. La nota solo se genera cuando la lectura era ambigua.
    """
    if value is None or isinstance(value, bool):
        raise AmountError("valor vacío o no numérico")
    if isinstance(value, Decimal):
        if not value.is_finite():
            raise AmountError("valor no finito")
        return value, None
    if isinstance(value, int):
        return Decimal(value), None
    if isinstance(value, float):
        if not math.isfinite(value):
            raise AmountError("valor no finito")
        exact = Decimal(repr(value))
        rounded = round(value, 2)
        # Limpia solo el ruido binario (12592437.199999999 -> 12592437.2).
        if abs(value - rounded) < 1e-6 and Decimal(repr(rounded)) != exact:
            return Decimal(repr(rounded)), None
        return exact, None

    text = _WHITESPACE.sub("", str(value))
    text = _CURRENCY_TOKENS.sub("", text)
    if not text:
        raise AmountError("valor vacío")

    negative = False
    if text.startswith("(") and text.endswith(")"):
        negative, text = True, text[1:-1]
    if text.endswith("-") and not text.startswith("-"):
        negative, text = True, text[:-1]
    if text.startswith("-"):
        negative, text = True, text[1:]
    elif text.startswith("+"):
        text = text[1:]

    if _SCIENTIFIC.fullmatch(text):
        try:
            number = Decimal(text)
        except InvalidOperation as exc:
            raise AmountError("notación científica inválida") from exc
        return (-number if negative else number), None

    if not text or not _AMOUNT_CHARS.fullmatch(text) or not any(c.isdigit() for c in text):
        raise AmountError(f"formato no reconocido: {value!r}")

    note: str | None = None
    dots, commas = text.count("."), text.count(",")

    if dots and commas:
        decimal_sep = "." if text.rfind(".") > text.rfind(",") else ","
        thousands_sep = "," if decimal_sep == "." else "."
        int_part, _, frac = text.rpartition(decimal_sep)
        if thousands_sep in frac or decimal_sep in int_part or not _group_ok(int_part, thousands_sep):
            raise AmountError(f"separadores inconsistentes: {value!r}")
        int_digits = int_part.replace(thousands_sep, "")
    elif dots or commas:
        sep = "." if dots else ","
        if text.count(sep) > 1:
            if not _group_ok(text, sep):
                raise AmountError(f"separadores inconsistentes: {value!r}")
            int_digits, frac = text.replace(sep, ""), ""
        else:
            int_part, _, frac = text.partition(sep)
            if len(frac) == 3 and 1 <= len(int_part) <= 3 and int_part != "0":
                # "1.234" / "1,234": separador de miles (convención colombiana).
                int_digits, frac = int_part + frac, ""
                note = f"valor ambiguo '{value}' interpretado como {int_digits}"
            else:
                int_digits = int_part or "0"
    else:
        int_digits, frac = text, ""

    if not int_digits:
        int_digits = "0"
    try:
        number = Decimal(f"{int_digits}.{frac}" if frac else int_digits)
    except InvalidOperation as exc:
        raise AmountError(f"formato no reconocido: {value!r}") from exc
    return (-number if negative else number), note


def parse_amount(value: Any) -> Decimal:
    return parse_amount_ex(value)[0]


# --------------------------------------------------------------------------- #
# Fechas
# --------------------------------------------------------------------------- #
_YMD = re.compile(r"(\d{4})[-/.](\d{1,2})[-/.](\d{1,2})(?:[ T].*)?")
_DMY = re.compile(r"(\d{1,2})[-/.](\d{1,2})[-/.](\d{2,4})(?:[ T,].*)?")
_COMPACT = re.compile(r"\d{8}")
_SERIAL_TEXT = re.compile(r"\d{5}(?:\.\d+)?")
_DAY_MONTH_YEAR_TEXT = re.compile(
    r"(\d{1,2})[\s\-/.]*(?:de\s+)?([a-z]{3,10})\.?,?[\s\-/.]*(?:de\s+|del\s+)?(\d{2,4})"
)
_MONTH_DAY_YEAR_TEXT = re.compile(r"([a-z]{3,10})\.?\s+(\d{1,2}),?\s+(\d{4})")


def _build(year: int, month: int, day: int) -> date:
    if year < 100:
        year += 2000 if year < 70 else 1900
    if not (MIN_YEAR <= year <= MAX_YEAR):
        raise DateParseError(f"año fuera de rango: {year}")
    try:
        return date(year, month, day)
    except ValueError as exc:
        raise DateParseError(str(exc)) from exc


def _from_serial(number: float) -> date:
    if not _SERIAL_MIN <= number <= _SERIAL_MAX:
        raise DateParseError(f"serial de Excel fuera de rango: {number}")
    return _EXCEL_EPOCH + timedelta(days=int(number))


def parse_date_ex(value: Any) -> tuple[date, str | None]:
    """Convierte ``value`` en ``date``. Prioriza día/mes/año (Colombia).

    Devuelve (fecha, nota|None). Lanza ``DateParseError`` si no es una fecha válida.
    """
    if value is None or isinstance(value, bool):
        raise DateParseError("fecha vacía")
    if isinstance(value, datetime):
        return _build(value.year, value.month, value.day), None
    if isinstance(value, date):
        return _build(value.year, value.month, value.day), None
    if isinstance(value, (int, float)):
        if isinstance(value, float) and not math.isfinite(value):
            raise DateParseError("fecha no finita")
        return _from_serial(float(value)), None

    text = str(value).strip()
    if not text:
        raise DateParseError("fecha vacía")

    match = _YMD.fullmatch(text)
    if match:
        year, month, day = (int(g) for g in match.groups())
        return _build(year, month, day), None

    match = _DMY.fullmatch(text)
    if match:
        first, second, year = (int(g) for g in match.groups())
        try:
            return _build(year, second, first), None  # día/mes/año
        except DateParseError:
            if second > 12 >= first:
                # Solo puede ser mes/día/año (p. ej. 1/13/2026).
                parsed = _build(year, first, second)
                return parsed, f"fecha '{text}' interpretada como mes/día/año"
            raise

    if _COMPACT.fullmatch(text):
        if 1990 <= int(text[:4]) <= MAX_YEAR:
            return _build(int(text[:4]), int(text[4:6]), int(text[6:8])), None
        return _build(int(text[4:]), int(text[2:4]), int(text[:2])), None

    if _SERIAL_TEXT.fullmatch(text):
        return _from_serial(float(text)), None

    lowered = strip_accents(text).lower()
    match = _DAY_MONTH_YEAR_TEXT.fullmatch(lowered)
    if match and match.group(2) in MONTH_LOOKUP:
        return _build(int(match.group(3)), MONTH_LOOKUP[match.group(2)], int(match.group(1))), None
    match = _MONTH_DAY_YEAR_TEXT.fullmatch(lowered)
    if match and match.group(1) in MONTH_LOOKUP:
        return _build(int(match.group(3)), MONTH_LOOKUP[match.group(1)], int(match.group(2))), None

    raise DateParseError(f"formato de fecha no reconocido: {value!r}")


def parse_date(value: Any) -> date:
    return parse_date_ex(value)[0]


def looks_like_date_text(value: Any) -> bool:
    """True si ``value`` es fecha explícita (objeto fecha o texto con formato de fecha).

    Los números sueltos NO cuentan: un importe como 46204 no debe confundirse con
    un serial de Excel al inferir columnas por contenido.
    """
    if isinstance(value, (datetime, date)):
        return True
    if not isinstance(value, str):
        return False
    text = value.strip()
    if not text or text.isdigit():
        return False
    try:
        parse_date_ex(text)
    except DateParseError:
        return False
    return True


def parse_int_ex(value: Any) -> int:
    """Entero a partir de número o texto ('90', '90.0'). Lanza ValueError si no aplica."""
    if value is None or isinstance(value, bool):
        raise ValueError("valor no entero")
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        if value.is_integer():
            return int(value)
        raise ValueError("valor no entero")
    text = str(value).strip()
    if re.fullmatch(r"[+-]?\d+(?:\.0+)?", text):
        return int(float(text))
    raise ValueError("valor no entero")

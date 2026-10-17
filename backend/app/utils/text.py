"""Utilidades de texto: normalización de encabezados y limpieza segura."""
from __future__ import annotations

import re
import unicodedata
from typing import Any

MONTHS_ES = (
    "ENERO", "FEBRERO", "MARZO", "ABRIL", "MAYO", "JUNIO",
    "JULIO", "AGOSTO", "SEPTIEMBRE", "OCTUBRE", "NOVIEMBRE", "DICIEMBRE",
)

# Nombre de mes (sin acentos, minúscula) -> número. Incluye abreviaturas comunes.
MONTH_LOOKUP: dict[str, int] = {}
for _i, _name in enumerate(MONTHS_ES, start=1):
    _low = _name.lower()
    MONTH_LOOKUP[_low] = _i
    MONTH_LOOKUP[_low[:3]] = _i
MONTH_LOOKUP.update({"sept": 9, "set": 9, "ago": 8, "dic": 12, "ene": 1, "abr": 4})
# Abreviaturas en inglés que no colisionan con las españolas.
MONTH_LOOKUP.update({"jan": 1, "apr": 4, "aug": 8, "dec": 12})

_CONTROL_RE = re.compile(r"[\x00-\x1f\x7f]")


def strip_accents(text: str) -> str:
    decomposed = unicodedata.normalize("NFKD", text)
    return "".join(ch for ch in decomposed if not unicodedata.combining(ch))


def normalize_header(value: Any) -> str:
    """Minúsculas, sin acentos, solo [a-z0-9] separados por un espacio."""
    if value is None:
        return ""
    text = strip_accents(str(value)).lower()
    return re.sub(r"[^a-z0-9]+", " ", text).strip()


def is_blank(value: Any) -> bool:
    if value is None:
        return True
    if isinstance(value, str):
        return value.strip() == ""
    return False


def to_text(value: Any) -> str:
    """Convierte un valor de celda a texto sin perder identificadores.

    Los números enteros que Excel entrega como float (800141506.0) se escriben
    sin decimales; el resto se convierte con ``str``.
    """
    if value is None:
        return ""
    if isinstance(value, bool):
        return str(value)
    if isinstance(value, float):
        if value.is_integer() and abs(value) < 1e15:
            return str(int(value))
        return repr(value)
    return str(value).strip()


def clean_name(value: Any) -> str:
    """Solo elimina espacios (incluido NBSP) al inicio y al final."""
    if value is None:
        return ""
    return str(value).strip()


def safe_display_name(filename: str | None, max_len: int = 120) -> str:
    """Nombre apto para mostrar/loggear. Nunca se usa como ruta de archivo."""
    if not filename:
        return "archivo"
    base = filename.replace("\\", "/").rsplit("/", 1)[-1]
    base = _CONTROL_RE.sub("", base).strip()
    return base[:max_len] or "archivo"

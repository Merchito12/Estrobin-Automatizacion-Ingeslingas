"""Interpreta el mensaje de error que mostró la plataforma destino.

El texto es SOLO una pista adicional: las reglas de transformación se aplican
siempre, aunque el usuario deje el campo vacío. Cada pista describe una
corrección que el sistema realmente aplica sobre el archivo nuevo.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any

from ..profile import Profile
from ..utils.text import strip_accents

MAX_MESSAGE_CHARS = 4000


@dataclass(frozen=True)
class _Rule:
    code: str
    title: str
    detail: str
    pattern: re.Pattern


def _rx(*words: str) -> re.Pattern:
    return re.compile("|".join(words))


_RULES: tuple[_Rule, ...] = (
    _Rule(
        "dates", "Fechas reales de Excel",
        "FECHA EMISIÓN y FECHA VENCIMIENTO se escriben como fechas reales de Excel (no texto ni "
        "números sueltos) con el formato de fecha de la plantilla aceptada, en todas las filas.",
        _rx(r"fecha corta", r"tipo fecha", r"formato de fecha", r"formato fecha", r"\bfecha\b", r"\bdate\b"),
    ),
    _Rule(
        "due_date", "Vencimiento = emisión + 90 días",
        "FECHA VENCIMIENTO se calcula siempre como FECHA EMISIÓN + 90 días y se guarda como valor "
        "de fecha, sin depender de fórmulas del archivo de origen.",
        _rx(r"vencimiento", r"g\s*\d+\s*\+\s*90", r"90\s*dias", r"\+\s*90"),
    ),
    _Rule(
        "formulas", "Sin fórmulas",
        "Las fórmulas del archivo de origen no se ejecutan ni se copian: el archivo nuevo se "
        "reconstruye con valores calculados directamente.",
        _rx(r"formula"),
    ),
    _Rule(
        "nit", "NIT / documento normalizado",
        "CÓDIGO DOCUMENTO se limpia (sin puntos, espacios ni guiones), se valida el dígito de "
        "verificación colombiano y se escribe como texto con el DV incluido.",
        _rx(r"\bnit\b", r"documento", r"identificacion", r"\bdv\b", r"digito de verificacion"),
    ),
    _Rule(
        "numbers", "Valores numéricos reales",
        "VALOR DE LA FACTURA y PLAZO DE VENTA se escriben como números reales de Excel, sin "
        "símbolos de moneda ni separadores de miles como texto.",
        _rx(r"\bvalor\b", r"moneda", r"\bpeso", r"\bnumero\b", r"numerico", r"\bnumber\b"),
    ),
    _Rule(
        "structure", "Estructura de la plantilla oficial",
        "El archivo se reconstruye siempre desde la plantilla base aceptada: mismas hojas, "
        "encabezados, orden de columnas y formatos.",
        _rx(r"estructura", r"columnas?\b", r"encabezado", r"plantilla", r"hoja"),
    ),
)

_COLUMN_REF = re.compile(r"columna\s+([a-z]{1,2})\b")
_ROW_REF = re.compile(r"fila\s+(\d+)")


def interpret(portal_error: str | None, profile: Profile) -> list[dict[str, Any]]:
    """Devuelve las correcciones reforzadas según el texto del error (lista vacía si no hay texto)."""
    if portal_error is None:
        return []
    text = portal_error.strip()[:MAX_MESSAGE_CHARS]
    if not text:
        return []

    normalized = strip_accents(text).lower()
    hints: list[dict[str, Any]] = []
    seen: set[str] = set()
    for rule in _RULES:
        if rule.pattern.search(normalized) and rule.code not in seen:
            seen.add(rule.code)
            hints.append({"code": rule.code, "title": rule.title, "detail": rule.detail})

    letters = {m.group(1).upper() for m in _COLUMN_REF.finditer(normalized)}
    columns_by_letter = {c.letter: c for c in profile.columns}
    mentioned = [columns_by_letter[l].public_name for l in sorted(letters) if l in columns_by_letter]
    rows = sorted({int(m.group(1)) for m in _ROW_REF.finditer(normalized)})
    if mentioned or rows:
        parts = []
        if mentioned:
            parts.append("columna(s) " + ", ".join(
                f"{l} ({columns_by_letter[l].public_name})" for l in sorted(letters) if l in columns_by_letter))
        if rows:
            parts.append("fila(s) " + ", ".join(str(r) for r in rows[:10]))
        hints.append({
            "code": "reference",
            "title": "Referencia indicada por la plataforma",
            "detail": "La plataforma mencionó " + " y ".join(parts) +
                      ". Todas las filas del archivo nuevo se escriben con las mismas reglas, no solo esas.",
        })

    if not hints:
        hints.append({
            "code": "generic",
            "title": "Mensaje recibido",
            "detail": "No se reconocieron palabras clave en el mensaje; igualmente se aplicaron todas "
                      "las reglas de la plantilla oficial.",
        })
    return hints

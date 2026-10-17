"""NIT colombiano: limpieza, detección y cálculo del dígito de verificación (DV).

Algoritmo oficial DIAN: cada dígito del NIT (de derecha a izquierda) se
multiplica por la secuencia de primos 3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47,
53, 59, 67, 71; la suma módulo 11 da el residuo ``r``; el DV es ``r`` si
``r`` < 2 y ``11 - r`` en otro caso.

Toda la lógica del DV vive en este módulo y está cubierta por tests.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from decimal import Decimal, InvalidOperation
from typing import Any

WEIGHTS: tuple[int, ...] = (3, 7, 13, 17, 19, 23, 29, 37, 41, 43, 47, 53, 59, 67, 71)
MIN_BASE_LEN = 5
MAX_BASE_LEN = 15

_ASCII_DIGITS = re.compile(r"[0-9]+")
_NIT_PREFIX = re.compile(r"^\s*n\s*\.?\s*i\s*\.?\s*t\s*\.?\s*[:#]?\s*", re.IGNORECASE)
_EXPLICIT_DV = re.compile(r"(.+?)\s*[-–—]\s*([0-9])")
_SCIENTIFIC = re.compile(r"[0-9]+(?:\.[0-9]+)?[eE]\+?[0-9]+")
_TRAILING_ZERO_DECIMALS = re.compile(r"([0-9]+)\.0+")
_ALLOWED_CHARS = re.compile(r"[0-9.,\s\-–—]*")


class NitError(ValueError):
    """Error de NIT con un código estable para los mensajes al usuario."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code
        self.message = message


@dataclass(frozen=True)
class NitResult:
    base: str          # dígitos sin DV
    dv: int            # dígito de verificación final (siempre el calculado)
    full: str          # base + dv, sin separadores (formato aceptado en julio)
    had_dv: bool       # el valor de entrada ya incluía DV
    dv_corrected: bool  # el DV de entrada era incorrecto y se reemplazó


def compute_dv(base: str) -> int:
    """Dígito de verificación DIAN para ``base`` (solo dígitos ASCII)."""
    if not _ASCII_DIGITS.fullmatch(base or ""):
        raise ValueError("La base del NIT solo puede contener dígitos")
    if len(base) > len(WEIGHTS):
        raise ValueError("La base del NIT excede 15 dígitos")
    total = sum(int(d) * w for d, w in zip(reversed(base), WEIGHTS))
    remainder = total % 11
    return remainder if remainder < 2 else 11 - remainder


def is_valid_with_dv(full: str) -> bool:
    """True si el último dígito de ``full`` es el DV correcto del resto."""
    if not _ASCII_DIGITS.fullmatch(full or "") or not MIN_BASE_LEN + 1 <= len(full) <= MAX_BASE_LEN + 1:
        return False
    return compute_dv(full[:-1]) == int(full[-1])


def _raw_to_text(raw: Any) -> str:
    if raw is None or isinstance(raw, bool):
        raise NitError("empty" if raw is None else "invalid", "NIT/documento vacío o inválido")
    if isinstance(raw, int):
        return str(raw)
    if isinstance(raw, (float, Decimal)):
        try:
            as_decimal = Decimal(repr(raw)) if isinstance(raw, float) else raw
        except InvalidOperation as exc:  # pragma: no cover - defensivo
            raise NitError("invalid", "el valor no es numérico") from exc
        if as_decimal != as_decimal.to_integral_value():
            raise NitError("invalid", "el NIT no puede tener decimales")
        return str(int(as_decimal))
    return str(raw).strip()


def normalize_nit(raw: Any, assume_dv: bool | None = None) -> NitResult:
    """Normaliza un NIT y garantiza que el resultado incluya un DV correcto.

    ``assume_dv``:
      * ``True``  -> el valor viene de una columna que normalmente incluye DV
        (por ejemplo "CÓDIGO DOCUMENTO" de un archivo rechazado). Con 10+ dígitos
        el último es el DV: si no coincide con el calculado se recalcula
        (``dv_corrected``). Con menos de 10 dígitos solo se considera DV si es válido;
        de lo contrario el valor se toma como base sin DV.
      * ``False`` -> el valor nunca incluye DV (se calcula siempre).
      * ``None``  -> heurística: guion explícito ("901.233.957-1") o 10+ dígitos
        cuyo último dígito es el DV correcto se consideran con DV; en cualquier
        otro caso se calcula.
    """
    text = _raw_to_text(raw)
    if not text:
        raise NitError("empty", "NIT/documento vacío")

    text = _NIT_PREFIX.sub("", text).strip()
    if not text:
        raise NitError("empty", "NIT/documento vacío")

    if _SCIENTIFIC.fullmatch(text):
        try:
            text = str(int(Decimal(text)))
        except (InvalidOperation, ValueError) as exc:
            raise NitError("invalid", "notación científica inválida") from exc
    trailing = _TRAILING_ZERO_DECIMALS.fullmatch(text)
    if trailing:
        text = trailing.group(1)

    if not _ALLOWED_CHARS.fullmatch(text):
        raise NitError("invalid_chars", "contiene caracteres distintos de dígitos, puntos y guion")

    explicit = _EXPLICIT_DV.fullmatch(text)
    if explicit:
        base = re.sub(r"\D", "", explicit.group(1))
        given_dv: int | None = int(explicit.group(2))
        digits = base + str(given_dv)
    else:
        digits = re.sub(r"\D", "", text)
        base = digits
        given_dv = None

    if not digits:
        raise NitError("empty", "NIT/documento vacío")

    # Con guion explícito la base ya está separada del DV.
    if given_dv is not None:
        _check_base_length(base)
        calculated = compute_dv(base)
        return NitResult(base, calculated, base + str(calculated), True, calculated != given_dv)

    if assume_dv is True:
        # Columna "CÓDIGO DOCUMENTO": los NIT empresariales (9 dígitos) llevan 1 dígito de DV.
        if len(digits) >= 10:
            if is_valid_with_dv(digits):
                return NitResult(digits[:-1], int(digits[-1]), digits, True, False)
            base = digits[:-1]
            _check_base_length(base)
            calculated = compute_dv(base)
            return NitResult(base, calculated, base + str(calculated), True, True)
        if is_valid_with_dv(digits):
            return NitResult(digits[:-1], int(digits[-1]), digits, True, False)
        # Menos de 10 dígitos y sin DV válido: es la base sin DV (error típico al armar el archivo a mano).
        _check_base_length(digits)
        calculated = compute_dv(digits)
        return NitResult(digits, calculated, digits + str(calculated), False, False)

    if assume_dv is None and len(digits) >= 10 and is_valid_with_dv(digits):
        return NitResult(digits[:-1], int(digits[-1]), digits, True, False)

    _check_base_length(digits)
    calculated = compute_dv(digits)
    return NitResult(digits, calculated, digits + str(calculated), False, False)


def _check_base_length(base: str) -> None:
    if len(base) < MIN_BASE_LEN:
        raise NitError("length", f"tiene muy pocos dígitos ({len(base)})")
    if len(base) > MAX_BASE_LEN:
        raise NitError("length", f"tiene demasiados dígitos ({len(base)})")

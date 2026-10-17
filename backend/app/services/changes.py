"""Resumen de los cambios que se hicieron al archivo de origen.

Se calcula comparando los valores crudos de cada fila con los normalizados.
Solo se informan cambios que realmente ocurrieron (cuenta > 0); todo en español
claro para el usuario final.
"""
from __future__ import annotations

import re
from datetime import date, datetime
from typing import Any

from ..models import Record
from ..profile import Profile
from ..utils.text import is_blank, to_text
from .transformer import ExtractionStats

_NON_DIGIT = re.compile(r"\D")


def _plural(count: int, singular: str, plural: str) -> str:
    return singular if count == 1 else plural


def _item(code: str, title: str, count: int | None = None, detail: str | None = None) -> dict[str, Any]:
    return {"code": code, "title": title, "count": count, "detail": detail}


def summarize_changes(records: list[Record], stats: ExtractionStats, profile: Profile) -> list[dict[str, Any]]:
    total = len(records)
    offset = int(profile.rules["due_offset_days"])
    term = int(profile.constants["term_days"])

    nit_dv_added = nit_dv_fixed = nit_cleaned = 0
    names_trimmed = dates_converted = amounts_converted = 0
    with_date = 0

    for rec in records:
        if rec.nit is not None:
            if rec.nit.dv_corrected:
                nit_dv_fixed += 1
            elif not rec.nit.had_dv:
                nit_dv_added += 1
            raw_nit = rec.raw.get("nit")
            if not is_blank(raw_nit) and _NON_DIGIT.search(to_text(raw_nit).strip()):
                nit_cleaned += 1

        raw_name = rec.raw.get("name")
        if isinstance(raw_name, str) and raw_name != raw_name.strip():
            names_trimmed += 1

        raw_date = rec.raw.get("issue_date")
        if rec.issue_date is not None:
            with_date += 1
            if not is_blank(raw_date) and not isinstance(raw_date, (datetime, date)):
                dates_converted += 1

        raw_amount = rec.raw.get("amount")
        if rec.amount is not None and isinstance(raw_amount, str):
            amounts_converted += 1

    changes: list[dict[str, Any]] = [
        _item("rebuilt", "Archivo reconstruido sobre la plantilla oficial aceptada",
              detail="Se conservan las hojas, los encabezados, el orden de columnas y los formatos de la plantilla; "
                     "del archivo cargado solo se toman los datos."),
    ]

    if nit_dv_added:
        changes.append(_item(
            "nit_dv_added", "Dígito de verificación agregado al NIT", nit_dv_added,
            "Se calculó con el algoritmo de la DIAN y quedó junto al NIT en CÓDIGO DOCUMENTO."))
    if nit_dv_fixed:
        changes.append(_item(
            "nit_dv_fixed", "Dígito de verificación corregido", nit_dv_fixed,
            "El dígito que traía el archivo no coincidía con el NIT; se reemplazó por el correcto."))
    if nit_cleaned:
        changes.append(_item(
            "nit_cleaned", "NIT limpiado y guardado como texto", nit_cleaned,
            "Se quitaron puntos, guiones, espacios o prefijos para dejar solo dígitos."))
    if names_trimmed:
        changes.append(_item(
            "names_trimmed", "Espacios sobrantes eliminados en el nombre del cliente", names_trimmed,
            "Solo se recortó el inicio y el final; el nombre no se modificó de ninguna otra forma."))
    if dates_converted:
        changes.append(_item(
            "dates_converted", "Fecha de emisión convertida a fecha real de Excel", dates_converted,
            "Venían como texto o número; ahora son fechas con el formato de la plantilla."))
    if with_date:
        changes.append(_item(
            "due_date", f"Fecha de vencimiento calculada: emisión + {offset} días", with_date,
            "Se escribe como fecha real de Excel en todas las facturas."))
    if amounts_converted:
        changes.append(_item(
            "amounts_converted", "Valor de la factura convertido a número", amounts_converted,
            "Venía como texto; ahora es un número exacto, sin símbolos ni separadores."))
    if total:
        changes.append(_item(
            "constants", f"TIPO DOCUMENTO = nitco, PAÍS = co y PLAZO DE VENTA = {term}", total,
            "Valores fijos que exige la plataforma para cada factura."))

    skipped = []
    if stats.total_rows:
        skipped.append(f"{stats.total_rows} {_plural(stats.total_rows, 'fila de totales', 'filas de totales')}")
    if stats.empty_rows:
        skipped.append(f"{stats.empty_rows} {_plural(stats.empty_rows, 'fila vacía', 'filas vacías')}")
    if skipped:
        changes.append(_item(
            "rows_skipped", "Filas del archivo original que no se incluyeron",
            stats.total_rows + stats.empty_rows,
            " y ".join(skipped).capitalize() + ": no son facturas."))

    return changes

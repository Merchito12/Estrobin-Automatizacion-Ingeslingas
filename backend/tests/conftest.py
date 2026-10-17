"""Fixtures compartidas. Los datos sintéticos usan nombres inventados; los archivos
reales (si existen en tests/fixtures/) solo alimentan las pruebas de regresión."""
from __future__ import annotations

import io
from datetime import date
from pathlib import Path

import openpyxl
import pytest

from app.profile import get_profile
from app.services.file_reader import SourceSheet
from app.services.jobs import JobStore

FIXTURES_DIR = Path(__file__).parent / "fixtures"
HELISA_FIXTURE = FIXTURES_DIR / "VENTAS HELISA JULIO 2026.xls"
GOLDEN_FIXTURE = FIXTURES_DIR / "PlantillaDeclaracionVentas JULIO 2026.xlsx"

HELISA_HEADER = ["}", None, "Doc. Fuente", "Modal. Pago Crédito", "Beneficiario Identidad",
                 "Beneficiario Nombre", "Vr Neto"]
SYNTHETIC_CLIENTS = [
    ("900123456", "CLIENTE UNO S.A.S."),
    ("800222333", "COMERCIAL DOS LTDA"),
    ("890333023", "INDUSTRIAS TRES S.A."),
]


@pytest.fixture(scope="session")
def profile():
    return get_profile()


@pytest.fixture
def store(tmp_path):
    return JobStore(tmp_path / "jobs", ttl_seconds=1800)


def helisa_rows(count: int = 5, month: int = 7, year: int = 2026) -> list[list]:
    """Tabla estilo HELISA: encabezado sin título de fecha, filas vacías y totales."""
    rows: list[list] = [list(HELISA_HEADER)]
    for i in range(count):
        nit, name = SYNTHETIC_CLIENTS[i % len(SYNTHETIC_CLIENTS)]
        rows.append(["+", f"{year}/{month:02d}/{i + 1:02d}", f"FECV{17000 + i}", 1000.5 * (i + 1),
                     nit, name, 1000000 + i * 12345.67])
        rows.append([None] * 7)
    rows.append([None, None, None, None, None, None, sum(r[6] for r in rows if r[0] == "+")])
    return rows


def sheet_from(rows: list[list], name: str = "Consulta") -> SourceSheet:
    return SourceSheet(name, rows)


def make_xlsx(rows: list[list], sheet: str = "Hoja1", extra_sheets: dict[str, list[list]] | None = None) -> bytes:
    workbook = openpyxl.Workbook()
    worksheet = workbook.active
    worksheet.title = sheet
    for row in rows:
        worksheet.append(row)
    for name, content in (extra_sheets or {}).items():
        other = workbook.create_sheet(name)
        for row in content:
            other.append(row)
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def simple_rows(dates=None, amounts=None, nits=None, invoices=None) -> list[list]:
    """Tabla mínima con encabezados estándar para pruebas de parseo."""
    header = ["NIT", "Cliente", "Número factura", "Fecha factura", "Valor Neto"]
    dates = dates or [date(2026, 8, 3)]
    count = len(dates)
    amounts = amounts or [1000 + i for i in range(count)]
    nits = nits or ["900123456"] * count
    invoices = invoices or [f"FE{i + 1}" for i in range(count)]
    rows = [header]
    for i in range(count):
        rows.append([nits[i], f"CLIENTE {i + 1}", invoices[i], dates[i], amounts[i]])
    return rows

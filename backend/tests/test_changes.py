"""Lista de cambios que se muestra al usuario tras procesar un archivo."""
from datetime import date

from app.services.pipeline import process_upload
from tests.conftest import helisa_rows, make_xlsx, simple_rows


def _changes(profile, store, rows, sheet="Consulta"):
    result = process_upload(make_xlsx(rows, sheet), ".xlsx", None, profile, store)
    assert result.ok, result.payload["errors"]
    return {c["code"]: c for c in result.payload["changes"]}


def test_helisa_changes_are_reported_with_counts(profile, store):
    changes = _changes(profile, store, helisa_rows(4))
    assert changes["rebuilt"]["count"] is None
    assert changes["nit_dv_added"]["count"] == 4          # los NIT de HELISA no traen DV
    assert changes["dates_converted"]["count"] == 4       # fechas en texto "2026/07/01"
    assert changes["due_date"]["count"] == 4
    assert changes["constants"]["count"] == 4
    assert changes["rows_skipped"]["count"] == 4 + 1      # 4 filas vacías + 1 fila de totales
    assert "amounts_converted" not in changes             # los valores ya eran numéricos


def test_only_real_changes_are_listed(profile, store):
    rows = simple_rows(dates=[date(2026, 8, 3)], nits=["900123456-8"], amounts=[1000])
    changes = _changes(profile, store, rows, "Hoja")
    assert "dates_converted" not in changes               # ya era una fecha real
    assert "nit_dv_added" not in changes                  # el DV venía y era correcto
    assert "names_trimmed" not in changes and "amounts_converted" not in changes


def test_trimmed_names_and_text_amounts_are_counted(profile, store):
    rows = simple_rows(dates=[date(2026, 8, 3), date(2026, 8, 4)], amounts=["1.234.567,89", "2000"])
    rows[1][1] = "  CLIENTE UNO  "
    changes = _changes(profile, store, rows, "Hoja")
    assert changes["names_trimmed"]["count"] == 1
    assert changes["amounts_converted"]["count"] == 2

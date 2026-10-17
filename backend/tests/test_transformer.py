from datetime import date, timedelta
from decimal import Decimal

from app.models import ERROR, WARNING
from app.services import transformer, validator
from app.services.mapping import detect_header_row, map_columns
from tests.conftest import helisa_rows, sheet_from, simple_rows


def _extract(rows, profile):
    sheet = sheet_from(rows)
    index, _ = detect_header_row(rows, profile)
    mapping = map_columns(sheet, index, profile)
    return transformer.extract_records(sheet, mapping, profile)


def _issues(extraction, profile):
    return validator.validate_data(extraction.records, profile) + validator.validate_rules(extraction.records, profile)


def test_helisa_like_extraction_skips_blank_and_total_rows(profile):
    extraction = _extract(helisa_rows(5), profile)
    assert len(extraction.records) == 5
    assert extraction.stats.empty_rows == 5
    assert extraction.stats.total_rows == 1
    first = extraction.records[0]
    assert first.nit.full == "9001234561" or first.nit.full.startswith("900123456")
    assert first.issue_date == date(2026, 7, 1)
    assert first.invoice == "FECV17000"


def test_due_date_is_always_issue_plus_90_and_fixed_values(profile):
    extraction = _extract(helisa_rows(5), profile)
    for rec in extraction.records:
        assert rec.due_date - rec.issue_date == timedelta(days=90)
        assert (rec.document_type, rec.country, rec.term) == ("nitco", "co", 90)
        assert isinstance(rec.term, int) and not isinstance(rec.term, bool)
    assert _issues(extraction, profile) == []


def test_source_due_date_is_overridden_with_warning(profile):
    rows = [["NIT", "Cliente", "Factura", "Fecha", "Vencimiento", "Plazo", "Vr Neto"],
            ["900123456", "ACME", "F1", "01/07/2026", "01/08/2026", 30, 100]]
    extraction = _extract(rows, profile)
    rec = extraction.records[0]
    assert rec.due_date == date(2026, 9, 29)       # 1-jul + 90 días, NO el vencimiento del origen
    assert rec.term == 90
    codes = {w.code for w in extraction.warnings}
    assert {"due_date_replaced", "term_replaced"} <= codes
    assert all(w.severity == WARNING for w in extraction.warnings)


def test_string_dates_excel_serials_and_colombian_amounts(profile):
    rows = [["NIT", "Cliente", "Factura", "Fecha factura", "Valor Neto"],
            ["900.123.456", "A", "F1", "01/07/2026", "$ 1.234.567,89"],
            ["800222333-5", " B ", "F2", 46204, "1,234,567.89"],
            [890333023, "C", "F3", date(2026, 7, 3), "1234567.89"],
            ["900123456", "D", "F4", "2026-07-04", 761926.06]]
    extraction = _extract(rows, profile)
    assert _issues(extraction, profile) == []
    dates = [r.issue_date for r in extraction.records]
    assert dates == [date(2026, 7, 1), date(2026, 7, 1), date(2026, 7, 3), date(2026, 7, 4)]
    assert [r.amount for r in extraction.records] == [
        Decimal("1234567.89"), Decimal("1234567.89"), Decimal("1234567.89"), Decimal("761926.06")]
    assert extraction.records[1].name == "B"                  # solo se recortan espacios
    assert extraction.records[0].nit.full == "9001234560" or extraction.records[0].nit.base == "900123456"


def test_empty_required_fields_report_row_numbers(profile):
    rows = [["NIT", "Cliente", "Factura", "Fecha", "Vr Neto"],
            [None, "A", "F1", "01/07/2026", 10],
            ["900123456", "", "F2", "01/07/2026", 10],
            ["900123456", "C", "", "01/07/2026", 10],
            ["900123456", "D", "F4", None, 10],
            ["900123456", "E", "F5", "01/07/2026", None]]
    issues = _issues(_extract(rows, profile), profile)
    by_code = {i.code: i.row for i in issues}
    assert by_code == {"nit_empty": 2, "name_empty": 3, "invoice_empty": 4, "date_empty": 5, "amount_empty": 6}
    assert all(i.severity == ERROR for i in issues)


def test_invalid_values_are_errors(profile):
    rows = [["NIT", "Cliente", "Factura", "Fecha", "Vr Neto"],
            ["ABC", "A", "F1", "01/07/2026", 10],
            ["900123456", "B", "F2", "31/02/2026", 10],
            ["900123456", "C", "F3", "01/07/2026", "abc"]]
    codes = sorted(i.code for i in _issues(_extract(rows, profile), profile))
    assert codes == ["amount_invalid", "date_invalid", "nit_invalid"]


def test_duplicate_invoices_are_errors_and_never_dropped(profile):
    rows = [["NIT", "Cliente", "Factura", "Fecha", "Vr Neto"],
            ["900123456", "A", "FECV1", "01/07/2026", 10],
            ["800222333", "B", "FECV2", "01/07/2026", 20],
            ["900123456", "A", "FECV1", "02/07/2026", 30]]
    extraction = _extract(rows, profile)
    assert len(extraction.records) == 3
    duplicates = [i for i in _issues(extraction, profile) if i.code == "invoice_duplicate"]
    assert len(duplicates) == 1 and duplicates[0].row == 4 and "fila 2" in duplicates[0].message


def test_negative_amount_is_error_and_zero_is_warning(profile):
    rows = [["NIT", "Cliente", "Factura", "Fecha", "Vr Neto"],
            ["900123456", "A", "F1", "01/07/2026", -5],
            ["900123456", "B", "F2", "01/07/2026", 0]]
    issues = {i.code: i.severity for i in _issues(_extract(rows, profile), profile)}
    assert issues == {"amount_negative": ERROR, "amount_zero": WARNING}


def test_invoice_prefix_and_numeric_invoice_stay_text(profile):
    rows = [["NIT", "Cliente", "Factura", "Fecha", "Vr Neto"],
            ["900123456", "A", "FECV17609", "01/07/2026", 10],
            ["900123456", "B", 17610.0, "01/07/2026", 10]]
    extraction = _extract(rows, profile)
    assert [r.invoice for r in extraction.records] == ["FECV17609", "17610"]


def test_optional_columns_are_none_when_absent(profile):
    extraction = _extract(helisa_rows(2), profile)
    for rec in extraction.records:
        assert rec.solunion_code is None and rec.debtor_reference is None and rec.payment_condition is None


def test_dominant_period_and_filename(profile):
    rows = simple_rows(dates=[date(2026, 8, 3), date(2026, 8, 4), date(2026, 9, 1)])
    extraction = _extract(rows, profile)
    year, month, counts = transformer.dominant_period(extraction.records)
    assert (year, month) == (2026, 8) and len(counts) == 2
    assert transformer.output_filename(extraction.records, profile) == "PlantillaDeclaracionVentas AGOSTO 2026.xlsx"


def test_month_names_in_spanish_uppercase(profile):
    for month, name in [(1, "ENERO"), (9, "SEPTIEMBRE"), (12, "DICIEMBRE")]:
        extraction = _extract(simple_rows(dates=[date(2026, month, 5)]), profile)
        assert transformer.output_filename(extraction.records, profile) == f"PlantillaDeclaracionVentas {name} 2026.xlsx"


def test_fallback_filename_without_dates(profile):
    assert transformer.output_filename([], profile) == "PlantillaDeclaracionVentas CORREGIDA.xlsx"

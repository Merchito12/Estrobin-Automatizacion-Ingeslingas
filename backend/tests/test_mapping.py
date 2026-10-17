import pytest

from app.services.mapping import MappingError, detect_header_row, map_columns, select_sheet
from tests.conftest import HELISA_HEADER, helisa_rows, sheet_from


def _map(rows, profile):
    sheet = sheet_from(rows)
    index, _ = detect_header_row(rows, profile)
    return map_columns(sheet, index, profile)


def test_helisa_headers_and_unlabeled_date_column(profile):
    result = _map(helisa_rows(), profile)
    sources = {k: m.source_header for k, m in result.matches.items()}
    assert sources["nit"] == "Beneficiario Identidad"
    assert sources["name"] == "Beneficiario Nombre"
    assert sources["invoice"] == "Doc. Fuente"
    assert sources["amount"] == "Vr Neto"
    assert result.matches["amount"].confidence == 1.0
    assert result.missing_required == []
    date_match = result.matches["issue_date"]
    assert date_match.method == "contenido" and date_match.source_header == "" and date_match.confidence >= 0.7


def test_modal_pago_credito_is_not_mapped_to_payment_condition(profile):
    result = _map(helisa_rows(), profile)
    assert "payment_condition" not in result.matches
    assert all(m.source_header != "Modal. Pago Crédito" for m in result.matches.values())


@pytest.mark.parametrize("headers", [
    ["Nit", "Cliente", "No. Factura", "Fecha factura", "Vr. Neto"],
    ["N.I.T", "Razón social", "Número de factura", "Fecha emisión", "Valor Neto"],
    ["Identificacion", "Nombre tercero", "Nro factura", "Fecha documento", "Total Neto"],
    ["NIT cliente", "Nombre cliente", "Documento factura", "Fecha elaboración", "Valor de la factura"],
    ["Código tercero", "Tercero", "N° factura", "Fecha", "Neto"],
    ["Numero identificacion", "Razon social", "Factura", "Fecha emision", "Total factura"],
])
def test_known_aliases_map_with_full_confidence(headers, profile):
    rows = [headers, ["900123456", "ACME", "F1", "01/08/2026", 100]]
    result = _map(rows, profile)
    assert result.missing_required == []
    assert all(m.confidence >= 0.88 for m in result.matches.values())


def test_platform_template_headers_are_recognized(profile):
    rows = [profile.headers, ["", "nitco", "9012339571", "ACME", "co", "F1", "01/08/2026", "30/10/2026", 90, 100, "", ""]]
    result = _map(rows, profile)
    assert result.missing_required == []
    assert result.matches["nit"].source_header == "CÓDIGO DOCUMENTO"
    assert result.matches["due_date"].source_header == "FECHA VENCIMIENTO"
    assert result.matches["term"].source_header == "PLAZO DE VENTA"


def test_due_date_column_is_not_taken_as_issue_date(profile):
    rows = [["NIT", "Cliente", "Factura", "Fecha vencimiento", "Fecha", "Vr Neto"],
            ["900123456", "ACME", "F1", "01/10/2026", "01/07/2026", 5]]
    result = _map(rows, profile)
    assert result.matches["issue_date"].source_header == "Fecha"
    assert result.matches["due_date"].source_header == "Fecha vencimiento"


def test_unrelated_date_header_is_not_an_alias(profile):
    rows = [["NIT", "Cliente", "Factura", "Fecha pago", "Vr Neto"], ["900123456", "ACME", "F1", "x", 5]]
    result = _map(rows, profile)
    assert "issue_date" not in result.matches
    assert "FECHA EMISIÓN" in result.missing_required


def test_header_row_is_found_below_title_rows(profile):
    rows = [["REPORTE DE VENTAS"], ["Generado por HELISA"], [], list(HELISA_HEADER),
            ["+", "2026/07/01", "FECV1", 1, "900123456", "ACME", 10]]
    index, _ = detect_header_row(rows, profile)
    assert index == 3


def test_header_row_not_found_raises_clear_error(profile):
    with pytest.raises(MappingError) as info:
        detect_header_row([["a", "b"], [1, 2], [3, 4]], profile)
    assert "encabezados" in info.value.message


def test_missing_required_column_is_reported(profile):
    rows = [["NIT", "Cliente", "Número factura", "Fecha factura"], ["900123456", "ACME", "F1", "01/08/2026"]]
    sheet = sheet_from(rows)
    result = map_columns(sheet, 0, profile)
    assert "VALOR DE LA FACTURA" in result.missing_required


def test_main_sheet_is_selected_among_auxiliary_sheets(profile):
    helper = sheet_from([["Valor a introducir", "Descripción"], ["ad", "Andorra"]], "País")
    main = sheet_from([list(profile.headers), ["", "nitco", "9012339571", "ACME", "co", "F1", "01/08/2026",
                                               "30/10/2026", 90, 100, "", ""]], "Declaración de ventas")
    sheet, index = select_sheet([helper, main], profile)
    assert sheet.name == "Declaración de ventas" and index == 0


def test_each_column_is_assigned_only_once(profile):
    rows = [["NIT", "Nit cliente", "Cliente", "Factura", "Fecha", "Vr Neto"], ["900123456", "900123456", "A", "F", "01/08/2026", 1]]
    result = _map(rows, profile)
    indices = [m.source_index for m in result.matches.values()]
    assert len(indices) == len(set(indices))

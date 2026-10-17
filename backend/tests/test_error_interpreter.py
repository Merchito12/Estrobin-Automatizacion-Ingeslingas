from app.services.error_interpreter import interpret


def codes(text, profile):
    return [h["code"] for h in interpret(text, profile)]


def test_empty_or_missing_message_gives_no_hints(profile):
    assert interpret(None, profile) == []
    assert interpret("   ", profile) == []


def test_real_platform_message(profile):
    text = ("La fila 2 de la columna G está incorrecta, debe quedar en formato fecha corta. "
            "En la columna H existe un campo tipo fórmula G2 + 90.")
    found = codes(text, profile)
    assert {"dates", "due_date", "formulas", "reference"} <= set(found)
    reference = next(h for h in interpret(text, profile) if h["code"] == "reference")
    assert "G (FECHA EMISIÓN)" in reference["detail"] and "H (FECHA VENCIMIENTO)" in reference["detail"]
    assert "2" in reference["detail"]


def test_accents_and_case_are_ignored(profile):
    assert "nit" in codes("EL DÍGITO DE VERIFICACIÓN DEL NIT ES INVÁLIDO", profile)
    assert "numbers" in codes("El VALOR contiene el símbolo de moneda", profile)
    assert "structure" in codes("La estructura de columnas no coincide con la plantilla", profile)


def test_unrecognized_message_is_acknowledged(profile):
    assert codes("algo completamente distinto", profile) == ["generic"]


def test_message_length_is_bounded(profile):
    hints = interpret("fecha " * 5000, profile)
    assert hints and all(len(h["detail"]) < 600 for h in hints)

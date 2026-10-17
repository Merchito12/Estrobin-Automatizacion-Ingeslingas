import pytest

from app.utils.nit import NitError, compute_dv, is_valid_with_dv, normalize_nit


@pytest.mark.parametrize("base, dv", [
    ("901233957", 1),
    ("800166199", 1),
    ("900902497", 2),
    ("890333023", 8),
    ("800197268", 4),   # NIT de la DIAN, referencia pública
])
def test_compute_dv_examples(base, dv):
    assert compute_dv(base) == dv


def test_compute_dv_rejects_non_digits():
    with pytest.raises(ValueError):
        compute_dv("90123A957")
    with pytest.raises(ValueError):
        compute_dv("")


def test_is_valid_with_dv():
    assert is_valid_with_dv("9012339571")
    assert not is_valid_with_dv("9012339572")
    assert not is_valid_with_dv("123")


@pytest.mark.parametrize("raw", [
    "901233957", "901.233.957", " 901 233 957 ", 901233957, 901233957.0, "901233957.0",
    "NIT 901.233.957", "N.I.T. 901233957", "9.01233957E8",
])
def test_normalize_without_dv_calculates_it(raw):
    result = normalize_nit(raw)
    assert result.full == "9012339571"
    assert (result.base, result.dv) == ("901233957", 1)
    assert not result.had_dv


@pytest.mark.parametrize("raw", ["901233957-1", "901.233.957-1", "901233957 - 1", "9012339571", 9012339571])
def test_normalize_with_valid_dv_is_preserved(raw):
    result = normalize_nit(raw)
    assert result.full == "9012339571"
    assert result.had_dv and not result.dv_corrected


def test_wrong_explicit_dv_is_corrected():
    result = normalize_nit("901233957-5")
    assert result.full == "9012339571"
    assert result.had_dv and result.dv_corrected


def test_assume_dv_true_recalculates_invalid_check_digit():
    result = normalize_nit("9012339570", assume_dv=True)
    assert result.full == "9012339571"
    assert result.dv_corrected


def test_assume_dv_false_never_strips_a_digit():
    result = normalize_nit("9012339571", assume_dv=False)
    assert result.base == "9012339571" and not result.had_dv
    assert result.full == "9012339571" + str(compute_dv("9012339571"))


def test_leading_zeros_are_kept_as_text():
    result = normalize_nit("0012345678")
    assert result.full.startswith("00123456")
    assert isinstance(result.full, str)


@pytest.mark.parametrize("raw, code", [
    (None, "empty"), ("", "empty"), ("   ", "empty"),
    ("ABC", "invalid_chars"), ("90123A957", "invalid_chars"), ("12", "length"),
    ("1234567890123456789", "length"), (True, "invalid"), (123.45, "invalid"),
])
def test_invalid_values_raise_nit_error(raw, code):
    with pytest.raises(NitError) as info:
        normalize_nit(raw)
    assert info.value.code == code

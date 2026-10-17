from datetime import date, datetime
from decimal import Decimal

import pytest

from app.utils.parsing import (
    AmountError,
    DateParseError,
    looks_like_date_text,
    parse_amount,
    parse_amount_ex,
    parse_date,
    parse_date_ex,
    parse_int_ex,
)


# ------------------------------- importes ----------------------------------- #
@pytest.mark.parametrize("raw, expected", [
    ("1234567.89", "1234567.89"),
    ("1,234,567.89", "1234567.89"),
    ("1.234.567,89", "1234567.89"),
    ("$ 1.234.567,89", "1234567.89"),
    ("COP 1.234.567,89", "1234567.89"),
    ("$1.234.567", "1234567"),
    ("1,234,567", "1234567"),
    ("12,5", "12.5"),
    ("1234567,89", "1234567.89"),
    ("0.5", "0.5"),
    ("-1.234,56", "-1234.56"),
    ("(1.234,56)", "-1234.56"),
    ("1.234,56-", "-1234.56"),
    ("1.2E+7", "12000000"),
    ("14208600", "14208600"),
    (14208600, "14208600"),
    (761926.06, "761926.06"),
    (Decimal("10.10"), "10.10"),
])
def test_parse_amount(raw, expected):
    assert parse_amount(raw) == Decimal(expected)


def test_float_noise_is_cleaned_but_real_decimals_are_kept():
    assert parse_amount(12592437.199999999) == Decimal("12592437.2")
    assert parse_amount(100.123) == Decimal("100.123")


def test_ambiguous_single_separator_adds_note():
    value, note = parse_amount_ex("1.234")
    assert value == Decimal("1234") and note
    value, note = parse_amount_ex("1234.56")
    assert value == Decimal("1234.56") and note is None


def test_decimals_are_exact_and_total_has_no_float_error():
    values = ["0.1", "0.2", "0.3"]
    assert sum((parse_amount(v) for v in values), Decimal(0)) == Decimal("0.6")


@pytest.mark.parametrize("raw", ["abc", "", "   ", None, True, "1.2.3,4.5", "12a", "--5", float("nan"), "1,23,456"])
def test_parse_amount_invalid(raw):
    with pytest.raises(AmountError):
        parse_amount(raw)


# -------------------------------- fechas ------------------------------------ #
@pytest.mark.parametrize("raw", [
    "01/07/2026", "1/7/2026", "01-07-2026", "01.07.2026", "2026-07-01", "2026/07/01",
    "2026-07-01 00:00:00", "1 de julio de 2026", "01-jul-2026", "julio 1, 2026", "20260701",
    "01072026", date(2026, 7, 1), datetime(2026, 7, 1, 13, 30), 46204, 46204.0, "46204", "1/7/26",
])
def test_parse_date_gives_first_of_july(raw):
    assert parse_date(raw) == date(2026, 7, 1)


def test_ambiguous_dates_are_day_first_for_colombia():
    assert parse_date("01/07/2026") == date(2026, 7, 1)      # NO 7 de enero
    assert parse_date("03/04/2026") == date(2026, 4, 3)


def test_month_day_year_fallback_only_when_day_first_is_impossible():
    parsed, note = parse_date_ex("1/13/2026")
    assert parsed == date(2026, 1, 13) and note


@pytest.mark.parametrize("raw", ["31/02/2026", "xx", "", None, "13/13/2026", "01/01/1899", 5, 99999999, True, "hola mundo"])
def test_parse_date_invalid(raw):
    with pytest.raises(DateParseError):
        parse_date(raw)


def test_looks_like_date_text_ignores_plain_numbers():
    assert looks_like_date_text("2026/07/01")
    assert looks_like_date_text(date(2026, 7, 1))
    assert not looks_like_date_text(46204)
    assert not looks_like_date_text("46204")
    assert not looks_like_date_text("FECV17609")


@pytest.mark.parametrize("raw, expected", [(90, 90), (90.0, 90), ("90", 90), ("90.0", 90), (" 90 ", 90)])
def test_parse_int(raw, expected):
    assert parse_int_ex(raw) == expected


@pytest.mark.parametrize("raw", [None, "x", 90.5, True, "9.5"])
def test_parse_int_invalid(raw):
    with pytest.raises(ValueError):
        parse_int_ex(raw)

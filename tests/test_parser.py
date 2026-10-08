"""Parser: Interval Data File text -> validated readings."""

from __future__ import annotations

from datetime import datetime
from pathlib import Path

import pytest

from custom_components.synergy_csv.parser import IntervalFileError, parse_interval_file

FIXTURES = Path(__file__).parent / "fixtures"
HEADER = "Date,Time,ANYTIME (KWH),Solar export (Units),Billing Status\n"


def test_parses_canonical_file() -> None:
    parsed = parse_interval_file(
        HEADER + "01/06/2026,00:00,0.207,0.000,Billed\n01/06/2026,00:30,0.199,1.500,Billed\n"
    )

    assert parsed.names == {"anytime": "ANYTIME", "solar_export": "Solar export"}
    assert parsed.readings["anytime"] == {
        datetime(2026, 6, 1, 0, 0): 0.207,
        datetime(2026, 6, 1, 0, 30): 0.199,
    }
    assert parsed.readings["solar_export"][datetime(2026, 6, 1, 0, 30)] == 1.5
    assert parsed.ignored_columns == []


def test_tolerates_bom_crlf_blank_lines_and_missing_billing_status() -> None:
    text = "﻿Date,Time,ANYTIME (KWH)\r\n01/06/2026,00:00,0.2\r\n\r\n"

    parsed = parse_interval_file(text)

    assert parsed.readings == {"anytime": {datetime(2026, 6, 1): 0.2}}


def test_registers_are_matched_case_insensitively_and_tariffs_are_generic() -> None:
    text = "date,time,Peak (kwh),Off-Peak (KWH)\n01/06/2026,00:00,0.1,0.2\n"

    parsed = parse_interval_file(text)

    assert parsed.names == {"peak": "Peak", "off_peak": "Off-Peak"}


def test_other_unit_columns_are_ignored_but_reported() -> None:
    text = (
        "Date,Time,ANYTIME (KWH),Reactive (KVARH),Billing Status\n01/06/2026,00:00,0.1,9,Billed\n"
    )

    parsed = parse_interval_file(text)

    assert list(parsed.readings) == ["anytime"]
    assert parsed.ignored_columns == ["Reactive (KVARH)"]


def test_parses_committed_synthetic_fixtures() -> None:
    parsed = parse_interval_file((FIXTURES / "summer_2w.csv").read_text())

    assert set(parsed.readings) == {"anytime", "solar_export"}
    assert len(parsed.readings["anytime"]) == 14 * 48


@pytest.mark.parametrize(
    ("fixture", "line", "fragment"),
    [
        ("invalid_header.csv", None, "Not a Synergy interval data file"),
        ("invalid_no_registers.csv", None, "No energy columns found"),
        ("invalid_column_count.csv", 2, "expected 5 columns"),
        ("invalid_datetime.csv", 2, "invalid date/time"),
        ("invalid_boundary.csv", 2, "not on a 30-minute boundary"),
        ("invalid_value.csv", 2, "invalid value for ANYTIME"),
        ("invalid_negative.csv", 2, "invalid value for ANYTIME"),
        ("invalid_duplicate.csv", 3, "duplicate interval"),
        ("invalid_empty.csv", None, "File contains no readings"),
    ],
)
def test_each_validation_rule_rejects_with_line_number(
    fixture: str, line: int | None, fragment: str
) -> None:
    with pytest.raises(IntervalFileError) as err:
        parse_interval_file((FIXTURES / fixture).read_text())

    assert err.value.line == line
    assert fragment in str(err.value)
    if line is not None:
        assert str(err.value).startswith(f"Line {line}: ")


@pytest.mark.parametrize("bad", ["", "   \n", "\n\n"])
def test_empty_text_is_not_an_interval_file(bad: str) -> None:
    with pytest.raises(IntervalFileError, match="Not a Synergy interval data file"):
        parse_interval_file(bad)


@pytest.mark.parametrize("bad", ["nan", "inf", "-inf", "", " "])
def test_non_finite_or_blank_values_are_rejected(bad: str) -> None:
    with pytest.raises(IntervalFileError, match="invalid value"):
        parse_interval_file(f"Date,Time,ANYTIME (KWH)\n01/06/2026,00:00,{bad}\n")


def test_two_columns_with_the_same_slug_are_rejected() -> None:
    text = "Date,Time,Solar export (Units),Solar-Export (KWH)\n01/06/2026,00:00,1,2\n"

    with pytest.raises(IntervalFileError, match="same name"):
        parse_interval_file(text)

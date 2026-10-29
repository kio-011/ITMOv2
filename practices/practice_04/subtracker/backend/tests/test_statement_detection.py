"""Detection rules checked against the reference statement.

The expected result is the acceptance standard in the agreed contract
(`practices/practice_05/artifacts/contract.md`, section 8).
"""

from datetime import date
from decimal import Decimal
from pathlib import Path

import pytest

from app.services.statement import (
    StatementError,
    detect,
    normalise,
    parse_statement,
)

FIXTURE = Path(__file__).parent / "fixtures" / "statement-sample.csv"
TODAY = date(2026, 10, 29)


@pytest.fixture
def detection():
    parsed = parse_statement(FIXTURE.read_bytes(), "USD")
    return parsed, detect(parsed.operations, TODAY)


def test_one_row_is_skipped_and_the_rest_are_parsed(detection):
    parsed, _ = detection
    assert parsed.rows_total == 38
    assert [(row.line, row.code) for row in parsed.skipped] == [
        (26, "row.amount_missing")
    ]


def test_candidates_match_the_agreed_acceptance_standard(detection):
    _, result = detection
    found = {
        candidate.name: (
            candidate.amount,
            candidate.billing_cycle,
            len(candidate.occurrences),
            candidate.confidence,
            candidate.review,
        )
        for candidate in result.candidates
    }
    assert found == {
        "Adobe Creative Cloud": (Decimal("54.99"), "monthly", 4, 90, False),
        "Claude.ai": (Decimal("20.00"), "monthly", 4, 90, False),
        "Яндекс Плюс": (Decimal("3.49"), "monthly", 4, 90, False),
        "Notion Labs": (Decimal("10.00"), "monthly", 4, 80, False),
        "Spotify": (Decimal("10.99"), "monthly", 4, 80, False),
        "Netflix": (Decimal("17.99"), "monthly", 4, 78, False),
        "VPN Service": (Decimal("19.90"), "custom_days", 2, 40, True),
        "Github Pro Annual": (Decimal("100.00"), "yearly", 1, 30, True),
    }


def test_rejection_reasons(detection):
    """Salary, transfers, one-offs and varying receipts are not subscriptions."""
    _, result = detection
    assert result.rejected == {
        "rejected.inflow": 1,  # SALARY ACME CORP, perfectly periodic
        "rejected.transfer": 1,  # TRANSFER TO IVAN P.
        "rejected.too_few_occurrences": 1,  # UBER TRIP, a single charge
        "rejected.unstable_amount": 2,  # PYATEROCHKA and AMZN MKTP
    }


def test_price_step_keeps_one_candidate_with_the_latest_amount(detection):
    _, result = detection
    netflix = next(c for c in result.candidates if c.name == "Netflix")
    assert netflix.amount_stability == "price_step"
    assert netflix.previous_amount == Decimal("15.49")
    assert netflix.suggested_next_billing_date == date(2026, 11, 2)


def test_single_charge_needs_a_period_marker(detection):
    """GITHUB survives on the word ANNUAL; UBER, with no marker, does not."""
    _, result = detection
    github = next(c for c in result.candidates if c.name.startswith("Github"))
    assert github.cycle_basis == "text"
    assert github.billing_cycle == "yearly"
    assert "Uber" not in {c.name for c in result.candidates}


@pytest.mark.parametrize(
    ("description", "key", "name"),
    [
        ("NETFLIX.COM AMSTERDAM", "netflix", "Netflix"),
        ("SPOTIFY P0A1B2C3", "spotify", "Spotify"),
        ("AMZN MKTP US*2K4L5,MX", "amzn mktp", "Amzn Mktp"),
        ("AMZN MKTP US*9H2P1", "amzn mktp", "Amzn Mktp"),
        ("ЯНДЕКС ПЛЮС ПОДПИСКА", "яндекс плюс", "Яндекс Плюс"),
        ("VPN SERVICE LTD", "vpn service", "VPN Service"),
    ],
)
def test_normalisation(description, key, name):
    result = normalise(description)
    assert (result.key, result.name) == (key, name)


def test_empty_and_malformed_files_are_rejected_whole():
    with pytest.raises(StatementError) as empty:
        parse_statement(b"", "USD")
    assert empty.value.code == "statement.empty"

    with pytest.raises(StatementError) as columns:
        parse_statement(b"a;b;c\n1;2;3\n", "USD")
    assert columns.value.code == "statement.missing_columns"


def test_rows_in_another_currency_are_skipped():
    raw = b"date,description,amount,currency\n2026-07-01,NETFLIX,-15.49,EUR\n"
    parsed = parse_statement(raw, "USD")
    assert parsed.operations == []
    assert parsed.skipped[0].code == "row.currency_mismatch"

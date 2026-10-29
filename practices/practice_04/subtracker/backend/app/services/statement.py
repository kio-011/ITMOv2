"""Statement parsing and subscription detection.

Pure functions: no database access, no FastAPI. The orchestration layer in
``app.services.imports`` turns the result into rows and HTTP responses.

Rules, thresholds and their justification live in the agreed contract
(`practices/practice_05/artifacts/contract.md`) and in the server specification.
"""

import csv
import io
import re
import statistics
from collections import Counter, defaultdict
from dataclasses import dataclass
from datetime import date
from decimal import ROUND_HALF_UP, Decimal, InvalidOperation

RULESET_VERSION = "2026-10-29.2"

MAX_FILE_BYTES = 2 * 1024 * 1024
MAX_DATA_ROWS = 10_000
MAX_SKIPPED_RETURNED = 100
MAX_RAW_LENGTH = 200
MIN_DATE = date(2000, 1, 1)
MAX_DATE = date(2100, 12, 31)
TWO_PLACES = Decimal("0.01")

REQUIRED_COLUMNS = ("date", "description", "amount", "currency")
ENCODINGS = ("utf-8-sig", "utf-8", "cp1251")
DELIMITERS = (",", ";", "\t")

# Tokens dropped from the merchant name: they identify the payment, not the service.
LEGAL_TOKENS = frozenset(
    ["LTD", "INC", "LLC", "CORP", "GMBH", "PLC", "OOO", "ООО", "ИП", "AB", "BV", "SA"]
)
GEO_TOKENS = frozenset(
    ["AMSTERDAM", "MOSCOW", "US", "USA", "EU", "NL", "RU", "GB", "DE", "MX", "FR"]
)
PAYMENT_TOKENS = frozenset(["PAYPAL", "PMNT", "PURCHASE", "DEBIT", "POS", "CARD"])
# Removed from the name but remembered as a subscription signal.
SUBSCRIPTION_TOKENS = frozenset({"SUBSCRIPTION", "ПОДПИСКА"})
# Kept in the name, also count as a signal.
SIGNAL_TOKENS = frozenset({"PLUS", "PRO", "PREMIUM", "CLOUD"})
TRANSFER_PREFIXES = ("transfer", "перевод", "p2p", "card2card", "cash", "atm")

# Closed list: a token outside it is not a period marker (FR-313).
PERIOD_MARKERS: dict[str, str] = {
    "ANNUAL": "yearly",
    "ANNUALLY": "yearly",
    "YEARLY": "yearly",
    "YEAR": "yearly",
    "YR": "yearly",
    "ГОД": "yearly",
    "ГОДОВАЯ": "yearly",
    "ГОДОВОЙ": "yearly",
    "ЕЖЕГОДНО": "yearly",
    "MONTHLY": "monthly",
    "MONTH": "monthly",
    "МЕСЯЧНАЯ": "monthly",
    "ЕЖЕМЕСЯЧНО": "monthly",
    "WEEKLY": "weekly",
    "WEEK": "weekly",
    "ЕЖЕНЕДЕЛЬНО": "weekly",
}

CODE_TOKEN = re.compile(r"^(?=.*\d)[A-Z0-9]{4,}$")
SPLIT_CHARS = re.compile(r"[\s*,/#;]+")


@dataclass(frozen=True)
class Operation:
    """One parsed statement row."""

    line: int
    occurred_on: date
    amount: Decimal  # signed, as in the file
    description: str


@dataclass
class SkippedRow:
    line: int
    code: str
    raw: str


@dataclass
class ParseResult:
    encoding: str
    delimiter: str
    rows_total: int
    operations: list[Operation]
    skipped: list[SkippedRow]


class StatementError(Exception):
    """A whole-file failure: nothing can be analysed."""

    def __init__(self, code: str, **params: object) -> None:
        super().__init__(code)
        self.code = code
        self.params = params


def _decode(raw: bytes) -> tuple[str, str]:
    for encoding in ENCODINGS:
        try:
            return raw.decode(encoding), encoding.removesuffix("-sig")
        except UnicodeDecodeError:
            continue
    raise StatementError("statement.undecodable")


def _detect_delimiter(header_line: str) -> str:
    best = max(DELIMITERS, key=header_line.count)
    if header_line.count(best) == 0:
        raise StatementError("statement.delimiter_unknown")
    return best


def _parse_amount(value: str) -> Decimal:
    cleaned = value.strip().replace(" ", "").replace(" ", "").replace(",", ".")
    amount = Decimal(cleaned)
    if -amount.as_tuple().exponent > 2:
        raise InvalidOperation(cleaned)
    return amount.quantize(TWO_PLACES)


def parse_statement(raw: bytes, currency: str) -> ParseResult:
    """Split the file into usable operations and skipped rows.

    Raises ``StatementError`` only when the file as a whole is unusable; a bad
    single row is reported in ``skipped`` and does not stop the import.
    """
    if not raw:
        raise StatementError("statement.empty")

    text, encoding = _decode(raw)
    lines = text.splitlines()
    if not lines or not lines[0].strip():
        raise StatementError("statement.empty")

    delimiter = _detect_delimiter(lines[0])
    reader = csv.reader(io.StringIO(text), delimiter=delimiter)
    header = [cell.strip().lower() for cell in next(reader, [])]
    missing = [column for column in REQUIRED_COLUMNS if column not in header]
    if missing:
        raise StatementError("statement.missing_columns", missing=missing)

    index = {column: header.index(column) for column in REQUIRED_COLUMNS}
    operations: list[Operation] = []
    skipped: list[SkippedRow] = []
    rows_total = 0

    for offset, row in enumerate(reader, start=2):
        if not any(cell.strip() for cell in row):
            continue
        rows_total += 1
        if rows_total > MAX_DATA_ROWS:
            raise StatementError(
                "statement.too_many_rows", limit=MAX_DATA_ROWS, actual=rows_total
            )
        raw_line = delimiter.join(row)[:MAX_RAW_LENGTH]

        def skip(code: str, line: int = offset, text: str = raw_line) -> None:
            skipped.append(SkippedRow(line=line, code=code, raw=text))

        if len(row) != len(header):
            skip("row.field_count_mismatch")
            continue

        description = row[index["description"]].strip()
        if not description:
            skip("row.description_missing")
            continue

        raw_date = row[index["date"]].strip()
        if not raw_date:
            skip("row.date_missing")
            continue
        try:
            occurred_on = date.fromisoformat(raw_date)
        except ValueError:
            skip("row.date_invalid")
            continue
        if not MIN_DATE <= occurred_on <= MAX_DATE:
            skip("row.date_out_of_range")
            continue

        raw_amount = row[index["amount"]].strip()
        if not raw_amount:
            skip("row.amount_missing")
            continue
        try:
            amount = _parse_amount(raw_amount)
        except (InvalidOperation, ArithmeticError, ValueError):
            skip("row.amount_invalid")
            continue

        if row[index["currency"]].strip().upper() != currency.upper():
            skip("row.currency_mismatch")
            continue

        operations.append(
            Operation(
                line=offset,
                occurred_on=occurred_on,
                amount=amount,
                description=description[:512],
            )
        )

    if rows_total == 0:
        raise StatementError("statement.empty")

    return ParseResult(
        encoding=encoding,
        delimiter=delimiter,
        rows_total=rows_total,
        operations=operations,
        skipped=skipped,
    )


# --- Normalisation ---------------------------------------------------------


@dataclass(frozen=True)
class Normalised:
    key: str
    name: str
    text_signal: bool
    period_marker: str | None


def _titlecase(token: str) -> str:
    """Title-case a token, keeping short acronyms (VPN, SMS) as they are."""
    if "." in token:
        head, _, tail = token.partition(".")
        return f"{head.capitalize()}.{tail.lower()}"
    is_word = token in SIGNAL_TOKENS or token in PERIOD_MARKERS
    if len(token) <= 3 and token.isalpha() and not is_word:
        return token
    return token.capitalize()


def normalise(description: str) -> Normalised:
    """Reduce a statement description to a stable grouping key and a display name."""
    raw_tokens = [token for token in SPLIT_CHARS.split(description.upper()) if token]
    kept: list[str] = []
    text_signal = False
    period_marker: str | None = None

    for token in raw_tokens:
        token = token.strip(".-_")
        if not token or len(token) == 1:
            continue
        if token.endswith(".COM"):
            token = token.removesuffix(".COM")
            text_signal = True
        elif "." in token:
            text_signal = True
        if token in SUBSCRIPTION_TOKENS:
            text_signal = True
            continue
        if token in SIGNAL_TOKENS:
            text_signal = True
        if token in PERIOD_MARKERS:
            period_marker = period_marker or PERIOD_MARKERS[token]
            text_signal = True
        if token in LEGAL_TOKENS or token in GEO_TOKENS or token in PAYMENT_TOKENS:
            continue
        if token.isdigit() or CODE_TOKEN.match(token):
            continue
        kept.append(token)

    if not kept:
        kept = [raw_tokens[0]] if raw_tokens else ["UNKNOWN"]
    return Normalised(
        key=" ".join(kept).lower(),
        name=" ".join(_titlecase(token) for token in kept),
        text_signal=text_signal,
        period_marker=period_marker,
    )


# --- Cycle inference -------------------------------------------------------

CYCLE_WINDOWS: tuple[tuple[str, int, int], ...] = (
    ("weekly", 6, 8),
    ("monthly", 26, 32),
    ("yearly", 355, 375),
)


def _cycle_from_median(median_days: int) -> tuple[str, int | None]:
    for cycle, low, high in CYCLE_WINDOWS:
        if low <= median_days <= high:
            return cycle, None
    return "custom_days", max(1, min(median_days, 3650))


# --- Confidence ------------------------------------------------------------


def _repeats_points(count: int) -> int:
    return {1: 0, 2: 10, 3: 20, 4: 30, 5: 35}.get(count, 40 if count >= 6 else 0)


def _date_points(intervals: list[int]) -> int:
    if len(intervals) == 0:
        return 10  # cycle taken from the description: nothing to verify
    if len(intervals) == 1:
        return 10  # a single interval proves nothing about regularity
    median = statistics.median(intervals)
    deviation = max(abs(value - median) for value in intervals)
    if deviation <= 1:
        return 30
    if deviation <= 3:
        return 20
    if deviation <= 7:
        return 10
    return 0


def _amount_points(stability: str) -> int:
    return {"stable": 20, "near_stable": 16, "price_step": 8, "single": 10}.get(
        stability, 0
    )


def _label(confidence: int) -> str:
    if confidence >= 70:
        return "high"
    if confidence >= 50:
        return "medium"
    return "low"


# --- Grouping and rejection ------------------------------------------------


@dataclass
class Candidate:
    key: str
    name: str
    amount: Decimal
    previous_amount: Decimal | None
    billing_cycle: str
    custom_interval_days: int | None
    cycle_basis: str
    amount_stability: str
    occurrences: list[Operation]
    confidence: int
    confidence_parts: dict[str, int]
    confidence_label: str
    review: bool
    suggested_next_billing_date: date | None = None

    @property
    def first_seen(self) -> date:
        return self.occurrences[0].occurred_on

    @property
    def last_seen(self) -> date:
        return self.occurrences[-1].occurred_on


@dataclass
class Detection:
    candidates: list[Candidate]
    rejected: dict[str, int]


def _stability(amounts: list[Decimal]) -> tuple[str, Decimal | None]:
    """Classify how the amount behaves across a group, in date order."""
    if len(amounts) == 1:
        return "single", None
    unique = list(dict.fromkeys(amounts))
    if len(unique) == 1:
        return "stable", None

    low, high = min(amounts), max(amounts)
    if (high - low) / high <= Decimal("0.01"):
        return "near_stable", None

    # A price step: one value up to some point, another after it, and never back.
    # Needs at least three operations: with two, any pair of different amounts
    # looks like a step, and a shop with varying receipts would pass as a service.
    changes = [i for i in range(1, len(amounts)) if amounts[i] != amounts[i - 1]]
    if len(amounts) >= 3 and len(changes) == 1 and len(unique) == 2:
        return "price_step", amounts[0]
    return "unstable", None


def detect(operations: list[Operation], today: date) -> Detection:
    """Group operations into subscription candidates and count what was rejected."""
    from app.services import billing

    groups: dict[str, list[Operation]] = defaultdict(list)
    meta: dict[str, Normalised] = {}
    for operation in operations:
        normalised = normalise(operation.description)
        groups[normalised.key].append(operation)
        meta.setdefault(normalised.key, normalised)

    candidates: list[Candidate] = []
    rejected: Counter[str] = Counter()

    for key, raw_group in groups.items():
        group = sorted(raw_group, key=lambda item: item.occurred_on)
        info = meta[key]

        if all(item.amount >= 0 for item in group):  # R1
            rejected["rejected.inflow"] += 1
            continue
        if key.startswith(TRANSFER_PREFIXES):  # R2
            rejected["rejected.transfer"] += 1
            continue
        if len(group) < 2 and info.period_marker is None:  # R3
            rejected["rejected.too_few_occurrences"] += 1
            continue

        amounts = [-item.amount for item in group]
        stability, previous = _stability(amounts)
        if stability == "unstable":  # R4
            rejected["rejected.unstable_amount"] += 1
            continue

        intervals = [
            (group[i].occurred_on - group[i - 1].occurred_on).days
            for i in range(1, len(group))
        ]
        if intervals:
            cycle, interval = _cycle_from_median(round(statistics.median(intervals)))
            cycle_basis = "intervals" if len(intervals) > 1 else "single_interval"
        else:
            cycle, interval = info.period_marker or "monthly", None
            cycle_basis = "text"

        parts = {
            "repeats": _repeats_points(len(group)),
            "dates": _date_points(intervals),
            "amount": _amount_points(stability),
            "text": 10 if info.text_signal else 0,
        }
        confidence = sum(parts.values())
        if confidence < 30:  # R6
            rejected["rejected.low_confidence"] += 1
            continue

        amount = amounts[-1].quantize(TWO_PLACES, rounding=ROUND_HALF_UP)
        candidates.append(
            Candidate(
                key=key,
                name=info.name,
                amount=amount,
                previous_amount=previous,
                billing_cycle=cycle,
                custom_interval_days=interval,
                cycle_basis=cycle_basis,
                amount_stability=stability,
                occurrences=group,
                confidence=confidence,
                confidence_parts=parts,
                confidence_label=_label(confidence),
                review=len(group) < 3 or confidence < 70,
            )
        )

    candidates.sort(
        key=lambda item: (-item.confidence, -len(item.occurrences), item.name)
    )
    for candidate in candidates:
        candidate.suggested_next_billing_date = billing.first_on_or_after(
            candidate.last_seen,
            candidate.billing_cycle,
            candidate.custom_interval_days,
            today,
        )
    return Detection(candidates=candidates, rejected=dict(rejected))

from datetime import date, datetime
from datetime import date as DateValue
from enum import StrEnum
from typing import Annotated, Self

from pydantic import AliasChoices, BaseModel, ConfigDict, Field, model_validator

from app.schemas.subscriptions import (
    MAX_INTERVAL_DAYS,
    Amount,
    BillingCycle,
    BoundedDate,
    Name,
)
from app.schemas.types import MoneyStr

MAX_CONFIRM_ITEMS = 200


class DuplicateMatch(StrEnum):
    none = "none"
    exact = "exact"
    amount_differs = "amount_differs"
    cycle_differs = "cycle_differs"


class ConfirmAction(StrEnum):
    create = "create"
    update = "update"


class OccurrenceRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    line: int
    date: DateValue = Field(validation_alias=AliasChoices("occurred_on", "date"))
    amount: MoneyStr
    raw_description: str


class MatchedSubscription(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    id: int
    name: str
    amount: MoneyStr
    billing_cycle: BillingCycle


class CandidateRead(BaseModel):
    model_config = ConfigDict(from_attributes=True)

    candidate_id: str = Field(validation_alias=AliasChoices("id", "candidate_id"))
    name: str
    amount: MoneyStr
    previous_amount: MoneyStr | None = None
    billing_cycle: BillingCycle
    custom_interval_days: int | None = None
    start_date: date
    suggested_next_billing_date: date
    occurrence_count: int
    first_seen: date
    last_seen: date
    cycle_basis: str
    amount_stability: str
    confidence_label: str
    preselect_recommended: bool
    duplicate_match: DuplicateMatch
    matched_subscription: MatchedSubscription | None = None
    occurrences: list[OccurrenceRead]
    # Diagnostics only: the client must not compare these with any threshold.
    confidence: int
    confidence_parts: dict[str, int]


class SkippedRowRead(BaseModel):
    line: int
    code: str
    raw: str


class StatementRead(BaseModel):
    filename: str
    encoding: str
    delimiter: str
    currency: str
    period_start: date | None
    period_end: date | None
    rows_total: int
    rows_parsed: int
    rows_skipped: int
    incomplete_data: bool
    skipped_rows: list[SkippedRowRead]
    skipped_by_code: dict[str, int]
    rejected_groups: dict[str, int]


class ImportRead(BaseModel):
    import_id: str
    status: str
    expires_at: datetime
    ruleset_version: str
    statement: StatementRead
    candidates: list[CandidateRead]
    candidates_review: list[CandidateRead]


class ActiveImport(BaseModel):
    import_id: str
    filename: str
    created_at: datetime


class ConfirmItem(BaseModel):
    """One candidate the owner decided about.

    ``action`` may be omitted when the candidate has no match: there is exactly
    one legal value, and demanding it would fail every client that did not know
    about the field (contract, decision Р2).
    """

    model_config = ConfigDict(extra="forbid")

    candidate_id: str
    action: ConfirmAction | None = None
    target_subscription_id: int | None = None
    expected_amount: Amount | None = None
    # Edits allowed when creating.
    name: Name | None = None
    amount: Amount | None = None
    billing_cycle: BillingCycle | None = None
    custom_interval_days: int | None = Field(default=None, gt=0, le=MAX_INTERVAL_DAYS)
    next_billing_date: BoundedDate | None = None

    @model_validator(mode="after")
    def check_update_fields(self) -> Self:
        if self.action == ConfirmAction.update:
            if self.target_subscription_id is None:
                raise ValueError("target_subscription_id is required for update")
            if self.expected_amount is None:
                raise ValueError("expected_amount is required for update")
        return self


class ConfirmRequest(BaseModel):
    idempotency_key: Annotated[str, Field(min_length=8, max_length=100)]
    items: Annotated[
        list[ConfirmItem], Field(min_length=1, max_length=MAX_CONFIRM_ITEMS)
    ]


class CreatedItem(BaseModel):
    candidate_id: str
    subscription_id: int
    name: str
    amount: MoneyStr
    billing_cycle: BillingCycle
    start_date: date
    next_billing_date: date
    created_despite_duplicate: bool


class UpdatedItem(BaseModel):
    candidate_id: str
    subscription_id: int
    name: str
    previous: dict[str, str]
    current: dict[str, str]


class SkippedItem(BaseModel):
    candidate_id: str
    code: str
    params: dict[str, str] = Field(default_factory=dict)


class ConfirmResponse(BaseModel):
    import_id: str
    status: str
    created: list[CreatedItem]
    updated: list[UpdatedItem]
    skipped: list[SkippedItem]
    created_count: int
    updated_count: int
    skipped_count: int

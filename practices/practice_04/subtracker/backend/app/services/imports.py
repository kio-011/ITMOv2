"""Statement import: creation, reading, confirmation and discard.

The detection rules live in ``app.services.statement``; this module turns them
into stored rows and into the API contract agreed between the two teams.
"""

import hashlib
import json
import secrets
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal

from fastapi import HTTPException, status
from pydantic import ValidationError
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.models import (
    CandidateOccurrence,
    ImportCandidate,
    StatementImport,
    Subscription,
    User,
)
from app.schemas.imports import (
    ActiveImport,
    ConfirmAction,
    ConfirmItem,
    ConfirmRequest,
    ConfirmResponse,
    CreatedItem,
    DuplicateMatch,
    SkippedItem,
    UpdatedItem,
)
from app.schemas.subscriptions import SubscriptionCreate
from app.services import billing, statement
from app.services.statement import StatementError

TTL = timedelta(hours=2)
MAX_ACTIVE_IMPORTS = 3
RATE_LIMIT_PER_HOUR = 10
AMOUNT_TOLERANCE = Decimal("0.01")

# A whole-file failure that is the client's fault but not a size problem.
FILE_ERROR_STATUS = {
    "statement.too_many_rows": status.HTTP_422_UNPROCESSABLE_CONTENT,
    "statement.too_large": status.HTTP_413_CONTENT_TOO_LARGE,
}


def api_error(code: str, http_status: int, **params: object) -> HTTPException:
    """The single error shape agreed in the contract: a code plus parameters."""
    return HTTPException(
        status_code=http_status, detail={"code": code, "params": params}
    )


def _aware(value: datetime) -> datetime:
    """SQLite gives naive datetimes back; Postgres gives aware ones."""
    return value if value.tzinfo else value.replace(tzinfo=UTC)


def _new_id(prefix: str) -> str:
    return f"{prefix}_{secrets.token_hex(8)}"


def _fingerprint(items: list[ConfirmItem]) -> str:
    """Canonical form of a confirmation, used to detect a replayed request."""
    canonical = sorted(
        (item.model_dump(mode="json", exclude_none=False) for item in items),
        key=lambda row: row["candidate_id"],
    )
    return hashlib.sha256(
        json.dumps(canonical, sort_keys=True, default=str).encode()
    ).hexdigest()


# --- Creation --------------------------------------------------------------


def _classify_match(
    candidate: statement.Candidate, subscription: Subscription
) -> DuplicateMatch:
    if subscription.billing_cycle != candidate.billing_cycle:
        return DuplicateMatch.cycle_differs
    difference = abs(subscription.amount - candidate.amount)
    if difference <= subscription.amount * AMOUNT_TOLERANCE:
        return DuplicateMatch.exact
    return DuplicateMatch.amount_differs


MATCH_RANK = {
    DuplicateMatch.exact: 3,
    DuplicateMatch.amount_differs: 2,
    DuplicateMatch.cycle_differs: 1,
    DuplicateMatch.none: 0,
}


def _match(
    candidate: statement.Candidate, owned: list[Subscription]
) -> tuple[DuplicateMatch, Subscription | None]:
    best: tuple[DuplicateMatch, Subscription | None] = (DuplicateMatch.none, None)
    for subscription in owned:
        if statement.normalise(subscription.name).key != candidate.key:
            continue
        match = _classify_match(candidate, subscription)
        if MATCH_RANK[match] > MATCH_RANK[best[0]]:
            best = (match, subscription)
    return best


async def _guard_limits(session: AsyncSession, user: User, now: datetime) -> None:
    active = (
        await session.scalars(
            select(StatementImport)
            .where(
                StatementImport.owner_id == user.id,
                StatementImport.status == "analyzed",
                StatementImport.expires_at > now,
            )
            .order_by(StatementImport.created_at)
        )
    ).all()
    if len(active) >= MAX_ACTIVE_IMPORTS:
        raise api_error(
            "import.too_many_active",
            status.HTTP_409_CONFLICT,
            limit=MAX_ACTIVE_IMPORTS,
            active=[
                ActiveImport(
                    import_id=item.id,
                    filename=item.filename,
                    created_at=item.created_at,
                ).model_dump(mode="json")
                for item in active
            ],
        )

    # Only successful analyses count: a rejected file should not lock the owner out.
    recent = await session.scalar(
        select(func.count())
        .select_from(StatementImport)
        .where(
            StatementImport.owner_id == user.id,
            StatementImport.created_at > now - timedelta(hours=1),
        )
    )
    if (recent or 0) >= RATE_LIMIT_PER_HOUR:
        raise api_error(
            "import.rate_limited",
            status.HTTP_429_TOO_MANY_REQUESTS,
            limit=RATE_LIMIT_PER_HOUR,
            retry_after=(now + timedelta(hours=1)).isoformat(),
        )


async def create_import(
    session: AsyncSession,
    user: User,
    filename: str,
    raw: bytes,
    now: datetime,
    today: date,
) -> StatementImport:
    if len(raw) > statement.MAX_FILE_BYTES:
        raise api_error(
            "statement.too_large",
            status.HTTP_413_CONTENT_TOO_LARGE,
            limit_bytes=statement.MAX_FILE_BYTES,
            actual_bytes=len(raw),
        )
    await _guard_limits(session, user, now)

    try:
        parsed = statement.parse_statement(raw, user.default_currency)
    except StatementError as error:
        raise api_error(
            error.code,
            FILE_ERROR_STATUS.get(error.code, status.HTTP_400_BAD_REQUEST),
            **error.params,
        ) from error

    detection = statement.detect(parsed.operations, today)
    owned = list(
        await session.scalars(
            select(Subscription).where(Subscription.owner_id == user.id)
        )
    )

    dates = [operation.occurred_on for operation in parsed.operations]
    record = StatementImport(
        id=_new_id("imp"),
        owner_id=user.id,
        filename=filename,
        encoding=parsed.encoding,
        delimiter=parsed.delimiter,
        currency=user.default_currency,
        status="analyzed",
        ruleset_version=statement.RULESET_VERSION,
        rows_total=parsed.rows_total,
        rows_parsed=len(parsed.operations),
        rows_skipped=len(parsed.skipped),
        period_start=min(dates, default=None),
        period_end=max(dates, default=None),
        skipped_rows=[
            {"line": row.line, "code": row.code, "raw": row.raw}
            for row in parsed.skipped[: statement.MAX_SKIPPED_RETURNED]
        ],
        rejected_groups=detection.rejected,
        created_at=now,
        expires_at=now + TTL,
    )
    session.add(record)

    for candidate in detection.candidates:
        match, subscription = _match(candidate, owned)
        row = ImportCandidate(
            id=_new_id("cnd"),
            import_id=record.id,
            owner_id=user.id,
            name=candidate.name,
            group_key=candidate.key,
            amount=candidate.amount,
            previous_amount=candidate.previous_amount,
            billing_cycle=candidate.billing_cycle,
            custom_interval_days=candidate.custom_interval_days,
            start_date=candidate.first_seen,
            suggested_next_billing_date=candidate.suggested_next_billing_date,
            occurrence_count=len(candidate.occurrences),
            first_seen=candidate.first_seen,
            last_seen=candidate.last_seen,
            cycle_basis=candidate.cycle_basis,
            amount_stability=candidate.amount_stability,
            confidence=candidate.confidence,
            confidence_parts=candidate.confidence_parts,
            confidence_label=candidate.confidence_label,
            review=candidate.review,
            preselect_recommended=not candidate.review and match is DuplicateMatch.none,
            duplicate_match=match.value,
            matched_subscription_id=subscription.id if subscription else None,
        )
        row.occurrences = [
            CandidateOccurrence(
                line=operation.line,
                occurred_on=operation.occurred_on,
                amount=-operation.amount,
                raw_description=operation.description,
            )
            for operation in candidate.occurrences
        ]
        session.add(row)

    await session.commit()
    return await load_import(session, user, record.id, now)


# --- Reading ---------------------------------------------------------------


async def load_import(
    session: AsyncSession, user: User, import_id: str, now: datetime
) -> StatementImport:
    record = await session.scalar(
        select(StatementImport)
        .where(StatementImport.id == import_id, StatementImport.owner_id == user.id)
        .options(
            selectinload(StatementImport.candidates).selectinload(
                ImportCandidate.occurrences
            )
        )
    )
    # Another owner's import is indistinguishable from a missing one.
    if record is None or record.status == "discarded":
        raise api_error("import.not_found", status.HTTP_404_NOT_FOUND)
    if record.status == "analyzed" and _aware(record.expires_at) <= now:
        record.status = "expired"
        await session.commit()
    if record.status == "expired":
        raise api_error("import.expired", status.HTTP_410_GONE)
    return record


async def discard_import(
    session: AsyncSession, user: User, import_id: str, now: datetime
) -> None:
    record = await load_import(session, user, import_id, now)
    if record.status == "confirmed":
        raise api_error("import.already_confirmed", status.HTTP_409_CONFLICT)
    record.status = "discarded"
    await session.commit()


def to_read(record: StatementImport) -> dict:
    """Shape an import for the API: two candidate lists plus statement facts."""
    from app.schemas.imports import CandidateRead, ImportRead, StatementRead

    skipped_by_code: dict[str, int] = {}
    for row in record.skipped_rows:
        skipped_by_code[row["code"]] = skipped_by_code.get(row["code"], 0) + 1

    def shape(candidate: ImportCandidate) -> CandidateRead:
        return CandidateRead.model_validate(candidate)

    return ImportRead(
        import_id=record.id,
        status=record.status,
        expires_at=record.expires_at,
        ruleset_version=record.ruleset_version,
        statement=StatementRead(
            filename=record.filename,
            encoding=record.encoding,
            delimiter=record.delimiter,
            currency=record.currency,
            period_start=record.period_start,
            period_end=record.period_end,
            rows_total=record.rows_total,
            rows_parsed=record.rows_parsed,
            rows_skipped=record.rows_skipped,
            incomplete_data=record.rows_skipped > 0,
            skipped_rows=record.skipped_rows,
            skipped_by_code=skipped_by_code,
            rejected_groups=record.rejected_groups,
        ),
        candidates=[shape(item) for item in record.candidates if not item.review],
        candidates_review=[shape(item) for item in record.candidates if item.review],
    ).model_dump(mode="json")


# --- Confirmation ----------------------------------------------------------


def _as_money(value: Decimal) -> str:
    return format(value.quantize(Decimal("0.01")), "f")


def _resolve_action(candidate: ImportCandidate, item: ConfirmItem) -> ConfirmAction:
    """Pick the action, enforcing the narrow update rule from decision Р1."""
    match = DuplicateMatch(candidate.duplicate_match)
    if item.action is None:
        if match is not DuplicateMatch.none:
            raise api_error(
                "confirm.action_required",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                candidate_id=candidate.id,
            )
        return ConfirmAction.create
    if item.action is ConfirmAction.update:
        if match is not DuplicateMatch.amount_differs:
            raise api_error(
                "confirm.update_not_allowed",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                candidate_id=candidate.id,
                duplicate_match=candidate.duplicate_match,
            )
        if item.target_subscription_id != candidate.matched_subscription_id:
            raise api_error(
                "confirm.target_required",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                candidate_id=candidate.id,
            )
    return item.action


def _build_create(
    candidate: ImportCandidate, item: ConfirmItem, today: date
) -> SubscriptionCreate:
    cycle = item.billing_cycle or candidate.billing_cycle
    interval = (
        item.custom_interval_days
        if item.custom_interval_days is not None
        else candidate.custom_interval_days
    )
    if cycle != "custom_days":
        interval = None
    next_billing = item.next_billing_date or candidate.suggested_next_billing_date
    return SubscriptionCreate(
        name=item.name or candidate.name,
        amount=item.amount or candidate.amount,
        billing_cycle=cycle,
        custom_interval_days=interval,
        start_date=candidate.start_date,
        next_billing_date=billing.first_on_or_after(
            next_billing, cycle, interval, today
        )
        if next_billing < today
        else next_billing,
    )


async def confirm_import(
    session: AsyncSession,
    user: User,
    import_id: str,
    body: ConfirmRequest,
    now: datetime,
    today: date,
) -> tuple[ConfirmResponse, bool]:
    """Apply the owner's choices. Returns the response and whether it is a replay."""
    record = await load_import(session, user, import_id, now)
    fingerprint = _fingerprint(body.items)

    if record.status == "confirmed":
        if record.idempotency_key == body.idempotency_key:
            if record.confirm_fingerprint != fingerprint:
                raise api_error(
                    "confirm.idempotency_key_reused", status.HTTP_409_CONFLICT
                )
            return ConfirmResponse.model_validate(record.confirm_result), True
        raise api_error(
            "import.already_confirmed",
            status.HTTP_409_CONFLICT,
            subscription_ids=[
                candidate.applied_subscription_id
                for candidate in record.candidates
                if candidate.applied_subscription_id
            ],
        )

    by_id = {candidate.id: candidate for candidate in record.candidates}
    seen: set[str] = set()
    for item in body.items:
        if item.candidate_id in seen:
            raise api_error(
                "confirm.duplicate_candidate",
                status.HTTP_422_UNPROCESSABLE_CONTENT,
                candidate_id=item.candidate_id,
            )
        seen.add(item.candidate_id)
        if item.candidate_id not in by_id:
            raise api_error("candidate.not_found", status.HTTP_404_NOT_FOUND)

    created: list[CreatedItem] = []
    updated: list[UpdatedItem] = []
    skipped: list[SkippedItem] = []

    for item in body.items:
        candidate = by_id[item.candidate_id]
        action = _resolve_action(candidate, item)

        if action is ConfirmAction.update:
            target = await session.get(Subscription, item.target_subscription_id)
            if target is None or target.owner_id != user.id:
                skipped.append(
                    SkippedItem(
                        candidate_id=candidate.id, code="item.subscription_not_found"
                    )
                )
                continue
            # The owner may have edited the subscription in another tab.
            if target.amount != item.expected_amount:
                skipped.append(
                    SkippedItem(
                        candidate_id=candidate.id,
                        code="confirm.amount_conflict",
                        params={"actual_amount": _as_money(target.amount)},
                    )
                )
                continue
            previous = target.amount
            target.amount = item.amount or candidate.amount
            candidate.applied_action = "update"
            candidate.applied_subscription_id = target.id
            updated.append(
                UpdatedItem(
                    candidate_id=candidate.id,
                    subscription_id=target.id,
                    name=target.name,
                    previous={"amount": _as_money(previous)},
                    current={"amount": _as_money(target.amount)},
                )
            )
            continue

        try:
            payload = _build_create(candidate, item, today)
        except ValidationError as error:
            skipped.append(
                SkippedItem(
                    candidate_id=candidate.id,
                    code="item.invalid_value",
                    params={"field": str(error.errors()[0]["loc"][0])},
                )
            )
            continue

        subscription = Subscription(
            owner_id=user.id,
            name=payload.name,
            amount=payload.amount,
            billing_cycle=payload.billing_cycle.value,
            custom_interval_days=payload.custom_interval_days,
            start_date=payload.start_date,
            next_billing_date=payload.next_billing_date,
            is_active=True,
        )
        session.add(subscription)
        await session.flush()
        candidate.applied_action = "create"
        candidate.applied_subscription_id = subscription.id
        created.append(
            CreatedItem(
                candidate_id=candidate.id,
                subscription_id=subscription.id,
                name=subscription.name,
                amount=subscription.amount,
                billing_cycle=subscription.billing_cycle,
                start_date=subscription.start_date,
                next_billing_date=subscription.next_billing_date,
                created_despite_duplicate=candidate.duplicate_match != "none",
            )
        )

    if not created and not updated:
        await session.rollback()
        codes = {item.code for item in skipped}
        # One cause for every element: report that cause, not a generic failure.
        code = codes.pop() if len(codes) == 1 else "confirm.all_items_failed"
        raise api_error(
            code,
            status.HTTP_422_UNPROCESSABLE_CONTENT,
            items=[item.model_dump(mode="json") for item in skipped],
        )

    record.status = "confirmed"
    record.confirmed_at = now
    record.idempotency_key = body.idempotency_key
    record.confirm_fingerprint = fingerprint
    response = ConfirmResponse(
        import_id=record.id,
        status="confirmed",
        created=created,
        updated=updated,
        skipped=skipped,
        created_count=len(created),
        updated_count=len(updated),
        skipped_count=len(skipped),
    )
    record.confirm_result = response.model_dump(mode="json")
    await session.commit()
    return response, False

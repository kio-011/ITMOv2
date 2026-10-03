from decimal import ROUND_HALF_UP, Decimal

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import Subscription, User
from app.schemas.stats import StatsSummaryResponse
from app.services.billing import monthly_cost

TWO_PLACES = Decimal("0.01")


async def get_stats_summary(session: AsyncSession, user: User) -> StatsSummaryResponse:
    stmt = select(Subscription).where(
        Subscription.owner_id == user.id,
        Subscription.is_active.is_(True),
    )
    subscriptions = (await session.execute(stmt)).scalars().all()

    monthly_total = sum(
        (
            monthly_cost(sub.amount, sub.billing_cycle, sub.custom_interval_days)
            for sub in subscriptions
        ),
        Decimal("0.00"),
    ).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    yearly_total = (monthly_total * 12).quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

    return StatsSummaryResponse(
        monthly_total=monthly_total,
        yearly_total=yearly_total,
        currency=user.default_currency,
    )

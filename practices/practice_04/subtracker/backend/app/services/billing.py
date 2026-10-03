from decimal import ROUND_HALF_UP, Decimal

TWO_PLACES = Decimal("0.01")


def monthly_cost(
    amount: Decimal,
    billing_cycle: str,
    custom_interval_days: int | None = None,
) -> Decimal:
    if billing_cycle == "monthly":
        result = amount
    elif billing_cycle == "yearly":
        result = amount / 12
    elif billing_cycle == "weekly":
        result = amount * 52 / 12
    elif billing_cycle == "custom_days":
        if not custom_interval_days:
            raise ValueError(
                "custom_interval_days is required for custom_days billing_cycle"
            )
        result = amount * 30 / custom_interval_days
    else:
        raise ValueError(f"Unknown billing_cycle: {billing_cycle!r}")

    return result.quantize(TWO_PLACES, rounding=ROUND_HALF_UP)

from decimal import Decimal

from pydantic import BaseModel, field_serializer


class StatsSummaryResponse(BaseModel):
    monthly_total: Decimal
    yearly_total: Decimal
    currency: str

    @field_serializer("monthly_total", "yearly_total")
    def serialize_decimal(self, value: Decimal) -> str:
        return str(value)

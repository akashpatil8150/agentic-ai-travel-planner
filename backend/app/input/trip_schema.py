from datetime import date, datetime
from decimal import Decimal

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
    ConfigDict,
)

from app.models.trip_models import TripStatus


class TripCreate(BaseModel):
    source_city: str = Field(min_length=2, max_length=100)
    destination_city: str = Field(min_length=2, max_length=100)

    start_date: date
    end_date: date

    adults: int = Field(gt=0)
    children: int = Field(default=0, ge=0)
    travellers: int = Field(gt=0)

    trip_type: str = Field(min_length=2, max_length=50)

    budget: Decimal | None = Field(default=None, ge=0)

    transport_pref: str | None = Field(
        default=None,
        max_length=50
    )

    preferences: list = Field(default_factory=list)

    @field_validator(
        "source_city",
        "destination_city",
        "trip_type",
        "transport_pref"
    )
    @classmethod
    def clean_text(cls, value):
        if value is None:
            return value

        value = value.strip().lower()

        if not value:
            raise ValueError("Field cannot be empty")

        return value

    @model_validator(mode="after")
    def validate_trip(self):
        # Date validation
        if self.end_date < self.start_date:
            raise ValueError(
                "End date cannot be before start date"
            )

        # Source and destination validation
        if self.source_city.lower() == self.destination_city.lower():
            raise ValueError(
                "Source and destination cannot be the same"
            )

        # Traveller count validation
        expected_travellers = self.adults + self.children

        if self.travellers != expected_travellers:
            raise ValueError(
                "Travellers must equal adults + children"
            )

        return self


class TripStatusUpdate(BaseModel):
    status: TripStatus


class TripResponse(BaseModel):
    id: int
    user_id: int

    source_city: str
    destination_city: str

    start_date: date
    end_date: date

    adults: int
    children: int
    travellers: int

    trip_type: str

    budget: Decimal | None
    transport_pref: str | None
    preferences: list

    status: TripStatus

    created_at: datetime
    updated_at: datetime

    model_config = ConfigDict(
        from_attributes=True
    )
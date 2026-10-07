from datetime import date
from typing import Literal, Optional

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


class TransportSearchRequest(BaseModel):

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    origin: str = Field(
        min_length=2,
        max_length=100,
    )

    destination: str = Field(
        min_length=2,
        max_length=100,
    )

    departure_date: date

    return_date: Optional[date] = None

    adults: int = Field(
        default=1,
        ge=1,
    )

    children: int = Field(
        default=0,
        ge=0,
    )

    transport_type: Literal[
        "flight",
        "train",
        "both",
    ] = "both"

    # ========================================================
    # LOCATION VALIDATION
    # ========================================================

    @field_validator(
        "origin",
        "destination",
    )
    @classmethod
    def clean_location(cls, value: str):

        value = value.strip()

        if not value:
            raise ValueError(
                "Location cannot be empty"
            )

        return value

    # ========================================================
    # TRANSPORT TYPE VALIDATION
    # ========================================================

    @field_validator(
        "transport_type",
        mode="before",
    )
    @classmethod
    def clean_transport_type(cls, value):

        if isinstance(value, str):
            return value.strip().lower()

        return value

    # ========================================================
    # JOURNEY VALIDATION
    # ========================================================

    @model_validator(mode="after")
    def validate_journey(self):

        today = date.today()

        # ----------------------------------------------------
        # Origin and destination
        # ----------------------------------------------------

        if (
            self.origin.lower()
            == self.destination.lower()
        ):

            raise ValueError(
                "Origin and destination cannot be the same"
            )

        # ----------------------------------------------------
        # Departure date
        # ----------------------------------------------------

        if self.departure_date < today:

            raise ValueError(
                "Departure date cannot be in the past"
            )

        # ----------------------------------------------------
        # Return date
        # ----------------------------------------------------

        if self.return_date is not None:

            if self.return_date < today:

                raise ValueError(
                    "Return date cannot be in the past"
                )

            if self.return_date < self.departure_date:

                raise ValueError(
                    "Return date cannot be before "
                    "departure date"
                )

        return self
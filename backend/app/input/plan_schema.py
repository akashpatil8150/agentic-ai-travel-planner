from datetime import date

from pydantic import (
    BaseModel,
    Field,
    field_validator,
    model_validator,
)


class PlanTripRequest(BaseModel):

    # Persisted Trip master record created by the frontend before planning.
    trip_id: int = Field(
        ...,
        gt=0,
        description="Persisted trip ID owned by the authenticated user.",
    )

    origin: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )

    destination: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )

    start_date: date

    end_date: date

    adults: int = Field(
        default=1,
        ge=1,
    )

    children: int = Field(
        default=0,
        ge=0,
    )

    budget: float | None = Field(
        default=None,
        ge=0,
    )

    transport_preference: str = Field(
        default="train",
        description="Preferred transport: train or flight.",
    )

    preferences: list[str] = Field(
        default_factory=list,
    )

    # Optional explicit transport selections made by the user
    selected_outbound_transport: dict | None = Field(
        default=None,
        description="User-selected outbound transport option.",
    )

    selected_outbound_option: dict | None = Field(
        default=None,
        description="Alias for selected_outbound_transport.",
    )

    selected_return_transport: dict | None = Field(
        default=None,
        description="User-selected return transport option.",
    )

    selected_return_option: dict | None = Field(
        default=None,
        description="Alias for selected_return_transport.",
    )

    selected_outbound_class: str | None = Field(
        default=None,
        description="User-selected outbound class/cabin code.",
    )

    selected_return_class: str | None = Field(
        default=None,
        description="User-selected return class/cabin code.",
    )

    selected_outbound_fare: float | None = Field(
        default=None,
        ge=0,
        description="User-selected outbound fare per traveler.",
    )

    selected_return_fare: float | None = Field(
        default=None,
        ge=0,
        description="User-selected return fare per traveler.",
    )

    @model_validator(mode="after")
    def unify_transport_aliases(self):
        if not self.selected_outbound_transport and self.selected_outbound_option:
            self.selected_outbound_transport = self.selected_outbound_option
        if not self.selected_return_transport and self.selected_return_option:
            self.selected_return_transport = self.selected_return_option
        return self

    # =====================================================
    # LOCATION CLEANING
    # =====================================================

    @field_validator(
        "origin",
        "destination",
    )
    @classmethod
    def clean_location(
        cls,
        value: str,
    ):

        value = value.strip()

        if not value:

            raise ValueError(
                "Location cannot be empty."
            )

        return value

    # =====================================================
    # DATE VALIDATION
    # =====================================================

    @field_validator("end_date")
    @classmethod
    def validate_end_date(
        cls,
        value,
        info,
    ):

        start_date = info.data.get(
            "start_date"
        )

        if (
            start_date is not None
            and value < start_date
        ):

            raise ValueError(
                "End date cannot be before start date."
            )

        return value

    # =====================================================
    # PAST DATE VALIDATION
    # =====================================================

    @field_validator("start_date")
    @classmethod
    def validate_start_date(
        cls,
        value: date,
    ):

        if value < date.today():

            raise ValueError(
                "Start date cannot be in the past."
            )

        return value

    # =====================================================
    # SAME LOCATION VALIDATION
    # =====================================================

    @model_validator(mode="after")
    def validate_route(self):

        origin = (
            self.origin
            .strip()
            .lower()
        )

        destination = (
            self.destination
            .strip()
            .lower()
        )

        if origin == destination:

            raise ValueError(
                "Origin and destination cannot be the same."
            )

        return self

    # =====================================================
    # TRANSPORT PREFERENCE VALIDATION
    # =====================================================

    @field_validator("transport_preference")
    @classmethod
    def validate_transport_preference(cls, value: str):
        value = value.strip().lower()

        allowed = {"train", "flight"}

        if value not in allowed:
            raise ValueError(
                "Transport preference must be 'train' or 'flight'."
            )

        return value

    # =====================================================
    # PREFERENCE CLEANING
    # =====================================================

    @field_validator("preferences")
    @classmethod
    def clean_preferences(
        cls,
        values,
    ):
    

        cleaned = []

        for value in values:

            if not isinstance(
                value,
                str,
            ):

                raise ValueError(
                    "Each preference must be a string."
                )

            value = (
                value
                .strip()
                .lower()
            )

            if (
                value
                and value not in cleaned
            ):

                cleaned.append(value)

        return cleaned


# =========================================================
# TRANSPORT SEARCH API REQUEST
# =========================================================

class TransportSearchApiRequest(BaseModel):
    """
    Request schema for standalone transport search (Outbound or Return).
    """

    origin: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )

    destination: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )

    departure_date: date | None = None
    travel_date: date | None = None

    return_date: date | None = None

    transport_mode: str = Field(
        default="train",
        description="Transport mode: 'train' or 'flight'.",
    )
    mode: str | None = None

    adults: int = Field(
        default=1,
        ge=1,
    )

    children: int = Field(
        default=0,
        ge=0,
    )

    direction: str = Field(
        default="outbound",
        description="'outbound' or 'return'.",
    )
    leg: str | None = None

    # Context from chosen outbound to assist return station-pair ranking
    outbound_origin_code: str | None = None
    outbound_destination_code: str | None = None

    @model_validator(mode="after")
    def populate_defaults(self):
        if self.departure_date is None:
            if self.travel_date is not None:
                self.departure_date = self.travel_date
            else:
                raise ValueError("departure_date or travel_date must be provided.")

        if self.mode:
            self.transport_mode = self.mode

        if self.leg:
            self.direction = self.leg

        self.transport_mode = self.transport_mode.strip().lower()
        if self.transport_mode not in {"train", "flight"}:
            raise ValueError("transport_mode must be 'train' or 'flight'.")

        self.direction = self.direction.strip().lower()
        if self.direction not in {"outbound", "return"}:
            raise ValueError("direction must be 'outbound' or 'return'.")

        return self


# =========================================================
# BUDGET PREVIEW API REQUEST
# =========================================================

class BudgetPreviewApiRequest(BaseModel):
    """
    Request schema to calculate preview budget after transport selection.
    """

    outbound_fare: float = Field(
        ...,
        ge=0,
        description="Selected outbound fare per traveler.",
    )

    return_fare: float = Field(
        default=0.0,
        ge=0,
        description="Selected return fare per traveler.",
    )

    adults: int = Field(
        default=1,
        ge=1,
    )

    children: int = Field(
        default=0,
        ge=0,
    )

    budget: float | None = Field(
        default=None,
        ge=0,
        description="Total trip budget limit in INR.",
    )
    total_budget: float | None = None

    destination: str | None = Field(
        default=None,
        description="Destination city for hotel price estimation.",
    )

    nights: int | None = None
    estimated_hotel_rate: float | None = None

    start_date: date | None = None
    end_date: date | None = None

    @model_validator(mode="after")
    def populate_budget_defaults(self):
        if self.budget is None and self.total_budget is not None:
            self.budget = self.total_budget
        return self

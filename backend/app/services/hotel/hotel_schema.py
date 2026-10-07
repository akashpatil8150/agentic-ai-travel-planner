from datetime import date

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_validator,
    model_validator,
)


# =========================================================
# HOTEL SEARCH REQUEST
# =========================================================

class HotelSearchRequest(BaseModel):

    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    city: str = Field(
        ...,
        min_length=2,
        max_length=100,
    )

    country_code: str = Field(
        default="IN",
        min_length=2,
        max_length=2,
    )

    checkin: date

    checkout: date

    adults: int = Field(
        default=1,
        ge=1,
    )

    children: int = Field(
        default=0,
        ge=0,
    )

    rooms: int = Field(
        default=1,
        ge=1,
    )

    currency: str = Field(
        default="INR",
        min_length=3,
        max_length=3,
    )

    max_hotels: int = Field(
        default=5,
        ge=1,
        le=20,
    )

    # =====================================================
    # TEXT CLEANING
    # =====================================================

    @field_validator("city")
    @classmethod
    def validate_city(cls, value: str):

        value = value.strip()

        if not value:
            raise ValueError(
                "City cannot be empty"
            )

        return value

    # =====================================================
    # COUNTRY CODE
    # =====================================================

    @field_validator("country_code")
    @classmethod
    def validate_country_code(cls, value: str):

        value = value.strip().upper()

        if not value.isalpha() or not value.isascii():
            raise ValueError(
                "Country code must contain exactly 2 letters"
            )

        if len(value) != 2:
            raise ValueError(
                "Country code must contain exactly 2 letters"
            )

        return value

    # =====================================================
    # CURRENCY
    # =====================================================

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value: str):

        value = value.strip().upper()

        if not value.isalpha() or not value.isascii():
            raise ValueError(
                "Currency must contain exactly 3 letters"
            )

        if len(value) != 3:
            raise ValueError(
                "Currency must contain exactly 3 letters"
            )

        return value

    # =====================================================
    # DATE VALIDATION
    # =====================================================

    @model_validator(mode="after")
    def validate_dates(self):

        today = date.today()

        # -------------------------------------------------
        # CHECK-IN CANNOT BE IN THE PAST
        # -------------------------------------------------

        if self.checkin < today:

            raise ValueError(
                "Check-in date cannot be in the past"
            )

        # -------------------------------------------------
        # CHECK-OUT MUST BE AFTER CHECK-IN
        # -------------------------------------------------

        if self.checkout <= self.checkin:

            raise ValueError(
                "Check-out date must be after check-in date"
            )

        # -------------------------------------------------
        # HOTEL BOOKING WINDOW
        # Maximum 1 year from today
        # -------------------------------------------------

        try:

            max_date = today.replace(
                year=today.year + 1
            )

        except ValueError:

            # Handles Feb 29
            max_date = today.replace(
                year=today.year + 1,
                day=28,
            )

        if self.checkin > max_date:

            raise ValueError(
                "Check-in date cannot be more than "
                "1 year from today"
            )

        if self.checkout > max_date:

            raise ValueError(
                "Check-out date cannot be more than "
                "1 year from today"
            )

        return self


# =========================================================
# HOTEL RESULT
# =========================================================

class HotelOption(BaseModel):

    model_config = ConfigDict(
        extra="allow",
    )

    hotel_id: str | None = None

    hotel_name: str = "Hotel"

    rating: float | None = None

    address: str | None = None

    photo: str | None = None

    room_name: str | None = None

    board_name: str | None = None

    price: float | None = None

    currency: str = "INR"

    taxes: str | None = None

    cancellation: str | None = None

    cancellation_deadline: str | None = None

    offer_id: str | None = None

    provider: str

    raw_data: dict | None = None


# =========================================================
# HOTEL SEARCH RESPONSE
# =========================================================

class HotelSearchResponse(BaseModel):

    status: str

    provider: str

    hotels: list[HotelOption] = Field(
        default_factory=list
    )

    message: str | None = None
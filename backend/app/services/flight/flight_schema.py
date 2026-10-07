from datetime import date as Date

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator


class FlightSearchRequest(BaseModel):
    model_config = ConfigDict(
        str_strip_whitespace=True,
        extra="forbid",
    )

    from_code: str = Field(..., min_length=3, max_length=3)
    to_code: str = Field(..., min_length=3, max_length=3)
    date: Date
    return_date: Date | None = None

    adults: int = Field(default=1, ge=1)
    children: int = Field(default=0, ge=0)

    cabin_class: str = "ECONOMY"
    currency: str = Field(default="INR", min_length=3, max_length=3)

    @field_validator("from_code", "to_code", "currency", mode="before")
    @classmethod
    def normalize_codes(cls, value):
        if not isinstance(value, str):
            raise ValueError("Value must be a string")
        return value.strip().upper()

    @field_validator("from_code", "to_code")
    @classmethod
    def validate_airport_code(cls, value):
        if not value.isalpha() or not value.isascii():
            raise ValueError("Airport code must contain exactly 3 letters")
        return value

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value):
        if not value.isalpha() or not value.isascii():
            raise ValueError("Currency must contain exactly 3 letters")
        return value

    @field_validator("cabin_class")
    @classmethod
    def validate_cabin_class(cls, value):
        value = value.strip().upper()
        allowed = {
            "ECONOMY",
            "PREMIUM_ECONOMY",
            "BUSINESS",
            "FIRST",
        }
        if value not in allowed:
            raise ValueError(
                "cabin_class must be one of: "
                "ECONOMY, PREMIUM_ECONOMY, BUSINESS, FIRST"
            )
        return value

    @model_validator(mode="after")
    def validate_journey(self):
        today = Date.today()

        if self.date < today:
            raise ValueError("Journey date cannot be in the past")

        try:
            max_date = today.replace(year=today.year + 1)
        except ValueError:
            # Feb 29 -> Feb 28 in the following year.
            max_date = today.replace(
                year=today.year + 1,
                day=28,
            )

        if self.date > max_date:
            raise ValueError(
                "Journey date cannot be more than 1 year from today"
            )

        if self.from_code == self.to_code:
            raise ValueError(
                "From and To airports cannot be the same"
            )

        if self.return_date is not None:
            if self.return_date < today:
                raise ValueError(
                    "Return date cannot be in the past"
                )

            if self.return_date < self.date:
                raise ValueError(
                    "Return date cannot be before journey date"
                )

            if self.return_date > max_date:
                raise ValueError(
                    "Return date cannot be more than 1 year from today"
                )

        return self


class FlightAirport(BaseModel):
    model_config = ConfigDict(extra="ignore")

    code: str | None = None
    name: str | None = None
    city: str | None = None


class FlightFare(BaseModel):
    model_config = ConfigDict(extra="ignore")

    amount: float | None = Field(default=None, ge=0)
    currency: str = Field(default="INR", min_length=3, max_length=3)


class FlightResponse(BaseModel):
    model_config = ConfigDict(extra="ignore")

    id: int
    type: str = "flight"
    airline: str | None = None
    flight_number: str | None = None
    name: str | None = None
    flight_name: str | None = None

    source: FlightAirport
    destination: FlightAirport

    departure_time: str | None = None
    arrival_time: str | None = None

    duration_minutes: int | None = Field(default=None, ge=0)
    stops: int = Field(default=0, ge=0)

    cabin_class: str | None = None
    fare: FlightFare | None = None
    provider: str

    @model_validator(mode="after")
    def populate_names(self):
        airline = (self.airline or "").strip()
        f_no = (self.flight_number or "").strip()
        if not self.name or not self.flight_name or self.name.lower() in ("flight", "none", "unknown", "") or self.flight_name.lower() in ("flight", "none", "unknown", ""):
            if airline and f_no:
                label = f"{airline} {f_no}" if airline.lower() not in f_no.lower() else f_no
            elif airline:
                orig = self.source.code if self.source and self.source.code else "Origin"
                dest = self.destination.code if self.destination and self.destination.code else "Destination"
                label = f"{airline} ({orig} - {dest})"
            elif f_no:
                label = f"Flight {f_no}"
            else:
                orig = self.source.code if self.source and self.source.code else "Origin"
                dest = self.destination.code if self.destination and self.destination.code else "Destination"
                label = f"{orig} - {dest} Flight"
            self.name = label
            self.flight_name = label
        return self


class SelectedFlight(BaseModel):
    model_config = ConfigDict(extra="forbid")

    flight_id: int = Field(..., ge=1)

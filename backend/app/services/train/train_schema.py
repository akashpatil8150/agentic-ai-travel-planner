from typing import Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# ============================================================
# STATION
# ============================================================

class Station(BaseModel):

    code: Optional[str] = None

    name: Optional[str] = None


# ============================================================
# TRAIN FARE
# ============================================================

class TrainFare(BaseModel):

    class_code: str

    amount: Optional[float] = None

    currency: str = "INR"


# ============================================================
# TRAIN SEARCH AVAILABILITY
# ============================================================

class TrainAvailability(BaseModel):

    class_code: str

    status: Optional[str] = None

    text: Optional[str] = None

    confidence: Optional[str] = None


# ============================================================
# SELECTED TRAIN AVAILABILITY
# ============================================================

class TrainDetailsAvailability(BaseModel):

    date: Optional[str] = None

    status: Optional[str] = None

    text: Optional[str] = None

    available: Optional[bool] = None

    available_seats: Optional[int] = None

    waitlist_number: Optional[int] = None

    waitlist_type: Optional[str] = None


# ============================================================
# TRAIN SEARCH RESPONSE
# ============================================================

class TrainResponse(BaseModel):

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="ignore",
    )

    train_number: str

    train_name: str

    train_type: Optional[str] = None

    source: Union[Station, dict]

    destination: Union[Station, dict]

    departure_time: Optional[str] = None

    arrival_time: Optional[str] = None

    duration_minutes: Optional[int] = None

    distance_km: Optional[float] = None

    total_halts: Optional[int] = None

    running_days: list[str] = Field(
        default_factory=list
    )

    classes: list[str] = Field(
        default_factory=list
    )

    fares: list[Union[TrainFare, dict]] = Field(
        default_factory=list
    )

    availability: list[Union[TrainAvailability, dict]] = Field(
        default_factory=list
    )

    provider: str
    data_source: Optional[str] = "live"

    fare: Optional[Union[TrainFare, dict]] = None
    return_trip: Optional[dict] = None

    # Canonical transport & routing fields
    train_origin_station: Optional[str] = None
    train_destination_station: Optional[str] = None
    boarding_station: Optional[str] = None
    alighting_station: Optional[str] = None
    boarding_station_code: Optional[str] = None
    boarding_station_name: Optional[str] = None
    alighting_station_code: Optional[str] = None
    alighting_station_name: Optional[str] = None
    boarding_index: Optional[int] = None
    alighting_index: Optional[int] = None
    train_route_summary: Optional[str] = None

    actual_origin_station: Optional[str] = None
    actual_destination_station: Optional[str] = None
    actual_train_origin: Optional[str] = None
    actual_train_destination: Optional[str] = None
    from_station_code: Optional[str] = None
    to_station_code: Optional[str] = None
    from_station_name: Optional[str] = None
    to_station_name: Optional[str] = None
    from_code: Optional[str] = None
    to_code: Optional[str] = None
    user_origin: Optional[str] = None
    user_destination: Optional[str] = None
    first_mile_transfer: Optional[dict] = None
    last_mile_transfer: Optional[dict] = None
    outbound_transfer: Optional[dict] = None
    return_transfer: Optional[dict] = None
    transfer: Optional[dict] = None
    stations: Optional[list] = None
    stops: Optional[list] = None
    route: Optional[list] = None


# ============================================================
# SELECTED TRAIN DETAILS FARE
# ============================================================

class TrainDetailsFare(BaseModel):

    amount: Optional[float] = None

    currency: str = "INR"

    base_fare: Optional[float] = None

    reservation_charge: Optional[float] = None

    superfast_charge: Optional[float] = None

    gst: Optional[float] = None

    catering_charge: Optional[float] = None

    dynamic_fare: Optional[float] = None


# ============================================================
# SELECTED TRAIN DETAILS DATA
# ============================================================

class TrainDetailsData(BaseModel):

    train_number: str

    source: Station

    destination: Station

    journey_date: str

    class_code: str

    quota_code: str

    fare: Optional[TrainDetailsFare] = None

    availability: list[
        TrainDetailsAvailability
    ] = Field(
        default_factory=list
    )

    provider: str


# ============================================================
# SELECTED TRAIN DETAILS RESPONSE
# ============================================================

class TrainDetailsResponse(BaseModel):

    success: bool

    data: TrainDetailsData
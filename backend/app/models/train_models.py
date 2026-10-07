from pydantic import BaseModel
from typing import Optional


class Station(BaseModel):
    code: Optional[str] = None
    name: Optional[str] = None


class TrainFare(BaseModel):
    amount: Optional[float] = None
    currency: str = "INR"

    base_fare: Optional[float] = None
    reservation_charge: Optional[float] = None
    superfast_charge: Optional[float] = None
    gst: Optional[float] = None
    catering_charge: Optional[float] = None
    dynamic_fare: Optional[float] = None


class TrainAvailability(BaseModel):
    date: str
    status: Optional[str] = None
    text: Optional[str] = None

    available: bool = False
    available_seats: Optional[int] = None

    waitlist_number: Optional[int] = None
    waitlist_type: Optional[str] = None


class TrainDetails(BaseModel):
    train_number: str

    source: Station
    destination: Station

    journey_date: str

    class_code: str
    quota_code: str

    fare: Optional[TrainFare] = None
    availability: list[TrainAvailability] = []

    provider: str


class TrainDetailsResponse(BaseModel):
    success: bool
    data: TrainDetails
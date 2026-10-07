from sqlalchemy.orm import Session

from app.models.trip_models import Trip, TripStatus
from app.input.trip_schema import TripCreate


def create_trip(
    db: Session,
    trip_data: TripCreate,
    user_id: int
):
    trip = Trip(
        user_id=user_id,

        # Route
        source_city=trip_data.source_city,
        destination_city=trip_data.destination_city,

        # Dates
        start_date=trip_data.start_date,
        end_date=trip_data.end_date,

        # Travellers
        adults=trip_data.adults,
        children=trip_data.children,
        travellers=trip_data.travellers,

        # Trip details
        trip_type=trip_data.trip_type,

        # Budget & preferences
        budget=trip_data.budget,
        transport_pref=trip_data.transport_pref,
        preferences=trip_data.preferences,

        # Initial workflow state
        status=TripStatus.DRAFT
    )

    db.add(trip)
    db.commit()
    db.refresh(trip)

    return trip


def get_user_trips(
    db: Session,
    user_id: int
):
    return (
        db.query(Trip)
        .filter(Trip.user_id == user_id)
        .all()
    )


def get_user_trip(
    db: Session,
    trip_id: int,
    user_id: int
):
    return (
        db.query(Trip)
        .filter(
            Trip.id == trip_id,
            Trip.user_id == user_id
        )
        .first()
    )


def update_trip(
    db: Session,
    trip_id: int,
    user_id: int,
    trip_data: TripCreate
):
    trip = (
        db.query(Trip)
        .filter(
            Trip.id == trip_id,
            Trip.user_id == user_id
        )
        .first()
    )

    if not trip:
        return None

    # Route
    trip.source_city = trip_data.source_city
    trip.destination_city = trip_data.destination_city

    # Dates
    trip.start_date = trip_data.start_date
    trip.end_date = trip_data.end_date

    # Travellers
    trip.adults = trip_data.adults
    trip.children = trip_data.children
    trip.travellers = trip_data.travellers

    # Trip details
    trip.trip_type = trip_data.trip_type

    # Budget & preferences
    trip.budget = trip_data.budget
    trip.transport_pref = trip_data.transport_pref
    trip.preferences = trip_data.preferences

    db.commit()
    db.refresh(trip)

    return trip


def delete_trip(
    db: Session,
    trip_id: int,
    user_id: int
):
    trip = (
        db.query(Trip)
        .filter(
            Trip.id == trip_id,
            Trip.user_id == user_id
        )
        .first()
    )

    if not trip:
        return None

    db.delete(trip)
    db.commit()

    return trip


def update_trip_status(
    db: Session,
    trip_id: int,
    user_id: int,
    new_status: TripStatus
):
    trip = (
        db.query(Trip)
        .filter(
            Trip.id == trip_id,
            Trip.user_id == user_id
        )
        .first()
    )

    if not trip:
        return None

    allowed_transitions = {
        TripStatus.DRAFT: [
            TripStatus.PLANNING
        ],

        TripStatus.PLANNING: [
            TripStatus.READY,
            TripStatus.DRAFT
        ],

        TripStatus.READY: []
    }

    if new_status not in allowed_transitions[trip.status]:
        raise ValueError(
            f"Invalid status transition: "
            f"{trip.status.value} -> {new_status.value}"
        )

    trip.status = new_status

    db.commit()
    db.refresh(trip)

    return trip
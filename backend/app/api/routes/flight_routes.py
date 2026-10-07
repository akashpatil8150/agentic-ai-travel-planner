from fastapi import APIRouter, HTTPException

from app.services.flight.flight_schema import (
    FlightSearchRequest,
    SelectedFlight,
)
from app.services.flight.flight_service import FlightService


router = APIRouter(
    prefix="/flights",
    tags=["Flights"],
)

flight_service = FlightService()


@router.post("/search")
async def search_flights(
    request: FlightSearchRequest,
):
    try:
        flights = flight_service.search_flights(request)

        clean_flights = []

        for flight in flights:
            clean_flights.append(
                {
                    "id": flight.id,
                    "airline": flight.airline,
                    "flight_number": flight.flight_number,
                    "from": flight.source.code,
                    "to": flight.destination.code,
                    "departure": flight.departure_time,
                    "arrival": flight.arrival_time,
                    "duration_minutes": flight.duration_minutes,
                    "stops": flight.stops,
                    "cabin_class": flight.cabin_class,
                    "fare": (
                        flight.fare.model_dump()
                        if flight.fare
                        else None
                    ),
                    "provider": flight.provider,
                }
            )

        return {
            "success": True,
            "count": len(clean_flights),
            "flights": clean_flights,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc


@router.post("/selected/details")
async def selected_flight_details(
    selected: SelectedFlight,
    request: FlightSearchRequest,
):
    try:
        details = flight_service.get_selected_flight_details(
            flight_id=selected.flight_id,
            request=request,
        )

        return {
            "success": True,
            "data": details,
        }

    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    except RuntimeError as exc:
        raise HTTPException(
            status_code=503,
            detail=str(exc),
        ) from exc

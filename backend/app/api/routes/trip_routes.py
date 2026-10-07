from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)

from pydantic import BaseModel

from sqlalchemy.orm import Session

from uuid import uuid4

from datetime import datetime, date, timezone



# =========================================================
# DATABASE
# =========================================================

from app.core.database import (
    get_db,
)
from app.models.planning_session import PlanningSession


# =========================================================
# AUTHENTICATION
# =========================================================

from app.auth.auth_dependencies import (
    get_current_user,
)


# =========================================================
# TRIP INPUT / RESPONSE SCHEMAS
# =========================================================

from app.input.trip_schema import (
    TripCreate,
    TripResponse,
    TripStatusUpdate,
)

from app.input.plan_schema import (
    PlanTripRequest,
    TransportSearchApiRequest,
    BudgetPreviewApiRequest,
)

from app.resolvers.transport_access_resolver import (
    TransportAccessResolver,
)

from app.services.train.train_service import (
    TrainService,
)

from app.services.flight.flight_service import (
    FlightService,
)

from app.services.flight.flight_schema import (
    FlightSearchRequest,
)

from app.itinerary.itinerary_builder import (
    format_transport_class_name,
)


# =========================================================
# TRIP SERVICE
# =========================================================

from app.services.trip_service import (
    create_trip,
    get_user_trips,
    get_user_trip,
    update_trip,
    delete_trip,
    update_trip_status,
)

from app.models.trip_models import TripStatus


# =========================================================
# OBSERVABILITY
# =========================================================

import logging

from app.observability.audit_logger import (
    audit_log,
)

logger = logging.getLogger(__name__)


# =========================================================
# TRIP STATE
# =========================================================

from app.state.trip_state import (
    TripState,
    resolve_location,
)


# =========================================================
# TRAVEL ORCHESTRATOR
# =========================================================

from app.orchestrator.travel_orchestrator import (
    TravelOrchestrator,
)


# =========================================================
# ROUTER
# =========================================================

router = APIRouter()


# =========================================================
# PERSISTENT PLANNING SESSION
# =========================================================
# TripState is persisted in PostgreSQL between Phase 1 and Phase 2.
# =========================================================

# =========================================================
# REQUEST SCHEMA
# =========================================================


class SelectTravelOptionRequest(BaseModel):
    """
    User selects one generated travel option.
    """

    option_id: str


class SelectHotelRequest(BaseModel):
    """
    User selects a hotel option by hotel_id.
    """
    hotel_id: str


# =========================================================
# RESPONSE MAPPERS
# =========================================================


def _to_dict(value):
    """
    Convert Pydantic objects into dictionaries.
    """

    if value is None:
        return None

    if hasattr(value, "model_dump"):
        return value.model_dump()

    if isinstance(value, dict):
        return value

    return value


# =========================================================
# TRANSPORT CLEANER
# =========================================================


def _clean_transport_option(option: dict) -> dict:
    """
    Convert internal transport data into a public API shape.
    """

    option = _to_dict(option)

    if not isinstance(option, dict):
        return {}

    return_trip = option.get("return_trip")
    cleaned_return = None
    if isinstance(return_trip, dict) and return_trip:
        cleaned_return = _clean_transport_option(return_trip)

    # ---------------------------------------------------------
    # TRAIN
    # ---------------------------------------------------------

    if option.get("train_number") or option.get("type") == "train" or option.get("train_name"):
        t_name = option.get("train_name") or option.get("name") or "Express"
        return {
            "type": "train",
            "name": t_name,
            "train_number": option.get("train_number"),
            "train_name": t_name,
            "train_type": option.get("train_type"),
            "selected_class": option.get("selected_class") or option.get("class_code"),
            "selected_class_name": option.get("selected_class_name") or option.get("class_name"),
            "class_name": option.get("class_name") or option.get("selected_class_name"),
            "class_code": option.get("class_code") or option.get("selected_class"),
            "price": option.get("price"),
            "source": option.get("source"),
            "destination": option.get("destination"),
            "from_station_code": option.get("boarding_station_code") or option.get("boarding_station") or option.get("from_station_code") or option.get("from_code") or option.get("source"),
            "to_station_code": option.get("alighting_station_code") or option.get("alighting_station") or option.get("to_station_code") or option.get("to_code") or option.get("destination"),
            "from_station_name": option.get("boarding_station_name") or option.get("from_station_name") or option.get("origin_station_name"),
            "to_station_name": option.get("alighting_station_name") or option.get("to_station_name") or option.get("destination_station_name"),
            "boarding_station": option.get("boarding_station") or option.get("boarding_station_code") or option.get("from_station_code") or option.get("from_code"),
            "alighting_station": option.get("alighting_station") or option.get("alighting_station_code") or option.get("to_station_code") or option.get("to_code"),
            "boarding_station_code": option.get("boarding_station_code") or option.get("boarding_station") or option.get("from_station_code") or option.get("from_code"),
            "alighting_station_code": option.get("alighting_station_code") or option.get("alighting_station") or option.get("to_station_code") or option.get("to_code"),
            "boarding_station_name": option.get("boarding_station_name") or option.get("from_station_name"),
            "alighting_station_name": option.get("alighting_station_name") or option.get("to_station_name"),
            "train_origin_station": option.get("train_origin_station"),
            "train_destination_station": option.get("train_destination_station"),
            "boarding_index": option.get("boarding_index"),
            "alighting_index": option.get("alighting_index"),
            "train_route_summary": option.get("train_route_summary"),
            "actual_origin_station": option.get("boarding_station_code") or option.get("boarding_station") or option.get("actual_origin_station") or option.get("from_station_code") or option.get("from_code"),
            "actual_destination_station": option.get("alighting_station_code") or option.get("alighting_station") or option.get("actual_destination_station") or option.get("to_station_code") or option.get("to_code"),
            "actual_train_origin": option.get("actual_train_origin") or option.get("actual_origin_station") or option.get("from_station_name") or option.get("from_station_code"),
            "actual_train_destination": option.get("actual_train_destination") or option.get("actual_destination_station") or option.get("to_station_name") or option.get("to_station_code"),
            "user_origin": option.get("user_origin"),
            "user_destination": option.get("user_destination"),
            "first_mile_transfer": option.get("first_mile_transfer"),
            "last_mile_transfer": option.get("last_mile_transfer"),
            "origin": option.get("origin") or option.get("boarding_station_code") or option.get("from_station_code") or option.get("from_code") or option.get("source"),
            "departure_time": option.get("departure_time"),
            "arrival_time": option.get("arrival_time"),
            "duration_minutes": option.get(
                "duration_minutes"
            ),
            "distance_km": option.get(
                "distance_km"
            ),
            "classes": option.get(
                "classes",
                []
            ),
            "fares": option.get(
                "fares",
                []
            ),
            "availability": option.get(
                "availability",
                []
            ),
            "provider": option.get(
                "provider"
            ),
            "transfer": option.get(
                "transfer"
            ),
            "outbound_transfer": option.get(
                "outbound_transfer"
            ) or option.get("transfer"),
            "return_transfer": option.get(
                "return_transfer"
            ),
            "return_trip": cleaned_return,
        }

    # ---------------------------------------------------------
    # FLIGHT
    # ---------------------------------------------------------

    if option.get("flight_number") or option.get("type") == "flight" or option.get("airline") or option.get("flight_name"):
        f_num = str(option.get("flight_number") or "").strip()
        f_airline = str(option.get("airline") or "").strip()
        if not f_airline:
            if f_num.startswith("AI"):
                f_airline = "Air India"
            elif f_num.startswith("6E"):
                f_airline = "IndiGo"
            elif f_num.startswith("SG"):
                f_airline = "SpiceJet"
            elif f_num.startswith("UK"):
                f_airline = "Vistara"
            elif f_num.startswith("QP"):
                f_airline = "Akasa Air"
            else:
                f_airline = "Flight"

        raw_n = option.get("flight_name") or option.get("name")
        if raw_n and str(raw_n).strip().lower() not in ("flight", "none", "unknown", "null", ""):
            f_name = str(raw_n).strip()
        elif f_airline and f_num:
            f_name = f"{f_airline} {f_num}".strip()
        elif f_num:
            f_name = f"Flight {f_num}"
        else:
            f_name = f"{f_airline} Flight"

        f_price = option.get("price")
        if f_price is None and isinstance(option.get("fare"), dict):
            f_price = option.get("fare", {}).get("amount")

        return {
            "type": "flight",
            "name": f_name,
            "flight_name": f_name,
            "flight_number": option.get(
                "flight_number"
            ),
            "airline": f_airline,
            "selected_class": option.get("selected_class") or option.get("cabin_class") or "ECONOMY",
            "selected_class_name": option.get("selected_class_name") or option.get("class_name") or "Economy Class",
            "cabin_class": option.get("cabin_class") or option.get("selected_class") or "Economy Class",
            "class_name": option.get("class_name") or option.get("selected_class_name") or "Economy Class",
            "source": option.get(
                "source"
            ),
            "destination": option.get(
                "destination"
            ),
            "from_station_code": option.get("from_station_code") or option.get("from_code") or option.get("source"),
            "to_station_code": option.get("to_station_code") or option.get("to_code") or option.get("destination"),
            "from_station_name": option.get("from_station_name") or option.get("origin_station_name"),
            "to_station_name": option.get("to_station_name") or option.get("destination_station_name"),
            "actual_origin_station": option.get("actual_origin_station") or option.get("actual_train_origin") or option.get("from_station_name") or option.get("from_station_code"),
            "actual_destination_station": option.get("actual_destination_station") or option.get("actual_train_destination") or option.get("to_station_name") or option.get("to_station_code"),
            "actual_train_origin": option.get("actual_train_origin") or option.get("actual_origin_station") or option.get("from_station_name") or option.get("from_station_code"),
            "actual_train_destination": option.get("actual_train_destination") or option.get("actual_destination_station") or option.get("to_station_name") or option.get("to_station_code"),
            "user_origin": option.get("user_origin"),
            "user_destination": option.get("user_destination"),
            "first_mile_transfer": option.get("first_mile_transfer"),
            "last_mile_transfer": option.get("last_mile_transfer"),
            "origin": option.get("origin") or option.get("from_station_code") or option.get("from_code") or option.get("source"),
            "departure_time": option.get(
                "departure_time"
            ),
            "arrival_time": option.get(
                "arrival_time"
            ),
            "duration_minutes": option.get(
                "duration_minutes"
            ),
            "price": f_price,
            "currency": option.get(
                "currency",
                "INR"
            ),
            "provider": option.get(
                "provider"
            ),
            "transfer": option.get(
                "transfer"
            ),
            "outbound_transfer": option.get(
                "outbound_transfer"
            ) or option.get("transfer"),
            "return_transfer": option.get(
                "return_transfer"
            ),
            "return_trip": cleaned_return,
        }

    return {}


# =========================================================
# TRANSPORT SELECTION FORMATTER
# =========================================================

def _format_transport_option_for_selection(option: dict, mode: str = "train") -> dict:
    """
    Format transport option for explicit user selection.
    Extracts authentic available classes/cabins and their respective fares.
    """
    option = _to_dict(option)
    if not isinstance(option, dict):
        return {}

    cleaned = _clean_transport_option(option)
    is_train = mode == "train" or option.get("type") == "train" or bool(option.get("train_number"))

    available_classes = []
    seen_classes = set()

    fares = option.get("fares") or []
    if isinstance(fares, list) and fares:
        for f in fares:
            f_dict = _to_dict(f)
            if not isinstance(f_dict, dict):
                continue
            ccode = str(f_dict.get("class_code") or f_dict.get("class") or f_dict.get("code") or "").strip().upper()
            amt = f_dict.get("amount") or f_dict.get("fare") or f_dict.get("price")
            if ccode and amt is not None and ccode not in seen_classes:
                try:
                    amt_f = float(amt)
                    if amt_f > 0:
                        c_name = format_transport_class_name(ccode, mode="train" if is_train else "flight")
                        available_classes.append({
                            "class_code": ccode,
                            "code": ccode,
                            "class_name": c_name,
                            "name": c_name,
                            "fare": amt_f,
                            "currency": f_dict.get("currency", "INR"),
                            "status": "AVAILABLE",
                        })
                        seen_classes.add(ccode)
                except (ValueError, TypeError):
                    pass

    # If classes list exists but no fares list, build class entries
    if not available_classes:
        raw_classes = option.get("classes") or []
        base_price = float(option.get("price") or (800.0 if is_train else 4500.0))
        if isinstance(raw_classes, list) and raw_classes:
            for c in raw_classes:
                ccode = str(c).strip().upper()
                if ccode and ccode not in seen_classes:
                    c_name = format_transport_class_name(ccode, mode="train" if is_train else "flight")
                    mult = 1.0
                    if is_train:
                        mult_map = {"SL": 1.0, "3E": 2.4, "3A": 2.5, "2A": 3.6, "1A": 6.0, "CC": 1.8, "EC": 3.2, "2S": 0.4}
                        mult = mult_map.get(ccode, 1.0)
                    available_classes.append({
                        "class_code": ccode,
                        "code": ccode,
                        "class_name": c_name,
                        "name": c_name,
                        "fare": round(base_price * mult, 2),
                        "currency": "INR",
                        "status": "AVAILABLE",
                    })
                    seen_classes.add(ccode)
        else:
            def_code = "SL" if is_train else "ECONOMY"
            available_classes.append({
                "class_code": def_code,
                "code": def_code,
                "class_name": format_transport_class_name(def_code, mode="train" if is_train else "flight"),
                "name": format_transport_class_name(def_code, mode="train" if is_train else "flight"),
                "fare": base_price,
                "currency": "INR",
                "status": "AVAILABLE",
            })

    cleaned["available_classes"] = available_classes
    return cleaned


# =========================================================
# HOTEL CLEANER
# =========================================================


def _clean_hotel_option(hotel) -> dict:
    """
    Convert internal HotelOption object into
    clean public API response.

    Supports:

    - Pydantic HotelOption
    - dict
    """

    if hotel is None:
        return {}

    # ---------------------------------------------------------
    # PYDANTIC MODEL -> DICT
    # ---------------------------------------------------------

    hotel = _to_dict(hotel)

    # ---------------------------------------------------------
    # INVALID DATA
    # ---------------------------------------------------------

    if not isinstance(hotel, dict):
        return {}

    # ---------------------------------------------------------
    # CLEAN PUBLIC HOTEL RESPONSE
    # ---------------------------------------------------------

    h_name = hotel.get("hotel_name") or hotel.get("name")
    h_address = hotel.get("address") or hotel.get("location")
    h_id = hotel.get("hotel_id") or hotel.get("id")
    tier = hotel.get("tier") or str(hotel.get("budget_category", "")).upper() or "MEDIUM"
    budget_cat = hotel.get("budget_category") or tier.lower()

    return {
        "hotel_id": h_id,
        "id": h_id,
        "hotel_name": h_name,
        "name": h_name,
        "tier": tier,
        "budget_category": budget_cat,
        "rating": hotel.get(
            "rating"
        ),
        "address": h_address,
        "location": h_address,
        "latitude": hotel.get("latitude") or hotel.get("lat"),
        "longitude": hotel.get("longitude") or hotel.get("lon") or hotel.get("lng"),
        "photo": hotel.get(
            "photo"
        ),
        "room_name": hotel.get(
            "room_name"
        ),
        "board_name": hotel.get(
            "board_name"
        ),
        "price": hotel.get(
            "price"
        ),
        "price_per_night": hotel.get(
            "price_per_night"
        ),
        "currency": hotel.get(
            "currency",
            "INR"
        ),
        "taxes": hotel.get(
            "taxes"
        ),
        "cancellation": hotel.get(
            "cancellation"
        ),
        "cancellation_deadline": hotel.get(
            "cancellation_deadline"
        ),
        "provider": hotel.get(
            "provider"
        ),
    }


# =========================================================
# PLACE CLEANER
# =========================================================


def _clean_place_option(place: dict) -> dict:
    """
    Expose useful place information
    and hide provider internals.
    """

    place = _to_dict(place)

    if not isinstance(place, dict):
        return {}

    category = place.get(
        "category"
    )

    if category is None:

        category = place.get(
            "categories",
            []
        )

    return {
        "place_id": (
            place.get("place_id")
            or place.get("id")
        ),
        "name": place.get(
            "name"
        ),
        "category": category,
        "address": place.get(
            "address"
        ),
        "city": place.get(
            "city"
        ),
        "state": place.get(
            "state"
        ),
        "country": place.get(
            "country"
        ),
        "latitude": place.get(
            "latitude"
        ),
        "longitude": place.get(
            "longitude"
        ),
        "distance_meters": place.get(
            "distance_meters"
        ),
        "rank": place.get(
            "rank"
        ),
    }


# =========================================================
# WEATHER CLEANER
# =========================================================


def _parse_weather_sort_date(item) -> date:
    if not isinstance(item, dict):
        return date.min
    d_val = item.get("date")
    if isinstance(d_val, date):
        return d_val
    if hasattr(d_val, "date") and callable(d_val.date):
        return d_val.date()
    if d_val:
        d_str = str(d_val).strip()[:10]
        try:
            return date.fromisoformat(d_str)
        except Exception:
            for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
                try:
                    return datetime.strptime(d_str, fmt).date()
                except Exception:
                    continue
    return date.min


def _clean_weather(weather: dict) -> dict:
    """
    Return only user-facing weather data.
    """

    weather = _to_dict(weather)

    if not isinstance(weather, dict):

        return {
            "status": "unavailable",
            "forecast": [],
        }

    forecast = weather.get(
        "forecast"
    )

    if forecast is None:

        forecast = weather.get(
            "daily",
            []
        )

    if isinstance(forecast, list) and forecast:
        before_dates = [str(x.get("date")) for x in forecast if isinstance(x, dict)]
        forecast = sorted(forecast, key=_parse_weather_sort_date)
        after_dates = [str(x.get("date")) for x in forecast if isinstance(x, dict)]

        print("\nWEATHER ORDERING")
        print("----------------")
        print(f"Before: {before_dates}")
        print(f"After:  {after_dates}\n")

    result = {
        "status": weather.get(
            "status",
            "unavailable"
        ),
        "forecast": forecast,
    }

    if weather.get(
        "location"
    ) is not None:

        result["location"] = (
            weather.get("location")
        )

    return result


# =========================================================
# ITINERARY CLEANER
# =========================================================


def _clean_itinerary(itinerary: dict) -> dict:
    """
    Return itinerary without internal workflow metadata.
    """

    itinerary = _to_dict(itinerary)

    if not isinstance(itinerary, dict):

        return {
            "status": "unavailable",
            "days": [],
        }

    clean_days = []

    for day in itinerary.get(
        "days",
        []
    ):

        day = _to_dict(day)

        if not isinstance(day, dict):
            continue

        activities = []

        for activity in day.get(
            "activities",
            []
        ):

            activity = _to_dict(
                activity
            )

            if not isinstance(
                activity,
                dict
            ):
                continue

            activities.append(
                {
                    "place_id": (
                        activity.get(
                            "place_id"
                        )
                        or activity.get(
                            "id"
                        )
                    ),
                    "name": activity.get(
                        "name"
                    ),
                    "category": (
                        activity.get(
                            "category"
                        )
                        or activity.get(
                            "categories",
                            []
                        )
                    ),
                    "date": activity.get("date"),
                    "start_time": (
                        activity.get(
                            "start_time"
                        )
                    ),
                    "duration_minutes": (
                        activity.get(
                            "duration_minutes"
                        )
                    ),
                    "duration": activity.get("duration"),
                    "estimated_cost": (
                        activity.get(
                            "estimated_cost",
                            0,
                        )
                    ),
                    "optimization_score": (
                        activity.get(
                            "optimization_score",
                            0,
                        )
                    ),
                }
            )

        clean_days.append(
            {
                "day": (
                    day.get("day")
                    or day.get(
                        "day_number"
                    )
                ),
                "date": day.get(
                    "date"
                ),
                "status": day.get(
                    "status",
                    "full_day",
                ),
                "travel_constraint": day.get(
                    "travel_constraint"
                ),
                "transport": day.get(
                    "transport"
                ),
                "activities": activities,
            }
        )

    return {
        "status": itinerary.get(
            "status",
            "draft"
        ),
        "start_date": itinerary.get(
            "start_date"
        ),
        "end_date": itinerary.get(
            "end_date"
        ),
        "total_days": itinerary.get(
            "total_days"
        ),
        "total_nights": itinerary.get(
            "total_nights",
            max(1, itinerary.get("total_days", 1) - 1)
        ),
        "hotel_nights": itinerary.get(
            "hotel_nights"
        ),
        "hotel_price_per_night": itinerary.get(
            "hotel_price_per_night"
        ),
        "transport_timing": itinerary.get(
            "transport_timing",
            {}
        ),
        "hotel_timing": itinerary.get(
            "hotel_timing",
            {}
        ),
        "days": clean_days,
        "travelers_count": (
            itinerary.get(
                "travelers_count",
                1,
            )
        ),
        "transport_class": (
            itinerary.get(
                "transport_class"
            )
        ),
        "transport_class_code": (
            itinerary.get(
                "transport_class_code"
            )
        ),
        "return_transport_class": (
            itinerary.get(
                "return_transport_class"
            )
        ),
        "return_transport_class_code": (
            itinerary.get(
                "return_transport_class_code"
            )
        ),
        "outbound_transport_price": (
            itinerary.get(
                "outbound_transport_price",
                0,
            )
        ),
        "return_transport_price": (
            itinerary.get(
                "return_transport_price",
                0,
            )
        ),
        "total_transport_per_traveler": (
            itinerary.get(
                "total_transport_per_traveler",
                0,
            )
        ),
        "estimated_transport": (
            itinerary.get(
                "estimated_transport",
                0
            )
        ),
        "estimated_hotel": (
            itinerary.get(
                "estimated_hotel",
                0
            )
        ),
        "estimated_activities": (
            itinerary.get(
                "estimated_activities",
                "Not included"
            )
        ),
        "food_local_transport": (
            itinerary.get(
                "food_local_transport",
                "Not included (Self-managed)"
            )
        ),
        "calculated_cost": (
            itinerary.get(
                "calculated_cost"
            )
            or itinerary.get(
                "estimated_cost",
                0
            )
        ),
        "estimated_cost": (
            itinerary.get(
                "estimated_cost",
                0
            )
        ),
        "budget_limit": (
            itinerary.get(
                "budget_limit",
                0
            )
        ),
        "remaining_budget": (
            itinerary.get(
                "remaining_budget",
                0
            )
        ),
        "currency": (
            itinerary.get(
                "currency",
                "INR"
            )
        ),
        "hotel": _clean_hotel_option(
            itinerary.get("hotel")
        ) if itinerary.get("hotel") else {},
        "transport": _clean_transport_option(
            itinerary.get("transport")
        ) if itinerary.get("transport") else {},
        "transfer": itinerary.get("transfer") or itinerary.get("outbound_transfer") or (
            itinerary.get("transport", {}).get("transfer")
            if isinstance(itinerary.get("transport"), dict)
            else None
        ),
        "outbound_transfer": itinerary.get("outbound_transfer") or itinerary.get("transfer") or (
            itinerary.get("transport", {}).get("outbound_transfer")
            if isinstance(itinerary.get("transport"), dict)
            else None
        ),
        "return_transfer": itinerary.get("return_transfer") or (
            itinerary.get("transport", {}).get("return_transfer")
            if isinstance(itinerary.get("transport"), dict)
            else None
        ) or (
            itinerary.get("transport", {}).get("return_trip", {}).get("transfer")
            if isinstance(itinerary.get("transport"), dict) and isinstance(itinerary.get("transport", {}).get("return_trip"), dict)
            else None
        ),
    }


# =========================================================
# TRAVEL OPTION CLEANER
# =========================================================


def _clean_travel_option(
    option: dict
) -> dict:
    """
    Convert internal generated travel option
    into public API response.
    """

    option = _to_dict(option)

    if not isinstance(option, dict):
        return {}

    transport = option.get(
        "transport"
    )

    hotel = option.get(
        "hotel"
    )

    return {
        "option_id": option.get(
            "option_id"
        ),

        "option_number": option.get(
            "option_number"
        ),

        "transport": (
            _clean_transport_option(
                transport
            )
            if transport
            else {}
        ),

        "hotel": (
            _clean_hotel_option(
                hotel
            )
            if hotel
            else {}
        ),

        "estimated_transport": (
            option.get(
                "estimated_transport",
                0
            )
        ),

        "estimated_hotel": (
            option.get(
                "estimated_hotel",
                0
            )
        ),

        "estimated_cost": (
            option.get(
                "estimated_cost",
                0
            )
        ),

        "budget_remaining": (
            option.get(
                "budget_remaining",
                0
            )
        ),

        "currency": (
            option.get(
                "currency",
                "INR"
            )
        ),

        "reason": option.get(
            "reason"
        ),
    }


# =========================================================
# CREATE TRIP
# =========================================================


@router.post(
    "/",
    response_model=TripResponse,
)
async def create_new_trip(
    trip_data: TripCreate,
    current_user=Depends(
        get_current_user
    ),
    db: Session = Depends(
        get_db
    ),
):

    trip = create_trip(
        db=db,
        trip_data=trip_data,
        user_id=int(
            current_user[
                "user_id"
            ]
        ),
    )

    audit_log(
        action="TRIP_CREATED",
        user_id=str(
            current_user[
                "user_id"
            ]
        ),
        details=(
            f"trip_id={trip.id}"
        ),
    )

    return trip


# =========================================================
# GET MY TRIPS
# =========================================================


@router.get(
    "/",
    response_model=list[TripResponse],
)
async def get_my_trips(
    current_user=Depends(
        get_current_user
    ),
    db: Session = Depends(
        get_db
    ),
):

    trips = get_user_trips(
        db=db,
        user_id=int(
            current_user[
                "user_id"
            ]
        ),
    )

    return trips


# =========================================================
# GET SINGLE TRIP
# =========================================================


@router.get(
    "/{trip_id}",
    response_model=TripResponse,
)
async def get_single_trip(
    trip_id: int,
    current_user=Depends(
        get_current_user
    ),
    db: Session = Depends(
        get_db
    ),
):

    trip = get_user_trip(
        db=db,
        trip_id=trip_id,
        user_id=int(
            current_user[
                "user_id"
            ]
        ),
    )

    if not trip:

        raise HTTPException(
            status_code=404,
            detail="Trip not found",
        )

    return trip


# =========================================================
# UPDATE TRIP
# =========================================================


@router.put(
    "/{trip_id}",
    response_model=TripResponse,
)
async def update_existing_trip(
    trip_id: int,
    trip_data: TripCreate,
    current_user=Depends(
        get_current_user
    ),
    db: Session = Depends(
        get_db
    ),
):

    trip = update_trip(
        db=db,
        trip_id=trip_id,
        user_id=int(
            current_user[
                "user_id"
            ]
        ),
        trip_data=trip_data,
    )

    if not trip:

        raise HTTPException(
            status_code=404,
            detail="Trip not found",
        )

    audit_log(
        action="TRIP_UPDATED",
        user_id=str(
            current_user[
                "user_id"
            ]
        ),
        details=(
            f"trip_id={trip.id}"
        ),
    )

    return trip


# =========================================================
# DELETE TRIP
# =========================================================


@router.delete(
    "/{trip_id}"
)
async def delete_existing_trip(
    trip_id: int,
    current_user=Depends(
        get_current_user
    ),
    db: Session = Depends(
        get_db
    ),
):

    trip = delete_trip(
        db=db,
        trip_id=trip_id,
        user_id=int(
            current_user[
                "user_id"
            ]
        ),
    )

    if not trip:

        raise HTTPException(
            status_code=404,
            detail="Trip not found",
        )

    audit_log(
        action="TRIP_DELETED",
        user_id=str(
            current_user[
                "user_id"
            ]
        ),
        details=(
            f"trip_id={trip_id}"
        ),
    )

    return {
        "message": (
            "Trip deleted successfully"
        ),
        "trip_id": trip_id,
    }


# =========================================================
# CHANGE TRIP STATUS
# =========================================================


@router.patch(
    "/{trip_id}/status",
    response_model=TripResponse,
)
async def change_trip_status(
    trip_id: int,
    status_data: TripStatusUpdate,
    current_user=Depends(
        get_current_user
    ),
    db: Session = Depends(
        get_db
    ),
):

    try:

        trip = update_trip_status(
            db=db,
            trip_id=trip_id,
            user_id=int(
                current_user[
                    "user_id"
                ]
            ),
            new_status=(
                status_data.status
            ),
        )

    except ValueError as exc:

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    if not trip:

        raise HTTPException(
            status_code=404,
            detail="Trip not found",
        )

    audit_log(
        action="TRIP_STATUS_CHANGED",
        user_id=str(
            current_user[
                "user_id"
            ]
        ),
        details=(
            f"trip_id={trip.id}, "
            f"status={trip.status.value}"
        ),
    )

    return trip


# =========================================================
# SEARCH TRANSPORT (OUTBOUND / RETURN OPTIONS)
# =========================================================

@router.post("/search-transport")
async def search_transport_options(
    request: TransportSearchApiRequest,
    current_user=Depends(get_current_user),
):
    """
    Discover available transport options for a specific leg (outbound or return).
    Does NOT select or lock an option - returns available_options[] with available_classes[].
    """
    try:
        origin = resolve_location(request.origin)
        destination = resolve_location(request.destination)
    except Exception as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Unable to resolve locations: {exc}",
        )

    mode = request.transport_mode.lower()
    dep_date_str = request.departure_date.isoformat()
    direction = request.direction.lower()

    access_resolver = TransportAccessResolver()
    train_service = TrainService()
    flight_service = FlightService()

    options_list = []

    if mode == "train":
        if direction == "return":
            # Reverse search: user journey from request.origin (e.g. Manali) back to request.destination (e.g. Mumbai)
            orig_candidates = access_resolver.discover_candidates(
                origin.name, mode="train", geo_coords=(origin.latitude, origin.longitude)
            )
            dest_candidates = access_resolver.discover_candidates(
                destination.name, mode="train", geo_coords=(destination.latitude, destination.longitude)
            )

            selected_out_orig = None
            selected_out_dest = None
            if request.outbound_origin_code:
                selected_out_orig = {"code": request.outbound_origin_code, "name": request.outbound_origin_code}
            if request.outbound_destination_code:
                selected_out_dest = {"code": request.outbound_destination_code, "name": request.outbound_destination_code}

            ranked_pairs = access_resolver.rank_return_candidate_pairs(
                orig_candidates, dest_candidates, selected_out_orig=selected_out_orig, selected_out_dest=selected_out_dest
            )

            found_trains = []
            for r_orig_c, r_dest_c, score in ranked_pairs:
                if found_trains:
                    break
                try:
                    res = train_service.search_trains(
                        from_code=r_orig_c["code"],
                        to_code=r_dest_c["code"],
                        date=dep_date_str,
                    )
                    if res:
                        found_trains = res
                        ret_fm = access_resolver.create_transfer_info(
                            origin.name, r_orig_c, geo_info=access_resolver.geocode_location(origin.name), is_origin=True, mode="train"
                        )
                        ret_lm = access_resolver.create_transfer_info(
                            destination.name, r_dest_c, geo_info=access_resolver.geocode_location(destination.name), is_origin=False, mode="train"
                        )
                        for t in found_trains:
                            t_d = t.model_dump() if hasattr(t, "model_dump") else (dict(t) if isinstance(t, dict) else {})
                            if ret_fm:
                                t_d["first_mile_transfer"] = ret_fm
                                t_d["transfer"] = ret_fm
                            if ret_lm:
                                t_d["last_mile_transfer"] = ret_lm
                                t_d["return_transfer"] = ret_lm
                            t_d["journey_type"] = "return"
                            options_list.append(_format_transport_option_for_selection(t_d, mode="train"))
                        break
                except Exception as exc:
                    continue
        else:
            # Outbound search
            res = access_resolver.resolve_and_validate(
                user_origin=origin.name,
                user_destination=destination.name,
                transport_type="train",
                departure_date=dep_date_str,
                train_service=train_service,
                flight_service=flight_service,
                adults=request.adults,
                children=request.children,
                orig_location=origin,
                dest_location=destination,
            )
            raw_options = res.get("outbound_options", [])
            for opt in raw_options:
                opt_d = opt.model_dump() if hasattr(opt, "model_dump") else (dict(opt) if isinstance(opt, dict) else {})
                opt_d["journey_type"] = "outbound"
                options_list.append(_format_transport_option_for_selection(opt_d, mode="train"))

    else:
        # Flight mode
        from app.resolvers.airport_resolver import AirportResolver
        airport_resolver = AirportResolver()
        if direction == "return":
            route = airport_resolver.resolve_route(origin=destination.name, destination=origin.name)
        else:
            route = airport_resolver.resolve_route(origin=origin.name, destination=destination.name)

        freq = FlightSearchRequest(
            from_code=route["origin"]["code"],
            to_code=route["destination"]["code"],
            date=request.departure_date,
            adults=request.adults,
            children=request.children,
            cabin_class="ECONOMY",
            currency="INR",
        )
        try:
            flights = flight_service.search_flights(freq)
            for f in flights:
                f_dict = f.model_dump() if hasattr(f, "model_dump") else (dict(f) if isinstance(f, dict) else {})
                f_dict["from_station_code"] = route["origin"]["code"]
                f_dict["to_station_code"] = route["destination"]["code"]
                f_dict["from_station_name"] = route["origin"]["name"]
                f_dict["to_station_name"] = route["destination"]["name"]
                f_dict["journey_type"] = direction
                options_list.append(_format_transport_option_for_selection(f_dict, mode="flight"))
        except Exception as exc:
            pass

    return {
        "success": True,
        "mode": mode,
        "direction": direction,
        "count": len(options_list),
        "options": options_list,
    }


# =========================================================
# PREVIEW BUDGET (FARE + BUDGET CALCULATION)
# =========================================================

@router.post("/preview-budget")
async def preview_budget_endpoint(
    request: BudgetPreviewApiRequest,
    current_user=Depends(get_current_user),
):
    """
    Calculate and preview exact trip costs after explicit transport selection.
    """
    traveler_count = max(1, request.adults + request.children)
    outbound_total = float(request.outbound_fare) * traveler_count
    return_total = float(request.return_fare) * traveler_count
    transport_total = round(outbound_total + return_total, 2)

    total_nights = request.nights or 1
    if request.start_date and request.end_date:
        total_nights = max(1, (request.end_date - request.start_date).days)

    if request.estimated_hotel_rate is not None:
        hotel_total = round(float(request.estimated_hotel_rate) * total_nights, 2)
    elif request.destination and request.start_date and request.end_date:
        hotel_total = 4933.0
        try:
            from app.services.hotel.hotel_service import HotelService
            from app.services.hotel.hotel_schema import HotelSearchRequest
            h_req = HotelSearchRequest(
                city=request.destination,
                check_in_date=request.start_date,
                check_out_date=request.end_date,
                adults=request.adults,
                children=request.children,
                rooms=1,
            )
            hotels = HotelService().search_hotels(h_req)
            if hotels and len(hotels) > 0:
                hotel_total = round(float(hotels[0].price or (hotels[0].price_per_night * total_nights)), 2)
        except Exception:
            hotel_total = round(3500.0 * total_nights, 2)
    else:
        hotel_total = round(3500.0 * total_nights, 2)

    calculated_trip_cost = round(transport_total + hotel_total, 2)
    budget_limit = float(request.budget) if request.budget is not None else None
    remaining_budget = round(budget_limit - calculated_trip_cost, 2) if budget_limit is not None else None
    budget_exceeded = bool(remaining_budget is not None and remaining_budget < 0)

    return {
        "success": True,
        "outbound_fare_per_traveler": float(request.outbound_fare),
        "return_fare_per_traveler": float(request.return_fare),
        "traveler_count": traveler_count,
        "travelers_count": traveler_count,
        "nights": total_nights,
        "transport_total": transport_total,
        "hotel_total": hotel_total,
        "estimated_hotel": hotel_total,
        "calculated_trip_cost": calculated_trip_cost,
        "budget": budget_limit,
        "total_budget": budget_limit,
        "remaining_budget": remaining_budget,
        "budget_exceeded": budget_exceeded,
        "currency": "INR",
    }


# =========================================================
# PLAN TRIP
# =========================================================

def _reset_trip_to_draft(
    db: Session,
    trip_id: int,
    user_id: int,
    planning_id: str | None = None,
    reason: str = "planning_failed",
):
    """Reset a failed planning attempt without deleting the Trip."""
    try:
        reset_trip = update_trip_status(
            db=db,
            trip_id=int(trip_id),
            user_id=int(user_id),
            new_status=TripStatus.DRAFT,
        )

        if reset_trip:
            audit_log(
                action="TRIP_PLANNING_RESET",
                user_id=str(user_id),
                details=(
                    f"trip_id={trip_id}, "
                    f"planning_id={planning_id}, "
                    f"reason={reason}, "
                    "status=DRAFT"
                ),
            )

        return reset_trip

    except Exception as reset_exc:
        print(
            f"[ERROR] Failed to reset trip {trip_id} to DRAFT: "
            f"{type(reset_exc).__name__}: {reset_exc}"
        )
        return None



@router.post(
    "/plan"
)
async def plan_trip(
    request: PlanTripRequest,
    current_user=Depends(
        get_current_user
    ),
    db: Session = Depends(
        get_db
    ),
):
    """
    Create a complete trip plan in one request.
    If explicit transport selections are provided, uses them directly.

    The frontend creates the Trip master record first and sends its
    trip_id here. This endpoint verifies ownership and moves the Trip
    from DRAFT -> PLANNING before starting the agent workflow.
    """
    # =====================================================
    # STEP 0
    # LINK PLANNING REQUEST TO PERSISTED TRIP
    # =====================================================

    trip_id = getattr(request, "trip_id", None)

    if trip_id is None:
        raise HTTPException(
            status_code=400,
            detail="trip_id is required to start trip planning.",
        )

    try:
        current_user_id = int(current_user["user_id"])
    except (TypeError, ValueError):
        raise HTTPException(
            status_code=401,
            detail="Invalid authenticated user.",
        )

    trip = get_user_trip(
        db=db,
        trip_id=int(trip_id),
        user_id=current_user_id,
    )

    if not trip:
        raise HTTPException(
            status_code=404,
            detail="Trip not found.",
        )

    # A persisted trip must be in DRAFT before planning starts.
    # Use the existing service so the lifecycle rules stay centralized.
    try:
        trip = update_trip_status(
            db=db,
            trip_id=int(trip_id),
            user_id=current_user_id,
            new_status=TripStatus.PLANNING,
        )
    except ValueError as exc:
        raise HTTPException(
            status_code=400,
            detail=str(exc),
        )

    if not trip:
        raise HTTPException(
            status_code=404,
            detail="Trip not found.",
        )

    audit_log(
        action="TRIP_PLANNING_STARTED",
        user_id=str(current_user_id),
        details=f"trip_id={trip.id}",
    )

    planning_id = str(uuid4())

    from app.observability.logger import request_id_context, planning_id_context, trip_id_context
    from app.observability.metrics import observability_metrics

    req_id = request_id_context.get() or f"req-{planning_id[:8]}"
    request_id_context.set(req_id)
    planning_id_context.set(planning_id)
    trip_id_context.set(int(trip.id))

    observability_metrics.reset()
    observability_metrics.set_correlation(
        request_id=req_id,
        planning_id=planning_id,
        trip_id=int(trip.id),
        user_id=str(current_user_id),
        route=f"{request.origin} → {request.destination}",
        dates=f"{request.start_date} → {request.end_date}",
        transport=(request.transport_preference or "TRAIN").upper(),
    )
    observability_metrics.print_planning_start_header()

    calculated_traveler_count = max(1, (request.adults or 1) + (request.children or 0))
    logger.debug(
        "Trip planning parameters: planning_id=%s user_id=%s route=%s->%s dates=%s->%s pref=%s budget=%s travelers=%s (adults=%s, children=%s)",
        planning_id, current_user_id, request.origin, request.destination, request.start_date, request.end_date,
        request.transport_preference, request.budget, calculated_traveler_count, request.adults, request.children
    )

    # =====================================================
    # STEP 1
    # RESOLVE LOCATIONS
    # =====================================================

    try:
        origin = resolve_location(
            request.origin
        )

        destination = resolve_location(
            request.destination
        )

    except Exception as exc:
        logger.error("Location resolution failed: %s: %s", type(exc).__name__, exc)

        raise HTTPException(
            status_code=400,
            detail=(
                "Unable to resolve "
                "origin or destination."
            ),
        )

    logger.debug("Locations resolved: origin=%s, destination=%s", origin.name, destination.name)

    # =====================================================
    # STEP 2
    # CREATE INITIAL TRIP STATE (WITH CONFIRMED TRANSPORT IF PROVIDED)
    # =====================================================

    outbound_transport = _to_dict(request.selected_outbound_transport) if request.selected_outbound_transport else None
    return_transport = _to_dict(request.selected_return_transport) if request.selected_return_transport else None

    # Strict transport confirmation gate validation
    if request.selected_outbound_transport is not None:
        if not request.selected_outbound_class:
            _reset_trip_to_draft(
                db=db,
                trip_id=int(trip.id),
                user_id=current_user_id,
                planning_id=planning_id,
                reason="missing_outbound_class",
            )
            raise HTTPException(
                status_code=400,
                detail="Outbound transport class selection is required. Trip has been reset to DRAFT.",
            )
        if not return_transport:
            _reset_trip_to_draft(
                db=db,
                trip_id=int(trip.id),
                user_id=current_user_id,
                planning_id=planning_id,
                reason="missing_return_transport",
            )
            raise HTTPException(
                status_code=400,
                detail="No verified return transport is currently available for the selected date. Confirmed round-trip transport selection is required. Trip has been reset to DRAFT.",
            )
        if isinstance(return_transport, dict) and (return_transport.get("status") == "unavailable" or return_transport.get("transport_unavailable") is True):
            raise HTTPException(
                status_code=400,
                detail="No verified return transport is currently available for the selected date. Confirmed round-trip transport selection is required.",
            )
        if not request.selected_return_class:
            _reset_trip_to_draft(
                db=db,
                trip_id=int(trip.id),
                user_id=current_user_id,
                planning_id=planning_id,
                reason="missing_return_class",
            )
            raise HTTPException(
                status_code=400,
                detail="Return transport class selection is required. Trip has been reset to DRAFT.",
            )

    if outbound_transport and isinstance(outbound_transport, dict):
        if request.selected_outbound_class:
            outbound_transport["selected_class"] = request.selected_outbound_class
            outbound_transport["class_code"] = request.selected_outbound_class
        if request.selected_outbound_fare is not None:
            outbound_transport["price"] = request.selected_outbound_fare
            outbound_transport["selected_fare"] = request.selected_outbound_fare

    if return_transport and isinstance(return_transport, dict):
        if request.selected_return_class:
            return_transport["selected_class"] = request.selected_return_class
            return_transport["class_code"] = request.selected_return_class
        if request.selected_return_fare is not None:
            return_transport["price"] = request.selected_return_fare
            return_transport["selected_fare"] = request.selected_return_fare

    if outbound_transport and return_transport and isinstance(outbound_transport, dict):
        outbound_transport["return_trip"] = return_transport

    transport_opts = [outbound_transport] if outbound_transport else []

    try:
        state = TripState(
            planning_id=planning_id,
            trip_id=int(trip.id),
            user_id=str(
                current_user[
                    "user_id"
                ]
            ),
            origin=origin,
            destination=destination,
            travel_dates={
                "start": request.start_date,
                "end": request.end_date,
            },
            travelers={
                "adults": request.adults,
                "children": request.children,
            },
            budget={
                "amount": request.budget,
                "currency": "INR",
            },
            preferences=request.preferences,
            transport_preference=(
                request.transport_preference
            ),
            outbound_transport=outbound_transport,
            return_transport=return_transport,
            selected_transport=outbound_transport,
            transport_options=transport_opts,
            hotel_options=[],
            place_options=[],
            weather={},
            recommendations={},
            verification={},
            travel_options=[],
            selected_options={
                "transport": outbound_transport,
                "return_transport": return_transport,
                "status": "user_selected",
            } if outbound_transport else {},
        )

        tripstate_traveler_count = max(1, (state.travelers.adults or 1) + (state.travelers.children or 0))
        logger.debug("TripState traveler_count: %s", tripstate_traveler_count)

    except Exception as exc:
        print(
            "\n========================================"
        )
        print(
            "       TRIP STATE CREATION FAILED"
        )
        print(
            "========================================"
        )

        print(
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        _reset_trip_to_draft(
            db=db,
            trip_id=int(trip.id),
            user_id=current_user_id,
            planning_id=planning_id,
            reason="trip_state_creation_failed",
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Failed to create TripState. "
                "Trip has been reset to DRAFT."
            ),
        )

    state.workflow_status = (
        "PLANNING"
    )

    # =====================================================
    # STEP 3
    # RUN PHASE 1: TRANSPORT + HOTEL OPTIONS
    # =====================================================

    try:
        print(
            "\n========================================"
        )
        print(
            "       RUNNING PHASE 1 PIPELINE"
        )
        print(
            "========================================"
        )

        orchestrator = (
            TravelOrchestrator()
        )

        state = await orchestrator.generate_options(
            state
        )

    except Exception as exc:
        print(
            "\n========================================"
        )
        print(
            "       TRIP PLANNING PHASE 1 FAILED"
        )
        print(
            "========================================"
        )

        print(
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        _reset_trip_to_draft(
            db=db,
            trip_id=int(trip.id),
            user_id=current_user_id,
            planning_id=planning_id,
            reason="phase_1_exception",
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Phase 1 trip planning failed. "
                "Trip has been reset to DRAFT."
            ),
        )

    if state.workflow_status in (
        "WORKFLOW_FAILED",
        "OPTIONS_GENERATION_FAILED",
    ):
        error_message = (
            "Trip planning workflow failed."
        )

        if state.errors:
            last_error = state.errors[-1]
            if isinstance(last_error, dict):
                error_message = last_error.get(
                    "error",
                    error_message,
                )

        _reset_trip_to_draft(
            db=db,
            trip_id=int(trip.id),
            user_id=current_user_id,
            planning_id=planning_id,
            reason="phase_1_workflow_failed",
        )

        raise HTTPException(
            status_code=500,
            detail=(
                f"{error_message} "
                "Trip has been reset to DRAFT."
            ),
        )

    # =====================================================
    # STEP 4
    # SAVE SESSION & RESPOND
    # =====================================================

    planning_session = PlanningSession(
        id=planning_id,
        trip_id=int(trip.id),
        user_id=int(current_user["user_id"]),
        state=state.model_dump(mode="json"),
        status="AWAITING_HOTEL_SELECTION",
    )

    db.add(planning_session)
    db.commit()
    db.refresh(planning_session)

    print(
        "\n========================================"
    )
    print(
        "       TRAVEL PLANNING PHASE 1 COMPLETE"
    )
    print(
        "========================================"
    )
    print(
        f"Planning ID: {planning_id}"
    )
    print(
        f"Workflow Status: {state.workflow_status}"
    )
    print(
        f"Transport Options: {len(state.transport_options)}"
    )
    print(
        f"Hotels: {len(state.hotel_options)}"
    )

    clean_hotels = [
        _clean_hotel_option(hotel)
        for hotel in getattr(state, "hotel_options", [])
    ]

    selected_transport = state.selected_transport or state.outbound_transport
    clean_transport = _clean_transport_option(selected_transport) if selected_transport else None

    return {
        "status": "AWAITING_HOTEL_SELECTION",
        "planning_id": planning_id,
        "trip_id": int(trip.id),
        "message": "Phase 1 complete. Awaiting hotel selection.",
        "selected_transport": clean_transport,
        "hotel_options": clean_hotels,
        "planning_state": {
            "origin": _to_dict(state.origin),
            "destination": _to_dict(state.destination),
            "travel_dates": _to_dict(state.travel_dates),
            "travelers": _to_dict(state.travelers),
            "budget": _to_dict(state.budget),
            "preferences": list(state.preferences or []),
            "transport_preference": state.transport_preference,
        },
    }


# =========================================================
# SELECT HOTEL OPTION
# =========================================================
#
# PHASE 2:
#
# User selects hotel
#       ↓
# selected_hotel
#       ↓
# Places + Weather
#       ↓
# Verification
#       ↓
# Aggregation
#       ↓
# Constraints
#       ↓
# Optimization
#       ↓
# Itinerary
#       ↓
# Validation
#
# =========================================================


@router.post(
    "/plan/{planning_id}/select-hotel"
)
async def select_hotel(
    planning_id: str,
    request: SelectHotelRequest,
    current_user=Depends(
        get_current_user
    ),
    db: Session = Depends(
        get_db
    ),
):

    print(
        "\n========================================"
    )
    print(
        "        HOTEL SELECTION"
    )
    print(
        "========================================"
    )

    print(
        f"Planning ID: "
        f"{planning_id}"
    )

    print(
        f"Selected hotel: "
        f"{request.hotel_id}"
    )

    # =====================================================
    # STEP 1
    # GET PLANNING SESSION
    # =====================================================

    session = (
        db.query(PlanningSession)
        .filter(PlanningSession.id == planning_id)
        .first()
    )

    if session is None:

        raise HTTPException(
            status_code=404,
            detail=(
                "Planning session not found "
                "or expired."
            ),
        )

    # =====================================================
    # STEP 2
    # OWNERSHIP CHECK
    # =====================================================

    session_user_id = str(session.user_id)

    current_user_id = str(
        current_user[
            "user_id"
        ]
    )

    if session_user_id != current_user_id:

        raise HTTPException(
            status_code=403,
            detail=(
                "You are not allowed "
                "to access this planning session."
            ),
        )

    # =====================================================
    # STEP 2.5
    # VERIFY LINKED TRIP
    # =====================================================

    session_trip_id = session.trip_id

    if session_trip_id is None:
        raise HTTPException(
            status_code=400,
            detail="Planning session is not linked to a trip.",
        )

    trip = get_user_trip(
        db=db,
        trip_id=int(session_trip_id),
        user_id=int(current_user["user_id"]),
    )

    if not trip:
        raise HTTPException(
            status_code=404,
            detail="Linked trip not found.",
        )

    # The planning session must belong to a trip that is currently
    # in the PLANNING lifecycle state.
    if trip.status != TripStatus.PLANNING:
        raise HTTPException(
            status_code=400,
            detail=(
                f"Trip {trip.id} is not in PLANNING status. "
                f"Current status: {trip.status.value}"
            ),
        )

    try:
        state: TripState = TripState.model_validate(session.state)
    except Exception as exc:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to restore planning state: {exc}",
        )

    if not state.planning_id:
        state.planning_id = str(planning_id)
    if not state.trip_id:
        state.trip_id = int(session_trip_id)

    from app.observability.logger import request_id_context, planning_id_context, trip_id_context
    from app.observability.metrics import observability_metrics

    req_id = request_id_context.get() or f"req-{str(planning_id)[:8]}"
    request_id_context.set(req_id)
    planning_id_context.set(str(planning_id))
    trip_id_context.set(int(session_trip_id))

    observability_metrics.set_correlation(
        request_id=req_id,
        planning_id=str(planning_id),
        trip_id=int(session_trip_id),
        user_id=str(current_user["user_id"]),
    )

    # =====================================================
    # STEP 4
    # CHECK OPTION
    # =====================================================

    selected_hotel = None

    for option in getattr(
        state,
        "hotel_options",
        []
    ):

        option_dict = _to_dict(
            option
        )

        if not isinstance(
            option_dict,
            dict
        ):
            continue

        if (
            str(option_dict.get(
                "hotel_id"
            ))
            == str(request.hotel_id)
        ) or (
            str(option_dict.get(
                "id"
            ))
            == str(request.hotel_id)
        ):

            selected_hotel = (
                option_dict
            )

            break

    if selected_hotel is None:

        raise HTTPException(
            status_code=400,
            detail=(
                f"Invalid hotel_id: "
                f"{request.hotel_id}"
            ),
        )

    # =====================================================
    # STEP 5
    # SAVE USER SELECTION
    # =====================================================

    state.selected_hotel = selected_hotel

    state.workflow_status = (
        "HOTEL_SELECTED"
    )

    # Keep the selected option persisted in the
    # temporary planning session before Phase 2.
    session.state = state.model_dump(mode="json")
    session.status = "PROCESSING"
    db.commit()

    # =====================================================
    # STEP 6
    # CONTINUE WORKFLOW
    # =====================================================

    try:

        orchestrator = (
            TravelOrchestrator()
        )

        # -------------------------------------------------
        # This method must continue from:
        #
        # selected transport + hotel
        #
        # and run:
        #
        # Places
        # Weather
        # Verification
        # Aggregation
        # Constraints
        # Optimization
        # Itinerary
        # Validator
        # -------------------------------------------------

        if not hasattr(
            orchestrator,
            "continue_after_hotel_selection"
        ):

            raise RuntimeError(
                "TravelOrchestrator is missing "
                "continue_after_hotel_selection(). "
                "Add the continuation method "
                "before using this route."
            )

        state = await (
            orchestrator.continue_after_hotel_selection(
                state,
                hotel_id=request.hotel_id
            )
        )

    except Exception as exc:

        print(
            "\n========================================"
        )
        print(
            "       CONTINUATION FAILED"
        )
        print(
            "========================================"
        )

        print(
            f"{type(exc).__name__}: "
            f"{exc}"
        )

        _reset_trip_to_draft(
            db=db,
            trip_id=int(trip.id),
            user_id=int(current_user["user_id"]),
            planning_id=planning_id,
            reason="continuation_exception",
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Trip planning continuation failed. "
                "Trip has been reset to DRAFT."
            ),
        )

    # =====================================================
    # STEP 7
    # READ FINAL STATE
    # =====================================================

    constraints = getattr(
        state,
        "constraints",
        {}
    )

    optimization = getattr(
        state,
        "optimization",
        {}
    )

    itinerary = getattr(
        state,
        "itinerary",
        {}
    )

    validation = getattr(
        state,
        "validation",
        {}
    )

    # =====================================================
    # STEP 7.5
    # FINALIZE TRIP LIFECYCLE
    # =====================================================

    validation_passed = bool(
        validation.get("valid", False)
    ) if isinstance(validation, dict) else False

    if validation_passed:
        try:
            trip = update_trip_status(
                db=db,
                trip_id=int(trip.id),
                user_id=int(current_user["user_id"]),
                new_status=TripStatus.READY,
            )
        except ValueError as exc:
            raise HTTPException(
                status_code=400,
                detail=str(exc),
            )

        if not trip:
            raise HTTPException(
                status_code=404,
                detail="Trip not found while finalizing planning.",
            )

        audit_log(
            action="TRIP_PLANNING_COMPLETED",
            user_id=str(current_user["user_id"]),
            details=(
                f"trip_id={trip.id}, "
                f"planning_id={planning_id}, "
                "status=READY"
            ),
        )

    # =====================================================
    else:
        reset_trip = _reset_trip_to_draft(
            db=db,
            trip_id=int(trip.id),
            user_id=int(current_user["user_id"]),
            planning_id=planning_id,
            reason="itinerary_validation_failed",
        )

        if not reset_trip:
            print(
                f"[WARNING] Trip {trip.id} could not be reset to DRAFT "
                "after itinerary validation failure."
            )

    # STEP 8
    # CLEAN FINAL DATA
    # =====================================================

    clean_itinerary = (
        _clean_itinerary(
            itinerary
        )
    )

    flights = []

    trains = []

    for option in getattr(
        state,
        "transport_options",
        []
    ):

        option_dict = _to_dict(
            option
        )

        if not isinstance(
            option_dict,
            dict
        ):
            continue

        cleaned = (
            _clean_transport_option(
                option_dict
            )
        )

        if option_dict.get(
            "flight_number"
        ):

            flights.append(
                cleaned
            )

        elif option_dict.get(
            "train_number"
        ):

            trains.append(
                cleaned
            )

    clean_hotels = [

        _clean_hotel_option(
            hotel
        )

        for hotel in getattr(
            state,
            "hotel_options",
            []
        )
    ]

    clean_places = [

        _clean_place_option(
            place
        )

        for place in getattr(
            state,
            "place_options",
            []
        )
    ]

    # =====================================================
    # LOG FINAL RESULT & SUMMARY
    # =====================================================

    logger.debug(
        "Travel planning complete: planning_id=%s hotel=%s status=%s transport=%s hotels=%s places=%s weather=%s valid=%s",
        planning_id, request.hotel_id, state.workflow_status, len(state.transport_options), len(state.hotel_options),
        len(state.place_options), bool(state.weather), validation.get("valid")
    )

    out_trans = (
        getattr(state, "outbound_transfer", None)
        or (clean_itinerary.get("outbound_transfer") if isinstance(clean_itinerary, dict) else None)
        or (clean_itinerary.get("transfer") if isinstance(clean_itinerary, dict) else None)
        or (state.recommendations.get("outbound_transfer") if isinstance(getattr(state, "recommendations", None), dict) else None)
        or (state.selected_transport.get("outbound_transfer") if isinstance(getattr(state, "selected_transport", None), dict) else None)
        or (state.selected_transport.get("transfer") if isinstance(getattr(state, "selected_transport", None), dict) else None)
        or {}
    )
    ret_trans = (
        getattr(state, "return_transfer", None)
        or (clean_itinerary.get("return_transfer") if isinstance(clean_itinerary, dict) else None)
        or (state.recommendations.get("return_transfer") if isinstance(getattr(state, "recommendations", None), dict) else None)
        or (state.selected_transport.get("return_transfer") if isinstance(getattr(state, "selected_transport", None), dict) else None)
        or (state.selected_transport.get("return_trip", {}).get("transfer") if isinstance(getattr(state, "selected_transport", None), dict) and isinstance(state.selected_transport.get("return_trip"), dict) else None)
        or {}
    )

    out_from = out_trans.get("from") or ""
    out_to = out_trans.get("to") or ""
    out_dist = out_trans.get("distance_km") or out_trans.get("road_distance_km") or ""
    out_dur = out_trans.get("duration") or out_trans.get("estimated_transfer_time") or ""

    ret_from = ret_trans.get("from") or ""
    ret_to = ret_trans.get("to") or ""
    ret_dist = ret_trans.get("distance_km") or ret_trans.get("road_distance_km") or ""
    ret_dur = ret_trans.get("duration") or ret_trans.get("estimated_transfer_time") or ""

    logger.debug("Outbound transfer: %s -> %s | %s km | %s", out_from, out_to, out_dist, out_dur)
    logger.debug("Return transfer: %s -> %s | %s km | %s", ret_from, ret_to, ret_dist, ret_dur)

    final_trip_status = trip.status.value.upper() if hasattr(trip.status, "value") else str(trip.status).upper()
    observability_metrics.print_final_observability_summary(
        final_status=final_trip_status,
        transport_result=f"{len(state.transport_options)} option(s)",
        hotel_result=f"{len(state.hotel_options)} option(s)",
        places_result=f"{len(state.place_options)} places",
        weather_result="Available" if state.weather else "Unavailable",
        itinerary_result="VALID" if validation_passed else "INVALID",
    )

    # =====================================================
    # AUDIT
    # =====================================================

    audit_log(
        action="HOTEL_SELECTED",
        user_id=str(
            current_user[
                "user_id"
            ]
        ),
        details=(
            f"planning_id={planning_id}, "
            f"hotel_id={request.hotel_id}"
        ),
    )

    # =====================================================
    # REMOVE SESSION
    # =====================================================
    #
    # Planning is complete.
    #
    # We don't need the temporary session anymore.
    #
    # =====================================================

    session.status = "COMPLETED"
    session.state = state.model_dump(mode="json")
    db.commit()

    # =====================================================
    # FINAL RESPONSE
    # =====================================================

    return {

        "status": "success",

        "planning_id": (
            planning_id
        ),

        "trip_id": int(trip.id),

        "trip_status": (
            trip.status.value
            if hasattr(trip.status, "value")
            else str(trip.status)
        ),

        "selected_option": (
            state.selected_options
        ),

        "trip": {

            "origin": (
                state.origin.model_dump()
            ),

            "destination": (
                state.destination.model_dump()
            ),

            "transport_preference": (
                state.transport_preference
            ),

            "budget_category": (
                state.budget_category
            ),

            "travel_dates": {

                "start": (
                    state.travel_dates.start
                ),

                "end": (
                    state.travel_dates.end
                ),
            },

            "travelers": (
                state.travelers.model_dump()
            ),

            "budget": (
                state.budget.model_dump()
            ),

            "preferences": (
                state.preferences
            ),
        },

        "transport": {

            "flights": flights,

            "trains": trains,

            "selected": clean_itinerary.get("transport") or _clean_transport_option(getattr(state, "selected_transport", {})),

            "outbound_transfer": out_trans,

            "return_transfer": ret_trans,

            "summary": {

                "total_options": (
                    len(
                        state.transport_options
                    )
                ),

                "flight_options": (
                    len(flights)
                ),

                "train_options": (
                    len(trains)
                ),
            },
        },

        "hotels": {

            "status": (
                "available"
                if state.hotel_options
                else "unavailable"
            ),

            "count": (
                len(
                    state.hotel_options
                )
            ),

            "selected": clean_itinerary.get("hotel") or _clean_hotel_option(getattr(state, "selected_hotel", {})),

            "options": clean_hotels,
        },

        "places": {

            "status": (
                "available"
                if state.place_options
                else "unavailable"
            ),

            "count": (
                len(
                    state.place_options
                )
            ),

            "options": clean_places,
        },

        "weather": _clean_weather(
            state.weather
        ),

        "transfer": out_trans or getattr(state, "transfer_info", None) or (
            state.selected_transport.get("transfer")
            if isinstance(state.selected_transport, dict)
            else None
        ) or (
            clean_itinerary.get("transfer")
            if isinstance(clean_itinerary, dict)
            else None
        ),

        "outbound_transfer": out_trans,

        "return_transfer": ret_trans,

        "itinerary": (
            clean_itinerary
        ),

        "transport_timing": (
            getattr(
                state,
                "selected_transport",
                {}
            )
            or clean_itinerary.get(
                "transport_timing",
                {}
            )
        ),

        "budget_summary": {
            "travelers_count": (
                clean_itinerary.get(
                    "travelers_count",
                    1,
                )
            ),
            "transport_class": (
                clean_itinerary.get(
                    "transport_class"
                )
            ),
            "transport_class_code": (
                clean_itinerary.get(
                    "transport_class_code"
                )
            ),
            "return_transport_class": (
                clean_itinerary.get(
                    "return_transport_class"
                )
            ),
            "return_transport_class_code": (
                clean_itinerary.get(
                    "return_transport_class_code"
                )
            ),
            "total_budget": (
                clean_itinerary.get(
                    "budget_limit",
                    getattr(
                        state.budget,
                        "amount",
                        0
                    )
                )
            ),
            "budget_limit": (
                clean_itinerary.get(
                    "budget_limit",
                    getattr(
                        state.budget,
                        "amount",
                        0
                    )
                )
            ),
            "outbound_transport_price": (
                clean_itinerary.get(
                    "outbound_transport_price",
                    0
                )
            ),
            "return_transport_price": (
                clean_itinerary.get(
                    "return_transport_price",
                    0
                )
            ),
            "total_transport_per_traveler": (
                clean_itinerary.get(
                    "total_transport_per_traveler",
                    0
                )
            ),
            "estimated_transport": (
                clean_itinerary.get(
                    "estimated_transport",
                    0
                )
            ),
            "estimated_hotel": (
                clean_itinerary.get(
                    "estimated_hotel",
                    0
                )
            ),
            "estimated_cost": (
                clean_itinerary.get(
                    "estimated_cost",
                    0
                )
            ),
            "estimated_total": (
                clean_itinerary.get(
                    "estimated_cost",
                    0
                )
            ),
            "remaining_budget": (
                clean_itinerary.get(
                    "remaining_budget",
                    getattr(
                        state.budget,
                        "amount",
                        0
                    )
                )
            ),
            "currency": (
                clean_itinerary.get(
                    "currency",
                    "INR"
                )
            ),
        },

        "validation": {

            "valid": (
                validation.get(
                    "valid",
                    False
                )
            ),

            "errors": (
                validation.get(
                    "errors",
                    []
                )
            ),

            "warnings": (
                validation.get(
                    "warnings",
                    []
                )
            ),
        },

        "pipeline": {

            "status": (
                state.workflow_status
            ),

            "supervisor": True,

            "transport": bool(
                state.transport_options
            ),

            "hotel": bool(
                state.hotel_options
            ),

            "places": bool(
                state.place_options
            ),

            "weather": bool(
                state.weather
            ),

            "verified": (
                state.verification.get(
                    "status"
                )
                == "verified"
            ),

            "constraints_valid": (
                constraints.get(
                    "overall_valid",
                    False
                )
            ),

            "optimized": bool(
                state.optimization
            ),

            "itinerary_built": bool(
                state.itinerary
            ),

            "validation_passed": (
                validation.get(
                    "valid",
                    False
                )
            ),
        },
    }
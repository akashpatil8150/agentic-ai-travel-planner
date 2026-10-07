from datetime import date, datetime
from typing import Optional, Union

import requests

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    ValidationError,
    field_validator,
    field_serializer,
)

from app.core.config import settings


# ============================================================
# CONSTANTS
# ============================================================

GEOCODING_URL = (
    "https://api.geoapify.com/v1/geocode/search"
)


# ============================================================
# LOCATION MODEL
# ============================================================

class Location(BaseModel):

    name: str

    formatted_address: Optional[str] = None

    city: Optional[str] = None

    state: Optional[str] = None

    country: Optional[str] = None

    latitude: Optional[float] = None

    longitude: Optional[float] = None

    # --------------------------------------------------------
    # LATITUDE VALIDATION
    # --------------------------------------------------------

    @field_validator("latitude")
    @classmethod
    def validate_latitude(cls, value):

        if value is None:
            return value

        if not -90 <= value <= 90:
            raise ValueError(
                "Latitude must be between -90 and 90."
            )

        return value

    # --------------------------------------------------------
    # LONGITUDE VALIDATION
    # --------------------------------------------------------

    @field_validator("longitude")
    @classmethod
    def validate_longitude(cls, value):

        if value is None:
            return value

        if not -180 <= value <= 180:
            raise ValueError(
                "Longitude must be between -180 and 180."
            )

        return value


# ============================================================
# LOCATION CACHE
# ============================================================

_LOCATION_CACHE: dict[str, Location] = {}


# ============================================================
# TRAVEL DATES
# ============================================================

class TravelDates(BaseModel):

    start: date

    end: date

    # --------------------------------------------------------
    # END DATE VALIDATION
    # --------------------------------------------------------

    @field_validator("end")
    @classmethod
    def validate_end_date(cls, end, info):

        start = info.data.get("start")

        if start is not None and end < start:
            raise ValueError(
                "End date cannot be before start date."
            )

        return end


# ============================================================
# TRAVELERS
# ============================================================

class Travelers(BaseModel):

    adults: int = 1

    children: int = 0

    # --------------------------------------------------------
    # ADULT VALIDATION
    # --------------------------------------------------------

    @field_validator("adults")
    @classmethod
    def validate_adults(cls, value):

        if value < 1:
            raise ValueError(
                "At least 1 adult is required."
            )

        return value

    # --------------------------------------------------------
    # CHILD VALIDATION
    # --------------------------------------------------------

    @field_validator("children")
    @classmethod
    def validate_children(cls, value):

        if value < 0:
            raise ValueError(
                "Children cannot be negative."
            )

        return value


# ============================================================
# BUDGET
# ============================================================

class Budget(BaseModel):

    amount: Optional[float] = None

    currency: str = "INR"

    # --------------------------------------------------------
    # AMOUNT VALIDATION
    # --------------------------------------------------------

    @field_validator("amount")
    @classmethod
    def validate_amount(cls, value):

        if value is None:
            return value

        if value < 0:
            raise ValueError(
                "Budget cannot be negative."
            )

        return value

    # --------------------------------------------------------
    # CURRENCY VALIDATION
    # --------------------------------------------------------

    @field_validator("currency")
    @classmethod
    def validate_currency(cls, value):

        value = value.strip().upper()

        if not value:
            raise ValueError(
                "Currency cannot be empty."
            )

        return value


# ============================================================
# TRIP STATE
# ============================================================

class TripState(BaseModel):

    # ========================================================
    # CORE TRIP INPUT
    # ========================================================

    user_id: str

    # Observability correlation identifiers.
    # These travel with TripState through every workflow node/agent.
    planning_id: Optional[str] = None
    trip_id: Optional[int] = None

    origin: Location

    destination: Location

    travel_dates: TravelDates

    travelers: Travelers

    budget: Budget

    preferences: list[str] = Field(
        default_factory=list
    )

    # ========================================================
    # TRAVEL PREFERENCES
    # ========================================================

    # User transport preference:
    #
    # "train"
    # "flight"
    #
    # Transport mode is mandatory.
    transport_preference: str = "train"

    # Budget classification:
    #
    # "cheap"
    # "mid"
    # "premium"
    #
    # This will be calculated during travel option generation.
    budget_category: Optional[str] = None

    # ========================================================
    # SELECTED TRANSPORT & SELECTION STATE
    # ========================================================

    # Complete transport selected by the user.
    selected_transport: Optional[dict] = None

    outbound_transport: Optional[dict] = None

    return_transport: Optional[dict] = None

    available_outbound_options: list[dict] = Field(
        default_factory=list
    )

    selected_outbound_option: Optional[dict] = None

    selected_outbound_class: Optional[str] = None

    selected_outbound_fare: Optional[float] = None

    available_return_options: list[dict] = Field(
        default_factory=list
    )

    selected_return_option: Optional[dict] = None

    selected_return_class: Optional[str] = None

    selected_return_fare: Optional[float] = None

    first_mile_transfer: Optional[dict] = None

    last_mile_transfer: Optional[dict] = None

    outbound_transfer: Optional[dict] = None

    return_first_mile_transfer: Optional[dict] = None

    return_last_mile_transfer: Optional[dict] = None

    return_transfer: Optional[dict] = None

    # ========================================================
    # TRAVEL TIMING
    # ========================================================

    model_config = ConfigDict(
        arbitrary_types_allowed=True,
        extra="ignore",
    )

    # Actual arrival time at destination.
    arrival_datetime: Optional[Union[datetime, str]] = None

    # Actual train arrival time at destination station before transfer.
    train_arrival_datetime: Optional[Union[datetime, str]] = None

    # Actual departure time from destination.
    departure_datetime: Optional[Union[datetime, str]] = None

    # Required departure time from destination to catch return train.
    destination_departure_datetime: Optional[Union[datetime, str]] = None

    # Earliest time when sightseeing can start.
    activity_start_datetime: Optional[Union[datetime, str]] = None

    # Latest time until which activities can be planned.
    activity_end_datetime: Optional[Union[datetime, str]] = None

    # Actual return arrival time at origin station.
    return_arrival_datetime: Optional[Union[datetime, str]] = None

    # Final arrival time at origin after return transfer.
    origin_final_arrival_datetime: Optional[Union[datetime, str]] = None

    @field_serializer(
        "arrival_datetime",
        "train_arrival_datetime",
        "departure_datetime",
        "destination_departure_datetime",
        "activity_start_datetime",
        "activity_end_datetime",
        "return_arrival_datetime",
        "origin_final_arrival_datetime",
        when_used="json-unless-none",
    )
    def serialize_datetime(self, value):
        if isinstance(value, datetime):
            return value.isoformat()
        return value

    # ========================================================
    # AGENT RESULTS
    # ========================================================

    transport_options: list[dict] = Field(
        default_factory=list
    )

    hotel_options: list[dict] = Field(
        default_factory=list
    )

    selected_hotel: Optional[dict] = None

    place_options: list[dict] = Field(
        default_factory=list
    )

    weather: dict = Field(
        default_factory=dict
    )

    verification: dict = Field(
        default_factory=dict
    )

    # ========================================================
    # RECOMMENDATIONS
    # ========================================================

    recommendations: dict = Field(default_factory=dict)

    # ========================================================
    # CONSTRAINT ENGINE
    # ========================================================

    constraints: dict = Field(
        default_factory=dict
    )

    # ========================================================
    # OPTIMIZATION ENGINE
    # ========================================================

    optimization: dict = Field(
        default_factory=dict
    )

    # ========================================================
    # ITINERARY
    # ========================================================

    itinerary: dict = Field(
        default_factory=dict
    )

    # ========================================================
    # VALIDATION
    # ========================================================

    validation: dict = Field(
        default_factory=dict
    )

    # ========================================================
    # USER SELECTABLE TRAVEL OPTIONS
    # ========================================================

    # Generated combinations of transport + hotel
    # shown to the user before detailed trip planning.
    #
    # Example:
    #
    # [
    #     {
    #         "option_id": "option_1",
    #         "category": "cheap",
    #         "transport": {...},
    #         "hotel": {...},
    #         "estimated_cost": 12000
    #     },
    #     {
    #         "option_id": "option_2",
    #         "category": "mid",
    #         "transport": {...},
    #         "hotel": {...},
    #         "estimated_cost": 17000
    #     },
    #     {
    #         "option_id": "option_3",
    #         "category": "premium",
    #         "transport": {...},
    #         "hotel": {...},
    #         "estimated_cost": 20000
    #     }
    # ]
    travel_options: list[dict] = Field(
        default_factory=list
    )

    # ========================================================
    # USER SELECTION / APPROVAL
    # ========================================================

    selected_options: dict = Field(
        default_factory=dict
    )

    approval: dict = Field(
        default_factory=dict
    )

    # ========================================================
    # BOOKING
    # ========================================================

    booking: dict = Field(
        default_factory=dict
    )

    # ========================================================
    # FINAL CONFIRMATION
    # ========================================================

    confirmation: dict = Field(
        default_factory=dict
    )

    # ========================================================
    # WORKFLOW STATUS
    # ========================================================

    workflow_status: str = "INITIALIZED"

    # ========================================================
    # ERRORS
    # ========================================================

    errors: list[dict] = Field(
        default_factory=list
    )

    # ========================================================
    # METADATA
    # ========================================================

    # Runtime workflow metadata such as:
    #
    # - supervisor plan
    # - execution information
    # - temporary identifiers
    # - budget analysis
    # - timing analysis
    # - option generation metadata
    metadata: dict = Field(
        default_factory=dict
    )

    # ========================================================
    # USER ID VALIDATION
    # ========================================================

    @field_validator("user_id")
    @classmethod
    def validate_user_id(cls, value):

        value = value.strip()

        if not value:
            raise ValueError(
                "User ID cannot be empty."
            )

        return value

    # ========================================================
    # PREFERENCES VALIDATION
    # ========================================================

    @field_validator("preferences")
    @classmethod
    def validate_preferences(cls, value):

        cleaned = []

        for preference in value:

            if not isinstance(
                preference,
                str
            ):
                raise ValueError(
                    "Each preference must be a string."
                )

            preference = (
                preference
                .strip()
                .lower()
            )

            if (
                preference
                and preference not in cleaned
            ):
                cleaned.append(preference)

        return cleaned

    # ========================================================
    # TRANSPORT PREFERENCE VALIDATION
    # ========================================================

    @field_validator("transport_preference")
    @classmethod
    def validate_transport_preference(cls, value):

        if not isinstance(value, str):
            raise ValueError(
                "Transport preference must be text."
            )

        value = value.strip().lower()

        allowed = {
            "train",
            "flight",
        }

        if value not in allowed:
            raise ValueError(
                "Transport preference must be "
                "'train' or 'flight'."
            )

        return value

    # ========================================================
    # BUDGET CATEGORY VALIDATION
    # ========================================================

    @field_validator("budget_category")
    @classmethod
    def validate_budget_category(cls, value):

        if value is None:
            return value

        if not isinstance(value, str):
            raise ValueError(
                "Budget category must be text."
            )

        value = value.strip().lower()

        allowed = {
            "cheap",
            "mid",
            "premium",
        }

        if value not in allowed:
            raise ValueError(
                "Budget category must be "
                "'cheap', 'mid', or 'premium'."
            )

        return value


# ============================================================
# LOCATION RESOLVER
# ============================================================

def resolve_location(place_name: str) -> Location:

    if not isinstance(place_name, str):
        raise ValueError(
            "Location must be text."
        )

    place_name = place_name.strip()

    if not place_name:
        raise ValueError(
            "Location cannot be empty."
        )

    if len(place_name) < 2:
        raise ValueError(
            "Location name is too short."
        )

    if len(place_name) > 100:
        raise ValueError(
            "Location name is too long."
        )

    # ========================================================
    # CANONICAL CITY ALIASES
    # ========================================================

    city_aliases = {

        "delhi": "Delhi",
        "new delhi": "Delhi",
        "delhi ncr": "Delhi",

        "mumbai": "Mumbai",
        "bombay": "Mumbai",
        "mumbai city": "Mumbai",

        "bangalore": "Bengaluru",
        "bengaluru": "Bengaluru",
        "bangalore city": "Bengaluru",

        "calcutta": "Kolkata",
        "kolkata": "Kolkata",

        "madras": "Chennai",
        "chennai": "Chennai",

        "hyderabad": "Hyderabad",

        "pune": "Pune",

        "jaipur": "Jaipur",

        "ahmedabad": "Ahmedabad",

        "surat": "Surat",

        "lucknow": "Lucknow",

        "indore": "Indore",

        "nagpur": "Nagpur",

        "goa": "Goa",

        "chandigarh": "Chandigarh",

        "bhopal": "Bhopal",

        "patna": "Patna",

        "varanasi": "Varanasi",

        "agra": "Agra",
    }

    normalized = " ".join(
        place_name.lower().split()
    )

    canonical_city = city_aliases.get(
        normalized
    )

    # ========================================================
    # CACHE
    # ========================================================

    # v4 prevents previously cached wrong results such as:
    # Delhi -> Delhi Darbar -> Mumbai

    cache_key = (
        f"v4:{canonical_city or normalized}"
    )

    if cache_key in _LOCATION_CACHE:

        print(
            f"\nLocation cache hit: '{place_name}'"
        )

        return _LOCATION_CACHE[
            cache_key
        ]

    # ========================================================
    # CHECK CANONICAL INDIA LOCATIONS DATASET FIRST
    # ========================================================

    try:
        from app.resolvers.india_locations import get_location_entry
        loc_entry = get_location_entry(canonical_city or place_name)
        if loc_entry:
            loc_name = place_name.strip().title()
            state_name = loc_entry.get("state", "India")
            loc_obj = Location(
                name=loc_name,
                formatted_address=f"{loc_name}, {state_name}, India" if state_name != "India" else f"{loc_name}, India",
                city=loc_entry.get("name", loc_name),
                state=state_name,
                country="India",
                latitude=float(loc_entry["lat"]),
                longitude=float(loc_entry["lon"]),
            )
            _LOCATION_CACHE[cache_key] = loc_obj
            print(
                f"\nResolved known India location '{place_name}': {loc_obj.city}, {loc_obj.state} ({loc_obj.latitude}, {loc_obj.longitude})"
            )
            return loc_obj
    except Exception as exc:
        pass

    # ========================================================
    # GEOAPIFY API KEY
    # ========================================================

    if not settings.geoapify_api_key:

        raise RuntimeError(
            "GEOAPIFY_API_KEY is not configured."
        )

    # ========================================================
    # CITY QUERY
    # ========================================================

    if canonical_city:

        # For city-level input like "Delhi",
        # explicitly search for a city in India.

        params = {

            "text": (
                f"{canonical_city}, India"
            ),

            "type": "city",

            "filter": "countrycode:in",

            "format": "json",

            "limit": 5,

            "apiKey": (
                settings.geoapify_api_key
            ),
        }

        print(
            f"\nResolving city '{canonical_city}'..."
        )

    # ========================================================
    # SPECIFIC PLACE / POI QUERY
    # ========================================================

    else:

        params = {

            "text": (
                f"{place_name}, India"
            ),

            "filter": "countrycode:in",

            "format": "json",

            "limit": 5,

            "apiKey": (
                settings.geoapify_api_key
            ),
        }

        print(
            f"\nResolving place '{place_name}'..."
        )

    # ========================================================
    # API REQUEST
    # ========================================================

    city_lookup_key = (canonical_city or normalized or place_name).strip().lower()

    KNOWN_LOCATIONS = {
        "mumbai": Location(name="Mumbai", formatted_address="Mumbai, Maharashtra, India", city="Mumbai", state="Maharashtra", country="India", latitude=19.0760, longitude=72.8777),
        "delhi": Location(name="Delhi", formatted_address="Delhi, India", city="Delhi", state="Delhi", country="India", latitude=28.6139, longitude=77.2090),
        "kolkata": Location(name="Kolkata", formatted_address="Kolkata, West Bengal, India", city="Kolkata", state="West Bengal", country="India", latitude=22.5726, longitude=88.3639),
        "manali": Location(name="Manali", formatted_address="Manali, Himachal Pradesh, India", city="Manali", state="Himachal Pradesh", country="India", latitude=32.2432, longitude=77.1892),
        "kullu": Location(name="Kullu", formatted_address="Kullu, Himachal Pradesh, India", city="Kullu", state="Himachal Pradesh", country="India", latitude=31.9579, longitude=77.1095),
        "goa": Location(name="Goa", formatted_address="Goa, India", city="Goa", state="Goa", country="India", latitude=15.2993, longitude=74.1240),
        "kolhapur": Location(name="Kolhapur", formatted_address="Kolhapur, Maharashtra, India", city="Kolhapur", state="Maharashtra", country="India", latitude=16.7050, longitude=74.2433),
        "bangalore": Location(name="Bangalore", formatted_address="Bengaluru, Karnataka, India", city="Bengaluru", state="Karnataka", country="India", latitude=12.9716, longitude=77.5946),
        "bengaluru": Location(name="Bengaluru", formatted_address="Bengaluru, Karnataka, India", city="Bengaluru", state="Karnataka", country="India", latitude=12.9716, longitude=77.5946),
        "chennai": Location(name="Chennai", formatted_address="Chennai, Tamil Nadu, India", city="Chennai", state="Tamil Nadu", country="India", latitude=13.0827, longitude=80.2707),
        "jaipur": Location(name="Jaipur", formatted_address="Jaipur, Rajasthan, India", city="Jaipur", state="Rajasthan", country="India", latitude=26.9124, longitude=75.7873),
        "darjeeling": Location(name="Darjeeling", formatted_address="Darjeeling, West Bengal, India", city="Darjeeling", state="West Bengal", country="India", latitude=27.0410, longitude=88.2663),
        "shimla": Location(name="Shimla", formatted_address="Shimla, Himachal Pradesh, India", city="Shimla", state="Himachal Pradesh", country="India", latitude=31.1048, longitude=77.1734),
        "ooty": Location(name="Ooty", formatted_address="Ooty, Tamil Nadu, India", city="Ooty", state="Tamil Nadu", country="India", latitude=11.4102, longitude=76.6950),
        "munnar": Location(name="Munnar", formatted_address="Munnar, Kerala, India", city="Munnar", state="Kerala", country="India", latitude=10.0889, longitude=77.0595),
        "mussoorie": Location(name="Mussoorie", formatted_address="Mussoorie, Uttarakhand, India", city="Mussoorie", state="Uttarakhand", country="India", latitude=30.4598, longitude=78.0644),
        "rishikesh": Location(name="Rishikesh", formatted_address="Rishikesh, Uttarakhand, India", city="Rishikesh", state="Uttarakhand", country="India", latitude=30.0869, longitude=78.2676),
        "surat": Location(name="Surat", formatted_address="Surat, Gujarat, India", city="Surat", state="Gujarat", country="India", latitude=21.1702, longitude=72.8311),
        "ahmedabad": Location(name="Ahmedabad", formatted_address="Ahmedabad, Gujarat, India", city="Ahmedabad", state="Gujarat", country="India", latitude=23.0225, longitude=72.5714),
        "hyderabad": Location(name="Hyderabad", formatted_address="Hyderabad, Telangana, India", city="Hyderabad", state="Telangana", country="India", latitude=17.3850, longitude=78.4867),
        "visakhapatnam": Location(name="Visakhapatnam", formatted_address="Visakhapatnam, Andhra Pradesh, India", city="Visakhapatnam", state="Andhra Pradesh", country="India", latitude=17.6868, longitude=83.2185),
        "pune": Location(name="Pune", formatted_address="Pune, Maharashtra, India", city="Pune", state="Maharashtra", country="India", latitude=18.5204, longitude=73.8567),
        "agra": Location(name="Agra", formatted_address="Agra, Uttar Pradesh, India", city="Agra", state="Uttar Pradesh", country="India", latitude=27.1767, longitude=78.0081),
        "varanasi": Location(name="Varanasi", formatted_address="Varanasi, Uttar Pradesh, India", city="Varanasi", state="Uttar Pradesh", country="India", latitude=25.3176, longitude=82.9739),
        "amritsar": Location(name="Amritsar", formatted_address="Amritsar, Punjab, India", city="Amritsar", state="Punjab", country="India", latitude=31.6340, longitude=74.8723),
        "chandigarh": Location(name="Chandigarh", formatted_address="Chandigarh, India", city="Chandigarh", state="Chandigarh", country="India", latitude=30.7333, longitude=76.7794),
        "kochi": Location(name="Kochi", formatted_address="Kochi, Kerala, India", city="Kochi", state="Kerala", country="India", latitude=9.9312, longitude=76.2673),
        "puri": Location(name="Puri", formatted_address="Puri, Odisha, India", city="Puri", state="Odisha", country="India", latitude=19.8135, longitude=85.8312),
    }

    try:

        response = requests.get(
            GEOCODING_URL,
            params=params,
            timeout=10,
        )

    except (requests.exceptions.Timeout, requests.exceptions.ConnectionError, requests.exceptions.RequestException) as error:

        if city_lookup_key in KNOWN_LOCATIONS:
            loc = KNOWN_LOCATIONS[city_lookup_key]
            _LOCATION_CACHE[cache_key] = loc
            return loc

        raise RuntimeError(
            f"Location API error: {error}"
        )

    print(
        "Geocoding API Status:",
        response.status_code
    )

    # ========================================================
    # STATUS HANDLING
    # ========================================================

    if response.status_code != 200:

        if city_lookup_key in KNOWN_LOCATIONS:
            loc = KNOWN_LOCATIONS[city_lookup_key]
            _LOCATION_CACHE[cache_key] = loc
            return loc

        if response.status_code == 400:
            raise RuntimeError("Geoapify rejected the request.")
        if response.status_code in (401, 403):
            raise RuntimeError("Geoapify API key is invalid or unauthorized.")
        if response.status_code == 429:
            raise RuntimeError("Geoapify API quota or rate limit reached.")
        if response.status_code >= 500:
            raise RuntimeError("Geoapify service is temporarily unavailable.")

    # ========================================================
    # HTTP ERROR
    # ========================================================

    try:

        response.raise_for_status()

    except requests.exceptions.HTTPError as error:

        raise RuntimeError(
            f"Location API error: {error}"
        )

    # ========================================================
    # JSON RESPONSE
    # ========================================================

    try:

        data = response.json()

    except ValueError:

        raise RuntimeError(
            "Geoapify returned invalid JSON."
        )

    # ========================================================
    # RESPONSE VALIDATION
    # ========================================================

    if not isinstance(data, dict):

        raise RuntimeError(
            "Unexpected Geoapify response."
        )

    results = data.get("results")

    if not isinstance(results, list):

        raise RuntimeError(
            "Invalid geocoding response format."
        )

    if not results:

        raise ValueError(
            f"Location not found: {place_name}"
        )

    # ========================================================
    # SELECT BEST RESULT
    # ========================================================

    result = None

    # ========================================================
    # CITY RESULT SELECTION
    # ========================================================

    if canonical_city:

        canonical_normalized = (
            canonical_city.lower()
        )

        # ----------------------------------------------------
        # FIRST PRIORITY:
        # Exact city/name match
        # ----------------------------------------------------

        for candidate in results:

            if not isinstance(candidate, dict):
                continue

            candidate_name = str(
                candidate.get("name") or ""
            ).strip().lower()

            candidate_city = str(
                candidate.get("city") or ""
            ).strip().lower()

            candidate_type = str(
                candidate.get("result_type")
                or candidate.get("type")
                or ""
            ).strip().lower()

            if (
                candidate_name
                == canonical_normalized
                or candidate_city
                == canonical_normalized
            ):

                result = candidate
                break

            # ------------------------------------------------
            # CITY TYPE + NAME MATCH
            # ------------------------------------------------

            if (
                candidate_type == "city"
                and canonical_normalized
                in candidate_name
            ):

                result = candidate
                break

        # ----------------------------------------------------
        # SECOND PRIORITY:
        # Any city result
        # ----------------------------------------------------

        if result is None:

            for candidate in results:

                if not isinstance(candidate, dict):
                    continue

                candidate_type = str(
                    candidate.get("result_type")
                    or candidate.get("type")
                    or ""
                ).strip().lower()

                if candidate_type == "city":

                    result = candidate
                    break

        # ----------------------------------------------------
        # FINAL FALLBACK
        # ----------------------------------------------------

        if result is None:

            result = results[0]

    # ========================================================
    # NORMAL PLACE RESULT
    # ========================================================

    else:

        result = results[0]

    # ========================================================
    # RESULT VALIDATION
    # ========================================================

    if not isinstance(result, dict):

        raise RuntimeError(
            "Invalid location data received."
        )

    # ========================================================
    # COORDINATES
    # ========================================================

    latitude = result.get("lat")

    longitude = result.get("lon")

    if latitude is None:

        raise RuntimeError(
            f"Latitude not available for '{place_name}'."
        )

    if longitude is None:

        raise RuntimeError(
            f"Longitude not available for '{place_name}'."
        )

    # ========================================================
    # LOCATION NAME
    # ========================================================

    if canonical_city:

        # Keep application-level city canonical.

        location_name = canonical_city

        city = canonical_city

        state = result.get("state")

        # Delhi is a Union Territory and Geoapify
        # may return state=None.

        if canonical_city == "Delhi":

            state = "Delhi"

    else:

        location_name = (
            result.get("name")
            or place_name
        )

        city = result.get("city")

        state = result.get("state")

    # ========================================================
    # CREATE LOCATION
    # ========================================================

    try:

        location = Location(

            name=location_name,

            formatted_address=(
                result.get("formatted")
                or f"{location_name}, India"
            ),

            city=city,

            state=state,

            country=(
                result.get("country")
                or "India"
            ),

            latitude=float(
                latitude
            ),

            longitude=float(
                longitude
            ),
        )

    except (
        ValidationError,
        ValueError,
        TypeError,
    ) as error:

        raise RuntimeError(
            f"Invalid location data: {error}"
        )

    # ========================================================
    # CACHE RESULT
    # ========================================================

    _LOCATION_CACHE[
        cache_key
    ] = location

    print(
        f"Location cached: '{place_name}'"
    )

    print(
        f"Resolved location: "
        f"{location.name}, "
        f"{location.city}, "
        f"{location.country}"
    )

    return location


# ============================================================
# SAME LOCATION VALIDATION
# ============================================================

def validate_different_locations(
    origin: Location,
    destination: Location,
):

    # --------------------------------------------------------
    # NAME CHECK
    # --------------------------------------------------------

    origin_name = (
        origin.name
        .strip()
        .lower()
    )

    destination_name = (
        destination.name
        .strip()
        .lower()
    )

    if origin_name == destination_name:

        raise ValueError(
            "Origin and destination cannot be the same."
        )

    # --------------------------------------------------------
    # COORDINATE CHECK
    # --------------------------------------------------------

    if (
        origin.latitude is not None
        and origin.longitude is not None
        and destination.latitude is not None
        and destination.longitude is not None
    ):

        same_latitude = (
            origin.latitude
            == destination.latitude
        )

        same_longitude = (
            origin.longitude
            == destination.longitude
        )

        if (
            same_latitude
            and same_longitude
        ):

            raise ValueError(
                "Origin and destination refer "
                "to the same location."
            )


# ============================================================
# READ INTEGER
# ============================================================

def read_integer(
    prompt: str,
    default=None,
):

    while True:

        value = input(prompt).strip()

        # ----------------------------------------------------
        # EMPTY INPUT
        # ----------------------------------------------------

        if not value:

            if default is not None:

                return default

            print(
                "Please enter a number."
            )

            continue

        # ----------------------------------------------------
        # INTEGER CONVERSION
        # ----------------------------------------------------

        try:

            return int(value)

        except ValueError:

            print(
                "Invalid number. "
                "Please enter an integer."
            )


# ============================================================
# READ BUDGET
# ============================================================

def read_budget():

    while True:

        value = input(
            "Enter budget "
            "(press Enter to skip): "
        ).strip()

        # ----------------------------------------------------
        # OPTIONAL
        # ----------------------------------------------------

        if not value:

            return None

        # ----------------------------------------------------
        # CONVERSION
        # ----------------------------------------------------

        try:

            budget = float(value)

        except ValueError:

            print(
                "Invalid budget. "
                "Enter a number like 20000."
            )

            continue

        # ----------------------------------------------------
        # NEGATIVE
        # ----------------------------------------------------

        if budget < 0:

            print(
                "Budget cannot be negative."
            )

            continue

        return budget


# ============================================================
# READ DATE
# ============================================================

def read_date(prompt: str):

    while True:

        value = input(prompt).strip()

        try:

            return date.fromisoformat(value)

        except ValueError:

            print(
                "Invalid date. "
                "Use YYYY-MM-DD."
            )


# ============================================================
# READ TRAVEL DATES
# ============================================================

def read_travel_dates():

    while True:

        start = read_date(
            "Enter start date (YYYY-MM-DD): "
        )

        end = read_date(
            "Enter end date (YYYY-MM-DD): "
        )

        today = date.today()

        # ----------------------------------------------------
        # START DATE IN PAST
        # ----------------------------------------------------

        if start < today:

            print(
                f"Start date cannot be before "
                f"today ({today})."
            )

            continue

        # ----------------------------------------------------
        # END BEFORE START
        # ----------------------------------------------------

        if end < start:

            print(
                "End date cannot be before "
                "start date."
            )

            continue

        return TravelDates(
            start=start,
            end=end,
        )


# ============================================================
# READ PREFERENCES
# ============================================================

def read_preferences():

    value = input(
        "Enter preferences separated by comma "
        "(example: beach, sightseeing): "
    ).strip()

    if not value:

        return []

    preferences = []

    for item in value.split(","):

        item = item.strip().lower()

        if (
            item
            and item not in preferences
        ):

            preferences.append(item)

    return preferences


# ============================================================
# READ TRANSPORT PREFERENCE
# ============================================================

def read_transport_preference():

    while True:

        value = input(
            "Choose transport "
            "(train / flight): "
        ).strip().lower()

        if not value:

            return "train"

        if value in {
            "train",
            "flight",
        }:

            return value

        print(
            "Invalid transport. "
            "Choose train or flight."
        )


# ============================================================
# PRINT LOCATION
# ============================================================

def print_location(
    label: str,
    location: Location,
):

    print(
        f"\n{label}"
    )

    print(
        "----------------------------------------"
    )

    print(
        "Name:",
        location.name
    )

    print(
        "Address:",
        location.formatted_address
    )

    print(
        "City:",
        location.city
    )

    print(
        "State:",
        location.state
    )

    print(
        "Country:",
        location.country
    )

    print(
        "Latitude:",
        location.latitude
    )

    print(
        "Longitude:",
        location.longitude
    )


# ============================================================
# PRINT TRIP STATE
# ============================================================

def print_trip_state(
    trip: TripState
):

    print(
        "\n========================================"
    )

    print(
        "          TRIP STATE CREATED"
    )

    print(
        "========================================"
    )

    print(
        "\nUser ID:"
    )

    print(
        trip.user_id
    )

    print(
        "\nOrigin:"
    )

    print(
        trip.origin.model_dump()
    )

    print(
        "\nDestination:"
    )

    print(
        trip.destination.model_dump()
    )

    print(
        "\nTravel Dates:"
    )

    print(
        trip.travel_dates.model_dump()
    )

    print(
        "\nTravelers:"
    )

    print(
        trip.travelers.model_dump()
    )

    print(
        "\nBudget:"
    )

    print(
        trip.budget.model_dump()
    )

    print(
        "\nPreferences:"
    )

    print(
        trip.preferences
    )

    print(
        "\nTransport Preference:"
    )

    print(
        trip.transport_preference
    )

    print(
        "\nBudget Category:"
    )

    print(
        trip.budget_category
    )

    print(
        "\nSelected Transport:"
    )

    print(
        trip.selected_transport
    )

    print(
        "\nArrival:"
    )

    print(
        trip.arrival_datetime
    )

    print(
        "\nDeparture:"
    )

    print(
        trip.departure_datetime
    )

    print(
        "\nActivity Start:"
    )

    print(
        trip.activity_start_datetime
    )

    print(
        "\nActivity End:"
    )

    print(
        trip.activity_end_datetime
    )

    print(
        "\nTransport Options:"
    )

    print(
        trip.transport_options
    )

    print(
        "\nHotel Options:"
    )

    print(
        trip.hotel_options
    )

    print(
        "\nPlace Options:"
    )

    print(
        trip.place_options
    )

    print(
        "\nWeather:"
    )

    print(
        trip.weather
    )

    print(
        "\nRecommendations:"
    )

    print(
        trip.recommendations
    )

    print(
        "\nVerification:"
    )

    print(
        trip.verification
    )


# ============================================================
# MAIN
# ============================================================

if __name__ == "__main__":

    print(
        "\n========================================"
    )

    print(
        "       TRIP STATE + LOCATION TEST"
    )

    print(
        "========================================"
    )

    try:

        # ====================================================
        # API KEY CHECK
        # ====================================================

        if not settings.geoapify_api_key:

            print(
                "\nERROR:"
            )

            print(
                "Geoapify API key is not configured."
            )

            raise SystemExit(1)

        # ====================================================
        # LOCATION INPUT
        # ====================================================

        origin_name = input(
            "\nEnter origin: "
        ).strip()

        destination_name = input(
            "Enter destination: "
        ).strip()

        # ----------------------------------------------------
        # EMPTY ORIGIN
        # ----------------------------------------------------

        if not origin_name:

            raise ValueError(
                "Origin cannot be empty."
            )

        # ----------------------------------------------------
        # EMPTY DESTINATION
        # ----------------------------------------------------

        if not destination_name:

            raise ValueError(
                "Destination cannot be empty."
            )

        # ====================================================
        # RESOLVE ORIGIN
        # ====================================================

        origin = resolve_location(
            origin_name
        )

        # ====================================================
        # RESOLVE DESTINATION
        # ====================================================

        destination = resolve_location(
            destination_name
        )

        # ====================================================
        # SAME LOCATION CHECK
        # ====================================================

        validate_different_locations(
            origin,
            destination,
        )

        # ====================================================
        # TRAVEL DATES
        # ====================================================

        travel_dates = read_travel_dates()

        # ====================================================
        # TRAVELERS
        # ====================================================

        adults = read_integer(
            "Enter number of adults: "
        )

        children = read_integer(
            "Enter number of children: ",
            default=0,
        )

        try:

            travelers = Travelers(
                adults=adults,
                children=children,
            )

        except ValidationError as error:

            print(
                "\nTraveler validation failed:"
            )

            for item in error.errors():

                print(
                    "-",
                    item["msg"]
                )

            raise SystemExit(1)

        # ====================================================
        # BUDGET
        # ====================================================

        budget_amount = read_budget()

        try:

            budget = Budget(
                amount=budget_amount,
                currency="INR",
            )

        except ValidationError as error:

            print(
                "\nBudget validation failed:"
            )

            for item in error.errors():

                print(
                    "-",
                    item["msg"]
                )

            raise SystemExit(1)

        # ====================================================
        # TRANSPORT PREFERENCE
        # ====================================================

        transport_preference = (
            read_transport_preference()
        )

        # ====================================================
        # PREFERENCES
        # ====================================================

        preferences = read_preferences()

        # ====================================================
        # CREATE TRIP STATE
        # ====================================================

        try:

            trip = TripState(

                user_id="test_user_123",

                origin=origin,

                destination=destination,

                travel_dates=travel_dates,

                travelers=travelers,

                budget=budget,

                preferences=preferences,

                transport_preference=(
                    transport_preference
                ),
            )

        except ValidationError as error:

            print(
                "\nTripState validation failed:"
            )

            for item in error.errors():

                print(
                    "-",
                    item["msg"]
                )

            raise SystemExit(1)

        # ====================================================
        # RESOLVED LOCATIONS
        # ====================================================

        print(
            "\n========================================"
        )

        print(
            "        RESOLVED LOCATIONS"
        )

        print(
            "========================================"
        )

        print_location(
            "ORIGIN",
            trip.origin,
        )

        print_location(
            "DESTINATION",
            trip.destination,
        )

        # ====================================================
        # PRINT STATE
        # ====================================================

        print_trip_state(
            trip
        )

        # ====================================================
        # FINAL JSON
        # ====================================================

        print(
            "\n========================================"
        )

        print(
            "          FINAL STATE JSON"
        )

        print(
            "========================================"
        )

        print(
            trip.model_dump_json(
                indent=4
            )
        )

        # ====================================================
        # SUCCESS
        # ====================================================

        print(
            "\n========================================"
        )

        print(
            "              TEST DONE"
        )

        print(
            "========================================"
        )

    # ========================================================
    # VALIDATION ERROR
    # ========================================================

    except ValueError as error:

        print(
            f"\nValidation Error: {error}"
        )

    # ========================================================
    # SERVICE ERROR
    # ========================================================

    except RuntimeError as error:

        print(
            f"\nService Error: {error}"
        )

    # ========================================================
    # PYDANTIC ERROR
    # ========================================================

    except ValidationError as error:

        print(
            "\nValidation Error:"
        )

        for item in error.errors():

            print(
                "-",
                item["msg"]
            )

    # ========================================================
    # KEYBOARD INTERRUPT
    # ========================================================

    except KeyboardInterrupt:

        print(
            "\n\nTest cancelled by user."
        )

    # ========================================================
    # UNEXPECTED ERROR
    # ========================================================

    except Exception as error:

        print(
            "\nUnexpected error occurred:"
        )

        print(
            type(error).__name__,
            ":",
            error
        )
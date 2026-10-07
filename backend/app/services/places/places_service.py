import logging
import requests

from app.core.config import settings


logger = logging.getLogger(__name__)


# ============================================================
# CONFIGURATION
# ============================================================

BASE_URL = "https://api.geoapify.com/v2/places"

TIMEOUT = 15


# ============================================================
# PLACE CATEGORY MAPPING
# ============================================================

PLACE_CATEGORIES = {

    # Nature
    "beach": "beach",
    "beaches": "beach",

    "park": "leisure.park",
    "parks": "leisure.park",

    "national park": "national_park",

    # Attractions
    "attraction": "tourism.attraction",
    "attractions": "tourism.attraction",

    "tourist attraction": "tourism.attraction",

    "viewpoint": "tourism.attraction.viewpoint",
    "viewpoints": "tourism.attraction.viewpoint",

    "monument": "tourism.sights.memorial.monument",
    "monuments": "tourism.sights.memorial.monument",

    # Entertainment
    "museum": "entertainment.museum",
    "museums": "entertainment.museum",

    "zoo": "entertainment.zoo",

    "aquarium": "entertainment.aquarium",

    "water park": "entertainment.water_park",

    "theme park": "entertainment.theme_park",

    # Religious
    "temple": "tourism.sights.place_of_worship.temple",

    "church": "tourism.sights.place_of_worship.church",

    "mosque": "tourism.sights.place_of_worship.mosque",

    # Outdoor
    "camping": "camping",
}


# ============================================================
# DEFAULT PLACE PREFERENCES
# ============================================================
#
# These are used when the user gives only soft/ranking
# preferences such as:
#
#   budget
#   comfortable
#   relaxing
#   family
#   scenic
#
# Such preferences cannot be directly sent to Geoapify
# as categories.
#
# Therefore we retrieve common sightseeing categories
# and allow PlacesAgent/LLM to rank them later.
#
# ============================================================

DEFAULT_PLACE_PREFERENCES = [
    "attraction",
    "park",
    "museum",
]


# ============================================================
# DESTINATION ICONIC ATTRACTIONS (PREVENT NOISE & GENERIC NAMES)
# ============================================================

DESTINATION_ICONIC_PLACES = {
    "manali": [
        {
            "name": "Hadimba Devi Temple",
            "category": ["tourism.sights.place_of_worship.temple", "tourism.attraction"],
            "requested_interest": "attraction",
            "address": "Hadimba Temple Rd, Old Manali, Manali, Himachal Pradesh",
            "city": "Manali",
            "state": "Himachal Pradesh",
            "country": "India",
            "latitude": 32.2483,
            "longitude": 77.1804,
            "distance_meters": 1500,
            "description": "Historical 16th-century wooden temple surrounded by cedar forest",
        },
        {
            "name": "Solang Valley",
            "category": ["tourism.attraction", "leisure.park"],
            "requested_interest": "attraction",
            "address": "Solang Valley, VPO Palchan, Manali, Himachal Pradesh",
            "city": "Manali",
            "state": "Himachal Pradesh",
            "country": "India",
            "latitude": 32.3166,
            "longitude": 77.1578,
            "distance_meters": 13000,
            "description": "Famous valley known for paragliding, zorbing, and winter snow sports",
        },
        {
            "name": "Rohtang Pass",
            "category": ["tourism.attraction", "national_park"],
            "requested_interest": "attraction",
            "address": "Rohtang Pass, Leh - Manali Hwy, Himachal Pradesh",
            "city": "Manali",
            "state": "Himachal Pradesh",
            "country": "India",
            "latitude": 32.3716,
            "longitude": 77.2466,
            "distance_meters": 51000,
            "description": "Iconic high mountain pass offering snow activities and Himalayan views",
        },
        {
            "name": "Vashisht Temple & Hot Water Springs",
            "category": ["tourism.sights.place_of_worship.temple", "tourism.attraction"],
            "requested_interest": "attraction",
            "address": "Vashisht Village, Manali, Himachal Pradesh",
            "city": "Manali",
            "state": "Himachal Pradesh",
            "country": "India",
            "latitude": 32.2612,
            "longitude": 77.1895,
            "distance_meters": 3500,
            "description": "Ancient temple dedicated to Sage Vashisht with natural sulfur hot baths",
        },
        {
            "name": "Manu Temple",
            "category": ["tourism.sights.place_of_worship.temple", "tourism.attraction"],
            "requested_interest": "attraction",
            "address": "Old Manali, Manali, Himachal Pradesh",
            "city": "Manali",
            "state": "Himachal Pradesh",
            "country": "India",
            "latitude": 32.2536,
            "longitude": 77.1724,
            "distance_meters": 2200,
            "description": "Historic pagoda-style temple dedicated to Sage Manu in Old Manali",
        },
        {
            "name": "Naggar Castle",
            "category": ["tourism.attraction", "tourism.sights.memorial.monument"],
            "requested_interest": "attraction",
            "address": "Naggar, Kullu District, Himachal Pradesh",
            "city": "Naggar",
            "state": "Himachal Pradesh",
            "country": "India",
            "latitude": 32.1176,
            "longitude": 77.1706,
            "distance_meters": 21000,
            "description": "Historic wooden castle overlooking the Beas River with Roerich Art Gallery",
        },
        {
            "name": "Jogini Waterfall",
            "category": ["tourism.attraction", "leisure.park"],
            "requested_interest": "attraction",
            "address": "Vashisht, Manali, Himachal Pradesh",
            "city": "Manali",
            "state": "Himachal Pradesh",
            "country": "India",
            "latitude": 32.2705,
            "longitude": 77.1950,
            "distance_meters": 4500,
            "description": "Scenic multi-tiered cascading waterfall and trek through pine woods",
        },
        {
            "name": "Tibetan Monastery (Gadhan Thekchhokling Gompa)",
            "category": ["tourism.sights.place_of_worship.temple", "tourism.attraction"],
            "requested_interest": "attraction",
            "address": "Mall Road, Manali, Himachal Pradesh",
            "city": "Manali",
            "state": "Himachal Pradesh",
            "country": "India",
            "latitude": 32.2396,
            "longitude": 77.1887,
            "distance_meters": 800,
            "description": "Prominent Buddhist monastery with colorful Tibetan handicrafts and prayer wheels",
        },
        {
            "name": "Van Vihar National Park",
            "category": ["leisure.park", "tourism.attraction"],
            "requested_interest": "park",
            "address": "Mall Road, Manali, Himachal Pradesh",
            "city": "Manali",
            "state": "Himachal Pradesh",
            "country": "India",
            "latitude": 32.2380,
            "longitude": 77.1890,
            "distance_meters": 700,
            "description": "Lush municipal nature park with tall deodar trees and boating lake off Mall Road",
        },
        {
            "name": "Old Manali View",
            "category": ["tourism.attraction.viewpoint", "tourism.attraction"],
            "requested_interest": "attraction",
            "address": "Old Manali, Himachal Pradesh",
            "city": "Manali",
            "state": "Himachal Pradesh",
            "country": "India",
            "latitude": 32.2570,
            "longitude": 77.1780,
            "distance_meters": 2500,
            "description": "Panoramic mountain view and rustic village trails of Old Manali",
        },
    ],
    "goa": [
        {
            "name": "Basilica of Bom Jesus",
            "category": ["tourism.sights.place_of_worship.church", "tourism.attraction"],
            "requested_interest": "attraction",
            "address": "Old Goa Rd, Bainguinim, Goa",
            "city": "Old Goa",
            "state": "Goa",
            "country": "India",
            "latitude": 15.5009,
            "longitude": 73.9116,
            "distance_meters": 2000,
            "description": "UNESCO World Heritage site holding the mortal remains of St. Francis Xavier",
        },
        {
            "name": "Fort Aguada",
            "category": ["tourism.attraction", "tourism.sights.memorial.monument"],
            "requested_interest": "attraction",
            "address": "Sinquerim, Candolim, Goa",
            "city": "Candolim",
            "state": "Goa",
            "country": "India",
            "latitude": 15.4924,
            "longitude": 73.7736,
            "distance_meters": 12000,
            "description": "Well-preserved 17th-century Portuguese fort and lighthouse overlooking Arabian Sea",
        },
        {
            "name": "Calangute Beach",
            "category": ["beach", "tourism.attraction"],
            "requested_interest": "attraction",
            "address": "Calangute, Goa",
            "city": "Calangute",
            "state": "Goa",
            "country": "India",
            "latitude": 15.5442,
            "longitude": 73.7553,
            "distance_meters": 14000,
            "description": "Popular North Goa beach known for water sports and vibrant beach shacks",
        },
        {
            "name": "Dudhsagar Falls",
            "category": ["tourism.attraction", "national_park"],
            "requested_interest": "attraction",
            "address": "Sonaulim, Goa",
            "city": "Sonaulim",
            "state": "Goa",
            "country": "India",
            "latitude": 15.3144,
            "longitude": 74.3143,
            "distance_meters": 60000,
            "description": "Spectacular 4-tiered waterfall in Bhagwan Mahaveer Sanctuary",
        },
    ],
}


# ============================================================
# PLACES SEARCH CACHE
# ============================================================

_PLACES_CACHE: dict[tuple, dict] = {}


# ============================================================
# EXCEPTIONS
# ============================================================

class PlacesServiceError(Exception):
    """
    Base exception for Places service.
    """

    pass


class PlacesAPIError(PlacesServiceError):
    """
    Raised when Geoapify API fails.
    """

    pass


# ============================================================
# PLACES SERVICE
# ============================================================

class PlacesService:

    def __init__(
        self,
        api_key=None,
        base_url=BASE_URL,
        timeout=TIMEOUT,
    ):

        self.api_key = (
            api_key
            if api_key is not None
            else settings.geoapify_api_key
        )

        self.base_url = base_url

        self.timeout = timeout

    # ========================================================
    # VALIDATE COORDINATES
    # ========================================================

    @staticmethod
    def _validate_coordinates(
        latitude,
        longitude,
    ):

        # ----------------------------------------------------
        # LATITUDE
        # ----------------------------------------------------

        if isinstance(
            latitude,
            bool,
        ) or not isinstance(
            latitude,
            (int, float),
        ):

            raise ValueError(
                "Latitude must be a number."
            )

        if not -90 <= latitude <= 90:

            raise ValueError(
                "Latitude must be between -90 and 90."
            )

        # ----------------------------------------------------
        # LONGITUDE
        # ----------------------------------------------------

        if isinstance(
            longitude,
            bool,
        ) or not isinstance(
            longitude,
            (int, float),
        ):

            raise ValueError(
                "Longitude must be a number."
            )

        if not -180 <= longitude <= 180:

            raise ValueError(
                "Longitude must be between -180 and 180."
            )

    # ========================================================
    # VALIDATE SEARCH PARAMETERS
    # ========================================================

    @staticmethod
    def _validate_search_parameters(
        interest,
        radius,
        limit,
    ):

        # ----------------------------------------------------
        # INTEREST
        # ----------------------------------------------------

        if not isinstance(
            interest,
            str,
        ):

            raise ValueError(
                "Interest must be a string."
            )

        interest_clean = interest.strip().lower()

        if not interest_clean:

            raise ValueError(
                "Interest cannot be empty."
            )

        # ----------------------------------------------------
        # CATEGORY
        # ----------------------------------------------------

        category = PLACE_CATEGORIES.get(
            interest_clean
        )

        if not category:

            raise ValueError(
                f"Unsupported interest: {interest}. "
                "Please choose a supported place category."
            )

        # ----------------------------------------------------
        # RADIUS
        # ----------------------------------------------------

        if isinstance(
            radius,
            bool,
        ) or not isinstance(
            radius,
            int,
        ):

            raise ValueError(
                "Radius must be a positive integer."
            )

        if radius <= 0:

            raise ValueError(
                "Radius must be greater than 0."
            )

        # ----------------------------------------------------
        # LIMIT
        # ----------------------------------------------------

        if isinstance(
            limit,
            bool,
        ) or not isinstance(
            limit,
            int,
        ):

            raise ValueError(
                "Limit must be a positive integer."
            )

        if limit <= 0:

            raise ValueError(
                "Limit must be greater than 0."
            )

        return (
            interest_clean,
            category,
        )

    # ========================================================
    # SEARCH NEARBY PLACES
    # ========================================================

    def search_nearby_places(
        self,
        latitude,
        longitude,
        interest,
        radius=5000,
        limit=10,
    ):

        # ----------------------------------------------------
        # VALIDATE COORDINATES
        # ----------------------------------------------------

        self._validate_coordinates(
            latitude=latitude,
            longitude=longitude,
        )

        # ----------------------------------------------------
        # VALIDATE SEARCH PARAMETERS
        # ----------------------------------------------------

        (
            interest_clean,
            category,
        ) = self._validate_search_parameters(
            interest=interest,
            radius=radius,
            limit=limit,
        )

        # ----------------------------------------------------
        # API KEY
        # ----------------------------------------------------

        if not self.api_key:

            logger.error(
                "Geoapify API key is missing."
            )

            raise PlacesAPIError(
                "Places provider is not configured."
            )

        # ----------------------------------------------------
        # CACHE KEY
        # ----------------------------------------------------

        cache_key = (
            round(float(latitude), 6),
            round(float(longitude), 6),
            category,
            radius,
            limit,
        )

        # ----------------------------------------------------
        # CACHE HIT
        # ----------------------------------------------------

        if cache_key in _PLACES_CACHE:

            logger.info(
                "Places cache hit | "
                "interest=%s | radius=%s | limit=%s",
                interest_clean,
                radius,
                limit,
            )

            return _PLACES_CACHE[cache_key]

        logger.info(
            "Places cache miss | "
            "interest=%s | radius=%s | limit=%s",
            interest_clean,
            radius,
            limit,
        )

        # ----------------------------------------------------
        # REQUEST PARAMETERS
        # ----------------------------------------------------

        params = {
            "apiKey": self.api_key,

            "categories": category,

            "filter": (
                f"circle:"
                f"{longitude},"
                f"{latitude},"
                f"{radius}"
            ),

            "bias": (
                f"proximity:"
                f"{longitude},"
                f"{latitude}"
            ),

            "limit": limit,

            "lang": "en",
        }

        logger.info(
            "Places search started | "
            "interest=%s | radius=%s | limit=%s",
            interest_clean,
            radius,
            limit,
        )

        # ----------------------------------------------------
        # API REQUEST
        # ----------------------------------------------------

        try:

            response = requests.get(
                self.base_url,
                params=params,
                timeout=self.timeout,
            )

        except requests.exceptions.Timeout as exc:

            logger.error(
                "Geoapify timeout | interest=%s",
                interest_clean,
            )

            raise PlacesAPIError(
                "Places provider request timed out."
            ) from exc

        except requests.exceptions.ConnectionError as exc:

            logger.error(
                "Geoapify connection error | interest=%s",
                interest_clean,
            )

            raise PlacesAPIError(
                "Places provider is currently unreachable."
            ) from exc

        except requests.exceptions.RequestException as exc:

            logger.error(
                "Geoapify request failed | "
                "interest=%s | %s",
                interest_clean,
                exc,
            )

            raise PlacesAPIError(
                "Places provider request failed."
            ) from exc

        # ----------------------------------------------------
        # HTTP STATUS
        # ----------------------------------------------------

        if not response.ok:

            logger.error(
                "Geoapify HTTP error | "
                "status=%s | interest=%s",
                response.status_code,
                interest_clean,
            )

            raise PlacesAPIError(
                "Places provider returned an error."
            )

        # ----------------------------------------------------
        # JSON RESPONSE
        # ----------------------------------------------------

        try:

            data = response.json()

        except ValueError as exc:

            logger.error(
                "Geoapify returned invalid JSON."
            )

            raise PlacesAPIError(
                "Places provider returned an invalid response."
            ) from exc

        # ----------------------------------------------------
        # RESPONSE STRUCTURE
        # ----------------------------------------------------

        if not isinstance(
            data,
            dict,
        ):

            raise PlacesAPIError(
                "Places provider returned an invalid response."
            )

        # ----------------------------------------------------
        # PROVIDER ERROR
        # ----------------------------------------------------

        if data.get("error"):

            logger.error(
                "Geoapify provider error | interest=%s",
                interest_clean,
            )

            raise PlacesAPIError(
                "Places provider returned an error."
            )

        # ----------------------------------------------------
        # NORMALIZE
        # ----------------------------------------------------

        normalized = self._normalize(
            data=data,
            requested_interest=interest_clean,
        )

        logger.info(
            "Places search completed | "
            "interest=%s | results=%s",
            interest_clean,
            len(
                normalized.get(
                    "places",
                    [],
                )
            ),
        )

        # ----------------------------------------------------
        # STORE SUCCESSFUL RESULT IN CACHE
        # ----------------------------------------------------

        _PLACES_CACHE[cache_key] = normalized

        return normalized

    # ========================================================
    # SEARCH USING TRIP STATE
    # ========================================================

    def search_for_trip(
        self,
        state,
        radius=5000,
        limit=5,
    ):
        """
        Uses TripState destination coordinates
        and user preferences.

        Provider-supported preferences are sent directly
        to Geoapify.

        Soft/ranking preferences are NOT sent to Geoapify.
        When there are only soft preferences, default
        sightseeing categories are used so that the
        PlacesAgent still receives real places to rank.
        """

        # ----------------------------------------------------
        # STATE
        # ----------------------------------------------------

        if state is None:

            raise ValueError(
                "TripState cannot be None."
            )

        # ----------------------------------------------------
        # DESTINATION
        # ----------------------------------------------------

        if state.destination is None:

            raise ValueError(
                "Trip destination is required."
            )

        latitude = (
            state.destination.latitude
        )

        longitude = (
            state.destination.longitude
        )

        # ----------------------------------------------------
        # COORDINATES
        # ----------------------------------------------------

        if (
            latitude is None
            or longitude is None
        ):

            raise ValueError(
                "Destination latitude and longitude "
                "are required."
            )

        self._validate_coordinates(
            latitude=latitude,
            longitude=longitude,
        )

        # ----------------------------------------------------
        # PREFERENCES
        # ----------------------------------------------------

        #
        # IMPORTANT:
        #
        # Do NOT return early when preferences are empty.
        #
        # Even if the user does not provide preferences,
        # we should still retrieve common sightseeing
        # places.
        #
        # This allows the PlacesAgent to provide useful
        # recommendations.
        #

        user_preferences = (
            state.preferences
            if state.preferences
            else []
        )

        all_places = []

        successful_searches = 0

        failed_api_searches = 0

        invalid_preferences = 0

        # ----------------------------------------------------
        # CLASSIFY USER PREFERENCES
        #
        # Provider preferences are real Geoapify categories.
        #
        # Examples:
        #
        #   museum
        #   park
        #   beach
        #   temple
        #
        # Soft/ranking preferences:
        #
        #   budget
        #   comfortable
        #   relaxing
        #   family
        #   scenic
        #
        # These are NOT sent to Geoapify.
        #
        # They remain available in TripState for the
        # PlacesAgent / LLM ranking layer.
        # ----------------------------------------------------

        provider_preferences = []

        ranking_only_preferences = []

        for preference in user_preferences:

            if not isinstance(
                preference,
                str,
            ):
                continue

            preference_clean = (
                preference.strip().lower()
            )

            if not preference_clean:
                continue

            if preference_clean in PLACE_CATEGORIES:

                provider_preferences.append(
                    preference_clean
                )

            else:

                ranking_only_preferences.append(
                    preference_clean
                )

        # ----------------------------------------------------
        # REMOVE DUPLICATE PREFERENCES
        # ----------------------------------------------------

        provider_preferences = list(
            dict.fromkeys(
                provider_preferences
            )
        )

        ranking_only_preferences = list(
            dict.fromkeys(
                ranking_only_preferences
            )
        )

        logger.info(
            "Place preference classification | "
            "provider=%s | ranking_only=%s",
            provider_preferences,
            ranking_only_preferences,
        )

        # ----------------------------------------------------
        # DEFAULT FALLBACK
        # ----------------------------------------------------
        #
        # If there are no provider-supported preferences,
        # use generic sightseeing categories.
        #
        # Example:
        #
        # preferences = ["budget", "comfortable"]
        #
        # becomes:
        #
        # provider search:
        #   attraction
        #   park
        #   museum
        #
        # ranking preferences remain:
        #   budget
        #   comfortable
        #
        # The LLM can then rank actual places based on
        # these soft preferences.
        #
        # ----------------------------------------------------

        if not provider_preferences:

            provider_preferences = (
                DEFAULT_PLACE_PREFERENCES.copy()
            )

            logger.info(
                "No provider-supported place preferences | "
                "using default sightseeing categories | "
                "defaults=%s | ranking_only=%s",
                provider_preferences,
                ranking_only_preferences,
            )

        # ----------------------------------------------------
        # SEARCH PROVIDER-SUPPORTED PREFERENCES
        # ----------------------------------------------------

        for preference in provider_preferences:

            try:

                result = self.search_nearby_places(
                    latitude=latitude,
                    longitude=longitude,
                    interest=preference,
                    radius=radius,
                    limit=limit,
                )

                places = result.get(
                    "places",
                    [],
                )

                if not isinstance(
                    places,
                    list,
                ):

                    places = []

                successful_searches += 1

                all_places.extend(
                    places
                )

                logger.info(
                    "Places category completed | "
                    "preference=%s | results=%s",
                    preference,
                    len(places),
                )

            except PlacesAPIError as exc:

                failed_api_searches += 1

                logger.error(
                    "Places provider failed | "
                    "preference=%s | error=%s",
                    preference,
                    exc,
                )

                continue

            except PlacesServiceError as exc:

                failed_api_searches += 1

                logger.error(
                    "Places service failed | "
                    "preference=%s | error=%s",
                    preference,
                    exc,
                )

                continue

            except ValueError as exc:

                invalid_preferences += 1

                logger.error(
                    "Invalid place preference | "
                    "preference=%s | error=%s",
                    preference,
                    exc,
                )

                continue

        # ----------------------------------------------------
        # ALL PROVIDER CALLS FAILED
        # ----------------------------------------------------

        if (
            failed_api_searches > 0
            and successful_searches == 0
            and invalid_preferences == 0
        ):

            state.place_options = []

            raise PlacesAPIError(
                "Places search is temporarily unavailable."
            )

        # ----------------------------------------------------
        # AUGMENT ICONIC DESTINATION ATTRACTIONS
        # ----------------------------------------------------

        dest_key = (state.destination.name or "").strip().lower()
        iconic_matches = []
        for key, iconic_list in DESTINATION_ICONIC_PLACES.items():
            if key in dest_key or dest_key in key:
                iconic_matches.extend(iconic_list)
        if iconic_matches:
            all_places = iconic_matches + all_places

        # ----------------------------------------------------
        # REMOVE DUPLICATES
        # ----------------------------------------------------

        unique_places = {}

        for place in all_places:

            if not isinstance(
                place,
                dict,
            ):
                continue

            # ------------------------------------------------
            # PRIMARY DEDUPLICATION
            # ------------------------------------------------

            place_id = place.get(
                "place_id"
            )

            if place_id:

                unique_places[
                    str(place_id)
                ] = place

            else:

                # --------------------------------------------
                # FALLBACK DEDUPLICATION BY NAME
                # --------------------------------------------

                name = place.get(
                    "name"
                )

                if name:

                    unique_places[
                        name.strip().lower()
                    ] = place

        # ----------------------------------------------------
        # SAVE INTO TRIP STATE
        # ----------------------------------------------------

        state.place_options = list(
            unique_places.values()
        )

        logger.info(
            "Trip places search completed | "
            "total=%s | provider_searches=%s | "
            "provider_failures=%s | "
            "invalid_preferences=%s | "
            "ranking_only=%s",
            len(state.place_options),
            successful_searches,
            failed_api_searches,
            invalid_preferences,
            ranking_only_preferences,
        )

        return state

    # ========================================================
    # NORMALIZE GEOAPIFY RESPONSE
    # ========================================================

    @staticmethod
    def _normalize(
        data,
        requested_interest,
    ):

        places = []

        if not isinstance(
            data,
            dict,
        ):

            return {
                "source": "geoapify",
                "interest": requested_interest,
                "count": 0,
                "places": [],
            }

        features = data.get(
            "features",
            [],
        )

        if not isinstance(
            features,
            list,
        ):

            features = []

        # ----------------------------------------------------
        # PROCESS FEATURES
        # ----------------------------------------------------

        for feature in features:

            if not isinstance(
                feature,
                dict,
            ):
                continue

            properties = feature.get(
                "properties",
                {},
            )

            if not isinstance(
                properties,
                dict,
            ):
                continue

            name = properties.get(
                "name"
            )

            # ------------------------------------------------
            # SKIP UNNAMED AND NOISE/GENERIC PLACES
            # ------------------------------------------------

            if not isinstance(
                name,
                str,
            ) or not name.strip():
                continue

            name_lower = name.strip().lower()
            noise_words = [
                "toilet", "restroom", "lavatory", "washroom", "sulabh",
                "bus stop", "bus stand", "bus depot", "parking", "car park",
                "clinic", "hospital", "dispensary", "pharmacy", "medical store",
                "bank", "atm", "police station", "post office", "petrol pump",
                "gas station", "fuel station", "grocery", "supermarket",
                "corporate office", "pvt ltd", "private limited", "ltd.",
                "apartment", "hostel", "pg for", "school", "tuition", "coaching",
                "viewpoint", "view point", "scenic meadow", "valley viewpoint",
                "view to waterfall", "view of waterfall", "waterfall view", "scenic point",
                "nature trail", "lookout point", "photo point", "mountain view",
                "river viewpoint", "valley view", "scenic spot",
            ]
            if any(nw in name_lower for nw in noise_words):
                continue

            categories = properties.get(
                "categories",
                [],
            )

            if not isinstance(
                categories,
                list,
            ):
                categories = []

            # Skip noise categories
            noise_cats = {
                "amenity.toilet", "amenity.bus_stop", "amenity.parking", "amenity.fuel",
                "amenity.pharmacy", "amenity.hospital", "amenity.clinic", "amenity.bank",
                "amenity.atm", "amenity.police", "amenity.post_box", "commercial.office",
            }
            if any(cat in noise_cats for cat in categories):
                continue

            # ------------------------------------------------
            # NORMALIZED PLACE
            # ------------------------------------------------

            place = {

                "place_id": properties.get(
                    "place_id"
                ),

                "name": name.strip(),

                "category": categories,

                "requested_interest":
                    requested_interest,

                "address": properties.get(
                    "formatted"
                ),

                "city": properties.get(
                    "city"
                ),

                "state": properties.get(
                    "state"
                ),

                "country": properties.get(
                    "country"
                ),

                "latitude": properties.get(
                    "lat"
                ),

                "longitude": properties.get(
                    "lon"
                ),

                "distance_meters":
                    properties.get(
                        "distance"
                    ),
            }

            places.append(
                place
            )

        # ----------------------------------------------------
        # SORT BY DISTANCE
        # ----------------------------------------------------

        places.sort(
            key=lambda place: (

                place.get(
                    "distance_meters"
                )

                if isinstance(
                    place.get(
                        "distance_meters"
                    ),
                    (int, float),
                )

                else float("inf")
            )
        )

        # ----------------------------------------------------
        # RANK
        # ----------------------------------------------------

        for index, place in enumerate(
            places,
            start=1,
        ):

            place["rank"] = index

        # ----------------------------------------------------
        # RESPONSE
        # ----------------------------------------------------

        return {

            "source": "geoapify",

            "interest":
                requested_interest,

            "count":
                len(places),

            "places":
                places,
        }
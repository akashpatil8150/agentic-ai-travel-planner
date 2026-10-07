import logging
import time
import requests

from app.core.config import settings
from app.observability.metrics import observability_metrics


logger = logging.getLogger(__name__)


# ============================================================
# SHARED LITEAPI HOTEL SEARCH CACHE
# ============================================================
#
# Module-level cache means multiple LiteAPIClient instances
# share the same cache during the application process.
#
# Same hotel search:
#
# Client #1 -> CACHE MISS -> LiteAPI -> CACHE STORE
# Client #2 -> CACHE HIT  -> NO LiteAPI CALL
#
# IMPORTANT:
# Only hotel SEARCH responses are cached.
# PREBOOK responses are NEVER cached.
#
# ============================================================

_LITEAPI_SEARCH_CACHE: dict[tuple, dict] = {}


class LiteAPIClient:
    """
    Primary hotel provider.

    Responsibilities:
        - Call LiteAPI
        - Return raw provider response
        - Handle provider/network errors
        - Prebook selected hotel offer
        - Prevent duplicate hotel search API calls

    Does NOT:
        - normalize provider response
        - rank hotels
        - decide fallback
        - contain agent logic
    """

    BASE_URL = "https://api.liteapi.travel/v3.0"

    RATES_ENDPOINT = (
        f"{BASE_URL}/hotels/rates"
    )

    PREBOOK_ENDPOINT = (
        f"{BASE_URL}/rates/prebook"
    )

    SEARCH_TIMEOUT = 30

    PREBOOK_TIMEOUT = 60

    def __init__(self):

        self.api_key = (
            settings.liteapi_api_key
        )

        if not self.api_key:

            raise RuntimeError(
                "LITEAPI_API_KEY not found in .env"
            )

        self.headers = {
            "X-API-Key": self.api_key,
            "Accept": "application/json",
            "Content-Type": "application/json",
        }

    # ========================================================
    # SEARCH CACHE KEY
    # ========================================================

    @staticmethod
    def _build_search_cache_key(
        city: str,
        country_code: str,
        checkin: str,
        checkout: str,
        adults: int,
        children: int,
        rooms: int,
        currency: str,
    ) -> tuple:

        return (
            city.strip().lower(),
            country_code.strip().upper(),
            checkin.strip(),
            checkout.strip(),
            int(adults),
            int(children),
            int(rooms),
            currency.strip().upper(),
        )

    # ========================================================
    # SEARCH HOTELS
    # ========================================================

    def search_hotels(
        self,
        city: str,
        country_code: str,
        checkin: str,
        checkout: str,
        adults: int,
        children: int,
        rooms: int,
        currency: str,
    ) -> dict:

        # ====================================================
        # BASIC SAFETY VALIDATION
        # ====================================================

        if not city or not city.strip():

            raise ValueError(
                "City cannot be empty"
            )

        if (
            not country_code
            or not country_code.strip()
        ):

            raise ValueError(
                "Country code is required"
            )

        if (
            not checkin
            or not checkin.strip()
        ):

            raise ValueError(
                "Check-in date is required"
            )

        if (
            not checkout
            or not checkout.strip()
        ):

            raise ValueError(
                "Check-out date is required"
            )

        if adults < 1:

            raise ValueError(
                "Adults must be at least 1"
            )

        if children < 0:

            raise ValueError(
                "Children cannot be negative"
            )

        if rooms < 1:

            raise ValueError(
                "Rooms must be at least 1"
            )

        if (
            not currency
            or not currency.strip()
        ):

            raise ValueError(
                "Currency is required"
            )

        # ====================================================
        # NORMALIZE
        # ====================================================

        city = city.strip()

        country_code = (
            country_code.strip().upper()
        )

        checkin = checkin.strip()

        checkout = checkout.strip()

        currency = (
            currency.strip().upper()
        )

        # ====================================================
        # CACHE KEY
        # ====================================================

        cache_key = (
            self._build_search_cache_key(
                city=city,
                country_code=country_code,
                checkin=checkin,
                checkout=checkout,
                adults=adults,
                children=children,
                rooms=rooms,
                currency=currency,
            )
        )

        # ====================================================
        # CACHE HIT
        # ====================================================

        cached_result = (
            _LITEAPI_SEARCH_CACHE.get(
                cache_key
            )
        )

        if cached_result is not None:
            logger.debug(
                "LiteAPI hotel search cache hit | "
                "city=%s | checkin=%s | checkout=%s",
                city,
                checkin,
                checkout,
            )
            observability_metrics.record_cache_event(
                provider="LiteAPI",
                type="hotel_search",
                city=city,
                result="HIT",
            )
            return cached_result

        # ====================================================
        # CACHE MISS
        # ====================================================

        logger.debug(
            "LiteAPI hotel search cache miss | "
            "city=%s | checkin=%s | checkout=%s",
            city,
            checkin,
            checkout,
        )
        observability_metrics.record_cache_event(
            provider="LiteAPI",
            type="hotel_search",
            city=city,
            result="MISS",
        )

        # ====================================================
        # OCCUPANCIES
        # ====================================================

        rooms_count = max(1, rooms)
        base_adults = max(1, adults // rooms_count)
        rem_adults = adults % rooms_count if adults >= rooms_count else 0

        children_per_room = [[] for _ in range(rooms_count)]
        for c_idx in range(children):
            # Standard child age (7) for rate searches
            children_per_room[c_idx % rooms_count].append(7)

        occupancies = []
        for i in range(rooms_count):
            room_adults = base_adults + (1 if i < rem_adults else 0)
            occupancies.append(
                {
                    "adults": max(1, room_adults),
                    "children": children_per_room[i],
                }
            )

        # ====================================================
        # REQUEST PAYLOAD
        # ====================================================

        payload = {
            "cityName": city,
            "countryCode": country_code,
            "checkin": checkin,
            "checkout": checkout,
            "occupancies": occupancies,
            "currency": currency,
            "guestNationality": country_code,
            "roomMapping": True,
            "maxRatesPerHotel": 1,
            "includeHotelData": True,
        }

        logger.debug(
            "LiteAPI hotel search | "
            "city=%s checkin=%s checkout=%s "
            "adults=%s children=%s rooms=%s",
            city,
            checkin,
            checkout,
            adults,
            children,
            rooms,
        )

        # ====================================================
        # API REQUEST
        # ====================================================

        start_time = time.perf_counter()
        try:

            response = requests.post(
                self.RATES_ENDPOINT,
                headers=self.headers,
                json=payload,
                timeout=self.SEARCH_TIMEOUT,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000
            observability_metrics.record_api_call(
                provider="LiteAPI",
                operation="hotel_search",
                city=city,
                status=response.status_code,
                latency_ms=latency_ms,
                cache="MISS",
            )

        except requests.Timeout as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            observability_metrics.record_api_call(
                provider="LiteAPI",
                operation="hotel_search",
                city=city,
                status="TIMEOUT",
                latency_ms=latency_ms,
                cache="MISS",
            )

            logger.error(
                "LiteAPI timeout | "
                "city=%s | %s",
                city,
                exc,
            )

            raise RuntimeError(
                "Hotel provider request timed out"
            ) from exc

        except requests.ConnectionError as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            observability_metrics.record_api_call(
                provider="LiteAPI",
                operation="hotel_search",
                city=city,
                status="ERROR",
                latency_ms=latency_ms,
                cache="MISS",
            )

            logger.error(
                "LiteAPI connection error | "
                "city=%s | %s",
                city,
                exc,
            )

            raise RuntimeError(
                "Hotel provider is currently unreachable"
            ) from exc

        except requests.RequestException as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            observability_metrics.record_api_call(
                provider="LiteAPI",
                operation="hotel_search",
                city=city,
                status="ERROR",
                latency_ms=latency_ms,
                cache="MISS",
            )

            logger.error(
                "LiteAPI request error | "
                "city=%s | %s",
                city,
                exc,
            )

            raise RuntimeError(
                "Hotel provider request failed"
            ) from exc

        # ====================================================
        # PARSE JSON
        # ====================================================

        try:

            result = response.json()

        except ValueError as exc:

            logger.error(
                "LiteAPI returned invalid JSON | "
                "status=%s",
                response.status_code,
            )

            raise RuntimeError(
                "Hotel provider returned an invalid response"
            ) from exc

        # ====================================================
        # HTTP ERROR
        # ====================================================

        if not response.ok:

            logger.error(
                "LiteAPI HTTP error | "
                "status=%s | response=%s",
                response.status_code,
                result,
            )

            raise RuntimeError(
                self._build_provider_error(
                    result=result,
                    status_code=response.status_code,
                )
            )

        # ====================================================
        # RESPONSE TYPE
        # ====================================================

        if not isinstance(
            result,
            dict,
        ):

            logger.error(
                "LiteAPI returned non-object response"
            )

            raise RuntimeError(
                "Hotel provider returned an invalid response"
            )

        # ====================================================
        # PROVIDER-LEVEL FAILURE
        # ====================================================

        if result.get("success") is False:

            message = (
                result.get("message")
                or result.get("error")
                or "Hotel provider request failed"
            )

            logger.error(
                "LiteAPI provider failure | %s",
                message,
            )

            raise RuntimeError(
                f"Hotel provider error: {message}"
            )

        # ====================================================
        # SUCCESS
        # ====================================================

        logger.info(
            "LiteAPI hotel search successful | "
            "status=%s",
            response.status_code,
        )

        # ====================================================
        # STORE ONLY SUCCESSFUL RESPONSE
        # ====================================================
        #
        # Important:
        # Errors are NOT cached.
        #
        # This means a temporary LiteAPI failure won't poison
        # the cache and permanently force fallback behavior.
        #
        # ====================================================

        _LITEAPI_SEARCH_CACHE[
            cache_key
        ] = result

        logger.info(
            "LiteAPI hotel search cached | "
            "city=%s | checkin=%s | checkout=%s",
            city,
            checkin,
            checkout,
        )

        print(
            "\n[LITEAPI CACHE STORE]"
        )

        return result

    # ========================================================
    # PREBOOK
    # ========================================================

    def prebook(
        self,
        offer_id: str,
    ) -> dict:

        # ----------------------------------------------------
        # LOCAL VALIDATION
        # ----------------------------------------------------

        if (
            not offer_id
            or not offer_id.strip()
        ):

            raise ValueError(
                "Offer ID cannot be empty"
            )

        offer_id = offer_id.strip()

        # ----------------------------------------------------
        # REQUEST PAYLOAD
        # ----------------------------------------------------

        payload = {
            "offerId": offer_id,
            "usePaymentSdk": True,
        }

        logger.info(
            "LiteAPI prebook | "
            "offer_id=%s",
            offer_id,
        )

        # ====================================================
        # API REQUEST
        # ====================================================

        try:

            response = requests.post(
                self.PREBOOK_ENDPOINT,
                headers=self.headers,
                json=payload,
                timeout=self.PREBOOK_TIMEOUT,
            )

        except requests.Timeout as exc:

            logger.error(
                "LiteAPI prebook timeout | "
                "offer_id=%s",
                offer_id,
            )

            raise RuntimeError(
                "Hotel prebooking request timed out"
            ) from exc

        except requests.ConnectionError as exc:

            logger.error(
                "LiteAPI prebook connection error | "
                "offer_id=%s",
                offer_id,
            )

            raise RuntimeError(
                "Hotel provider is currently unreachable"
            ) from exc

        except requests.RequestException as exc:

            logger.error(
                "LiteAPI prebook request failed | "
                "offer_id=%s | %s",
                offer_id,
                exc,
            )

            raise RuntimeError(
                "Hotel prebooking request failed"
            ) from exc

        # ====================================================
        # PARSE JSON
        # ====================================================

        try:

            result = response.json()

        except ValueError as exc:

            raise RuntimeError(
                "Hotel provider returned an invalid "
                "prebook response"
            ) from exc

        # ====================================================
        # HTTP ERROR
        # ====================================================

        if not response.ok:

            logger.error(
                "LiteAPI prebook HTTP error | "
                "status=%s | offer_id=%s",
                response.status_code,
                offer_id,
            )

            raise RuntimeError(
                self._build_provider_error(
                    result=result,
                    status_code=response.status_code,
                )
            )

        # ====================================================
        # RESPONSE TYPE
        # ====================================================

        if not isinstance(
            result,
            dict,
        ):

            raise RuntimeError(
                "Hotel provider returned an invalid "
                "prebook response"
            )

        # ====================================================
        # PROVIDER FAILURE
        # ====================================================

        if result.get("success") is False:

            message = (
                result.get("message")
                or result.get("error")
                or "Hotel prebooking failed"
            )

            raise RuntimeError(
                f"Hotel prebooking error: {message}"
            )

        # ====================================================
        # SUCCESS
        # ====================================================

        logger.info(
            "LiteAPI prebook successful | "
            "offer_id=%s",
            offer_id,
        )

        return result

    # ========================================================
    # PROVIDER ERROR MESSAGE
    # ========================================================

    @staticmethod
    def _build_provider_error(
        result: dict,
        status_code: int,
    ) -> str:

        message = None

        if isinstance(
            result,
            dict,
        ):

            message = (
                result.get("message")
                or result.get("error")
            )

            error_data = result.get(
                "errors"
            )

            if (
                not message
                and isinstance(
                    error_data,
                    list,
                )
                and error_data
            ):

                first_error = (
                    error_data[0]
                )

                if isinstance(
                    first_error,
                    dict,
                ):

                    message = (
                        first_error.get(
                            "message"
                        )
                        or first_error.get(
                            "detail"
                        )
                    )

        if message:

            return (
                "Hotel provider request failed: "
                f"{message}"
            )

        return (
            "Hotel provider request failed "
            f"with status {status_code}"
        )
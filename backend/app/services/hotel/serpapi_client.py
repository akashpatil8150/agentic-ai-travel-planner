import logging
import re
from collections.abc import Mapping

import serpapi

from app.core.config import settings


logger = logging.getLogger(__name__)


# ============================================================
# SHARED SERPAPI HOTEL SEARCH CACHE
# ============================================================
#
# Multiple SerpAPIHotelClient instances will share this cache.
#
# Same search request:
#
# First call  -> CACHE MISS -> SerpAPI -> CACHE STORE
# Next call   -> CACHE HIT  -> NO SerpAPI call
#
# Failed responses are NEVER cached.
#
# ============================================================

_SERPAPI_HOTEL_CACHE: dict[tuple, dict] = {}


class SerpAPIHotelClient:
    """
    Secondary / fallback hotel provider.

    Responsibilities:
        - Basic client-level validation
        - Call SerpAPI
        - Handle provider/network failures
        - Cache successful hotel searches
        - Return raw provider response

    Does NOT:
        - normalize hotels
        - rank hotels
        - decide fallback
        - contain agent logic
    """

    def __init__(self):

        self.api_key = settings.serp_api_key

        if not self.api_key:

            raise RuntimeError(
                "SERP_API_KEY not found in .env"
            )

        self.client = serpapi.Client(
            api_key=self.api_key
        )

    # ========================================================
    # CACHE KEY
    # ========================================================

    @staticmethod
    def _build_cache_key(
        city: str,
        checkin: str,
        checkout: str,
        adults: int,
        currency: str,
    ) -> tuple:

        return (
            "hotels",
            city.strip().lower(),
            checkin.strip(),
            checkout.strip(),
            int(adults),
            currency.strip().upper(),
        )

    # ========================================================
    # SAFE ERROR EXTRACTION
    # ========================================================

    @staticmethod
    def _extract_safe_error(exc: Exception) -> tuple[int | None, str]:
        """
        Extract status code and safe error reason from exception
        without leaking API keys or request URLs into logs.
        """
        response = getattr(exc, "response", None)
        status_code = getattr(response, "status_code", None)
        reason = None
        if response is not None:
            try:
                body = response.json()
                if isinstance(body, dict):
                    reason = body.get("error") or body.get("message")
            except Exception:
                if getattr(response, "text", None):
                    reason = response.text[:200]

        if not reason:
            msg = str(exc)
            if "for url:" in msg:
                msg = msg.split("for url:")[0].strip()
            msg = re.sub(r'(api_key|apiKey|key)=[a-zA-Z0-9_\-]+', r'\1=REDACTED', msg)
            reason = msg or type(exc).__name__

        return status_code, str(reason)

    # ========================================================
    # SEARCH HOTELS
    # ========================================================

    def search_hotels(
        self,
        city: str,
        checkin: str,
        checkout: str,
        adults: int,
        currency: str = "INR",
    ) -> dict:

        # ----------------------------------------------------
        # BASIC SAFETY VALIDATION
        # ----------------------------------------------------

        if not city or not city.strip():

            raise ValueError(
                "City cannot be empty"
            )

        if not checkin or not checkin.strip():

            raise ValueError(
                "Check-in date is required"
            )

        if not checkout or not checkout.strip():

            raise ValueError(
                "Check-out date is required"
            )

        if adults < 1:

            raise ValueError(
                "Adults must be at least 1"
            )

        if not currency or not currency.strip():

            raise ValueError(
                "Currency is required"
            )

        # ----------------------------------------------------
        # NORMALIZE
        # ----------------------------------------------------

        city = city.strip()

        checkin = checkin.strip()

        checkout = checkout.strip()

        currency = (
            currency.strip().upper()
        )

        # ----------------------------------------------------
        # CACHE KEY
        # ----------------------------------------------------

        cache_key = (
            self._build_cache_key(
                city=city,
                checkin=checkin,
                checkout=checkout,
                adults=adults,
                currency=currency,
            )
        )

        # ----------------------------------------------------
        # CACHE HIT
        # ----------------------------------------------------

        cached_result = (
            _SERPAPI_HOTEL_CACHE.get(
                cache_key
            )
        )

        if cached_result is not None:

            logger.info(
                "SerpAPI hotel search cache hit | "
                "city=%s | checkin=%s | checkout=%s",
                city,
                checkin,
                checkout,
            )

            print(
                "\n[SERPAPI CACHE HIT]"
            )

            print(
                f"City     : {city}"
            )

            print(
                f"Check-in : {checkin}"
            )

            print(
                f"Checkout : {checkout}"
            )

            return cached_result

        # ----------------------------------------------------
        # CACHE MISS
        # ----------------------------------------------------

        logger.info(
            "SerpAPI hotel search cache miss | "
            "city=%s | checkin=%s | checkout=%s",
            city,
            checkin,
            checkout,
        )

        print(
            "\n[SERPAPI CACHE MISS]"
        )

        print(
            f"City     : {city}"
        )

        print(
            f"Check-in : {checkin}"
        )

        print(
            f"Checkout : {checkout}"
        )

        # ----------------------------------------------------
        # SERPAPI PARAMETERS
        # ----------------------------------------------------
        # Google Hotels engine caps total travelers at 6.
        # Cap adults between 1 and 6 for query validity.
        serp_adults = max(1, min(adults, 6))

        search_params = {

            "engine": "google_hotels",

            "q": f"hotels in {city}",

            "check_in_date": checkin,

            "check_out_date": checkout,

            "adults": serp_adults,

            "currency": currency,

            "gl": "in",

            "hl": "en",

            "sort_by": "3",
        }

        logger.info(
            "SerpAPI hotel search | "
            "city=%s checkin=%s checkout=%s adults=%s (query_adults=%s)",
            city,
            checkin,
            checkout,
            adults,
            serp_adults,
        )

        # ----------------------------------------------------
        # API REQUEST
        # ----------------------------------------------------

        try:

            results = self.client.search(
                search_params
            )

        except TimeoutError:

            logger.error(
                "SerpAPI hotel timeout | city=%s",
                city,
            )

            raise RuntimeError(
                "Hotel fallback provider timed out"
            )

        except Exception as exc:

            status_code, reason = self._extract_safe_error(exc)

            if status_code:
                logger.error(
                    "SerpAPI hotel request failed | status=%s | reason=%s",
                    status_code,
                    reason,
                )
            else:
                logger.error(
                    "SerpAPI hotel request failed | reason=%s",
                    reason,
                )

            raise RuntimeError(
                f"Hotel fallback provider failed: {reason}"
            )

        # ----------------------------------------------------
        # RESPONSE VALIDATION
        # ----------------------------------------------------

        if results is None:

            logger.error(
                "SerpAPI returned empty response"
            )

            raise RuntimeError(
                "Hotel fallback provider returned "
                "an empty response"
            )

        if not isinstance(results, Mapping):
            logger.error(
                "SerpAPI returned invalid response type: %s",
                type(results).__name__,
            )

            raise RuntimeError(
                "Hotel fallback provider returned "
                "an invalid response"
            )

        # The SerpAPI SDK may return SerpResults,
        # which is mapping-like. Convert it to a plain dict
        # before the rest of the application reads the response.
        results = dict(results)

        # ----------------------------------------------------
        # SERPAPI PROVIDER ERROR
        # ----------------------------------------------------

        if results.get("error"):

            error_message = results.get(
                "error"
            )

            logger.error(
                "SerpAPI provider error | %s",
                error_message,
            )

            raise RuntimeError(
                "Hotel fallback provider returned "
                "an error"
            )

        # ----------------------------------------------------
        # RESULTS
        # ----------------------------------------------------

        properties = results.get(
            "properties",
            []
        )

        if properties is None:

            properties = []

        if not isinstance(
            properties,
            list,
        ):

            logger.warning(
                "SerpAPI properties field is invalid"
            )

            properties = []

        logger.info(
            "SerpAPI hotel search successful | "
            "hotels=%s",
            len(properties),
        )

        # ----------------------------------------------------
        # CACHE SUCCESSFUL RESPONSE ONLY
        # ----------------------------------------------------
        #
        # Empty successful responses are also safe to cache
        # for the current application run because repeating
        # the exact same fallback search would otherwise create
        # another unnecessary provider call.
        #
        # Provider errors are never cached.
        #
        # ----------------------------------------------------

        _SERPAPI_HOTEL_CACHE[
            cache_key
        ] = results

        logger.info(
            "SerpAPI hotel search cached | "
            "city=%s | checkin=%s | checkout=%s",
            city,
            checkin,
            checkout,
        )

        print(
            "\n[SERPAPI CACHE STORE]"
        )

        return results
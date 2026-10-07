import logging

from app.services.hotel.hotel_schema import (
    HotelSearchRequest,
    HotelSearchResponse,
)

from app.services.hotel.hotel_location_resolver import (
    HotelLocationResolver,
)

from app.services.hotel.liteapi_client import (
    LiteAPIClient,
)

from app.services.hotel.serpapi_client import (
    SerpAPIHotelClient,
)

from app.services.hotel.hotel_normalizer import (
    HotelNormalizer,
)


logger = logging.getLogger(__name__)


# Provider-friendly city aliases.
# The user's destination name remains unchanged; aliases are used only
# when querying external hotel providers.
PROVIDER_CITY_ALIASES = {
    "mysuru": "Mysore",
    "bengaluru": "Bangalore",
    "gurugram": "Gurgaon",
    "kochi": "Cochin",
    "thiruvananthapuram": "Trivandrum",
    "mangaluru": "Mangalore",
    "puducherry": "Pondicherry",
    "prayagraj": "Allahabad",
}




class HotelService:

    PROVIDER_CITY_ALIASES = PROVIDER_CITY_ALIASES
    """
    Hotel search coordinator.

    Provider priority:

        1. LiteAPI  -> Primary
        2. SerpAPI  -> Fallback

    Responsibilities:
        - Coordinate providers
        - Trigger fallback
        - Normalize provider responses
        - Resolve provider-friendly hotel locations
        - Return application-level response

    Does NOT:
        - perform HTTP requests directly
        - expose provider exceptions to users
        - perform agent reasoning
    """

    def __init__(self):

        self.liteapi_client = LiteAPIClient()

        self.serpapi_client = SerpAPIHotelClient()

        self.normalizer = HotelNormalizer()

        self.location_resolver = HotelLocationResolver()

    @classmethod
    def _provider_city_candidates(cls, city: str) -> list[str]:
        """
        Return the original provider city first, followed by a known
        provider-friendly alias when one exists.
        """
        clean = str(city or "").strip()
        if not clean:
            return []

        candidates = [clean]
        alias = cls.PROVIDER_CITY_ALIASES.get(clean.lower())

        if alias and alias.lower() != clean.lower():
            candidates.append(alias)

        return candidates

    # ========================================================
    # SEARCH HOTELS
    # ========================================================

    def search_hotels(
        self,
        request: HotelSearchRequest,
    ) -> HotelSearchResponse:

        # ====================================================
        # HOTEL LOCATION RESOLUTION
        # ====================================================

        original_city = request.city

        provider_city = self.location_resolver.resolve(
            request.city
        )

        logger.info(
            "Hotel search location resolved | "
            "original_city=%s | provider_city=%s",
            original_city,
            provider_city,
        )

        # ====================================================
        # PRIMARY PROVIDER: LITEAPI
        # ====================================================

        try:

            logger.info(
                "Starting hotel search | "
                "provider=liteapi | "
                "city=%s | provider_city=%s | "
                "checkin=%s | checkout=%s",
                request.city,
                provider_city,
                request.checkin,
                request.checkout,
            )

            liteapi_hotels = []

            for candidate_city in self._provider_city_candidates(provider_city):
                logger.info(
                    "LiteAPI city candidate | "
                    "provider_city=%s",
                    candidate_city,
                )

                liteapi_response = (
                    self.liteapi_client.search_hotels(
                        city=candidate_city,
                        country_code=request.country_code,
                        checkin=request.checkin.isoformat(),
                        checkout=request.checkout.isoformat(),
                        adults=request.adults,
                        children=request.children,
                        rooms=request.rooms,
                        currency=request.currency,
                    )
                )

                candidate_hotels = (
                    self.normalizer.normalize_liteapi(
                        result=liteapi_response,
                        max_hotels=request.max_hotels,
                    )
                )

                logger.info(
                    "LiteAPI candidate completed | "
                    "city=%s | usable_hotels=%s",
                    candidate_city,
                    len(candidate_hotels),
                )

                if candidate_hotels:
                    liteapi_hotels = candidate_hotels
                    provider_city = candidate_city
                    break

            # ------------------------------------------------
            # PRIMARY SUCCESS
            # ------------------------------------------------

            if liteapi_hotels:

                return HotelSearchResponse(
                    status="available",
                    provider="liteapi",
                    hotels=liteapi_hotels,
                    message=(
                        "Hotels found successfully."
                    ),
                )

            # ------------------------------------------------
            # PRIMARY RETURNED NO USABLE RESULTS
            # ------------------------------------------------

            logger.info(
                "LiteAPI returned no usable hotels for any "
                "provider city candidate. Trying fallback provider."
            )

        except ValueError:

            # ------------------------------------------------
            # DO NOT FALLBACK FOR LOCAL VALIDATION ERRORS
            # ------------------------------------------------

            raise

        except Exception as exc:

            err_msg = (
                str(exc)
                .split("for url:")[0]
                .strip()
            )

            logger.warning(
                "LiteAPI hotel search failed. "
                "Switching to SerpAPI fallback. "
                "error=%s",
                err_msg,
            )

        # ====================================================
        # FALLBACK PROVIDER: SERPAPI
        # ====================================================

        try:

            logger.info(
                "Starting hotel search | "
                "provider=serpapi | "
                "city=%s | provider_city=%s",
                request.city,
                provider_city,
            )

            serpapi_hotels = []

            for candidate_city in self._provider_city_candidates(provider_city):
                logger.info(
                    "SerpAPI city candidate | "
                    "provider_city=%s",
                    candidate_city,
                )

                serpapi_response = (
                    self.serpapi_client.search_hotels(
                        city=candidate_city,
                        checkin=request.checkin.isoformat(),
                        checkout=request.checkout.isoformat(),
                        adults=request.adults,
                        currency=request.currency,
                    )
                )

                candidate_hotels = (
                    self.normalizer.normalize_serpapi(
                        result=serpapi_response,
                        max_hotels=request.max_hotels,
                    )
                )

                logger.info(
                    "SerpAPI candidate completed | "
                    "city=%s | usable_hotels=%s",
                    candidate_city,
                    len(candidate_hotels),
                )

                if candidate_hotels:
                    serpapi_hotels = candidate_hotels
                    provider_city = candidate_city
                    break

            # ------------------------------------------------
            # FALLBACK SUCCESS
            # ------------------------------------------------

            if serpapi_hotels:

                return HotelSearchResponse(
                    status="available",
                    provider="serpapi",
                    hotels=serpapi_hotels,
                    message=(
                        "Hotels found successfully."
                    ),
                )

            # ------------------------------------------------
            # BOTH PROVIDERS RETURNED NO RESULTS
            # ------------------------------------------------

            logger.info(
                "No usable hotels returned "
                "by either provider."
            )

            return HotelSearchResponse(
                status="unavailable",
                provider="none",
                hotels=[],
                message=(
                    "Sorry, no hotels were found "
                    "for the selected dates and location."
                ),
            )

        except ValueError:

            raise

        except Exception as exc:

            err_msg = (
                str(exc)
                .split("for url:")[0]
                .strip()
            )

            logger.error(
                "SerpAPI hotel search failed. "
                "All hotel providers unavailable. "
                "error=%s",
                err_msg,
            )

            # ------------------------------------------------
            # BOTH PROVIDERS FAILED
            # ------------------------------------------------

            return HotelSearchResponse(
                status="unavailable",
                provider="none",
                hotels=[],
                message=(
                    "Sorry, hotel search is temporarily "
                    "unavailable. Please try again later."
                ),
            )

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

        if not isinstance(
            offer_id,
            str,
        ):

            raise ValueError(
                "Offer ID must be a string"
            )

        offer_id = offer_id.strip()

        if not offer_id:

            raise ValueError(
                "Offer ID cannot be empty"
            )

        # ----------------------------------------------------
        # PREBOOK THROUGH PRIMARY PROVIDER
        # ----------------------------------------------------

        try:

            logger.info(
                "Hotel prebook started | "
                "provider=liteapi"
            )

            result = self.liteapi_client.prebook(
                offer_id
            )

            logger.info(
                "Hotel prebook completed successfully"
            )

            return result

        except ValueError:

            raise

        except Exception as exc:

            logger.error(
                "Hotel prebook failed | error=%s",
                exc,
            )

            raise RuntimeError(
                "Sorry, hotel prebooking is "
                "currently unavailable. "
                "Please try again later."
            ) from exc
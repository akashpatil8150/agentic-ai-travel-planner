import logging
import re


logger = logging.getLogger(__name__)


class HotelLocationResolver:
    """
    Resolves application/display city names into provider-friendly
    hotel search city names.

    Example:
        Ooty (Udhagamandalam) -> Ooty
        Bengaluru (Bangalore) -> Bengaluru
        Mumbai -> Mumbai

    This resolver does not maintain city-specific hardcoded mappings.
    """

    @staticmethod
    def resolve(city: str) -> str:
        """
        Return a clean provider-search city while preserving
        the original city outside the provider layer.
        """

        if not isinstance(city, str):
            raise ValueError("Hotel city must be a string")

        original_city = city.strip()

        if not original_city:
            raise ValueError("Hotel city cannot be empty")

        resolved_city = original_city

        # --------------------------------------------------------
        # REMOVE PARENTHETICAL ALIASES / ALTERNATE NAMES
        # --------------------------------------------------------
        #
        # Example:
        # Ooty (Udhagamandalam)
        #        ↓
        # Ooty
        #
        # Bengaluru (Bangalore)
        #        ↓
        # Bengaluru
        #
        resolved_city = re.sub(
            r"\s*\([^)]*\)",
            "",
            resolved_city,
        )

        # --------------------------------------------------------
        # NORMALIZE WHITESPACE
        # --------------------------------------------------------

        resolved_city = re.sub(
            r"\s+",
            " ",
            resolved_city,
        ).strip()

        # Safety fallback
        if not resolved_city:
            resolved_city = original_city

        logger.info(
            "Hotel location resolved | original=%s | provider_city=%s",
            original_city,
            resolved_city,
        )

        return resolved_city
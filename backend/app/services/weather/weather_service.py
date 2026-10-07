import logging
import requests


logger = logging.getLogger(__name__)


# ============================================================
# OPEN-METEO CONFIG
# ============================================================

BASE_URL = "https://api.open-meteo.com/v1/forecast"
ARCHIVE_BASE_URL = "https://archive-api.open-meteo.com/v1/archive"

TIMEOUT = 10


# ============================================================
# WEATHER CACHE
# ============================================================
#
# Shared in-memory cache.
#
# Same coordinates + same forecast configuration
# will not hit Open-Meteo again during the same
# application process.
#
# Failed requests are NEVER cached.
#
# ============================================================

_WEATHER_CACHE: dict[tuple, dict] = {}


# ============================================================
# CUSTOM EXCEPTIONS
# ============================================================


class WeatherServiceError(Exception):
    """
    Base exception for weather service.
    """

    pass


class WeatherAPIError(WeatherServiceError):
    """
    Raised when Open-Meteo returns an API/HTTP error.
    """

    pass


class WeatherTimeoutError(WeatherServiceError):
    """
    Raised when Open-Meteo request times out.
    """

    pass


class WeatherConnectionError(WeatherServiceError):
    """
    Raised when Open-Meteo cannot be reached.
    """

    pass


# ============================================================
# WEATHER SERVICE
# ============================================================


class WeatherService:
    """
    Service responsible for communicating with Open-Meteo.

    Responsibilities:
        - Validate coordinates
        - Build API parameters
        - Check cache
        - Call Open-Meteo
        - Handle provider/network errors
        - Validate raw provider response
        - Store successful responses in cache

    Normalization is handled by WeatherAgent.
    """

    def __init__(
        self,
        base_url: str = BASE_URL,
        timeout: int = TIMEOUT,
    ):

        self.base_url = base_url
        self.timeout = timeout

    # ========================================================
    # VALIDATE COORDINATES
    # ========================================================

    @staticmethod
    def _validate_coordinates(
        latitude: float,
        longitude: float,
    ) -> None:

        # ----------------------------------------------------
        # LATITUDE TYPE
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

        # ----------------------------------------------------
        # LATITUDE RANGE
        # ----------------------------------------------------

        if not -90 <= latitude <= 90:

            raise ValueError(
                "Latitude must be between -90 and 90."
            )

        # ----------------------------------------------------
        # LONGITUDE TYPE
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

        # ----------------------------------------------------
        # LONGITUDE RANGE
        # ----------------------------------------------------

        if not -180 <= longitude <= 180:

            raise ValueError(
                "Longitude must be between -180 and 180."
            )

    # ========================================================
    # BUILD PARAMETERS
    # ========================================================

    @staticmethod
    def _build_params(
        latitude: float,
        longitude: float,
    ) -> dict:

        return {

            "latitude": latitude,

            "longitude": longitude,

            # Open-Meteo supports up to 16 forecast days.
            "forecast_days": 16,

            # Automatically use destination timezone.
            "timezone": "auto",

            # ------------------------------------------------
            # DAILY WEATHER DATA
            # ------------------------------------------------

            "daily": (
                "weather_code,"
                "temperature_2m_max,"
                "temperature_2m_min,"
                "apparent_temperature_max,"
                "apparent_temperature_min,"
                "precipitation_sum,"
                "rain_sum,"
                "precipitation_probability_max,"
                "precipitation_hours,"
                "wind_speed_10m_max,"
                "sunrise,"
                "sunset"
            ),

            # ------------------------------------------------
            # UNITS
            # ------------------------------------------------

            "temperature_unit": "celsius",

            "wind_speed_unit": "kmh",

            "precipitation_unit": "mm",
        }

    # ========================================================
    # BUILD CACHE KEY
    # ========================================================

    @staticmethod
    def _build_cache_key(
        latitude: float,
        longitude: float,
        params: dict,
    ) -> tuple:

        return (
            # Coordinates rounded to avoid tiny floating-point
            # differences creating different cache entries.
            round(float(latitude), 6),
            round(float(longitude), 6),

            params.get(
                "forecast_days"
            ),

            params.get(
                "timezone"
            ),

            params.get(
                "daily"
            ),

            params.get(
                "temperature_unit"
            ),

            params.get(
                "wind_speed_unit"
            ),

            params.get(
                "precipitation_unit"
            ),
        )

    # ========================================================
    # VALIDATE API RESPONSE
    # ========================================================

    @staticmethod
    def _validate_response(
        data,
    ) -> dict:

        # ----------------------------------------------------
        # ROOT RESPONSE
        # ----------------------------------------------------

        if not isinstance(
            data,
            dict,
        ):

            raise WeatherAPIError(
                "Unexpected weather API response."
            )

        # ----------------------------------------------------
        # PROVIDER ERROR
        # ----------------------------------------------------

        if data.get("error") is True:

            reason = data.get(
                "reason"
            )

            logger.error(
                "Open-Meteo returned provider error | "
                "reason=%s",
                reason,
            )

            raise WeatherAPIError(
                "Open-Meteo returned a weather API error."
            )

        # ----------------------------------------------------
        # DAILY DATA
        # ----------------------------------------------------

        daily = data.get(
            "daily"
        )

        if not isinstance(
            daily,
            dict,
        ):

            raise WeatherAPIError(
                "Weather API response does not contain "
                "valid daily forecast data."
            )

        # ----------------------------------------------------
        # REQUIRED DATE ARRAY
        # ----------------------------------------------------

        dates = daily.get(
            "time"
        )

        if not isinstance(
            dates,
            list,
        ):

            raise WeatherAPIError(
                "Weather API response contains "
                "invalid forecast dates."
            )

        if not dates:

            raise WeatherAPIError(
                "Weather API returned an empty forecast."
            )

        return data

    # ========================================================
    # GET WEATHER
    # ========================================================

    def get_weather(
        self,
        latitude: float,
        longitude: float,
    ) -> dict:

        # ----------------------------------------------------
        # VALIDATE INPUT
        #
        # IMPORTANT:
        # No API request happens before this validation.
        # ----------------------------------------------------

        self._validate_coordinates(
            latitude=latitude,
            longitude=longitude,
        )

        # ----------------------------------------------------
        # BUILD REQUEST
        # ----------------------------------------------------

        params = self._build_params(
            latitude=latitude,
            longitude=longitude,
        )

        # ----------------------------------------------------
        # CACHE KEY
        # ----------------------------------------------------

        cache_key = self._build_cache_key(
            latitude=latitude,
            longitude=longitude,
            params=params,
        )

        # ----------------------------------------------------
        # CACHE HIT
        # ----------------------------------------------------

        cached_weather = _WEATHER_CACHE.get(
            cache_key
        )

        if cached_weather is not None:

            logger.info(
                "Weather cache hit | "
                "latitude=%s | longitude=%s",
                latitude,
                longitude,
            )

            return cached_weather

        # ----------------------------------------------------
        # CACHE MISS
        # ----------------------------------------------------

        logger.info(
            "Weather cache miss | "
            "latitude=%s | longitude=%s",
            latitude,
            longitude,
        )

        logger.info(
            "Weather search started | "
            "latitude=%s | longitude=%s",
            latitude,
            longitude,
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

        except requests.exceptions.Timeout as error:

            logger.error(
                "Open-Meteo request timed out | "
                "latitude=%s | longitude=%s",
                latitude,
                longitude,
            )

            raise WeatherTimeoutError(
                "Weather API request timed out."
            ) from error

        except requests.exceptions.ConnectionError as error:

            logger.error(
                "Could not connect to Open-Meteo | "
                "latitude=%s | longitude=%s",
                latitude,
                longitude,
            )

            raise WeatherConnectionError(
                "Could not connect to the weather provider."
            ) from error

        except requests.exceptions.RequestException as error:

            logger.error(
                "Open-Meteo request failed | error=%s",
                error,
            )

            raise WeatherServiceError(
                "Weather provider request failed."
            ) from error

        # ----------------------------------------------------
        # HTTP STATUS
        # ----------------------------------------------------

        if response.status_code == 400:

            logger.warning(
                "Open-Meteo rejected request | status=400"
            )

            raise WeatherAPIError(
                "Weather provider rejected the request."
            )

        # ----------------------------------------------------
        # RATE LIMIT
        # ----------------------------------------------------

        if response.status_code == 429:

            logger.warning(
                "Open-Meteo rate limit reached."
            )

            raise WeatherAPIError(
                "Weather provider rate limit reached. "
                "Please try again later."
            )

        # ----------------------------------------------------
        # SERVER ERROR
        # ----------------------------------------------------

        if 500 <= response.status_code <= 599:

            logger.error(
                "Open-Meteo server error | status=%s",
                response.status_code,
            )

            raise WeatherAPIError(
                "Weather provider is temporarily unavailable."
            )

        # ----------------------------------------------------
        # OTHER HTTP ERRORS
        # ----------------------------------------------------

        try:

            response.raise_for_status()

        except requests.exceptions.HTTPError as error:

            logger.error(
                "Open-Meteo HTTP error | status=%s",
                response.status_code,
            )

            raise WeatherAPIError(
                "Weather provider returned an HTTP error."
            ) from error

        # ----------------------------------------------------
        # JSON RESPONSE
        # ----------------------------------------------------

        try:

            data = response.json()

        except ValueError as error:

            logger.error(
                "Open-Meteo returned invalid JSON."
            )

            raise WeatherAPIError(
                "Weather provider returned an invalid response."
            ) from error

        # ----------------------------------------------------
        # VALIDATE RESPONSE
        # ----------------------------------------------------

        data = self._validate_response(
            data
        )

        # ----------------------------------------------------
        # STORE SUCCESSFUL RESPONSE
        #
        # IMPORTANT:
        # Only validated successful responses are cached.
        # Errors are never stored.
        # ----------------------------------------------------

        _WEATHER_CACHE[
            cache_key
        ] = data

        logger.info(
            "Weather cache store | "
            "latitude=%s | longitude=%s",
            latitude,
            longitude,
        )

        # ----------------------------------------------------
        # SUCCESS LOG
        # ----------------------------------------------------

        logger.info(
            "Weather search completed successfully | "
            "latitude=%s | longitude=%s",
            latitude,
            longitude,
        )

        return data

    # ========================================================
    # GET WEATHER ARCHIVE (SEASONAL / HISTORICAL)
    # ========================================================

    def get_weather_archive(
        self,
        latitude: float,
        longitude: float,
        start_date: str,
        end_date: str,
    ) -> dict:
        """
        Query Open-Meteo Archive API for historical/seasonal weather
        data for specific dates (e.g. from previous year for distant travel dates).
        """
        self._validate_coordinates(
            latitude=latitude,
            longitude=longitude,
        )

        params = {
            "latitude": latitude,
            "longitude": longitude,
            "start_date": start_date,
            "end_date": end_date,
            "timezone": "auto",
            "daily": (
                "weather_code,"
                "temperature_2m_max,"
                "temperature_2m_min,"
                "apparent_temperature_max,"
                "apparent_temperature_min,"
                "precipitation_sum,"
                "rain_sum,"
                "precipitation_hours,"
                "wind_speed_10m_max,"
                "sunrise,"
                "sunset"
            ),
            "temperature_unit": "celsius",
            "wind_speed_unit": "kmh",
            "precipitation_unit": "mm",
        }

        cache_key = (
            "archive",
            round(float(latitude), 6),
            round(float(longitude), 6),
            start_date,
            end_date,
        )

        cached_weather = _WEATHER_CACHE.get(cache_key)
        if cached_weather is not None:
            logger.info(
                "Weather archive cache hit | latitude=%s | longitude=%s | dates=%s to %s",
                latitude,
                longitude,
                start_date,
                end_date,
            )
            return cached_weather

        logger.info(
            "Weather archive request | latitude=%s | longitude=%s | dates=%s to %s",
            latitude,
            longitude,
            start_date,
            end_date,
        )

        try:
            response = requests.get(
                ARCHIVE_BASE_URL,
                params=params,
                timeout=self.timeout,
            )
            response.raise_for_status()
            data = response.json()
        except requests.exceptions.Timeout as error:
            logger.error("Weather archive request timed out: %s", error)
            raise WeatherTimeoutError("Weather archive API request timed out.") from error
        except requests.exceptions.RequestException as error:
            logger.error("Weather archive request failed: %s", error)
            raise WeatherServiceError("Weather archive request failed.") from error
        except ValueError as error:
            logger.error("Weather archive returned invalid JSON: %s", error)
            raise WeatherAPIError("Weather archive returned invalid response.") from error

        data = self._validate_response(data)
        _WEATHER_CACHE[cache_key] = data

        logger.info(
            "Weather archive request completed | latitude=%s | longitude=%s",
            latitude,
            longitude,
        )
        return data


# ============================================================
# SIMPLE FUNCTIONS
# ============================================================


def get_weather(
    latitude: float,
    longitude: float,
) -> dict:

    service = WeatherService()

    return service.get_weather(
        latitude=latitude,
        longitude=longitude,
    )


def get_weather_archive(
    latitude: float,
    longitude: float,
    start_date: str,
    end_date: str,
) -> dict:

    service = WeatherService()

    return service.get_weather_archive(
        latitude=latitude,
        longitude=longitude,
        start_date=start_date,
        end_date=end_date,
    )
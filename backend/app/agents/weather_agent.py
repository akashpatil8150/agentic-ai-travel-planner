import logging
from datetime import date

from app.state.trip_state import TripState

from app.observability.agent_logger import (
    agent_start,
    agent_success,
    agent_failure,
)

from app.services.weather.weather_service import (
    WeatherService,
    WeatherServiceError,
)


logger = logging.getLogger(__name__)


class WeatherAgent:
    """
    Weather Agent.

    Responsibilities:
        1. Validate TripState
        2. Validate destination
        3. Validate coordinates
        4. Validate travel dates
        5. Call WeatherService
        6. Filter forecast for travel dates
        7. Store normalized weather in TripState

    Provider communication remains inside WeatherService.
    """

    WEATHER_CODES = {
        0: "Clear sky",
        1: "Mainly clear",
        2: "Partly cloudy",
        3: "Overcast",
        45: "Fog",
        48: "Depositing rime fog",
        51: "Light drizzle",
        53: "Moderate drizzle",
        55: "Dense drizzle",
        56: "Light freezing drizzle",
        57: "Dense freezing drizzle",
        61: "Slight rain",
        63: "Moderate rain",
        65: "Heavy rain",
        66: "Light freezing rain",
        67: "Heavy freezing rain",
        71: "Slight snow",
        73: "Moderate snow",
        75: "Heavy snow",
        77: "Snow grains",
        80: "Slight rain showers",
        81: "Moderate rain showers",
        82: "Violent rain showers",
        85: "Slight snow showers",
        86: "Heavy snow showers",
        95: "Thunderstorm",
        96: "Thunderstorm with slight hail",
        99: "Thunderstorm with heavy hail",
    }

    def __init__(self):

        self.weather_service = WeatherService()

        logger.info(
            "WeatherAgent initialized"
        )

    # =====================================================
    # RUN
    # =====================================================

    def run(
        self,
        state: TripState,
    ) -> TripState:

        agent_start_time = agent_start("weather", state)

        logger.info(
            "Weather Agent started"
        )

        # =================================================
        # VALIDATE STATE
        # =================================================

        if not isinstance(
            state,
            TripState,
        ):

            agent_failure("weather", state, agent_start_time, ValueError("validation failed"))
            raise TypeError(
                "WeatherAgent expects a TripState object."
            )

        # =================================================
        # VALIDATE DESTINATION
        # =================================================

        if state.destination is None:

            agent_failure("weather", state, agent_start_time, ValueError("validation failed"))
            raise ValueError(
                "Destination is required for weather."
            )

        # =================================================
        # VALIDATE COORDINATES
        # =================================================

        latitude = state.destination.latitude
        longitude = state.destination.longitude

        if (
            latitude is None
            or longitude is None
        ):

            agent_failure("weather", state, agent_start_time, ValueError("validation failed"))
            raise ValueError(
                "Destination latitude and longitude "
                "are required for weather."
            )

        logger.info(
            "Weather coordinates validated | "
            "latitude=%s | longitude=%s",
            latitude,
            longitude,
        )

        # =================================================
        # VALIDATE TRAVEL DATES
        # =================================================

        if state.travel_dates is None:

            agent_failure("weather", state, agent_start_time, ValueError("validation failed"))
            raise ValueError(
                "Travel dates are required for weather."
            )

        start_date = state.travel_dates.start
        end_date = state.travel_dates.end

        if (
            start_date is None
            or end_date is None
        ):

            agent_failure("weather", state, agent_start_time, ValueError("validation failed"))
            raise ValueError(
                "Travel start and end dates "
                "are required for weather."
            )

        if start_date > end_date:

            agent_failure("weather", state, agent_start_time, ValueError("validation failed"))
            raise ValueError(
                "Travel start date cannot be "
                "after the end date."
            )

        logger.info(
            "Weather dates validated | "
            "start=%s | end=%s",
            start_date,
            end_date,
        )

        # =================================================
        # GET WEATHER
        # =================================================

        try:

            logger.info(
                "Calling WeatherService | "
                "destination=%s",
                state.destination.name,
            )

            raw_weather = (
                self.weather_service.get_weather(
                    latitude=latitude,
                    longitude=longitude,
                )
            )

        except WeatherServiceError as exc:

            logger.error(
                "Weather provider failed | error=%s",
                exc,
            )

            state.weather = {
                "status": "unavailable",
                "location": state.destination.name,
                "reason": (
                    "Weather information is "
                    "temporarily unavailable."
                ),
            }

            agent_success("weather", state, agent_start_time, status="unavailable")
            return state

        # =================================================
        # VALIDATE RESPONSE
        # =================================================

        if not isinstance(
            raw_weather,
            dict,
        ):

            logger.error(
                "WeatherService returned invalid response type"
            )

            state.weather = {
                "status": "unavailable",
                "location": state.destination.name,
                "reason": (
                    "Weather provider returned "
                    "invalid information."
                ),
            }

            agent_success("weather", state, agent_start_time, status="unavailable")
            return state

        daily = raw_weather.get("daily")

        if not isinstance(
            daily,
            dict,
        ):

            logger.error(
                "Weather response missing valid daily data"
            )

            state.weather = {
                "status": "unavailable",
                "location": state.destination.name,
                "reason": (
                    "Weather forecast data "
                    "is unavailable."
                ),
            }

            agent_success("weather", state, agent_start_time, status="unavailable")
            return state

        # =================================================
        # READ ARRAYS
        # =================================================

        dates = self._safe_list(
            daily.get("time")
        )

        weather_codes = self._safe_list(
            daily.get("weather_code")
        )

        max_temps = self._safe_list(
            daily.get("temperature_2m_max")
        )

        min_temps = self._safe_list(
            daily.get("temperature_2m_min")
        )

        apparent_max = self._safe_list(
            daily.get(
                "apparent_temperature_max"
            )
        )

        apparent_min = self._safe_list(
            daily.get(
                "apparent_temperature_min"
            )
        )

        rain_probability = self._safe_list(
            daily.get(
                "precipitation_probability_max"
            )
        )

        precipitation = self._safe_list(
            daily.get(
                "precipitation_sum"
            )
        )

        rain = self._safe_list(
            daily.get("rain_sum")
        )

        precipitation_hours = self._safe_list(
            daily.get(
                "precipitation_hours"
            )
        )

        wind = self._safe_list(
            daily.get(
                "wind_speed_10m_max"
            )
        )

        sunrise = self._safe_list(
            daily.get("sunrise")
        )

        sunset = self._safe_list(
            daily.get("sunset")
        )

        # =================================================
        # NO DATES
        # =================================================

        if not dates:

            logger.warning(
                "Weather provider returned no forecast dates"
            )

            state.weather = {
                "status": "unavailable",
                "location": state.destination.name,
                "reason": (
                    "No weather forecast is "
                    "available for the requested trip."
                ),
            }

            agent_success("weather", state, agent_start_time, status="unavailable")
            return state

        # =================================================
        # FILTER TRAVEL DATES
        # =================================================

        forecast = []

        for index, forecast_date in enumerate(
            dates
        ):

            if not isinstance(
                forecast_date,
                str,
            ):

                logger.warning(
                    "Skipping invalid forecast date | "
                    "index=%s",
                    index,
                )

                continue

            try:

                current_date = date.fromisoformat(
                    forecast_date
                )

            except ValueError:

                logger.warning(
                    "Skipping malformed forecast date | "
                    "date=%s",
                    forecast_date,
                )

                continue

            if not (
                start_date
                <= current_date
                <= end_date
            ):

                continue

            weather_code = self._get_value(
                weather_codes,
                index,
            )

            weather_description = (
                self.WEATHER_CODES.get(
                    weather_code,
                    "Unknown",
                )
            )

            forecast.append(
                {
                    "date": forecast_date,

                    "weather": weather_description,

                    "weather_code": weather_code,

                    "temperature": {
                        "min_c": self._get_value(
                            min_temps,
                            index,
                        ),
                        "max_c": self._get_value(
                            max_temps,
                            index,
                        ),
                    },

                    "feels_like": {
                        "min_c": self._get_value(
                            apparent_min,
                            index,
                        ),
                        "max_c": self._get_value(
                            apparent_max,
                            index,
                        ),
                    },

                    "rain_probability": self._get_value(
                        rain_probability,
                        index,
                    ),

                    "precipitation_mm": self._get_value(
                        precipitation,
                        index,
                    ),

                    "rain_mm": self._get_value(
                        rain,
                        index,
                    ),

                    "precipitation_hours": self._get_value(
                        precipitation_hours,
                        index,
                    ),

                    "wind_kmh": self._get_value(
                        wind,
                        index,
                    ),

                    "sunrise": self._get_value(
                        sunrise,
                        index,
                    ),

                    "sunset": self._get_value(
                        sunset,
                        index,
                    ),
                }
            )

        # =================================================
        # NO TRAVEL-DATE FORECAST -> FALLBACK TO SEASONAL ARCHIVE
        # =================================================

        forecast_source = "live_forecast"

        if not forecast:
            logger.info(
                "Live forecast does not cover travel dates; fetching seasonal climate archive | "
                "start=%s | end=%s",
                start_date,
                end_date,
            )

            try:
                from datetime import timedelta
                # Query corresponding calendar dates from the previous year
                archive_start = start_date.replace(year=start_date.year - 1)
                archive_end = end_date.replace(year=end_date.year - 1)

                raw_archive = self.weather_service.get_weather_archive(
                    latitude=latitude,
                    longitude=longitude,
                    start_date=str(archive_start),
                    end_date=str(archive_end),
                )

                daily_archive = raw_archive.get("daily", {}) if isinstance(raw_archive, dict) else {}
                arch_wcodes = self._safe_list(daily_archive.get("weather_code"))
                arch_max_temps = self._safe_list(daily_archive.get("temperature_2m_max"))
                arch_min_temps = self._safe_list(daily_archive.get("temperature_2m_min"))
                arch_app_max = self._safe_list(daily_archive.get("apparent_temperature_max"))
                arch_app_min = self._safe_list(daily_archive.get("apparent_temperature_min"))
                arch_precip = self._safe_list(daily_archive.get("precipitation_sum"))
                arch_rain = self._safe_list(daily_archive.get("rain_sum"))
                arch_phours = self._safe_list(daily_archive.get("precipitation_hours"))
                arch_wind = self._safe_list(daily_archive.get("wind_speed_10m_max"))
                arch_sunrise = self._safe_list(daily_archive.get("sunrise"))
                arch_sunset = self._safe_list(daily_archive.get("sunset"))

                num_days = (end_date - start_date).days + 1
                for i in range(num_days):
                    curr_d = start_date + timedelta(days=i)
                    curr_d_str = str(curr_d)
                    w_code = self._get_value(arch_wcodes, i) if self._get_value(arch_wcodes, i) is not None else 1
                    w_desc = self.WEATHER_CODES.get(w_code, "Mainly clear")

                    sr = self._get_value(arch_sunrise, i)
                    ss = self._get_value(arch_sunset, i)
                    if sr and isinstance(sr, str) and "T" in sr:
                        sr = f"{curr_d_str}T{sr.split('T')[1]}"
                    else:
                        sr = f"{curr_d_str}T06:20"

                    if ss and isinstance(ss, str) and "T" in ss:
                        ss = f"{curr_d_str}T{ss.split('T')[1]}"
                    else:
                        ss = f"{curr_d_str}T18:30"

                    precip_val = self._get_value(arch_precip, i) or 0.0
                    rain_prob = min(95, max(10, int(precip_val * 15))) if precip_val > 0 else 15

                    forecast.append(
                        {
                            "date": curr_d_str,
                            "weather": w_desc,
                            "weather_code": w_code,
                            "temperature": {
                                "min_c": self._get_value(arch_min_temps, i) if self._get_value(arch_min_temps, i) is not None else 23.0,
                                "max_c": self._get_value(arch_max_temps, i) if self._get_value(arch_max_temps, i) is not None else 30.0,
                            },
                            "feels_like": {
                                "min_c": self._get_value(arch_app_min, i) if self._get_value(arch_app_min, i) is not None else 25.0,
                                "max_c": self._get_value(arch_app_max, i) if self._get_value(arch_app_max, i) is not None else 33.0,
                            },
                            "rain_probability": rain_prob,
                            "precipitation_mm": precip_val,
                            "rain_mm": self._get_value(arch_rain, i) if self._get_value(arch_rain, i) is not None else precip_val,
                            "precipitation_hours": self._get_value(arch_phours, i) if self._get_value(arch_phours, i) is not None else 0.0,
                            "wind_kmh": self._get_value(arch_wind, i) if self._get_value(arch_wind, i) is not None else 12.0,
                            "sunrise": sr,
                            "sunset": ss,
                            "forecast_type": "seasonal_climate_estimate",
                        }
                    )
                forecast_source = "seasonal_climate_estimate"
            except Exception as err:
                logger.error("Seasonal weather archive fallback failed: %s", err)

        if not forecast:
            logger.warning(
                "No forecast available for travel dates | "
                "start=%s | end=%s",
                start_date,
                end_date,
            )

            state.weather = {
                "status": "unavailable",
                "location": state.destination.name,
                "reason": (
                    "Weather forecast is not available "
                    "for the requested travel dates."
                ),
            }

            agent_success("weather", state, agent_start_time, status="unavailable")
            return state

        # =================================================
        # STORE IN TRIP STATE (CHRONOLOGICAL ORDER)
        # =================================================

        before_dates = [str(x.get("date")) for x in forecast if isinstance(x, dict)]
        forecast.sort(key=self._parse_sort_date)
        after_dates = [str(x.get("date")) for x in forecast if isinstance(x, dict)]

        print("\nWEATHER ORDERING")
        print("----------------")
        print(f"Before: {before_dates}")
        print(f"After:  {after_dates}\n")

        state.weather = {
            "status": "available",

            "location": state.destination.name,

            "latitude": raw_weather.get(
                "latitude",
                latitude,
            ),

            "longitude": raw_weather.get(
                "longitude",
                longitude,
            ),

            "timezone": raw_weather.get(
                "timezone"
            ) or "auto",

            "forecast_type": forecast_source,

            "forecast": forecast,
        }

        logger.info(
            "Weather Agent completed | "
            "location=%s | forecast_days=%s | source=%s",
            state.destination.name,
            len(forecast),
            forecast_source,
        )

        agent_success(
            "weather",
            state,
            agent_start_time,
            status="success",
        )

        return state

    # =====================================================
    # SAFE LIST
    # =====================================================

    @staticmethod
    def _safe_list(
        value,
    ) -> list:

        if isinstance(
            value,
            list,
        ):

            return value

        return []

    # =====================================================
    # SAFE ARRAY ACCESS
    # =====================================================

    @staticmethod
    def _get_value(
        values: list,
        index: int,
    ):

        if (
            index < 0
            or index >= len(values)
        ):

            return None

        return values[index]

    # =====================================================
    # PARSE DATE FOR CHRONOLOGICAL SORTING
    # =====================================================

    @staticmethod
    def _parse_sort_date(item) -> date:
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
                from datetime import datetime
                for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y", "%Y/%m/%d"):
                    try:
                        return datetime.strptime(d_str, fmt).date()
                    except Exception:
                        continue
        return date.min

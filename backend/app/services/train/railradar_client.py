import time
import requests

from app.core.config import settings
from app.observability.metrics import observability_metrics


# ============================================================
# RAILRADAR EXCEPTIONS
# ============================================================

class RailRadarError(Exception):
    """Base exception for RailRadar client errors."""

class RailRadarRateLimitedError(RailRadarError):
    """Raised when RailRadar returns HTTP 429."""

class RailRadarAuthError(RailRadarError):
    """Raised when RailRadar authentication fails (HTTP 401/403)."""

class RailRadarServerError(RailRadarError):
    """Raised when RailRadar returns HTTP 5xx."""

class RailRadarTimeoutError(RailRadarError):
    """Raised when RailRadar request times out."""

class RailRadarNetworkError(RailRadarError):
    """Raised when RailRadar cannot be reached."""

class RailRadarCircuitOpenError(RailRadarError, RuntimeError):
    """Raised when RailRadar circuit breaker is active."""


# ============================================================
# SHARED IN-MEMORY CACHE
# ============================================================

_TRAIN_SEARCH_CACHE: dict[
    tuple[str, str],
    dict,
] = {}

_TRAIN_DETAILS_CACHE: dict[
    str,
    dict,
] = {}

_IS_RATE_LIMITED = False


class RailRadarClient:

    BASE_URL = "https://api.railradar.in/v1"

    def __init__(self):

        self.headers = {
            "Authorization": (
                f"Bearer "
                f"{settings.railradar_api_key}"
            )
        }

    # ========================================================
    # INTERNAL REQUEST HANDLER
    # ========================================================

    def _get(
        self,
        url: str,
        params: dict | None = None,
    ) -> dict:
        global _IS_RATE_LIMITED
        from app.services.train.api_tracker import api_tracker
        if _IS_RATE_LIMITED or api_tracker.is_railradar_rate_limited():
            api_tracker.log_skipped_circuit_breaker("RailRadar")
            raise RailRadarCircuitOpenError("RailRadar rate limited (HTTP 429 circuit breaker active).")

        try:
            response = requests.get(
                url,
                params=params,
                headers=self.headers,
                timeout=20,
            )

            if not response.ok:
                status_code = response.status_code
                if status_code in (429, 402):
                    retry_after = response.headers.get("retry-after") or response.headers.get("Retry-After")
                    api_tracker.mark_railradar_429(retry_after=retry_after)
                    raise RailRadarRateLimitedError(f"RailRadar returned HTTP {status_code} (Rate Limited).")
                elif status_code in (401, 403):
                    api_tracker.railradar_rate_limited = True
                    raise RailRadarAuthError(f"RailRadar authentication failed (HTTP {status_code}).")
                elif status_code == 404:
                    return {"success": True, "data": {"trains": []}}
                elif status_code >= 500:
                    raise RailRadarServerError(f"RailRadar server error (HTTP {status_code}).")
                raise RailRadarError(f"RailRadar returned HTTP {status_code}.")

        except requests.Timeout as e:
            raise RailRadarTimeoutError("RailRadar request timed out.") from e

        except (RailRadarRateLimitedError, RailRadarAuthError, RailRadarServerError, RailRadarCircuitOpenError):
            raise

        except requests.RequestException as e:
            raise RailRadarNetworkError("RailRadar service could not be reached.") from e

        try:
            data = response.json()
        except ValueError as e:
            raise RailRadarError("RailRadar returned an invalid JSON response.") from e

        return data

    # ========================================================
    # TRAIN SEARCH
    # ========================================================

    def search_trains(
        self,
        from_code: str,
        to_code: str,
    ) -> dict:

        # ----------------------------------------------------
        # NORMALIZE STATION CODES
        # ----------------------------------------------------

        from_code_clean = (
            str(from_code)
            .strip()
            .upper()
        )

        to_code_clean = (
            str(to_code)
            .strip()
            .upper()
        )

        # ----------------------------------------------------
        # VALIDATE
        # ----------------------------------------------------

        if not from_code_clean:

            raise ValueError(
                "RailRadar source station "
                "code is required."
            )

        if not to_code_clean:

            raise ValueError(
                "RailRadar destination station "
                "code is required."
            )

        if from_code_clean == to_code_clean:

            raise ValueError(
                "RailRadar source and destination "
                "stations cannot be the same."
            )

        # ----------------------------------------------------
        # CACHE KEY
        #
        # RailRadar endpoint searches trains between
        # two stations. The journey date is NOT part of
        # this endpoint's request.
        #
        # TrainService performs the running-day/date
        # filtering after receiving the route data.
        # ----------------------------------------------------

        cache_key = (
            from_code_clean,
            to_code_clean,
        )

        # ----------------------------------------------------
        # CACHE HIT
        # ----------------------------------------------------

        cached_result = _TRAIN_SEARCH_CACHE.get(
            cache_key
        )

        from app.services.train.api_tracker import api_tracker

        if cached_result is not None:
            api_tracker.log_request(
                provider="RailRadar",
                endpoint="/trains/between",
                origin=from_code_clean,
                destination=to_code_clean,
                date="N/A",
                request_type="journey",
                is_cache_hit=True,
            )
            observability_metrics.record_cache_event(
                provider="RailRadar",
                cache_type="journey",
                route=f"{from_code_clean}→{to_code_clean}",
                result="HIT",
            )
            return cached_result

        observability_metrics.record_cache_event(
            provider="RailRadar",
            cache_type="journey",
            route=f"{from_code_clean}→{to_code_clean}",
            result="MISS",
        )

        if not _IS_RATE_LIMITED:
            api_tracker.log_request(
                provider="RailRadar",
                endpoint="/trains/between",
                origin=from_code_clean,
                destination=to_code_clean,
                date="N/A",
                request_type="journey",
                is_cache_hit=False,
            )

        api_start = time.perf_counter()
        data = self._get(
            f"{self.BASE_URL}/trains/between/"
            f"{from_code_clean}/"
            f"{to_code_clean}"
        )
        api_lat = (time.perf_counter() - api_start) * 1000

        observability_metrics.record_api_call(
            provider="RailRadar",
            endpoint="/trains/between",
            route=f"{from_code_clean}→{to_code_clean}",
            status=200,
            latency_ms=api_lat,
            cache_state="MISS",
        )

        # ----------------------------------------------------
        # CACHE RESPONSE
        # ----------------------------------------------------

        _TRAIN_SEARCH_CACHE[
            cache_key
        ] = data

        return data

    # ========================================================
    # TRAIN FARE
    # ========================================================
    #
    # DO NOT CACHE
    #
    # Fare can change and is selected-train specific.
    #
    # ========================================================

    def get_fare(
        self,
        train_number: str,
        journey_date: str,
        from_code: str,
        to_code: str,
        class_code: str,
        quota_code: str,
    ) -> dict:

        return self._get(
            f"{self.BASE_URL}/trains/"
            f"{train_number}/fare",
            params={
                "journeyDate": journey_date,
                "source": (
                    str(from_code)
                    .strip()
                    .upper()
                ),
                "destination": (
                    str(to_code)
                    .strip()
                    .upper()
                ),
                "classCode": (
                    str(class_code)
                    .strip()
                    .upper()
                ),
                "quotaCode": (
                    str(quota_code)
                    .strip()
                    .upper()
                ),
            },
        )

    # ========================================================
    # SEAT AVAILABILITY
    # ========================================================
    #
    # DO NOT CACHE
    #
    # Seat availability is live/dynamic.
    #
    # ========================================================

    def get_seats(
        self,
        train_number: str,
        journey_date: str,
        from_code: str,
        to_code: str,
        class_code: str,
        quota_code: str,
    ) -> dict:

        return self._get(
            f"{self.BASE_URL}/trains/"
            f"{train_number}/seats",
            params={
                "journeyDate": journey_date,
                "source": (
                    str(from_code)
                    .strip()
                    .upper()
                ),
                "destination": (
                    str(to_code)
                    .strip()
                    .upper()
                ),
                "classCode": (
                    str(class_code)
                    .strip()
                    .upper()
                ),
                "quotaCode": (
                    str(quota_code)
                    .strip()
                    .upper()
                ),
            },
        )

    # ========================================================
    # TRAIN DETAILS / ROUTE
    # ========================================================

    def get_train_details(
        self,
        train_number: str,
    ) -> dict:
        t_num = str(train_number).strip()
        if not t_num:
            return {}

        cached = _TRAIN_DETAILS_CACHE.get(t_num)
        from app.services.train.api_tracker import api_tracker
        if cached is not None:
            api_tracker.log_request(
                provider="RailRadar",
                endpoint=f"/trains/{t_num}",
                origin="N/A",
                destination="N/A",
                date="N/A",
                request_type="details",
                is_cache_hit=True,
            )
            observability_metrics.record_cache_event(
                provider="RailRadar",
                cache_type="details",
                target=f"Train {t_num}",
                result="HIT",
            )
            return cached

        observability_metrics.record_cache_event(
            provider="RailRadar",
            cache_type="details",
            target=f"Train {t_num}",
            result="MISS",
        )

        if not _IS_RATE_LIMITED:
            api_tracker.log_request(
                provider="RailRadar",
                endpoint=f"/trains/{t_num}",
                origin="N/A",
                destination="N/A",
                date="N/A",
                request_type="details",
                is_cache_hit=False,
            )

        try:
            api_start = time.perf_counter()
            data = self._get(f"{self.BASE_URL}/trains/{t_num}")
            api_lat = (time.perf_counter() - api_start) * 1000
            if isinstance(data, dict) and data.get("success"):
                observability_metrics.record_api_call(
                    provider="RailRadar",
                    endpoint=f"/trains/{t_num}",
                    target=f"Train {t_num}",
                    status=200,
                    latency_ms=api_lat,
                    cache_state="MISS",
                )
                _TRAIN_DETAILS_CACHE[t_num] = data
                return data
        except (RailRadarRateLimitedError, RailRadarCircuitOpenError, RailRadarAuthError):
            raise
        except Exception:
            pass

        return {}
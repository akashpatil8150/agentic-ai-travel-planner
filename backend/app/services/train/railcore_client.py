import logging
import time
import requests

from app.core.config import settings
from app.observability.metrics import observability_metrics

logger = logging.getLogger(__name__)


# ============================================================
# RAILCORE EXCEPTIONS
# ============================================================

class RailCoreError(Exception):
    """Base exception for RailCore client errors."""

class RailCoreRateLimitedError(RailCoreError):
    """Raised when RailCore returns HTTP 429."""

class RailCoreAuthError(RailCoreError):
    """Raised when RailCore authentication fails (HTTP 401/403)."""

class RailCoreServerError(RailCoreError):
    """Raised when RailCore returns HTTP 5xx."""

class RailCoreTimeoutError(RailCoreError):
    """Raised when RailCore request times out."""

class RailCoreNetworkError(RailCoreError):
    """Raised when RailCore cannot be reached."""

class RailCoreCircuitOpenError(RailCoreError, RuntimeError):
    """Raised when RailCore circuit breaker is active."""


# ============================================================
# SHARED IN-MEMORY CACHE
# ============================================================

_JOURNEY_CACHE: dict[
    tuple[str, str, str],
    dict,
] = {}

_FARE_CACHE: dict[
    tuple[str, str, str, str],
    dict,
] = {}

_SCHEDULE_CACHE: dict[
    str,
    dict,
] = {}

_IS_RATE_LIMITED = False


class RailCoreClient:

    BASE_URL = "https://ir.railcore.tech/v1"

    def __init__(self):

        self.headers = {
            "X-RailCore-Key": settings.railcore_api_key
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
        if _IS_RATE_LIMITED or api_tracker.is_railcore_rate_limited():
            api_tracker.log_skipped_circuit_breaker("RailCore")
            raise RailCoreCircuitOpenError("RailCore rate limited (HTTP 429 circuit breaker active).")

        if not self.headers.get("X-RailCore-Key"):
            raise RailCoreAuthError("RailCore API key is not configured.")

        endpoint = url.replace(self.BASE_URL, "")
        orig = (params or {}).get("from", "N/A")
        dest = (params or {}).get("to", "N/A")
        jdate = (params or {}).get("date", "N/A")

        logger.debug("RailCore request: %s | params=%s", endpoint, params)

        start_time = time.perf_counter()
        status_code = 500
        try:
            time.sleep(0.2)

            response = requests.get(
                url,
                params=params,
                headers=self.headers,
                timeout=20,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000
            status_code = response.status_code

            route_str = f"{orig}→{dest}" if orig != "N/A" and dest != "N/A" else None
            observability_metrics.record_api_call(
                provider="RailCore",
                endpoint=endpoint,
                route=route_str,
                status=status_code,
                latency_ms=latency_ms,
                cache="MISS",
            )

            if not response.ok:
                if status_code in (429, 402):
                    err_msg = "Daily rate limit or credits exhausted"
                    try:
                        err_json = response.json()
                        err_info = err_json.get("error", {})
                        if isinstance(err_info, dict):
                            err_msg = err_info.get("message") or err_msg
                    except Exception:
                        pass
                    retry_after = response.headers.get("retry-after") or response.headers.get("Retry-After")
                    api_tracker.mark_railcore_429(retry_after=retry_after)
                    if retry_after:
                        logger.warning("RailCore HTTP %s: %s | Retry-After: %s seconds", status_code, err_msg, retry_after)
                    else:
                        logger.warning("RailCore HTTP %s: %s", status_code, err_msg)
                    raise RailCoreRateLimitedError(f"RailCore returned HTTP {status_code} (Rate Limited: {err_msg}).")
                elif status_code in (401, 403):
                    api_tracker.railcore_rate_limited = True
                    raise RailCoreAuthError(f"RailCore authentication failed (HTTP {status_code}).")
                elif status_code == 404:
                    return {"success": True, "data": {"trains": []}}
                elif status_code >= 500:
                    raise RailCoreServerError(f"RailCore server error (HTTP {status_code}).")

                reason_detail = "HTTP Error"
                err_code = f"HTTP_{status_code}"
                try:
                    err_json = response.json()
                    err_info = err_json.get("error", {})
                    if isinstance(err_info, dict):
                        err_code = err_info.get("code") or err_code
                        reason_detail = err_info.get("message") or response.reason
                except Exception:
                    reason_detail = response.reason or "Unknown Error"

                logger.debug("RailCore error: HTTP %s (%s - %s)", status_code, err_code, reason_detail)

                raise RailCoreError(
                    f"RailCore returned HTTP {status_code} ({err_code}: {reason_detail})."
                )

            data = response.json()
            return data

        except requests.Timeout as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            observability_metrics.record_api_call(
                provider="RailCore",
                endpoint=endpoint,
                status="TIMEOUT",
                latency_ms=latency_ms,
                cache="MISS",
            )
            logger.debug("RailCore request timed out")
            raise RailCoreTimeoutError("RailCore request timed out.") from e

        except (RailCoreRateLimitedError, RailCoreAuthError, RailCoreServerError, RailCoreCircuitOpenError):
            raise

        except requests.RequestException as e:
            latency_ms = (time.perf_counter() - start_time) * 1000
            observability_metrics.record_api_call(
                provider="RailCore",
                endpoint=endpoint,
                status="ERROR",
                latency_ms=latency_ms,
                cache="MISS",
            )
            logger.debug("RailCore request exception: %s", type(e).__name__)
            raise RailCoreNetworkError("RailCore service could not be reached.") from e

    # ========================================================
    # TRAIN SEARCH
    # ========================================================

    def search_trains(
        self,
        from_code: str,
        to_code: str,
        date: str,
    ) -> dict:

        # ----------------------------------------------------
        # NORMALIZE INPUT
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

        date_clean = (
            str(date)
            .strip()
        )

        # ----------------------------------------------------
        # VALIDATE INPUT
        # ----------------------------------------------------

        if not from_code_clean:

            raise ValueError(
                "RailCore origin station is required."
            )

        if not to_code_clean:

            raise ValueError(
                "RailCore destination station is required."
            )

        if not date_clean:

            raise ValueError(
                "RailCore travel date is required."
            )

        # ----------------------------------------------------
        # CACHE KEY
        # ----------------------------------------------------

        cache_key = (
            from_code_clean,
            to_code_clean,
            date_clean,
        )

        # ----------------------------------------------------
        # CACHE HIT
        # ----------------------------------------------------

        cached_result = _JOURNEY_CACHE.get(cache_key)

        from app.services.train.api_tracker import api_tracker

        if cached_result is not None:
            observability_metrics.record_cache_event(
                provider="RailCore",
                type="journey",
                route=f"{from_code_clean}→{to_code_clean}",
                result="HIT",
            )
            api_tracker.log_request(
                provider="RailCore",
                endpoint="/journeys/search",
                origin=from_code_clean,
                destination=to_code_clean,
                date=date_clean,
                request_type="journey",
                is_cache_hit=True,
            )
            return cached_result

        observability_metrics.record_cache_event(
            provider="RailCore",
            type="journey",
            route=f"{from_code_clean}→{to_code_clean}",
            result="MISS",
        )
        api_tracker.log_request(
            provider="RailCore",
            endpoint="/journeys/search",
            origin=from_code_clean,
            destination=to_code_clean,
            date=date_clean,
            request_type="journey",
            is_cache_hit=False,
        )

        data = self._get(
            f"{self.BASE_URL}/journeys/search",
            params={
                "from": from_code_clean,
                "to": to_code_clean,
                "date": date_clean,
            },
        )

        _JOURNEY_CACHE[cache_key] = data
        return data

    # ========================================================
    # FARE OPTIONS
    # ========================================================

    def get_fare_options(
        self,
        from_code: str,
        to_code: str,
        date: str,
        quota_code: str = "GN",
    ) -> dict:

        # ----------------------------------------------------
        # NORMALIZE INPUT
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

        date_clean = (
            str(date)
            .strip()
        )

        quota_clean = (
            str(quota_code)
            .strip()
            .upper()
        )

        # ----------------------------------------------------
        # VALIDATE INPUT
        # ----------------------------------------------------

        if not from_code_clean:

            raise ValueError(
                "RailCore origin station is required."
            )

        if not to_code_clean:

            raise ValueError(
                "RailCore destination station is required."
            )

        if not date_clean:

            raise ValueError(
                "RailCore travel date is required."
            )

        if not quota_clean:

            raise ValueError(
                "RailCore quota is required."
            )

        # ----------------------------------------------------
        # CACHE KEY
        # ----------------------------------------------------

        cache_key = (
            from_code_clean,
            to_code_clean,
            date_clean,
            quota_clean,
        )

        # ----------------------------------------------------
        # CACHE HIT
        # ----------------------------------------------------

        cached_result = _FARE_CACHE.get(
            cache_key
        )

        from app.services.train.api_tracker import api_tracker

        if cached_result is not None:
            observability_metrics.record_cache_event(
                provider="RailCore",
                type="fare",
                route=f"{from_code_clean}→{to_code_clean}",
                result="HIT",
            )
            api_tracker.log_request(
                provider="RailCore",
                endpoint="/fares/search",
                origin=from_code_clean,
                destination=to_code_clean,
                date=date_clean,
                request_type="fare",
                is_cache_hit=True,
            )
            return cached_result

        observability_metrics.record_cache_event(
            provider="RailCore",
            type="fare",
            route=f"{from_code_clean}→{to_code_clean}",
            result="MISS",
        )
        api_tracker.log_request(
            provider="RailCore",
            endpoint="/fares/search",
            origin=from_code_clean,
            destination=to_code_clean,
            date=date_clean,
            request_type="fare",
            is_cache_hit=False,
        )

        data = self._get(
            f"{self.BASE_URL}/fares/search",
            params={
                "from": from_code_clean,
                "to": to_code_clean,
                "date": date_clean,
                "quota": quota_clean,
            },
        )

        _FARE_CACHE[cache_key] = data
        return data

    # ========================================================
    # SELECTED TRAIN FARE
    # ========================================================

    def get_fare(
        self,
        train_number: str,
        from_code: str,
        to_code: str,
        date: str,
        class_code: str,
        quota_code: str,
    ) -> dict:

        # ----------------------------------------------------
        # IMPORTANT
        #
        # Do NOT call /fares/search directly here.
        #
        # get_fare_options() handles:
        #
        #     1. shared cache
        #     2. API call on cache miss
        #
        # ----------------------------------------------------

        data = self.get_fare_options(
            from_code=from_code,
            to_code=to_code,
            date=date,
            quota_code=quota_code,
        )

        # ----------------------------------------------------
        # EXTRACT TRAINS
        # ----------------------------------------------------

        data_root = data.get(
            "data",
            {}
        )

        if not isinstance(
            data_root,
            dict,
        ):

            raise RuntimeError(
                "Invalid RailCore fare response."
            )

        trains = data_root.get(
            "trains",
            []
        )

        if not isinstance(
            trains,
            list,
        ):

            raise RuntimeError(
                "Invalid RailCore train fare data."
            )

        # ----------------------------------------------------
        # FIND TRAIN
        # ----------------------------------------------------

        selected_train = next(
            (
                train
                for train in trains
                if str(
                    train.get(
                        "train_number"
                    )
                )
                == str(train_number)
            ),
            None,
        )

        if selected_train is None:

            raise RuntimeError(
                f"Train {train_number} was not found "
                "in RailCore fare response."
            )

        # ----------------------------------------------------
        # FIND CLASS
        # ----------------------------------------------------

        fares = selected_train.get(
            "fares",
            []
        )

        if not isinstance(
            fares,
            list,
        ):

            raise RuntimeError(
                "Invalid fare list returned by RailCore."
            )

        requested_class = (
            str(class_code)
            .strip()
            .upper()
        )

        selected_fare = next(
            (
                fare
                for fare in fares
                if str(
                    fare.get(
                        "class_code",
                        ""
                    )
                )
                .strip()
                .upper()
                == requested_class
            ),
            None,
        )

        if selected_fare is None:

            raise RuntimeError(
                f"Class {class_code} is not available "
                f"for train {train_number}."
            )

        # ----------------------------------------------------
        # RETURN NORMALIZED FARE
        # ----------------------------------------------------

        return {
            "success": True,
            "data": {
                "train_number": str(
                    train_number
                ),
                "class_code": requested_class,
                "fare": selected_fare.get(
                    "fare"
                ),
                "currency": selected_fare.get(
                    "currency",
                    "INR",
                ),
                "catering_charge": selected_fare.get(
                    "catering_charge"
                ),
            },
        }

    # ========================================================
    # SEAT AVAILABILITY
    # ========================================================

    def get_seats(
        self,
        train_number: str,
        from_code: str,
        to_code: str,
        date: str,
        class_code: str,
        quota_code: str,
    ) -> dict:

        return self._get(
            f"{self.BASE_URL}/availability/seats",
            params={
                "train_number": str(
                    train_number
                ),
                "from": str(
                    from_code
                ).strip().upper(),
                "to": str(
                    to_code
                ).strip().upper(),
                "date": str(
                    date
                ).strip(),
                "class": str(
                    class_code
                ).strip().upper(),
                "quota": str(
                    quota_code
                ).strip().upper(),
            },
        )

    # ========================================================
    # TRAIN SCHEDULE / ROUTE
    # ========================================================

    def get_train_schedule(
        self,
        train_number: str,
    ) -> dict:
        t_num = str(train_number).strip()
        if not t_num:
            return {}

        cached = _SCHEDULE_CACHE.get(t_num)
        from app.services.train.api_tracker import api_tracker
        if cached is not None:
            observability_metrics.record_cache_event(
                provider="RailCore",
                type="schedule",
                target=t_num,
                result="HIT",
            )
            api_tracker.log_request(
                provider="RailCore",
                endpoint=f"/trains/{t_num}/schedule",
                origin="N/A",
                destination="N/A",
                date="N/A",
                request_type="schedule",
                is_cache_hit=True,
            )
            return cached

        observability_metrics.record_cache_event(
            provider="RailCore",
            type="schedule",
            target=t_num,
            result="MISS",
        )
        api_tracker.log_request(
            provider="RailCore",
            endpoint=f"/trains/{t_num}/schedule",
            origin="N/A",
            destination="N/A",
            date="N/A",
            request_type="schedule",
            is_cache_hit=False,
        )

        try:
            data = self._get(f"{self.BASE_URL}/trains/{t_num}/schedule")
            if isinstance(data, dict) and data.get("success"):
                _SCHEDULE_CACHE[t_num] = data
                return data
        except (RailCoreRateLimitedError, RailCoreCircuitOpenError, RailCoreAuthError):
            raise
        except Exception as exc:
            logger.debug("RailCore get_train_schedule failed for train %s: %s", t_num, exc)

        return {}
   
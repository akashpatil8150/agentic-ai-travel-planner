import time
import httpx

from app.core.config import settings
from app.observability.metrics import observability_metrics


# ============================================================
# SHARED TAVILY SEARCH CACHE
# ============================================================
#
# Module-level cache.
#
# Important:
# TavilyClient() multiple times create hone par bhi
# sab instances same cache use karenge.
#
# Example:
#
# Client #1 -> query A -> API CALL -> CACHE
# Client #2 -> query A -> CACHE HIT -> NO API CALL
#
# Failed requests are NEVER cached.
#
# ============================================================

_TAVILY_SEARCH_CACHE: dict[
    tuple[str, int],
    dict,
] = {}


class TavilyAPIError(Exception):
    """
    Raised when Tavily API request fails.
    """

    pass


class TavilyClient:
    """
    Client for Tavily Search API.

    Responsibilities:
        - Validate search query
        - Normalize query
        - Check shared cache
        - Call Tavily
        - Handle API/network errors
        - Cache successful responses

    Verification logic belongs to OFVL.
    """

    BASE_URL = "https://api.tavily.com/search"

    def __init__(self):

        if not settings.tavily_api_key:

            raise ValueError(
                "TAVILY_API_KEY is not configured."
            )

        self.api_key = (
            settings.tavily_api_key
        )

    # ========================================================
    # SEARCH
    # ========================================================

    def search(
        self,
        query: str,
        max_results: int = 5,
    ) -> dict:

        # ----------------------------------------------------
        # VALIDATE QUERY
        # ----------------------------------------------------

        if not query or not query.strip():

            raise ValueError(
                "Tavily search query cannot be empty."
            )

        # ----------------------------------------------------
        # VALIDATE MAX RESULTS
        # ----------------------------------------------------

        if isinstance(
            max_results,
            bool,
        ) or not isinstance(
            max_results,
            int,
        ):

            raise ValueError(
                "Tavily max_results must be an integer."
            )

        if max_results <= 0:

            raise ValueError(
                "Tavily max_results must be greater than 0."
            )

        # ----------------------------------------------------
        # NORMALIZE QUERY
        # ----------------------------------------------------

        normalized_query = " ".join(
            query.strip().lower().split()
        )

        # ----------------------------------------------------
        # CACHE KEY
        # ----------------------------------------------------

        cache_key = (
            normalized_query,
            max_results,
        )

        # ----------------------------------------------------
        # CACHE HIT
        # ----------------------------------------------------

        cached_result = (
            _TAVILY_SEARCH_CACHE.get(
                cache_key
            )
        )

        if cached_result is not None:
            observability_metrics.record_cache_event(
                provider="Tavily",
                type="verification",
                target=normalized_query[:30],
                result="HIT",
            )
            return cached_result

        # ----------------------------------------------------
        # CACHE MISS
        # ----------------------------------------------------

        observability_metrics.record_cache_event(
            provider="Tavily",
            type="verification",
            target=normalized_query[:30],
            result="MISS",
        )

        # ----------------------------------------------------
        # REQUEST PAYLOAD
        # ----------------------------------------------------

        payload = {

            "api_key": self.api_key,

            "query": normalized_query,

            "search_depth": "basic",

            "topic": "general",

            "max_results": max_results,

            "include_answer": False,

            "include_raw_content": False,

            "include_images": False,
        }

        # ----------------------------------------------------
        # API REQUEST
        # ----------------------------------------------------

        start_time = time.perf_counter()
        try:

            response = httpx.post(
                self.BASE_URL,
                json=payload,
                timeout=15.0,
            )
            latency_ms = (time.perf_counter() - start_time) * 1000
            observability_metrics.record_api_call(
                provider="Tavily",
                operation="verification",
                target="place" if "hotel" not in normalized_query and "train" not in normalized_query and "flight" not in normalized_query else "entity",
                status=response.status_code,
                latency_ms=latency_ms,
                cache="MISS",
            )

        except httpx.TimeoutException as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            observability_metrics.record_api_call(
                provider="Tavily",
                operation="verification",
                target="entity",
                status="TIMEOUT",
                latency_ms=latency_ms,
                cache="MISS",
            )

            raise TavilyAPIError(
                "Tavily request timed out."
            ) from exc

        except httpx.RequestError as exc:
            latency_ms = (time.perf_counter() - start_time) * 1000
            observability_metrics.record_api_call(
                provider="Tavily",
                operation="verification",
                target="entity",
                status="ERROR",
                latency_ms=latency_ms,
                cache="MISS",
            )

            raise TavilyAPIError(
                f"Tavily request failed: {exc}"
            ) from exc

        # ====================================================
        # HTTP ERROR
        # ====================================================

        if response.status_code != 200:

            raise TavilyAPIError(
                f"Tavily API returned "
                f"status {response.status_code}: "
                f"{response.text}"
            )

        # ====================================================
        # JSON RESPONSE
        # ====================================================

        try:

            data = response.json()

        except ValueError as exc:

            raise TavilyAPIError(
                "Tavily returned invalid JSON."
            ) from exc

        # ----------------------------------------------------
        # BASIC RESPONSE VALIDATION
        # ----------------------------------------------------

        if not isinstance(
            data,
            dict,
        ):

            raise TavilyAPIError(
                "Tavily returned an invalid response."
            )

        # ----------------------------------------------------
        # STORE ONLY SUCCESSFUL RESPONSE
        # ----------------------------------------------------

        _TAVILY_SEARCH_CACHE[
            cache_key
        ] = data

        print(
            "\n[TAVILY CACHE STORE]"
        )

        print(
            f"Query: "
            f"'{normalized_query}'"
        )

        return data
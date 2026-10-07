import time
from typing import Any, Dict, List, Optional
from datetime import date, datetime

from app.observability.logger import (
    logger,
    request_id_context,
    planning_id_context,
    trip_id_context,
)


class ObservabilityMetrics:
    """
    Centralized collector and presentation manager for backend observability.
    Thread-safe and context-aware metric tracking across planning workflows.
    """

    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.reset()
        return cls._instance

    def reset(self):
        self.workflow_start_time: Optional[float] = None
        self.user_id: Optional[str] = None
        self.origin: Optional[str] = None
        self.destination: Optional[str] = None
        self.start_date: Optional[str] = None
        self.end_date: Optional[str] = None
        self.transport_mode: Optional[str] = None
        
        # Agent execution: agent_name -> {"status": str, "duration_ms": float}
        self.agent_runs: Dict[str, Dict[str, Any]] = {}
        
        # External API telemetry: provider -> count
        self.api_calls_count = 0
        self.api_provider_calls: Dict[str, int] = {}
        self.cache_hits_count = 0
        self.cache_misses_count = 0
        self.is_rate_limited = False
        
        # LLM telemetry (no cost calculation)
        self.llm_calls_count = 0
        self.llm_input_tokens = 0
        self.llm_output_tokens = 0
        self.llm_total_tokens = 0
        self.llm_latencies: List[float] = []
        self.llm_cache_hits_count = 0

        # Verification metrics
        self.verification_metrics: Dict[str, Any] = {}

        # Transport search metrics
        self.transport_metrics: Dict[str, Any] = {}

        # Results summary
        self.final_status: Optional[str] = None
        self.transport_count: Optional[int] = None
        self.hotel_count: Optional[int] = None
        self.places_count: Optional[int] = None
        self.weather_status: Optional[str] = None
        self.itinerary_status: Optional[str] = None

    def set_correlation(
        self,
        request_id: Optional[str] = None,
        planning_id: Optional[str] = None,
        trip_id: Optional[Any] = None,
        user_id: Optional[Any] = None,
        route: Optional[str] = None,
        dates: Optional[str] = None,
        transport: Optional[str] = None,
    ):
        """Set or update correlation and workflow metadata."""
        if request_id:
            request_id_context.set(request_id)
        if planning_id:
            planning_id_context.set(str(planning_id))
        if trip_id:
            trip_id_context.set(trip_id)
        if user_id:
            self.user_id = str(user_id)
        if route:
            parts = route.split("→") if "→" in route else route.split("->")
            if len(parts) == 2:
                self.origin = parts[0].strip()
                self.destination = parts[1].strip()
        if dates:
            d_parts = dates.split("→") if "→" in dates else dates.split("->")
            if len(d_parts) == 2:
                self.start_date = d_parts[0].strip()
                self.end_date = d_parts[1].strip()
        if transport:
            self.transport_mode = transport.strip().upper()

    def get_agent_metrics(self, agent_name: str) -> Optional[Dict[str, Any]]:
        return self.agent_runs.get(agent_name.lower())

    def get_api_count(self) -> int:
        return self.api_calls_count

    def get_cache_hit_count(self) -> int:
        return self.cache_hits_count

    def get_cache_miss_count(self) -> int:
        return self.cache_misses_count

    def get_llm_summary(self) -> Dict[str, Any]:
        return {
            "calls": self.llm_calls_count,
            "input_tokens": self.llm_input_tokens,
            "output_tokens": self.llm_output_tokens,
            "total_tokens": self.llm_total_tokens,
        }

    # ========================================================
    # CONTEXT ACCESSORS
    # ========================================================

    def get_correlation_ids(self, state=None) -> tuple[str, str, str]:
        """
        Safely extract (request_id, planning_id, trip_id).
        Checks state first, then contextvars.
        """
        req_id = request_id_context.get() or "-"
        if req_id == "-":
            req_id = "req_live"

        planning_id = None
        trip_id = None

        if state is not None:
            planning_id = getattr(state, "planning_id", None)
            trip_id = getattr(state, "trip_id", None)
            if planning_id is None and hasattr(state, "metadata") and isinstance(state.metadata, dict):
                planning_id = state.metadata.get("planning_id")
            if trip_id is None and hasattr(state, "metadata") and isinstance(state.metadata, dict):
                trip_id = state.metadata.get("trip_id")

        if planning_id is None:
            planning_id = planning_id_context.get()
        if trip_id is None:
            trip_id = trip_id_context.get()

        planning_id_str = str(planning_id) if planning_id is not None else "N/A"
        trip_id_str = str(trip_id) if trip_id is not None else "N/A"

        return req_id, planning_id_str, trip_id_str

    # ========================================================
    # 1. REQUEST / PLANNING START HEADER
    # ========================================================

    def print_planning_start_header(
        self,
        request_id: Optional[str] = None,
        planning_id: Optional[str] = None,
        trip_id: Optional[Any] = None,
        user_id: Optional[Any] = None,
        origin: Optional[str] = None,
        destination: Optional[str] = None,
        start_date: Optional[Any] = None,
        end_date: Optional[Any] = None,
        transport_mode: Optional[str] = None,
        **kwargs,
    ):
        self.workflow_start_time = time.perf_counter()
        req_id, p_id, t_id = self.get_correlation_ids()
        
        final_req_id = str(request_id or req_id)
        final_p_id = str(planning_id or p_id)
        final_t_id = str(trip_id or t_id)
        final_u_id = str(user_id or self.user_id or "N/A")

        self.user_id = final_u_id
        self.origin = origin or self.origin or "N/A"
        self.destination = destination or self.destination or "N/A"
        self.transport_mode = (transport_mode or self.transport_mode or "TRAIN").upper()

        def _format_date(d):
            if isinstance(d, (date, datetime)):
                return d.strftime("%d %b %Y")
            if isinstance(d, str) and d:
                try:
                    return datetime.fromisoformat(d.replace("Z", "")).strftime("%d %b %Y")
                except Exception:
                    return d
            return "N/A"

        date_str_1 = _format_date(start_date) if start_date else (self.start_date or "N/A")
        date_str_2 = _format_date(end_date) if end_date else (self.end_date or "N/A")
        self.start_date = date_str_1
        self.end_date = date_str_2

        route_str = f"{self.origin} → {self.destination}"
        dates_str = f"{date_str_1} → {date_str_2}"

        header_lines = [
            "╔════════════════════════════════════════════════════════════╗",
            "║                 TRIP PLANNING START                        ║",
            "╠════════════════════════════════════════════════════════════╣",
            f"║ Request ID   : {final_req_id}",
            f"║ Planning ID  : {final_p_id}",
            f"║ Trip ID      : {final_t_id}",
            f"║ User ID      : {final_u_id}",
            f"║ Route        : {route_str}",
            f"║ Dates        : {dates_str}",
            f"║ Transport    : {self.transport_mode}",
            "╚════════════════════════════════════════════════════════════╝",
        ]
        formatted = "\n".join(header_lines)
        print(f"\n{formatted}\n")
        logger.info(
            "TRIP PLANNING START | request_id=%s | planning_id=%s | trip_id=%s | route=%s | dates=%s | transport=%s",
            final_req_id,
            final_p_id,
            final_t_id,
            route_str,
            dates_str,
            self.transport_mode,
        )

    # ========================================================
    # 2. AGENT OBSERVABILITY
    # ========================================================

    def record_agent_start(self, agent_name: str, state=None) -> float:
        _, planning_id, trip_id = self.get_correlation_ids(state)
        print(f"[AGENT START] {agent_name} | planning_id={planning_id} | trip_id={trip_id}")
        logger.debug("AGENT START | agent=%s | planning_id=%s | trip_id=%s", agent_name, planning_id, trip_id)
        return time.perf_counter()

    def record_agent_complete(
        self,
        agent_name: str,
        start_time: float,
        state=None,
        status: str = "success",
    ) -> float:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        _, planning_id, trip_id = self.get_correlation_ids(state)
        self.agent_runs[agent_name.lower()] = {"status": status.upper(), "duration_ms": duration_ms}

        print(f"[AGENT COMPLETE] {agent_name} | status={status} | duration={duration_ms:.0f} ms")
        logger.debug(
            "AGENT COMPLETE | agent=%s | status=%s | duration_ms=%.2f | planning_id=%s | trip_id=%s",
            agent_name,
            status,
            duration_ms,
            planning_id,
            trip_id,
        )
        return duration_ms

    def record_agent_failed(
        self,
        agent_name: str,
        start_time: float,
        error: Any,
        state=None,
    ) -> float:
        duration_ms = round((time.perf_counter() - start_time) * 1000, 2)
        _, planning_id, trip_id = self.get_correlation_ids(state)
        short_err = str(error).splitlines()[0] if error else "Unknown error"
        self.agent_runs[agent_name.lower()] = {"status": "FAILED", "duration_ms": duration_ms}

        print(f"[AGENT FAILED] {agent_name} | duration={duration_ms:.0f} ms | error={short_err}")
        logger.error(
            "AGENT FAILED | agent=%s | status=failed | duration_ms=%.2f | error=%s | planning_id=%s | trip_id=%s",
            agent_name,
            duration_ms,
            short_err,
            planning_id,
            trip_id,
        )
        return duration_ms

    # ========================================================
    # 3. EXTERNAL API OBSERVABILITY
    # ========================================================

    def record_api_call(
        self,
        provider: str,
        endpoint: Optional[str] = None,
        operation: Optional[str] = None,
        route: Optional[str] = None,
        city: Optional[str] = None,
        target: Optional[str] = None,
        status: int | str = 200,
        latency_ms: float = 0.0,
        cache_state: str = "MISS",
        cache: Optional[str] = None,
    ):
        actual_cache = (cache or cache_state or "MISS").upper()
        if actual_cache == "MISS":
            self.api_calls_count += 1
            prov_key = provider.strip()
            self.api_provider_calls[prov_key] = self.api_provider_calls.get(prov_key, 0) + 1

        logger.debug(
            "API CALL | provider=%s | endpoint=%s | operation=%s | route=%s | city=%s | target=%s | status=%s | latency_ms=%.2f | cache=%s",
            provider,
            endpoint,
            operation,
            route,
            city,
            target,
            status,
            latency_ms,
            actual_cache,
        )

    # ========================================================
    # 4. CACHE OBSERVABILITY
    # ========================================================

    def record_cache_event(
        self,
        provider: str,
        cache_type: Optional[str] = None,
        type: Optional[str] = None,
        route: Optional[str] = None,
        city: Optional[str] = None,
        target: Optional[str] = None,
        result: str = "HIT",
    ):
        actual_type = type or cache_type
        res_upper = result.upper()
        if res_upper == "HIT":
            self.cache_hits_count += 1
        else:
            self.cache_misses_count += 1

        logger.debug(
            "CACHE EVENT | provider=%s | type=%s | route=%s | city=%s | target=%s | result=%s",
            provider,
            actual_type,
            route,
            city,
            target,
            res_upper,
        )

    # ========================================================
    # 5. LLM OBSERVABILITY
    # ========================================================

    def record_llm_call(
        self,
        model: str,
        input_tokens: int,
        output_tokens: int,
        total_tokens: int,
        latency_ms: float,
        status: str = "success",
        planning_id: Optional[str] = None,
        trip_id: Optional[Any] = None,
        state=None,
    ):
        self.llm_calls_count += 1
        self.llm_input_tokens += int(input_tokens or 0)
        self.llm_output_tokens += int(output_tokens or 0)
        self.llm_total_tokens += int(total_tokens or (input_tokens + output_tokens))
        self.llm_latencies.append(latency_ms)

        _, ctx_planning_id, ctx_trip_id = self.get_correlation_ids(state)
        final_planning_id = planning_id or ctx_planning_id
        final_trip_id = str(trip_id) if trip_id is not None else ctx_trip_id

        logger.debug(
            "LLM CALL | model=%s | tokens=%d/%d/%d | latency_ms=%.2f | status=%s | planning_id=%s | trip_id=%s",
            model,
            input_tokens,
            output_tokens,
            total_tokens,
            latency_ms,
            status,
            final_planning_id,
            final_trip_id,
        )

    def record_llm_cache(self, model: str, result: str = "HIT"):
        self.llm_cache_hits_count += 1
        self.cache_hits_count += 1
        logger.debug("LLM CACHE | model=%s | result=%s", model, result.upper())

    # ========================================================
    # 6. TRANSPORT SUMMARY
    # ========================================================

    def print_transport_summary(
        self,
        outbound_route: str = "N/A",
        outbound_train: str = "N/A",
        return_route: Optional[str] = "Not requested",
        return_train: Optional[str] = "Not requested",
        candidates_count: int = 0,
        api_calls: Optional[int] = None,
        cache_hits: Optional[int] = None,
        cache_misses: Optional[int] = None,
        rate_limited: bool = False,
        search_result: str = "VALID_TRAIN_FOUND",
    ):
        actual_api_calls = self.api_calls_count if api_calls is None else api_calls
        actual_cache_hits = self.cache_hits_count if cache_hits is None else cache_hits
        actual_cache_misses = self.cache_misses_count if cache_misses is None else cache_misses
        ret_route_display = return_route or "Not requested"
        ret_train_display = return_train or "Not requested"

        self.transport_metrics = {
            "outbound_route": outbound_route,
            "outbound_train": outbound_train,
            "return_route": ret_route_display,
            "return_train": ret_train_display,
            "candidates": candidates_count,
            "api_calls": actual_api_calls,
            "cache_hits": actual_cache_hits,
            "cache_misses": actual_cache_misses,
            "rate_limited": rate_limited,
            "search_result": search_result,
        }

        logger.debug(
            "TRANSPORT SUMMARY | outbound=%s (%s) | return=%s (%s) | candidates=%d | api_calls=%d | hits=%d | misses=%d | rate_limited=%s | result=%s",
            outbound_route,
            outbound_train,
            ret_route_display,
            ret_train_display,
            candidates_count,
            actual_api_calls,
            actual_cache_hits,
            actual_cache_misses,
            rate_limited,
            search_result,
        )

    # ========================================================
    # 7. VERIFICATION SUMMARY
    # ========================================================

    def print_verification_summary(
        self,
        transport_verified_str: Optional[str] = None,
        hotels_verified_str: Optional[str] = None,
        places_verified_str: Optional[str] = None,
        weather_status_str: Optional[str] = None,
        overall_status_str: Optional[str] = None,
        transport: Optional[str] = None,
        hotels: Optional[str] = None,
        places: Optional[str] = None,
        weather: Optional[str] = None,
        overall: Optional[str] = None,
    ):
        t_str = transport or transport_verified_str or "N/A"
        h_str = hotels or hotels_verified_str or "N/A"
        p_str = places or places_verified_str or "N/A"
        w_str = weather or weather_status_str or "Available"
        o_str = (overall or overall_status_str or "PARTIAL").upper()

        self.verification_metrics = {
            "transport": t_str,
            "hotels": h_str,
            "places": p_str,
            "weather": w_str,
            "overall": o_str,
        }

        logger.debug(
            "VERIFICATION SUMMARY | transport=%s | hotels=%s | places=%s | weather=%s | overall=%s",
            t_str,
            h_str,
            p_str,
            w_str,
            o_str,
        )

    # ========================================================
    # 8. FINAL OBSERVABILITY SUMMARY
    # ========================================================

    def print_final_observability_summary(
        self,
        request_id: Optional[str] = None,
        planning_id: Optional[str] = None,
        trip_id: Optional[Any] = None,
        final_status: str = "READY",
        transport_count: Optional[Any] = None,
        hotel_count: Optional[Any] = None,
        places_count: Optional[Any] = None,
        weather_available: bool = True,
        itinerary_valid: bool = True,
        transport_result: Optional[str] = None,
        hotel_result: Optional[str] = None,
        places_result: Optional[str] = None,
        weather_result: Optional[str] = None,
        itinerary_result: Optional[str] = None,
        state=None,
    ):
        req_id, p_id, t_id = self.get_correlation_ids(state)
        final_req = str(request_id or req_id)
        final_plan = str(planning_id or p_id)
        final_trip = str(trip_id or t_id)

        total_time_str = "N/A"
        if self.workflow_start_time:
            total_duration_sec = time.perf_counter() - self.workflow_start_time
            if total_duration_sec >= 1.0:
                total_time_str = f"{total_duration_sec:.1f} sec"
            else:
                total_time_str = f"{total_duration_sec * 1000:.0f} ms"

        # Standard agent list
        agent_names = ["Transport", "Hotel", "Places", "Weather", "Verification"]
        agent_lines = []
        for name in agent_names:
            key = name.lower()
            run_data = self.agent_runs.get(key)
            if run_data:
                st = run_data.get("status", "SUCCESS").upper()
                dur_val = run_data.get("duration_ms", 0)
                dur_str = f"{dur_val:>5.0f} ms"
                if st in ["SUCCESS", "CONFIRMED_SELECTION", "VALID"]:
                    icon = "✓"
                elif st in ["PARTIAL", "AVAILABLE"]:
                    icon = "⚠"
                else:
                    icon = "✗"
                agent_lines.append(f"{icon} {name:<12} {dur_str}")
            else:
                agent_lines.append(f"- {name:<12}    N/A")

        # External APIs
        total_api_calls = self.api_calls_count
        rate_limited_str = "YES" if self.is_rate_limited else "NO"
        cache_summary_str = f"{self.cache_hits_count} hit / {self.cache_misses_count} miss"

        # LLM token calculations
        avg_llm_latency_str = (
            f"{(sum(self.llm_latencies) / len(self.llm_latencies)):.0f} ms"
            if self.llm_latencies
            else "N/A"
        )

        t_res_str = transport_result if transport_result is not None else (str(transport_count) if transport_count is not None else "N/A")
        h_res_str = hotel_result if hotel_result is not None else (str(hotel_count) if hotel_count is not None else "N/A")
        p_res_str = places_result if places_result is not None else (str(places_count) if places_count is not None else "N/A")
        w_status_str = weather_result if weather_result is not None else ("Available" if weather_available else "Unavailable")
        itin_status_str = itinerary_result if itinerary_result is not None else ("VALID" if itinerary_valid else "INVALID")

        route_display = f"{self.origin} → {self.destination}" if self.origin and self.destination else "N/A"
        dates_display = f"{self.start_date} → {self.end_date}" if self.start_date and self.end_date else "N/A"

        sep_line = "=" * 60
        div_line = "-" * 60

        summary_lines = [
            sep_line,
            "              TRIP PLANNING OBSERVABILITY",
            sep_line,
            f"Request     : {final_req}",
            f"Planning    : {final_plan}",
            f"Trip        : {final_trip}",
            f"Route       : {route_display}",
            f"Dates       : {dates_display}",
            div_line,
            "AGENTS",
            *agent_lines,
            div_line,
            "EXTERNAL APIs",
            f"Calls        : {total_api_calls}",
            f"Cache        : {cache_summary_str}",
            f"Rate Limited : {rate_limited_str}",
            div_line,
            "LLM",
            f"Calls        : {self.llm_calls_count}",
            f"Input Tokens : {self.llm_input_tokens}",
            f"Output Tokens: {self.llm_output_tokens}",
            f"Total Tokens : {self.llm_total_tokens}",
            f"Avg Latency  : {avg_llm_latency_str}",
            div_line,
            "RESULT",
            f"Transport    : {t_res_str}",
            f"Hotels       : {h_res_str}",
            f"Places       : {p_res_str}",
            f"Weather      : {w_status_str}",
            f"Itinerary    : {itin_status_str}",
            div_line,
            f"FINAL STATUS : {final_status}",
            f"TOTAL TIME   : {total_time_str}",
            sep_line,
        ]
        formatted = "\n".join(summary_lines)
        print(f"\n{formatted}\n")
        logger.debug(
            "TRIP PLANNING OBSERVABILITY | request_id=%s | planning_id=%s | trip_id=%s | status=%s | total_api=%d | llm_calls=%d | total_tokens=%d",
            final_req,
            final_plan,
            final_trip,
            final_status,
            total_api_calls,
            self.llm_calls_count,
            self.llm_total_tokens,
        )


observability_metrics = ObservabilityMetrics()

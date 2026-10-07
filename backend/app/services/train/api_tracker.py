import logging
from app.observability.metrics import observability_metrics

logger = logging.getLogger(__name__)


class TransportApiTracker:
    """
    Centralized tracker for transport API usage, caching metrics, and circuit-breaker status.
    """
    _instance = None

    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
            cls._instance.reset()
        return cls._instance

    def reset(self):
        observability_metrics.reset()
        self.railcore_journey_requests = 0
        self.railcore_fare_requests = 0
        self.railcore_skipped_circuit_breaker = 0
        self._railcore_rate_limited = False
        self.railcore_retry_after = None
        self.railcore_blocked_until = None
        self.railradar_requests = 0
        self.railradar_skipped_circuit_breaker = 0
        self._railradar_rate_limited = False
        self.railradar_retry_after = None
        self.railradar_blocked_until = None
        self.llm_transfer_requests = 0
        self.llm_transfer_cache_hits = 0
        self.llm_transfer_cache_misses = 0
        self.llm_estimates_rejected = 0
        self.cache_hits = 0
        self.cache_misses = 0
        self.duplicate_requests_prevented = 0
        try:
            import app.services.train.railradar_client as rrc
            rrc._IS_RATE_LIMITED = False
            rrc._TRAIN_SEARCH_CACHE.clear()
            rrc._TRAIN_DETAILS_CACHE.clear()
        except Exception:
            pass
        try:
            import app.services.train.railcore_client as rcc
            rcc._IS_RATE_LIMITED = False
            rcc._JOURNEY_CACHE.clear()
            rcc._FARE_CACHE.clear()
            rcc._SCHEDULE_CACHE.clear()
        except Exception:
            pass

    @property
    def railcore_rate_limited(self) -> bool:
        return self.is_railcore_rate_limited()

    @railcore_rate_limited.setter
    def railcore_rate_limited(self, val: bool):
        self._railcore_rate_limited = bool(val)
        if not val:
            self.railcore_blocked_until = None
            self.railcore_retry_after = None

    @property
    def railradar_rate_limited(self) -> bool:
        return self.is_railradar_rate_limited()

    @railradar_rate_limited.setter
    def railradar_rate_limited(self, val: bool):
        self._railradar_rate_limited = bool(val)
        if not val:
            self.railradar_blocked_until = None
            self.railradar_retry_after = None

    def is_railcore_rate_limited(self) -> bool:
        import time
        if not getattr(self, "_railcore_rate_limited", False):
            return False
        if getattr(self, "railcore_blocked_until", None) is not None:
            if time.time() >= self.railcore_blocked_until:
                self._railcore_rate_limited = False
                self.railcore_blocked_until = None
                self.railcore_retry_after = None
                try:
                    import app.services.train.railcore_client as rcc
                    rcc._IS_RATE_LIMITED = False
                except Exception:
                    pass
                logger.info("RailCore rate-limit cooldown expired. RailCore is now AVAILABLE again.")
                return False
            return True
        return True

    def is_railradar_rate_limited(self) -> bool:
        import time
        if not getattr(self, "_railradar_rate_limited", False):
            return False
        if getattr(self, "railradar_blocked_until", None) is not None:
            if time.time() >= self.railradar_blocked_until:
                self._railradar_rate_limited = False
                self.railradar_blocked_until = None
                self.railradar_retry_after = None
                try:
                    import app.services.train.railradar_client as rrc
                    rrc._IS_RATE_LIMITED = False
                except Exception:
                    pass
                logger.info("RailRadar rate-limit cooldown expired. RailRadar is now AVAILABLE again.")
                return False
            return True
        return True

    def log_llm_transfer_rejected(self, origin: str, destination: str, reason: str):
        self.llm_estimates_rejected += 1
        print(f"[LLM ESTIMATE REJECTED] {origin} -> {destination} | Reason: {reason}")
        logger.warning("LLM estimate rejected for %s -> %s: %s", origin, destination, reason)

    def log_llm_transfer(self, is_cache_hit: bool, origin: str, destination: str):
        self.llm_transfer_requests += 1
        if is_cache_hit:
            self.llm_transfer_cache_hits += 1
            print(f"[LLM TRANSFER ESTIMATION] CACHE HIT | {origin} <-> {destination}")
        else:
            self.llm_transfer_cache_misses += 1
            print(f"[LLM TRANSFER ESTIMATION] CACHE MISS | Requesting LLM estimate for {origin} -> {destination}")

    def log_skipped_circuit_breaker(self, provider: str = "RailCore"):
        prov_lower = provider.lower()
        if "railcore" in prov_lower:
            self.railcore_skipped_circuit_breaker += 1
        else:
            self.railradar_skipped_circuit_breaker += 1
        print(f"[{provider.upper()} API] SKIPPED (Circuit Breaker Active)")
        logger.info("%s API SKIPPED | circuit_breaker_active=True", provider.upper())

    def log_request(
        self,
        provider: str,
        endpoint: str,
        origin: str,
        destination: str,
        date: str,
        request_type: str,
        is_cache_hit: bool,
    ):
        if is_cache_hit:
            self.cache_hits += 1
            self.duplicate_requests_prevented += 1
            hit_str = "CACHE HIT"
        else:
            self.cache_misses += 1
            hit_str = "CACHE MISS"
            prov_lower = provider.lower()
            if "railcore" in prov_lower:
                if "journey" in request_type.lower() or "journey" in endpoint.lower():
                    self.railcore_journey_requests += 1
                elif "fare" in request_type.lower() or "fare" in endpoint.lower():
                    self.railcore_fare_requests += 1
            elif "railradar" in prov_lower:
                self.railradar_requests += 1

        print(
            f"[{provider.upper()} API] {hit_str} | Endpoint: {endpoint} | "
            f"Route: {origin} -> {destination} | Date: {date} | Type: {request_type}"
        )
        logger.info(
            "%s API %s | endpoint=%s | route=%s->%s | date=%s | type=%s",
            provider.upper(),
            hit_str,
            endpoint,
            origin,
            destination,
            date,
            request_type,
        )

    def mark_railradar_429(self, retry_after: int | str | None = None):
        import time
        self._railradar_rate_limited = True
        observability_metrics.is_rate_limited = True
        retry_sec = None
        if retry_after is not None:
            try:
                retry_sec = int(retry_after)
            except (ValueError, TypeError):
                retry_sec = None
        self.railradar_retry_after = retry_sec
        if retry_sec is not None and retry_sec > 0:
            self.railradar_blocked_until = time.time() + retry_sec
            print(f"[RAILRADAR CIRCUIT BREAKER] HTTP 429 rate limit encountered. RailRadar calls disabled for {retry_sec} seconds (Retry-After: {retry_sec}).")
            logger.warning("RailRadar HTTP 429 encountered. Rate limiting activated for %s seconds.", retry_sec)
        else:
            self.railradar_blocked_until = None
            print("[RAILRADAR CIRCUIT BREAKER] HTTP 429 rate limit encountered. RailRadar calls disabled for this run.")
            logger.warning("RailRadar HTTP 429 encountered. Rate limiting activated.")
        try:
            import app.services.train.railradar_client as rrc
            rrc._IS_RATE_LIMITED = True
        except Exception:
            pass

    def mark_railcore_429(self, retry_after: int | str | None = None):
        import time
        self._railcore_rate_limited = True
        observability_metrics.is_rate_limited = True
        retry_sec = None
        if retry_after is not None:
            try:
                retry_sec = int(retry_after)
            except (ValueError, TypeError):
                retry_sec = None
        self.railcore_retry_after = retry_sec
        if retry_sec is not None and retry_sec > 0:
            self.railcore_blocked_until = time.time() + retry_sec
            print(f"[RAILCORE CIRCUIT BREAKER] HTTP 429 rate limit encountered. RailCore calls disabled for {retry_sec} seconds (Retry-After: {retry_sec}).")
            logger.warning("RailCore HTTP 429 encountered. Rate limiting activated for %s seconds.", retry_sec)
        else:
            self.railcore_blocked_until = None
            print("[RAILCORE CIRCUIT BREAKER] HTTP 429 rate limit encountered. RailCore calls disabled for this run.")
            logger.warning("RailCore HTTP 429 encountered. Rate limiting activated.")
        try:
            import app.services.train.railcore_client as rcc
            rcc._IS_RATE_LIMITED = True
        except Exception:
            pass

    def print_summary(self):
        print("\n==================================================")
        print("TRANSPORT API USAGE")
        print(f"RailCore journey requests:           {self.railcore_journey_requests}")
        print(f"RailCore fare requests:              {self.railcore_fare_requests}")
        print(f"RailCore skipped (circuit breaker):  {self.railcore_skipped_circuit_breaker}")
        print(f"RailCore rate limited:               {self.railcore_rate_limited}")
        print(f"RailRadar external requests:         {self.railradar_requests}")
        print(f"RailRadar skipped (circuit breaker): {self.railradar_skipped_circuit_breaker}")
        print(f"RailRadar rate limited:              {self.railradar_rate_limited}")
        print(f"LLM transfer requests:               {self.llm_transfer_requests}")
        print(f"LLM transfer cache hits:             {self.llm_transfer_cache_hits}")
        print(f"LLM transfer cache misses:           {self.llm_transfer_cache_misses}")
        print(f"LLM estimates rejected:              {self.llm_estimates_rejected}")
        print(f"Cache hits:                         {self.cache_hits}")
        print(f"Cache misses:                       {self.cache_misses}")
        print("==================================================\n")


# Global singleton instance accessor
api_tracker = TransportApiTracker()

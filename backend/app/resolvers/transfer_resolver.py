import json
import logging
from typing import Any, Dict, Optional

from app.core.config import settings
from app.resolvers.india_locations import estimate_road_transfer
from app.services.train.api_tracker import api_tracker
from app.observability.metrics import observability_metrics

logger = logging.getLogger(__name__)

# Shared in-memory cache for bi-directional road transfer estimates
_TRANSFER_CACHE: Dict[str, Dict[str, Any]] = {}


class TransferResolver:
    """
    Generic, deterministic transfer-resolution layer.
    Estimates first-mile/last-mile road transfer distance and travel duration
    for all transport modes (Train, Flight, etc.).

    Guarantees:
        1. Bi-directional cache normalization (A <-> B share same estimate).
        2. LLM fallback estimation for road distance when coordinates/APIs are missing.
        3. LLM is strictly restricted to road distance/time estimates (NEVER train/flight facts).
        4. Returns None when estimates cannot be reliably determined (no fabricated numbers).
    """

    def __init__(self):
        self._llm_client = None

    def _get_llm_client(self):
        if self._llm_client is None and settings.groq_api_key:
            try:
                from app.services.llm.llm_client import LLMClient
                self._llm_client = LLMClient()
            except Exception as exc:
                logger.warning("Could not initialize LLMClient for transfer estimation: %s", exc)
        return self._llm_client

    @staticmethod
    def normalize_cache_key(from_loc: str, to_loc: str, mode: str = "road") -> str:
        loc1 = " ".join(str(from_loc or "").lower().strip().split())
        loc2 = " ".join(str(to_loc or "").lower().strip().split())
        sorted_locs = "|".join(sorted([loc1, loc2]))
        return f"{sorted_locs}|{mode}|transfer"

    def estimate_transfer_distance_llm(
        self,
        from_location: str,
        to_location: str,
        transport_mode: str = "road",
    ) -> Optional[Dict[str, Any]]:
        """
        Query LLM to estimate realistic road travel distance (km) and duration (mins)
        between two specific transfer endpoints.
        """
        clean_from = str(from_location or "").strip()
        clean_to = str(to_location or "").strip()
        if not clean_from or not clean_to:
            return None

        cache_key = self.normalize_cache_key(clean_from, clean_to, mode="road")
        if cache_key in _TRANSFER_CACHE:
            api_tracker.log_llm_transfer(is_cache_hit=True, origin=clean_from, destination=clean_to)
            observability_metrics.record_llm_cache(model=settings.llm_model, result="HIT")
            cached = dict(_TRANSFER_CACHE[cache_key])
            cached["transfer_from"] = clean_from
            cached["transfer_to"] = clean_to
            cached["from"] = clean_from
            cached["to"] = clean_to
            return cached

        llm = self._get_llm_client()
        if not llm:
            return None

        api_tracker.log_llm_transfer(is_cache_hit=False, origin=clean_from, destination=clean_to)
        sys_prompt = (
            "You are a road travel distance and travel duration estimator for India. "
            "Estimate the approximate road travel distance in kilometers and duration between the specified origin and destination. "
            "Return ONLY a JSON object with: 'distance_km' (number in km), 'duration_hours' (number in hours) or 'duration_minutes' (number in minutes). "
            "Do NOT invent train or flight routes. Return only road transfer estimates."
        )
        usr_prompt = (
            f"Estimate approximate road travel distance in kilometers between:\n"
            f"{clean_from}\n"
            f"and\n"
            f"{clean_to}\n\n"
            f"Return a reasonable approximate road distance and estimated road travel time in JSON:\n"
            f'{{"distance_km": <number>, "duration_hours": <number>}}'
        )

        try:
            resp_str = llm.generate(
                system_prompt=sys_prompt,
                user_prompt=usr_prompt,
                temperature=0.1,
                max_tokens=800,
                reasoning_effort="low",
            )
            clean_resp = (resp_str or "").strip()
            if not clean_resp:
                return None

            if "```json" in clean_resp:
                clean_resp = clean_resp.split("```json")[1].split("```")[0].strip()
            elif "```" in clean_resp:
                clean_resp = clean_resp.split("```")[1].split("```")[0].strip()

            parsed = {}
            try:
                parsed = json.loads(clean_resp)
            except Exception:
                import re
                km_match = re.search(r"(\d+(?:\.\d+)?)\s*(?:km|kilometers|kms)", clean_resp, re.IGNORECASE)
                if km_match:
                    parsed["distance_km"] = float(km_match.group(1))

            raw_d_km = parsed.get("distance_km")
            raw_d_hours = parsed.get("duration_hours")
            raw_d_min = parsed.get("duration_minutes")

            if raw_d_km is not None and isinstance(raw_d_km, (int, float)) and raw_d_km > 0:
                road_km = int(round(float(raw_d_km)))
                if raw_d_hours and isinstance(raw_d_hours, (int, float)) and raw_d_hours > 0:
                    duration_mins = int(round(float(raw_d_hours) * 60))
                elif raw_d_min and isinstance(raw_d_min, (int, float)) and raw_d_min > 0:
                    duration_mins = int(round(float(raw_d_min)))
                else:
                    avg_speed = 35.0 if ("manali" in clean_from.lower() or "manali" in clean_to.lower() or "hill" in clean_from.lower() or "hill" in clean_to.lower() or "shimla" in clean_from.lower() or "shimla" in clean_to.lower()) else 45.0
                    duration_mins = max(15, int(round((road_km / avg_speed) * 60)))

                h = duration_mins // 60
                m = duration_mins % 60
                time_str = f"~{h}h {m:02d}m" if h > 0 else f"~{m}m"

                res = {
                    "transfer_from": clean_from,
                    "transfer_to": clean_to,
                    "from": clean_from,
                    "to": clean_to,
                    "origin": clean_from,
                    "destination": clean_to,
                    "mode": "road_transfer",
                    "road_distance_km": road_km,
                    "distance_km": road_km,
                    "estimated_distance_km": road_km,
                    "duration_minutes": duration_mins,
                    "estimated_duration": time_str,
                    "estimated_transfer_time": time_str,
                    "duration": time_str,
                    "source": "LLM",
                    "confidence": "high",
                    "has_transfer": True,
                }
                _TRANSFER_CACHE[cache_key] = res
                return res
        except Exception as exc:
            logger.warning("LLM transfer estimation failed for %s -> %s: %s", clean_from, clean_to, exc)

        return None

    def resolve_transfer(
        self,
        from_location: str,
        to_location: str,
        transport_mode: str = "train",
        lat1: Optional[float] = None,
        lon1: Optional[float] = None,
        lat2: Optional[float] = None,
        lon2: Optional[float] = None,
        is_hilly: bool = False,
        existing_distance_km: Optional[float] = None,
    ) -> Dict[str, Any]:
        """
        Resolve transfer between a city and a transport endpoint (station/airport).
        Follows priority:
        1. Calculate deterministic geographic baseline from coordinates/location data.
        2. Check in-memory cache (with validation against the deterministic baseline).
        3. Deterministic coordinate / road model fallback.

        LLM estimation is intentionally NOT used for transfer facts.
        """
        clean_from = str(from_location or "").strip()
        clean_to = str(to_location or "").strip()

        if not clean_from or not clean_to:
            return {
                "transfer_from": clean_from,
                "transfer_to": clean_to,
                "origin": clean_from,
                "destination": clean_to,
                "mode": "road_transfer",
                "road_distance_km": None,
                "distance_km": None,
                "estimated_distance_km": None,
                "duration_minutes": None,
                "estimated_transfer_time": None,
                "estimated_duration": None,
                "source": "none",
                "confidence": "low",
                "has_transfer": False,
                "from": clean_from,
                "to": clean_to,
            }

        cache_key = self.normalize_cache_key(clean_from, clean_to, mode="road")

        # 1. Compute baseline geometric ground truth
        geo_road_km: Optional[int] = None
        geo_duration_mins: Optional[int] = None
        geo_time_str: Optional[str] = None
        is_local = False
        coord_available = (lat1 is not None and lon1 is not None and lat2 is not None and lon2 is not None)

        if not coord_available:
            from app.resolvers.india_locations import get_location_entry
            entry1 = get_location_entry(clean_from)
            entry2 = get_location_entry(clean_to)
            if entry1:
                lat1 = lat1 if lat1 is not None else entry1.get("lat")
                lon1 = lon1 if lon1 is not None else entry1.get("lon")
                is_hilly = is_hilly or entry1.get("is_hilly", False)
            if entry2:
                lat2 = lat2 if lat2 is not None else entry2.get("lat")
                lon2 = lon2 if lon2 is not None else entry2.get("lon")
                is_hilly = is_hilly or entry2.get("is_hilly", False)
            coord_available = (lat1 is not None and lon1 is not None and lat2 is not None and lon2 is not None)

        if coord_available:
            try:
                from app.resolvers.india_locations import haversine_distance_km
                direct_km = haversine_distance_km(lat1, lon1, lat2, lon2)
                if direct_km <= 25.0:
                    is_local = True
                    geo_road_km = max(1, int(round(direct_km * 1.35)))
                    # Urban city traffic speed: ~20 km/h
                    geo_duration_mins = max(5, int(round((geo_road_km / 20.0) * 60)))
                else:
                    est = estimate_road_transfer(lat1, lon1, lat2, lon2, is_hilly=is_hilly)
                    geo_road_km = est.get("road_distance_km")
                    geo_duration_mins = est.get("duration_minutes")
            except Exception as exc:
                logger.warning("Coordinate distance calculation failed for %s -> %s: %s", clean_from, clean_to, exc)
        elif existing_distance_km is not None and existing_distance_km > 0:
            geo_road_km = int(round(float(existing_distance_km)))
            if geo_road_km <= 25:
                is_local = True
                geo_duration_mins = max(5, int(round((geo_road_km / 20.0) * 60)))
            else:
                avg_speed = 35.0 if is_hilly else 48.0
                geo_duration_mins = max(15, int(round((geo_road_km / avg_speed) * 60)))

        if geo_duration_mins is not None:
            h = geo_duration_mins // 60
            m = geo_duration_mins % 60
            geo_time_str = f"~{h}h {m:02d}m" if h > 0 else f"~{m}m"

        # 1. Check in-memory cache for transfers
        if cache_key in _TRANSFER_CACHE:
            cached_data = dict(_TRANSFER_CACHE[cache_key])
            cached_km = cached_data.get("road_distance_km") or 0
            cache_valid = True

            if geo_road_km is not None:
                if cached_km < 0.4 * geo_road_km or cached_km > 2.5 * geo_road_km:
                    cache_valid = False

            if cache_valid:
                api_tracker.log_llm_transfer(is_cache_hit=True, origin=clean_from, destination=clean_to)
                cached_data["transfer_from"] = clean_from
                cached_data["transfer_to"] = clean_to
                cached_data["origin"] = clean_from
                cached_data["destination"] = clean_to
                cached_data["from"] = clean_from
                cached_data["to"] = clean_to
                return cached_data
            else:
                _TRANSFER_CACHE.pop(cache_key, None)

        # 2. Never ask the LLM to calculate transfer distance/time.
        # The deterministic geographic result below is the only factual source.

        # 4. Deterministic Coordinate / Road Model Fallback
        source_type = "coordinates" if coord_available else ("existing" if existing_distance_km else "fallback")
        confidence = "high" if coord_available else ("medium" if geo_road_km else "low")

        result = {
            "transfer_from": clean_from,
            "transfer_to": clean_to,
            "origin": clean_from,
            "destination": clean_to,
            "mode": "road_transfer",
            "road_distance_km": geo_road_km,
            "distance_km": geo_road_km,
            "estimated_distance_km": geo_road_km,
            "duration_minutes": geo_duration_mins,
            "estimated_transfer_time": geo_time_str,
            "estimated_duration": geo_time_str,
            "duration": geo_time_str,
            "source": source_type,
            "confidence": confidence,
            "has_transfer": True if (clean_from and clean_to and clean_from.strip().lower() != clean_to.strip().lower()) else False,
            "from": clean_from,
            "to": clean_to,
        }

        if geo_road_km is not None:
            _TRANSFER_CACHE[cache_key] = result

        return result


# Global singleton and functional wrapper
transfer_resolver = TransferResolver()

def resolve_transfer(*args, **kwargs) -> Dict[str, Any]:
    return transfer_resolver.resolve_transfer(*args, **kwargs)

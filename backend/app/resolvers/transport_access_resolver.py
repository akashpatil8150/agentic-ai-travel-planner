"""
TransportAccessResolver Module
Generic India-Wide Transport Access & Station/Airport Endpoint Resolver.

Architecture:
User Origin/Destination
→ Geocoding
→ Transport Access Resolver
→ Discover nearby candidate railway stations/airports
→ Rank candidates
→ Validate transport connectivity/availability
→ Select best valid endpoint
→ Create transfer when endpoint differs from user destination
→ Store canonical result in TripState
"""

import logging
import requests
from typing import Dict, List, Any, Optional, Tuple
from datetime import date

from app.core.config import settings
from app.resolvers.india_locations import (
    resolve_stations_for_location,
    resolve_airports_for_location,
    get_location_entry,
    estimate_road_transfer,
)

logger = logging.getLogger(__name__)


class TransportAccessResolver:
    """
    Generic transport access resolver for Indian destinations.
    Works for both train and flight travel modes.
    """

    MAX_OUTBOUND_SEARCH_ATTEMPTS: int = 18
    MAX_RETURN_SEARCH_ATTEMPTS: int = 8

    def geocode_location(self, location_name: str) -> Dict[str, Any]:
        """Geocode a user location using the external geocoder.

        The India station registry is used only as a fallback when the
        geocoder is unavailable. Candidate station discovery itself is
        coordinate-driven and does not depend on a city -> station map.
        """
        clean_name = str(location_name).strip()
        if not clean_name:
            raise ValueError("Location cannot be empty")

        params = {
            "text": f"{clean_name}, India",
            "filter": "countrycode:in",
            "format": "json",
            "limit": 5,
            "apiKey": settings.geoapify_api_key,
        }

        try:
            response = requests.get(
                "https://api.geoapify.com/v1/geocode/search",
                params=params,
                timeout=10,
            )
            response.raise_for_status()
            payload = response.json()
            results = payload.get("results", []) if isinstance(payload, dict) else []

            if results:
                result = results[0]
                return {
                    "name": result.get("city") or result.get("name") or clean_name.title(),
                    "state": result.get("state") or "India",
                    "lat": float(result["lat"]),
                    "lon": float(result["lon"]),
                    "is_hilly": False,
                    "formatted_address": result.get("formatted"),
                    "source": "geoapify",
                }
        except (requests.RequestException, ValueError, KeyError, TypeError) as exc:
            logger.warning("Geocoding failed for '%s': %s", clean_name, exc)

        # Safe fallback for known locations. This must not be used for
        # station discovery unless coordinates are genuinely unavailable.
        loc_entry = get_location_entry(clean_name)
        if loc_entry:
            return {
                "name": loc_entry.get("name", clean_name.title()),
                "state": loc_entry.get("state", "India"),
                "lat": float(loc_entry.get("lat", 20.0)),
                "lon": float(loc_entry.get("lon", 78.0)),
                "is_hilly": loc_entry.get("is_hilly", False),
                "source": "local_fallback",
            }

        raise RuntimeError(f"Unable to geocode location: {clean_name}")

    def discover_candidates(
        self,
        location_name: str,
        mode: str = "train",
        geo_coords: Optional[Tuple[float, float]] = None,
    ) -> List[Dict[str, Any]]:
        """
        Dynamically generate transport endpoint candidates from location data.
        """
        is_flight = "flight" in str(mode).lower()
        if is_flight:
            return resolve_airports_for_location(location_name, geo_coords=geo_coords)
        else:
            candidates = resolve_stations_for_location(
                location_name,
                geo_coords=geo_coords,
            )
            exact_candidates = [
                candidate
                for candidate in candidates
                if candidate.get("is_exact_user_station")
            ]
            if exact_candidates:
                logger.info(
                    "Exact user station preserved | input=%s | station=%s (%s)",
                    location_name,
                    exact_candidates[0].get("name"),
                    exact_candidates[0].get("code"),
                )
            return candidates

    def rank_candidate_pairs(
        self,
        orig_candidates: List[Dict[str, Any]],
        dest_candidates: List[Dict[str, Any]],
    ) -> List[Tuple[Dict[str, Any], Dict[str, Any], float]]:
        """
        Rank candidate pairs using destination-first adaptive search.

        Search strategy:
        1. Rank destination candidates by station usefulness.
        2. For each destination, try ALL origin candidates.
        3. Only then move to the next destination.
        4. resolve_and_validate() stops immediately when a live journey is found.

        This preserves the 6 x 6 candidate architecture while ensuring
        destination alternatives are properly explored.

        No city-specific hardcoding.
        """

        def station_quality(
            candidate: Dict[str, Any],
            is_destination: bool = False,
        ) -> float:
            distance = float(candidate.get("distance_km") or 0)
            is_major = bool(candidate.get("is_major", True))
            is_railhead = bool(candidate.get("is_railhead", False))
            is_junction = bool(candidate.get("is_junction", False))
            is_minor = bool(candidate.get("is_minor", False))
            is_toy_train = bool(candidate.get("is_toy_train", False))

            name = str(candidate.get("name", "")).lower()

            # Generic railway-hub signals. These are intentionally
            # location-independent and do not hardcode any city.
            hub_keywords = (
                "junction",
                "central",
                "terminal",
                "cantt",
                "railway station",
            )
            hub_signal = any(keyword in name for keyword in hub_keywords)

            if is_destination:
                # For destination discovery, useful regional railheads and
                # major hubs should be preferred over special-purpose stations.
                quality = 0.0

                if is_major:
                    quality += 100.0

                if is_railhead:
                    quality += 40.0

                if is_junction:
                    quality += 30.0

                if hub_signal:
                    quality += 20.0

                if is_toy_train:
                    quality -= 60.0

                if is_minor:
                    quality -= 25.0

                # Distance is secondary. A useful regional railhead may
                # legitimately be farther away from the destination city.
                quality -= min(distance * 0.15, 20.0)
                return quality

            # For origin discovery, prefer major/useful stations close to
            # the user's actual origin.
            quality = 0.0

            if is_major:
                quality += 100.0

            if is_junction:
                quality += 20.0

            if hub_signal:
                quality += 15.0

            if distance == 0:
                quality += 30.0
            elif distance <= 10:
                quality += 20.0
            elif distance <= 25:
                quality += 10.0
            else:
                quality -= min(distance * 0.15, 20.0)

            if is_minor:
                quality -= 20.0

            return quality

        # ---------------------------------------------------------
        # DESTINATION-FIRST ORDER
        # ---------------------------------------------------------
        ranked_destinations = sorted(
            dest_candidates,
            key=lambda c: station_quality(c, is_destination=True),
            reverse=True,
        )

        # ---------------------------------------------------------
        # ORIGIN ORDER
        # ---------------------------------------------------------
        ranked_origins = sorted(
            orig_candidates,
            key=lambda c: station_quality(c, is_destination=False),
            reverse=True,
        )

        ranked: List[Tuple[Dict[str, Any], Dict[str, Any], float]] = []

        # ---------------------------------------------------------
        # DESTINATION-FIRST PAIR GENERATION
        # ---------------------------------------------------------
        # Example:
        #
        # Destination D1:
        #   O1 -> D1
        #   O2 -> D1
        #   O3 -> D1
        #   O4 -> D1
        #   O5 -> D1
        #   O6 -> D1
        #
        # Destination D2:
        #   O1 -> D2
        #   ...
        #
        # This ensures origin alternatives are exhausted for a useful
        # destination railhead before moving to the next destination.
        # ---------------------------------------------------------
        for dest_index, dest in enumerate(ranked_destinations):
            dest_quality = station_quality(
                dest,
                is_destination=True,
            )

            for orig_index, orig in enumerate(ranked_origins):
                orig_quality = station_quality(
                    orig,
                    is_destination=False,
                )

                # Score is primarily for observability/debugging. The actual
                # search ordering is controlled by destination-first generation.
                score = (
                    1000.0
                    - (dest_index * 100.0)
                    - (orig_index * 5.0)
                    + (dest_quality * 0.10)
                    + (orig_quality * 0.05)
                )

                ranked.append(
                    (
                        orig,
                        dest,
                        round(score, 2),
                    )
                )

        return ranked

    def rank_return_candidate_pairs(
        self,
        dest_candidates: List[Dict[str, Any]],
        orig_candidates: List[Dict[str, Any]],
        selected_out_orig: Optional[Dict[str, Any]] = None,
        selected_out_dest: Optional[Dict[str, Any]] = None,
    ) -> List[Tuple[Dict[str, Any], Dict[str, Any], float]]:
        """
        Rank return candidate pairs dynamically with outbound-endpoint awareness.

        Prioritizes:
        - Tier 1: Exact reverse pair of actual selected outbound endpoints (selected_out_dest -> selected_out_orig).
        - Tier 2:
            * Nearby destination candidates -> selected_out_orig
            * selected_out_dest -> nearby origin candidates
        - Tier 3:
            * Nearby destination candidates -> nearby origin candidates
        - Tier 4: Broader candidate pairs if needed.

        Deduplicates candidate pairs while strictly preserving tier priority.
        If outbound endpoints are not available, falls back to deterministic candidate pair ranking.
        """
        if not selected_out_orig or not selected_out_dest:
            return self.rank_candidate_pairs(dest_candidates, orig_candidates)

        out_orig_code = str(selected_out_orig.get("code", "")).strip().upper()
        out_dest_code = str(selected_out_dest.get("code", "")).strip().upper()

        primary_ret_orig = next(
            (c for c in dest_candidates if str(c.get("code", "")).strip().upper() == out_dest_code),
            selected_out_dest,
        )
        primary_ret_dest = next(
            (c for c in orig_candidates if str(c.get("code", "")).strip().upper() == out_orig_code),
            selected_out_orig,
        )

        ranked: List[Tuple[Dict[str, Any], Dict[str, Any], float]] = []
        seen_pairs = set()

        def _add_pair(orig_c: Dict[str, Any], dest_c: Dict[str, Any], score: float):
            pair_key = (
                str(orig_c.get("code", "")).strip().upper(),
                str(dest_c.get("code", "")).strip().upper(),
            )
            if not pair_key[0] or not pair_key[1] or pair_key[0] == pair_key[1]:
                return
            if pair_key not in seen_pairs:
                seen_pairs.add(pair_key)
                ranked.append((orig_c, dest_c, round(score, 2)))

        # Tier 1: Exact reverse pair (selected outbound destination -> selected outbound origin)
        _add_pair(primary_ret_orig, primary_ret_dest, 200.0)

        # Tier 2:
        # A. Other destination candidates -> selected outbound origin
        for d_idx, d in enumerate(dest_candidates):
            if str(d.get("code", "")).strip().upper() != out_dest_code:
                d_dist = d.get("distance_km", 0)
                d_major = d.get("is_major", True)
                score = 170.0 - (d_dist * 0.1) - (d_idx * 5.0) + (10.0 if d_major else 0.0)
                _add_pair(d, primary_ret_dest, score)

        # B. Selected outbound destination -> other origin candidates
        for o_idx, o in enumerate(orig_candidates):
            if str(o.get("code", "")).strip().upper() != out_orig_code:
                o_dist = o.get("distance_km", 0)
                o_major = o.get("is_major", True)
                score = 160.0 - (o_dist * 0.1) - (o_idx * 5.0) + (10.0 if o_major else 0.0)
                _add_pair(primary_ret_orig, o, score)

        # Tier 3 & Tier 4: Remaining combinations
        base_ranked = self.rank_candidate_pairs(dest_candidates, orig_candidates)
        for d_c, o_c, base_score in base_ranked:
            _add_pair(d_c, o_c, base_score)

        return ranked

    def _extract_option_endpoints(
        self,
        opt: Any,
        default_orig_c: Dict[str, Any],
        default_dest_c: Dict[str, Any],
        is_flight: bool = False,
    ) -> Tuple[Dict[str, Any], Dict[str, Any]]:
        orig_code = default_orig_c["code"] if default_orig_c else None
        orig_name = default_orig_c.get("name", orig_code) if default_orig_c else orig_code
        dest_code = default_dest_c["code"] if default_dest_c else None
        dest_name = default_dest_c.get("name", dest_code) if default_dest_c else dest_code

        if is_flight or not opt:
            return default_orig_c, default_dest_c

        # Support both dict and object (Pydantic models)
        if isinstance(opt, dict):
            src_dict = opt.get("source") if isinstance(opt.get("source"), dict) else {}
            dst_dict = opt.get("destination") if isinstance(opt.get("destination"), dict) else {}

            act_orig_code = (
                opt.get("boarding_station_code")
                or opt.get("boarding_station")
                or opt.get("from_station_code")
                or opt.get("from_code")
                or src_dict.get("code")
                or orig_code
            )
            act_orig_name = (
                opt.get("boarding_station_name")
                or opt.get("from_station_name")
                or src_dict.get("name")
                or orig_name
            )
            act_dest_code = (
                opt.get("alighting_station_code")
                or opt.get("alighting_station")
                or opt.get("to_station_code")
                or opt.get("to_code")
                or dst_dict.get("code")
                or dest_code
            )
            act_dest_name = (
                opt.get("alighting_station_name")
                or opt.get("to_station_name")
                or dst_dict.get("name")
                or dest_name
            )
        else:
            src = getattr(opt, "source", None)
            dst = getattr(opt, "destination", None)
            act_orig_code = (
                getattr(opt, "boarding_station_code", None)
                or getattr(opt, "boarding_station", None)
                or getattr(opt, "from_station_code", None)
                or getattr(opt, "from_code", None)
                or (getattr(src, "code", None) if hasattr(src, "code") else (src.get("code") if isinstance(src, dict) else None))
                or orig_code
            )
            act_orig_name = (
                getattr(opt, "boarding_station_name", None)
                or getattr(opt, "from_station_name", None)
                or (getattr(src, "name", None) if hasattr(src, "name") else (src.get("name") if isinstance(src, dict) else None))
                or orig_name
            )
            act_dest_code = (
                getattr(opt, "alighting_station_code", None)
                or getattr(opt, "alighting_station", None)
                or getattr(opt, "to_station_code", None)
                or getattr(opt, "to_code", None)
                or (getattr(dst, "code", None) if hasattr(dst, "code") else (dst.get("code") if isinstance(dst, dict) else None))
                or dest_code
            )
            act_dest_name = (
                getattr(opt, "alighting_station_name", None)
                or getattr(opt, "to_station_name", None)
                or (getattr(dst, "name", None) if hasattr(dst, "name") else (dst.get("name") if isinstance(dst, dict) else None))
                or dest_name
            )

        resolved_orig = self._resolve_endpoint_dict(
            act_orig_code, act_orig_name, fallback_cand=default_orig_c, is_flight=False
        )
        resolved_dest = self._resolve_endpoint_dict(
            act_dest_code, act_dest_name, fallback_cand=default_dest_c, is_flight=False
        )
        return resolved_orig, resolved_dest

    def _resolve_endpoint_dict(
        self,
        code: str,
        name: str,
        fallback_cand: Optional[Dict[str, Any]] = None,
        is_flight: bool = False,
    ) -> Dict[str, Any]:
        """
        Build an endpoint dictionary preserving the actual station/airport code and name.
        """
        from app.resolvers.india_locations import get_location_entry
        clean_code = str(code or "").strip().upper()
        clean_name = str(name or clean_code).strip()

        # Check fallback candidate first if it has matching code
        if fallback_cand and fallback_cand.get("code", "").upper() == clean_code:
            return {
                "code": clean_code,
                "name": clean_name or fallback_cand.get("name", clean_code),
                "city": fallback_cand.get("city") or clean_name or clean_code,
                "lat": fallback_cand.get("lat"),
                "lon": fallback_cand.get("lon"),
                "is_major": fallback_cand.get("is_major", True),
            }

        # Lookup in location registry
        entry = get_location_entry(clean_code) or get_location_entry(clean_name)
        lat = None
        lon = None
        city = clean_name
        is_major = True

        if entry:
            lat = entry.get("lat")
            lon = entry.get("lon")
            city = entry.get("name", clean_name)
            items = entry.get("airports" if is_flight else "stations", [])
            for item in items:
                if item.get("code", "").upper() == clean_code:
                    lat = item.get("lat", lat)
                    lon = item.get("lon", lon)
                    city = item.get("city", city)
                    is_major = item.get("is_major", is_major)
                    if not clean_name or clean_name == clean_code:
                        clean_name = item.get("name", clean_name)
                    break

        if lat is None and fallback_cand:
            lat = fallback_cand.get("lat")
            lon = fallback_cand.get("lon")
            is_major = fallback_cand.get("is_major", True)

        return {
            "code": clean_code,
            "name": clean_name or clean_code,
            "city": city or clean_name or clean_code,
            "lat": lat,
            "lon": lon,
            "is_major": is_major,
        }

    def create_transfer_info(
        self,
        user_loc: str,
        endpoint: Dict[str, Any],
        geo_info: Dict[str, Any],
        is_origin: bool = False,
        mode: str = "train",
    ) -> Optional[Dict[str, Any]]:
        """
        Generate transfer details when selected endpoint differs from user location.
        """
        if not user_loc or not endpoint or not isinstance(endpoint, dict):
            return None

        term = "Airport" if "flight" in str(mode).lower() else "Station"
        endpoint_name = endpoint.get("name", endpoint.get("code"))
        endpoint_code = endpoint.get("code")
        hub_city = endpoint.get("city") or endpoint_name

        clean_user = str(user_loc).strip().title()
        clean_hub = str(hub_city).strip().title()

        # Calculate transfer distance using TransferResolver
        from app.resolvers.transfer_resolver import TransferResolver
        transfer_res = TransferResolver()

        # Clean endpoint display
        ep_display = str(endpoint_name or endpoint_code or "").strip()
        from_loc_str = clean_user if is_origin else ep_display
        to_loc_str = ep_display if is_origin else clean_user

        resolved_t = transfer_res.resolve_transfer(
            from_location=from_loc_str,
            to_location=to_loc_str,
            transport_mode=mode,
            lat1=geo_info.get("lat"),
            lon1=geo_info.get("lon"),
            lat2=endpoint.get("lat", geo_info.get("lat")),
            lon2=endpoint.get("lon", geo_info.get("lon")),
            is_hilly=geo_info.get("is_hilly", False),
            existing_distance_km=endpoint.get("distance_km"),
        )

        road_km = resolved_t.get("road_distance_km")
        time_str = resolved_t.get("estimated_transfer_time")
        source_type = resolved_t.get("source", "existing")

        # Check if transfer card is required:
        # A transfer is required whenever the user location differs from the transport endpoint.
        u_low = clean_user.lower()
        code_low = str(endpoint_code or "").strip().lower()
        name_low = str(endpoint_name or "").strip().lower()
        hub_low = clean_hub.lower()

        is_same_location = (
            u_low == code_low
            or u_low == name_low
            or (u_low == hub_low and (endpoint.get("distance_km", 0) <= 15 or (road_km is not None and road_km <= 15)))
        )
        needs_transfer = not is_same_location

        if not needs_transfer:
            return None

        if road_km is not None and time_str:
            time_formatted = time_str if time_str.startswith("~") else f"~{time_str}"
            desc = f"{'First-mile' if is_origin else 'Last-mile'} road transfer from {from_loc_str} to {to_loc_str}: ~{road_km} km (Estimated: {time_formatted})."
        else:
            time_formatted = None
            desc = f"{'First-mile' if is_origin else 'Last-mile'} road transfer from {from_loc_str} to {to_loc_str}."

        from_code = None if is_origin else endpoint_code
        from_name = clean_user if is_origin else endpoint_name
        to_code = endpoint_code if is_origin else None
        to_name = endpoint_name if is_origin else clean_user

        return {
            "has_transfer": True,
            "transfer_type": "first_mile" if is_origin else "last_mile",
            "from": from_loc_str,
            "to": to_loc_str,
            "from_code": from_code,
            "from_name": from_name,
            "to_code": to_code,
            "to_name": to_name,
            "station_code": endpoint_code,
            "station_name": endpoint_name,
            "transfer_point": f"{from_loc_str} -> {to_loc_str}",
            "hub_city": clean_hub,
            "hub_name": endpoint_name,
            "target_city": clean_user,
            "road_distance_km": road_km,
            "distance_km": road_km,
            "estimated_distance_km": road_km,
            "distance": road_km,
            "duration_minutes": resolved_t.get("duration_minutes"),
            "estimated_transfer_time": time_formatted,
            "estimated_duration": time_formatted,
            "duration": time_formatted,
            "estimated_time": time_formatted,
            "time": time_formatted,
            "transfer_mode": "Cab / Taxi / Bus",
            "source": source_type,
            "notes": f"{'First-mile' if is_origin else 'Last-mile'} road transfer from {from_loc_str} to {to_loc_str}.",
            "description": desc,
        }

    def resolve_and_validate(
        self,
        user_origin: str,
        user_destination: str,
        transport_type: str,
        departure_date: str,
        return_date: Optional[str] = None,
        train_service: Any = None,
        flight_service: Any = None,
        adults: int = 1,
        children: int = 0,
        orig_location: Any = None,
        dest_location: Any = None,
    ) -> Dict[str, Any]:
        from app.services.train.api_tracker import api_tracker
        api_tracker.reset()

        mode = "flight" if "flight" in str(transport_type).lower() else "train"

        # 1. Geocoding / Location context propagation
        if orig_location and getattr(orig_location, "latitude", None) is not None:
            orig_entry = get_location_entry(user_origin) or {}
            orig_geo = {
                "name": getattr(orig_location, "city", None) or getattr(orig_location, "name", None) or user_origin,
                "state": getattr(orig_location, "state", "India"),
                "lat": float(orig_location.latitude),
                "lon": float(orig_location.longitude),
                "is_hilly": bool(getattr(orig_location, "is_hilly", None) or orig_entry.get("is_hilly", False) or (str(getattr(orig_location, "state", "")).strip() in ["Himachal Pradesh", "Uttarakhand", "Jammu and Kashmir", "Ladakh", "Sikkim", "Meghalaya"])),
            }
        else:
            orig_geo = self.geocode_location(user_origin)

        if dest_location and getattr(dest_location, "latitude", None) is not None:
            dest_entry = get_location_entry(user_destination) or {}
            dest_geo = {
                "name": getattr(dest_location, "city", None) or getattr(dest_location, "name", None) or user_destination,
                "state": getattr(dest_location, "state", "India"),
                "lat": float(dest_location.latitude),
                "lon": float(dest_location.longitude),
                "is_hilly": bool(getattr(dest_location, "is_hilly", None) or dest_entry.get("is_hilly", False) or (str(getattr(dest_location, "state", "")).strip() in ["Himachal Pradesh", "Uttarakhand", "Jammu and Kashmir", "Ladakh", "Sikkim", "Meghalaya"])),
            }
        else:
            dest_geo = self.geocode_location(user_destination)

        # 2. Discover candidate endpoints (up to 6 major nearby stations/airports)
        orig_coords = (orig_geo["lat"], orig_geo["lon"]) if orig_geo.get("lat") is not None and orig_geo.get("lon") is not None else None
        dest_coords = (dest_geo["lat"], dest_geo["lon"]) if dest_geo.get("lat") is not None and dest_geo.get("lon") is not None else None

        orig_candidates = self.discover_candidates(user_origin, mode=mode, geo_coords=orig_coords)[:6]
        dest_candidates = self.discover_candidates(user_destination, mode=mode, geo_coords=dest_coords)[:6]

        # 3. Print Required Candidate List Header
        print("\n==================================================")
        print("USER ROUTE")
        print(f"Origin:      {user_origin}")
        print(f"Destination: {user_destination}")
        print(f"Mode:        {mode.upper()}")
        print("\nORIGIN STATION CANDIDATES" if mode == "train" else "\nORIGIN AIRPORT CANDIDATES")
        for idx, c in enumerate(orig_candidates, 1):
            dist_str = f"{c.get('distance_km', 0)} km"
            name_str = f" - {c.get('name')}" if c.get('name') else ""
            print(f"{idx}. {c['code']}{name_str} ({dist_str})")

        print("\nDESTINATION STATION CANDIDATES" if mode == "train" else "\nDESTINATION AIRPORT CANDIDATES")
        for idx, c in enumerate(dest_candidates, 1):
            dist_str = f"{c.get('distance_km', 0)} km"
            name_str = f" - {c.get('name')}" if c.get('name') else ""
            print(f"{idx}. {c['code']}{name_str} ({dist_str})")
        print("==================================================\n")

        # 4. Outbound Connectivity Validation
        # Strategy: Iterate ranked (origin, destination) pairs sequentially.
        # Stop immediately when a valid train is found or providers are unavailable.
        from app.services.train.train_service import (
            TrainServiceError,
            TrainNoAvailabilityError,
            TrainRateLimitedError,
            TrainProviderUnavailableError,
            TrainCircuitOpenError,
            TrainAuthError,
            TrainServerError,
            TrainTimeoutError,
            TrainNetworkError,
        )

        selected_out_orig = None
        selected_out_dest = None
        selected_out_options = []
        ranked_outbound_pairs = self.rank_candidate_pairs(orig_candidates, dest_candidates)
        max_search_attempts = getattr(self, "MAX_OUTBOUND_SEARCH_ATTEMPTS", 18)
        attempts_count = 0
        out_stop_reason = "NO_RESULTS"

        for orig_c, dest_c, score in ranked_outbound_pairs:
            if attempts_count >= max_search_attempts:
                if not out_stop_reason or out_stop_reason == "NO_RESULTS":
                    out_stop_reason = "MAX_ATTEMPTS_REACHED"
                break
            orig_code = orig_c["code"]
            dest_code = dest_c["code"]
            attempts_count += 1

            options = []
            try:
                if mode == "train":
                    options = train_service.search_trains(
                        from_code=orig_code,
                        to_code=dest_code,
                        date=departure_date,
                    )
                else:
                    from app.services.flight.flight_schema import FlightSearchRequest
                    freq = FlightSearchRequest(
                        from_code=orig_code,
                        to_code=dest_code,
                        date=date.fromisoformat(departure_date) if isinstance(departure_date, str) else departure_date,
                        adults=adults,
                        children=children,
                    )
                    options = flight_service.search_flights(freq)
            except TrainNoAvailabilityError:
                options = []
                if out_stop_reason == "NO_RESULTS":
                    out_stop_reason = "NO_RESULTS"
            except TrainRateLimitedError:
                logger.warning("Outbound candidate %s->%s rate limited", orig_code, dest_code)
                out_stop_reason = "RATE_LIMITED"
                options = []
            except TrainCircuitOpenError:
                logger.warning("Outbound candidate %s->%s circuit open", orig_code, dest_code)
                out_stop_reason = "CIRCUIT_OPEN"
                options = []
            except TrainAuthError:
                logger.warning("Outbound candidate %s->%s auth error", orig_code, dest_code)
                out_stop_reason = "AUTH_ERROR"
                options = []
            except TrainServerError:
                logger.warning("Outbound candidate %s->%s server error", orig_code, dest_code)
                out_stop_reason = "SERVER_ERROR"
                options = []
            except TrainTimeoutError:
                logger.warning("Outbound candidate %s->%s timeout", orig_code, dest_code)
                out_stop_reason = "TIMEOUT"
                options = []
            except TrainNetworkError:
                logger.warning("Outbound candidate %s->%s network error", orig_code, dest_code)
                out_stop_reason = "NETWORK_ERROR"
                options = []
            except TrainProviderUnavailableError as err:
                logger.warning("Outbound candidate %s->%s provider unavailable (%s)", orig_code, dest_code, err)
                out_stop_reason = "PROVIDER_UNAVAILABLE"
                options = []
            except Exception as err:
                logger.debug("Outbound candidate search error for %s->%s: %s", orig_code, dest_code, err)
                options = []

            if options:
                out_stop_reason = "VALID_TRAIN_FOUND"
                first_opt = options[0]
                selected_out_orig, selected_out_dest = self._extract_option_endpoints(
                    first_opt, default_orig_c=orig_c, default_dest_c=dest_c, is_flight=(mode != "train")
                )
                selected_out_options = options
                print("\nVALID TRAIN FOUND")
                print("SEARCH STOPPED")
                print("SELECTED ROUTE:")
                print(f"{orig_code} -> {dest_code}\n")
                break

        # Result validity contract: if no live train found, selected options and endpoints MUST remain None/empty
        live_out_found = bool(selected_out_options and out_stop_reason == "VALID_TRAIN_FOUND")
        if not live_out_found:
            selected_out_orig = None
            selected_out_dest = None
            selected_out_options = []

        # Attach fare options ONLY for the final selected outbound journey
        if mode == "train" and selected_out_options and selected_out_orig and selected_out_dest and hasattr(train_service, "attach_fares_to_selected_trains"):
            try:
                fares_res = train_service.attach_fares_to_selected_trains(
                    trains=selected_out_options,
                    from_code=selected_out_orig["code"],
                    to_code=selected_out_dest["code"],
                    date=departure_date,
                )
                if isinstance(fares_res, list):
                    selected_out_options = fares_res
            except Exception as err:
                logger.debug(f"Outbound fare attachment failed: {err}")

        # Log concise outbound search summary (Authoritative Single Source of Truth)
        out_first_t = selected_out_options[0] if selected_out_options else None
        out_t_name = getattr(out_first_t, "train_name", None) or (out_first_t.get("train_name") if isinstance(out_first_t, dict) else "") or getattr(out_first_t, "flight_name", None) or (out_first_t.get("flight_name") if isinstance(out_first_t, dict) else "") or getattr(out_first_t, "name", "") or ""
        out_t_num = getattr(out_first_t, "train_number", None) or (out_first_t.get("train_number") if isinstance(out_first_t, dict) else "") or getattr(out_first_t, "flight_number", None) or (out_first_t.get("flight_number") if isinstance(out_first_t, dict) else "") or ""
        out_t_label = f"{out_t_name} / {out_t_num}".strip(" /") if (live_out_found and (out_t_name or out_t_num)) else "None"
        out_route_str = f"{selected_out_orig['code']} -> {selected_out_dest['code']}" if (live_out_found and selected_out_orig and selected_out_dest) else "None"

        print("==================================================")
        print("OUTBOUND SEARCH SUMMARY")
        print(f"Candidate station pairs considered: {len(ranked_outbound_pairs)}")
        print(f"API requests executed: {attempts_count}")
        print(f"Search stop reason: {out_stop_reason}")
        print(f"Valid train found: {'YES' if live_out_found else 'NO'}")
        print(f"Selected route: {out_route_str}")
        print(f"Selected train: {out_t_label}")
        print("==================================================\n")

        # 5. Return Connectivity Validation (Independent Direction Resolution)
        selected_ret_orig = None
        selected_ret_dest = None
        selected_ret_options = []
        ranked_return_pairs = self.rank_return_candidate_pairs(
            dest_candidates, orig_candidates, selected_out_orig=selected_out_orig, selected_out_dest=selected_out_dest
        )
        return_pairs_tried = []
        ret_stop_reason = "NO_RESULTS"
        ret_attempts_count = 0
        ret_max_search_attempts = getattr(self, "MAX_RETURN_SEARCH_ATTEMPTS", 8)

        if return_date:
            for r_orig_c, r_dest_c, score in ranked_return_pairs:
                if selected_ret_options:
                    ret_stop_reason = "VALID_TRAIN_FOUND"
                    break
                if ret_attempts_count >= ret_max_search_attempts:
                    if not ret_stop_reason or ret_stop_reason == "NO_RESULTS":
                        ret_stop_reason = "MAX_ATTEMPTS_REACHED"
                    break
                r_orig_code = r_orig_c["code"]
                r_dest_code = r_dest_c["code"]
                ret_attempts_count += 1
                return_pairs_tried.append((r_orig_c, r_dest_c))

                r_options = []
                try:
                    if mode == "train":
                        r_options = train_service.search_trains(
                            from_code=r_orig_code,
                            to_code=r_dest_code,
                            date=return_date,
                        )
                    else:
                        from app.services.flight.flight_schema import FlightSearchRequest
                        freq = FlightSearchRequest(
                            from_code=r_orig_code,
                            to_code=r_dest_code,
                            date=date.fromisoformat(return_date) if isinstance(return_date, str) else return_date,
                            adults=adults,
                            children=children,
                        )
                        r_options = flight_service.search_flights(freq)
                except TrainNoAvailabilityError:
                    r_options = []
                    if not selected_ret_options:
                        ret_stop_reason = "NO_RESULTS"
                except TrainRateLimitedError:
                    logger.warning("Return candidate %s->%s rate limited", r_orig_code, r_dest_code)
                    if not selected_ret_options:
                        ret_stop_reason = "RATE_LIMITED"
                    r_options = []
                except TrainCircuitOpenError:
                    logger.warning("Return candidate %s->%s circuit open", r_orig_code, r_dest_code)
                    if not selected_ret_options:
                        ret_stop_reason = "CIRCUIT_OPEN"
                    r_options = []
                except TrainAuthError:
                    logger.warning("Return candidate %s->%s auth error", r_orig_code, r_dest_code)
                    if not selected_ret_options:
                        ret_stop_reason = "AUTH_ERROR"
                    r_options = []
                except TrainServerError:
                    logger.warning("Return candidate %s->%s server error", r_orig_code, r_dest_code)
                    if not selected_ret_options:
                        ret_stop_reason = "SERVER_ERROR"
                    r_options = []
                except TrainTimeoutError:
                    logger.warning("Return candidate %s->%s timeout", r_orig_code, r_dest_code)
                    if not selected_ret_options:
                        ret_stop_reason = "TIMEOUT"
                    r_options = []
                except TrainNetworkError:
                    logger.warning("Return candidate %s->%s network error", r_orig_code, r_dest_code)
                    if not selected_ret_options:
                        ret_stop_reason = "NETWORK_ERROR"
                    r_options = []
                except TrainProviderUnavailableError as err:
                    logger.warning("Return candidate %s->%s provider unavailable (%s)", r_orig_code, r_dest_code, err)
                    if not selected_ret_options:
                        ret_stop_reason = "PROVIDER_UNAVAILABLE"
                    r_options = []
                except Exception as err:
                    logger.debug("Return candidate search error for %s->%s: %s", r_orig_code, r_dest_code, err)
                    r_options = []

                if r_options:
                    ret_stop_reason = "VALID_TRAIN_FOUND"
                    first_ret = r_options[0]
                    selected_ret_orig, selected_ret_dest = self._extract_option_endpoints(
                        first_ret, default_orig_c=r_orig_c, default_dest_c=r_dest_c, is_flight=(mode != "train")
                    )
                    selected_ret_options = r_options
                    ret_num = getattr(first_ret, "train_number", None) or (first_ret.get("train_number") if isinstance(first_ret, dict) else "") or getattr(first_ret, "flight_number", None) or (first_ret.get("flight_number") if isinstance(first_ret, dict) else "") or ""
                    ret_name = getattr(first_ret, "train_name", None) or (first_ret.get("train_name") if isinstance(first_ret, dict) else "") or getattr(first_ret, "flight_name", None) or (first_ret.get("flight_name") if isinstance(first_ret, dict) else "") or getattr(first_ret, "name", "") or ""
                    ret_label = f"{ret_num} {ret_name}".strip()
                    print(f"\nRETURN VALID TRAIN FOUND:\n{ret_label}")
                    print(f"RETURN SELECTED ROUTE:\n{r_orig_code} -> {r_dest_code}")
                    print("RETURN SEARCH STOPPED:\nVALID_TRAIN_FOUND\n")
                    break

            live_ret_found = bool(selected_ret_options)
            if live_ret_found:
                ret_stop_reason = "VALID_TRAIN_FOUND"
            else:
                selected_ret_orig = None
                selected_ret_dest = None
                selected_ret_options = []

            # Attach fare options ONLY for the final selected return journey
            if mode == "train" and selected_ret_options and selected_ret_orig and selected_ret_dest and hasattr(train_service, "attach_fares_to_selected_trains"):
                try:
                    fares_res = train_service.attach_fares_to_selected_trains(
                        trains=selected_ret_options,
                        from_code=selected_ret_orig["code"],
                        to_code=selected_ret_dest["code"],
                        date=return_date,
                    )
                    if isinstance(fares_res, list) and fares_res:
                        selected_ret_options = fares_res
                except Exception as err:
                    logger.debug(f"Return fare attachment failed: {err}")

            # Log concise return search summary (Authoritative Single Source of Truth)
            ret_first_t = selected_ret_options[0] if selected_ret_options else None
            ret_t_name = getattr(ret_first_t, "train_name", None) or (ret_first_t.get("train_name") if isinstance(ret_first_t, dict) else "") or getattr(ret_first_t, "flight_name", None) or (ret_first_t.get("flight_name") if isinstance(ret_first_t, dict) else "") or getattr(ret_first_t, "name", "") or ""
            ret_t_num = getattr(ret_first_t, "train_number", None) or (ret_first_t.get("train_number") if isinstance(ret_first_t, dict) else "") or getattr(ret_first_t, "flight_number", None) or (ret_first_t.get("flight_number") if isinstance(ret_first_t, dict) else "") or ""
            ret_t_label = f"{ret_t_name} / {ret_t_num}".strip(" /") if (ret_t_name or ret_t_num) else "None"
            ret_route_str = f"{selected_ret_orig['code']} -> {selected_ret_dest['code']}" if (selected_ret_orig and selected_ret_dest) else "None"

            ret_fare_val = 0
            if ret_first_t:
                f_obj = ret_first_t.get("fare") if isinstance(ret_first_t, dict) else getattr(ret_first_t, "fare", None)
                if isinstance(f_obj, dict):
                    ret_fare_val = f_obj.get("amount") or 0
                elif hasattr(f_obj, "amount"):
                    ret_fare_val = getattr(f_obj, "amount", 0) or 0
                if not ret_fare_val:
                    fares_list = ret_first_t.get("fares") if isinstance(ret_first_t, dict) else getattr(ret_first_t, "fares", None)
                    if isinstance(fares_list, list) and fares_list:
                        item0 = fares_list[0]
                        ret_fare_val = (item0.get("amount") if isinstance(item0, dict) else getattr(item0, "amount", 0)) or 0

            print("==================================================")
            print("RETURN SEARCH SUMMARY")
            print(f"Candidate station pairs considered: {len(ranked_return_pairs)}")
            print(f"API requests executed: {ret_attempts_count}")
            print(f"Search stop reason: {ret_stop_reason}")
            print(f"Valid return train found: {'YES' if live_ret_found else 'NO'}")
            print(f"Selected route: {ret_route_str}")
            print(f"Selected train: {ret_t_label}")
            print(f"RETURN FARE: {ret_fare_val}")
            print("==================================================\n")

        # 6. Create Separate First-Mile and Last-Mile Transfers (Fault Isolated)
        outbound_orig_transfer = None
        outbound_dest_transfer = None
        return_orig_transfer = None
        return_dest_transfer = None

        if live_out_found and selected_out_orig and selected_out_dest:
            try:
                outbound_orig_transfer = self.create_transfer_info(
                    user_origin, selected_out_orig, orig_geo, is_origin=True, mode=mode
                )
            except Exception as exc:
                logger.warning("First-mile outbound transfer resolution failed (keeping train): %s", exc)

            try:
                outbound_dest_transfer = self.create_transfer_info(
                    user_destination, selected_out_dest, dest_geo, is_origin=False, mode=mode
                )
            except Exception as exc:
                logger.warning("Last-mile outbound transfer resolution failed (keeping train): %s", exc)

        if return_date and live_ret_found and selected_ret_orig and selected_ret_dest and selected_ret_options:
            try:
                return_orig_transfer = self.create_transfer_info(
                    user_destination, selected_ret_orig, dest_geo, is_origin=True, mode=mode
                )
            except Exception as exc:
                logger.warning("First-mile return transfer resolution failed (keeping return transport): %s", exc)

            try:
                return_dest_transfer = self.create_transfer_info(
                    user_origin, selected_ret_dest, orig_geo, is_origin=False, mode=mode
                )
            except Exception as exc:
                logger.warning("Last-mile return transfer resolution failed (keeping return transport): %s", exc)

        # 7. Print Structured Debug Logs (Mandatory Format - Fault Isolated)
        try:
            self._log_debug_trace(
                user_origin=user_origin,
                user_destination=user_destination,
                orig_geo=orig_geo,
                dest_geo=dest_geo,
                mode=mode,
                orig_candidates=orig_candidates,
                dest_candidates=dest_candidates,
                ranked_pairs=ranked_outbound_pairs,
                selected_out_orig=selected_out_orig,
                selected_out_dest=selected_out_dest,
                selected_out_options=selected_out_options,
                outbound_orig_transfer=outbound_orig_transfer,
                outbound_dest_transfer=outbound_dest_transfer,
                selected_ret_orig=selected_ret_orig,
                selected_ret_dest=selected_ret_dest,
                selected_ret_options=selected_ret_options,
                return_orig_transfer=return_orig_transfer,
                return_dest_transfer=return_dest_transfer,
                return_date=return_date,
                return_pairs_tried=return_pairs_tried,
                ret_stop_reason=ret_stop_reason,
            )
        except Exception as err:
            logger.warning("Structured transport debug logging failed: %s", err)

        # Determine canonical transport status
        if live_out_found:
            transport_status = "AVAILABLE"
        elif out_stop_reason in ("RATE_LIMITED", "CIRCUIT_OPEN"):
            transport_status = "RATE_LIMITED"
        elif out_stop_reason in ("SERVER_ERROR", "PROVIDER_ERROR"):
            transport_status = "PROVIDER_ERROR"
        elif out_stop_reason in ("TIMEOUT", "NETWORK_ERROR"):
            transport_status = "NETWORK_ERROR"
        elif out_stop_reason == "NO_RESULTS":
            transport_status = "NO_RESULTS"
        else:
            transport_status = "PROVIDER_UNAVAILABLE"

        # 8. Return Canonical Result Structure
        return {
            "user_origin": user_origin,
            "user_destination": user_destination,
            "mode": mode,
            "origin_transport_endpoint": selected_out_orig,
            "destination_transport_endpoint": selected_out_dest,
            "actual_train_origin": f"{selected_out_orig.get('name')} ({selected_out_orig.get('code')})" if (selected_out_orig and selected_out_orig.get("name") != selected_out_orig.get("code")) else (selected_out_orig.get("code") if selected_out_orig else None),
            "actual_train_destination": f"{selected_out_dest.get('name')} ({selected_out_dest.get('code')})" if (selected_out_dest and selected_out_dest.get("name") != selected_out_dest.get("code")) else (selected_out_dest.get("code") if selected_out_dest else None),
            "first_mile_transfer": outbound_orig_transfer,
            "last_mile_transfer": outbound_dest_transfer,
            "outbound_transfer": outbound_dest_transfer or outbound_orig_transfer,
            "return_first_mile_transfer": return_orig_transfer,
            "return_last_mile_transfer": return_dest_transfer,
            "return_transfer": return_orig_transfer or return_dest_transfer,
            "return_actual_train_origin": f"{selected_ret_orig.get('name')} ({selected_ret_orig.get('code')})" if (selected_ret_orig and selected_ret_orig.get("name") != selected_ret_orig.get("code")) else (selected_ret_orig.get("code") if selected_ret_orig else None),
            "return_actual_train_destination": f"{selected_ret_dest.get('name')} ({selected_ret_dest.get('code')})" if (selected_ret_dest and selected_ret_dest.get("name") != selected_ret_dest.get("code")) else (selected_ret_dest.get("code") if selected_ret_dest else None),
            "outbound_options": selected_out_options,
            "return_options": selected_ret_options,
            "return_origin_transport_endpoint": selected_ret_orig,
            "return_destination_transport_endpoint": selected_ret_dest,
            "outbound_status": out_stop_reason,
            "return_status": ret_stop_reason if return_date else None,
            "transport_status": transport_status,
        }

    def _log_debug_trace(
        self,
        user_origin: str,
        user_destination: str,
        orig_geo: Dict[str, Any],
        dest_geo: Dict[str, Any],
        mode: str,
        orig_candidates: List[Dict[str, Any]],
        dest_candidates: List[Dict[str, Any]],
        ranked_pairs: List[Tuple[Dict[str, Any], Dict[str, Any], float]],
        selected_out_orig: Optional[Dict[str, Any]],
        selected_out_dest: Optional[Dict[str, Any]],
        selected_out_options: List[Any],
        outbound_orig_transfer: Optional[Dict[str, Any]] = None,
        outbound_dest_transfer: Optional[Dict[str, Any]] = None,
        selected_ret_orig: Optional[Dict[str, Any]] = None,
        selected_ret_dest: Optional[Dict[str, Any]] = None,
        selected_ret_options: Optional[List[Any]] = None,
        return_orig_transfer: Optional[Dict[str, Any]] = None,
        return_dest_transfer: Optional[Dict[str, Any]] = None,
        return_date: Optional[str] = None,
        return_pairs_tried: Optional[List[str]] = None,
        ret_stop_reason: Optional[str] = None,
    ):
        """Prints mandatory structured debug output."""
        selected_ret_options = selected_ret_options or []
        outbound_transfer = outbound_dest_transfer or outbound_orig_transfer
        out_trans = outbound_transfer
        return_transfer = return_orig_transfer or return_dest_transfer
        ret_trans = return_transfer

        first_opt = selected_out_options[0] if selected_out_options else {}
        t_num = getattr(first_opt, "train_number", getattr(first_opt, "flight_number", first_opt.get("train_number") if isinstance(first_opt, dict) else ""))
        t_name = getattr(first_opt, "train_name", getattr(first_opt, "airline", first_opt.get("train_name") if isinstance(first_opt, dict) else ""))
        sel_train_str = f"{t_num} {t_name}".strip() if (t_num or t_name) else "None"

        first_ret = selected_ret_options[0] if selected_ret_options else {}
        r_num = getattr(first_ret, "train_number", getattr(first_ret, "flight_number", first_ret.get("train_number") if isinstance(first_ret, dict) else ""))
        r_name = getattr(first_ret, "train_name", getattr(first_ret, "airline", first_ret.get("train_name") if isinstance(first_ret, dict) else ""))
        sel_ret_str = f"{r_num} {r_name}".strip() if (r_num or r_name) else "None"

        out_orig_disp = f"{selected_out_orig.get('name')} ({selected_out_orig.get('code')})" if (selected_out_orig and selected_out_orig.get("name") != selected_out_orig.get("code")) else (selected_out_orig.get("code") if selected_out_orig else "N/A")
        out_dest_disp = f"{selected_out_dest.get('name')} ({selected_out_dest.get('code')})" if (selected_out_dest and selected_out_dest.get("name") != selected_out_dest.get("code")) else (selected_out_dest.get("code") if selected_out_dest else "N/A")

        ret_orig_disp = f"{selected_ret_orig.get('name')} ({selected_ret_orig.get('code')})" if selected_ret_orig and selected_ret_orig.get("name") != selected_ret_orig.get("code") else (selected_ret_orig.get("code") if selected_ret_orig else "N/A")
        ret_dest_disp = f"{selected_ret_dest.get('name')} ({selected_ret_dest.get('code')})" if selected_ret_dest and selected_ret_dest.get("name") != selected_ret_dest.get("code") else (selected_ret_dest.get("code") if selected_ret_dest else "N/A")

        orig_codes = [f"{c['code']}" + (f" - {c['name']}" if c.get('name') else "") + f" ({c.get('distance_km', 0)}km)" for c in orig_candidates]
        dest_codes = [f"{c['code']}" + (f" - {c['name']}" if c.get('name') else "") + f" ({c.get('distance_km', 0)}km)" for c in dest_candidates]

        print("\n================================================================================")
        print("                      STRUCTURED TRANSPORT DEBUG LOGS")
        print("================================================================================")
        print(f"User origin:              {user_origin}")
        print(f"Candidate origin stations: {', '.join(orig_codes)}")
        print(f"Selected train:           {sel_train_str}")
        print(f"Actual train origin:      {out_orig_disp}")
        print(f"Actual train destination: {out_dest_disp}")
        print(f"User destination:         {user_destination}")
        if out_trans and out_trans.get("has_transfer"):
            print(f"Outbound transfer:        {out_trans.get('from')} -> {out_trans.get('to')} (~{out_trans.get('road_distance_km')} km, {out_trans.get('estimated_transfer_time')})")
        else:
            print("Outbound transfer:        None")
        print(f"Return train origin:      {ret_orig_disp}")
        print(f"Return train destination: {ret_dest_disp}")
        print("Transfer distances:")
        if outbound_orig_transfer and outbound_orig_transfer.get("has_transfer"):
            print(f"  - First-mile (Outbound): {outbound_orig_transfer.get('from')} -> {outbound_orig_transfer.get('to')}: ~{outbound_orig_transfer.get('road_distance_km')} km ({outbound_orig_transfer.get('estimated_transfer_time')}) [Source: {outbound_orig_transfer.get('source')}]")
        if outbound_dest_transfer and outbound_dest_transfer.get("has_transfer"):
            print(f"  - Last-mile (Outbound):  {outbound_dest_transfer.get('from')} -> {outbound_dest_transfer.get('to')}: ~{outbound_dest_transfer.get('road_distance_km')} km ({outbound_dest_transfer.get('estimated_transfer_time')}) [Source: {outbound_dest_transfer.get('source')}]")
        if return_orig_transfer and return_orig_transfer.get("has_transfer"):
            print(f"  - First-mile (Return):   {return_orig_transfer.get('from')} -> {return_orig_transfer.get('to')}: ~{return_orig_transfer.get('road_distance_km')} km ({return_orig_transfer.get('estimated_transfer_time')}) [Source: {return_orig_transfer.get('source')}]")
        if return_dest_transfer and return_dest_transfer.get("has_transfer"):
            print(f"  - Last-mile (Return):    {return_dest_transfer.get('from')} -> {return_dest_transfer.get('to')}: ~{return_dest_transfer.get('road_distance_km')} km ({return_dest_transfer.get('estimated_transfer_time')}) [Source: {return_dest_transfer.get('source')}]")
        if not (outbound_orig_transfer and outbound_orig_transfer.get("has_transfer")) and not (outbound_dest_transfer and outbound_dest_transfer.get("has_transfer")) and not (return_orig_transfer and return_orig_transfer.get("has_transfer")) and not (return_dest_transfer and return_dest_transfer.get("has_transfer")):
            print("  None")
        print("================================================================================\n")
        print("\n==================================================")
        print("USER LOCATION")
        print(f"Origin: {user_origin} | Destination: {user_destination}")
        print("==================================================")
        print("GEOCODED LOCATION")
        print(f"Origin: {orig_geo['name']} (Lat: {orig_geo['lat']}, Lon: {orig_geo['lon']}, Hilly: {orig_geo['is_hilly']})")
        print(f"Destination: {dest_geo['name']} (Lat: {dest_geo['lat']}, Lon: {dest_geo['lon']}, Hilly: {dest_geo['is_hilly']})")
        print("==================================================")
        print(f"CANDIDATE ENDPOINTS ({mode.upper()})")
        orig_codes = [f"{c['code']} ({c.get('distance_km', 0)}km)" for c in orig_candidates]
        dest_codes = [f"{c['code']} ({c.get('distance_km', 0)}km)" for c in dest_candidates]
        print(f"Origin Candidates: {', '.join(orig_codes)}")
        print(f"Destination Candidates: {', '.join(dest_codes)}")
        print("==================================================")
        print("RANKED ENDPOINTS")
        for idx, (o, d, s) in enumerate(ranked_pairs[:4], 1):
            print(f"[{idx}] {o['code']} -> {d['code']} (Score: {s}, Major: {o.get('is_major')}/{d.get('is_major')})")
        print("==================================================")
        print("SELECTED ENDPOINT")
        if selected_out_orig and selected_out_dest:
            print(f"Outbound: {selected_out_orig.get('name')} ({selected_out_orig.get('code')}) -> {selected_out_dest.get('name')} ({selected_out_dest.get('code')})")
        else:
            print("Outbound: None")
        if selected_ret_orig and selected_ret_dest and selected_ret_options:
            print(f"Return: {selected_ret_orig.get('name')} ({selected_ret_orig.get('code')}) -> {selected_ret_dest.get('name')} ({selected_ret_dest.get('code')})")
        else:
            print("Return: None")
        print("==================================================")
        print("ACTUAL TRANSPORT ROUTE")
        if selected_out_options and selected_out_orig and selected_out_dest:
            first_opt = selected_out_options[0]
            num_or_name = getattr(first_opt, "train_number", getattr(first_opt, "flight_number", "DIRECT"))
            name = getattr(first_opt, "train_name", getattr(first_opt, "airline", ""))
            print(f"Outbound Route: {selected_out_orig['code']} -> {selected_out_dest['code']} ({num_or_name} {name}) [{len(selected_out_options)} options found]")
        else:
            print("Outbound Route: None [Unavailable / No direct options]")
        if selected_ret_options and selected_ret_orig and selected_ret_dest:
            r_orig_code = selected_ret_orig.get("code", "N/A")
            r_dest_code = selected_ret_dest.get("code", "N/A")
            first_ret = selected_ret_options[0]
            num_or_name = getattr(first_ret, "train_number", getattr(first_ret, "flight_number", "DIRECT"))
            name = getattr(first_ret, "train_name", getattr(first_ret, "airline", ""))
            print(f"Return Route: {r_orig_code} -> {r_dest_code} ({num_or_name} {name}) [{len(selected_ret_options)} options found]")
        else:
            print("Return Route: None [Unavailable / No direct options]")
        print("==================================================")
        print("TRANSFER REQUIRED/NOT REQUIRED")
        if outbound_transfer and outbound_transfer.get("has_transfer"):
            print(f"Outbound Transfer REQUIRED: {outbound_transfer.get('from')} -> {outbound_transfer.get('to')} (Road: {outbound_transfer.get('road_distance_km')} km, Time: {outbound_transfer.get('estimated_transfer_time')})")
        else:
            print("Outbound Transfer: NOT REQUIRED")

        if return_transfer and return_transfer.get("has_transfer"):
            print(f"Return Transfer REQUIRED: {return_transfer.get('from')} -> {return_transfer.get('to')} (Road: {return_transfer.get('road_distance_km')} km, Time: {return_transfer.get('estimated_transfer_time')})")

        print("\n==================================================")
        print("RETURN TRANSPORT RESOLUTION")
        print(f"User return route:                     {user_destination} -> {user_origin}")
        print(f"Return date:                           {return_date or 'N/A'}")
        print(f"Candidate return origin stations:      {', '.join(dest_codes)}")
        ret_pairs_str = [f"{p[0]['code']} -> {p[1]['code']}" if isinstance(p, tuple) else str(p) for p in (return_pairs_tried or [])]
        print(f"Return route candidates tried:         {', '.join(ret_pairs_str) if ret_pairs_str else 'None'}")
        if selected_ret_options and selected_ret_orig and selected_ret_dest:
            first_ret = selected_ret_options[0]
            r_num = getattr(first_ret, "train_number", getattr(first_ret, "flight_number", ""))
            r_name = getattr(first_ret, "train_name", getattr(first_ret, "airline", ""))
            r_orig_c = selected_ret_orig.get("code") if isinstance(selected_ret_orig, dict) else "N/A"
            r_dest_c = selected_ret_dest.get("code") if isinstance(selected_ret_dest, dict) else "N/A"
            print(f"Selected return transport:             {r_num} {r_name}".strip())
            print(f"Actual return route:                   {r_orig_c} -> {r_dest_c}")
            print(f"Return status:                         Available ({len(selected_ret_options)} options)")
        else:
            print("Selected return transport:             None")
            print("Actual return route:                   None")

            # The outbound endpoint can intentionally be called without a
            # return_date because return transport is searched separately.
            # Do not report that as "No direct trains found".
            if not return_date:
                status_msg = "Not requested in this search"
            elif ret_stop_reason == "RATE_LIMITED":
                status_msg = "Provider unavailable (Rate limited)"
            elif ret_stop_reason == "CIRCUIT_OPEN":
                status_msg = "Provider unavailable (Circuit breaker open)"
            elif ret_stop_reason == "AUTH_ERROR":
                status_msg = "Provider unavailable (Auth error)"
            elif ret_stop_reason == "SERVER_ERROR":
                status_msg = "Provider unavailable (Server error)"
            elif ret_stop_reason == "TIMEOUT":
                status_msg = "Provider unavailable (Timeout)"
            elif ret_stop_reason == "NETWORK_ERROR":
                status_msg = "Provider unavailable (Network error)"
            elif ret_stop_reason == "PROVIDER_UNAVAILABLE":
                status_msg = "Provider unavailable"
            elif ret_stop_reason in ("NO_RESULTS", "NO_AVAILABILITY", "MAX_ATTEMPTS_REACHED"):
                status_msg = "No direct trains found"
            else:
                status_msg = "Unavailable"

            print(f"Return status:                         {status_msg}")

        if return_transfer and return_transfer.get("has_transfer"):
            print(f"Return transfer:                       {return_transfer.get('from')} -> {return_transfer.get('to')}")
        else:
            print("Return transfer:                       None")
        print("==================================================\n")

        print("\n==================================================")
        print("TRANSFER RESOLUTION")
        if outbound_transfer and outbound_transfer.get("has_transfer"):
            print("\nOutbound:")
            print(f"{outbound_transfer.get('from')} -> {outbound_transfer.get('to')}")
            print(f"Distance source: {outbound_transfer.get('source', 'existing')}")
            print(f"Distance: {outbound_transfer.get('road_distance_km')} km")
            print(f"Duration: {outbound_transfer.get('estimated_transfer_time')}")
        else:
            print("\nOutbound:\nNone")

        if return_transfer and return_transfer.get("has_transfer"):
            print("\nReturn:")
            print(f"{return_transfer.get('from')} -> {return_transfer.get('to')}")
            print(f"Distance source: {return_transfer.get('source', 'existing')}")
            print(f"Distance: {return_transfer.get('road_distance_km')} km")
            print(f"Duration: {return_transfer.get('estimated_transfer_time')}")
        else:
            print("\nReturn:\nNone")
        print("==================================================\n")

        from app.services.train.api_tracker import api_tracker
        api_tracker.print_summary()

    def _generate_scheduled_option(
        self,
        orig: Dict[str, Any],
        dest: Dict[str, Any],
        dep_date: str,
        mode: str = "train",
    ) -> Dict[str, Any]:
        """Disabled: transport options must come from live providers.

        This method previously fabricated train/flight numbers, schedules and
        fares. Keeping it as a hard failure prevents accidental use of
        synthetic transport data in production planning.
        """
        raise RuntimeError(
            "Synthetic transport generation is disabled. "
            "Use the live transport provider through TrainService/FlightService."
        )

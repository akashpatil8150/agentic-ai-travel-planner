import logging
import re
from datetime import date as date_type

from dateutil.relativedelta import relativedelta

from app.services.train.railradar_client import (
    RailRadarClient,
    RailRadarError,
    RailRadarRateLimitedError,
    RailRadarAuthError,
    RailRadarServerError,
    RailRadarTimeoutError,
    RailRadarNetworkError,
    RailRadarCircuitOpenError,
)
from app.services.train.railcore_client import (
    RailCoreClient,
    RailCoreError,
    RailCoreRateLimitedError,
    RailCoreAuthError,
    RailCoreServerError,
    RailCoreTimeoutError,
    RailCoreNetworkError,
    RailCoreCircuitOpenError,
)

from app.services.train.train_normalizer import (
    normalize_railradar_train,
    normalize_railcore_train,
    normalize_train_details,
)

from app.services.train.train_schema import (
    Station,
    TrainFare,
    TrainResponse,
)
from app.services.train.api_tracker import api_tracker
from app.services.train.exact_transport_cache import exact_transport_cache
from app.resolvers.india_locations import (
    get_canonical_station_code,
    is_same_station,
)
from typing import Optional, Tuple, Any, List, Dict


logger = logging.getLogger(__name__)


# ============================================================
# CUSTOM SERVICE ERRORS
# ============================================================

class TrainServiceError(Exception):
    """Base exception for train service operations."""

class TrainNoAvailabilityError(TrainServiceError):
    """
    Providers responded successfully with HTTP 200,
    but no train was available for the route/date.
    """

class TrainRateLimitedError(TrainServiceError):
    """Raised when providers return HTTP 429 (Rate Limited)."""

class TrainAuthError(TrainServiceError):
    """Raised when provider authentication fails (HTTP 401/403)."""

class TrainServerError(TrainServiceError):
    """Raised when providers return HTTP 5xx."""

class TrainTimeoutError(TrainServiceError):
    """Raised when provider requests time out."""

class TrainNetworkError(TrainServiceError):
    """Raised when providers cannot be reached."""

class TrainCircuitOpenError(TrainServiceError):
    """Raised when provider circuit breaker is active."""

class TrainProviderUnavailableError(TrainServiceError):
    """
    Providers were unable to provide a usable response
    due to rate limiting, server error, timeout, or network failure.
    """


class TrainService:

    def __init__(self):

        self.railradar = RailRadarClient()

        self.railcore = RailCoreClient()

    # ============================================================
    # STATION CODE VALIDATION
    # ============================================================

    def _validate_station_codes(
        self,
        from_code: str,
        to_code: str,
    ):

        if not from_code or not str(
            from_code
        ).strip():

            raise ValueError(
                "Source station code is required."
            )

        if not to_code or not str(
            to_code
        ).strip():

            raise ValueError(
                "Destination station code is required."
            )

        from_code = str(
            from_code
        ).strip().upper()

        to_code = str(
            to_code
        ).strip().upper()

        if not re.fullmatch(
            r"[A-Z]{2,5}",
            from_code
        ):

            raise ValueError(
                "Invalid source station code. "
                "Use 2 to 5 alphabetic characters."
            )

        if not re.fullmatch(
            r"[A-Z]{2,5}",
            to_code
        ):

            raise ValueError(
                "Invalid destination station code. "
                "Use 2 to 5 alphabetic characters."
            )

        if from_code == to_code or is_same_station(from_code, to_code):

            raise ValueError(
                "Source and destination stations "
                "cannot be the same."
            )

        return from_code, to_code

    # ============================================================
    # QUOTA VALIDATION
    # ============================================================

    def _validate_quota_code(
        self,
        quota_code: str,
    ) -> str:

        if not quota_code or not str(
            quota_code
        ).strip():

            raise ValueError(
                "Quota code is required."
            )

        quota_code = str(
            quota_code
        ).strip().upper()

        if not re.fullmatch(
            r"[A-Z0-9]{2,5}",
            quota_code
        ):

            raise ValueError(
                "Invalid quota code. "
                "Use 2 to 5 letters or numbers."
            )

        return quota_code

    # ============================================================
    # CLASS VALIDATION
    # ============================================================

    def _validate_class_code(
        self,
        class_code: str,
    ) -> str:

        if not class_code or not str(
            class_code
        ).strip():

            raise ValueError(
                "Class code is required."
            )

        class_code = str(
            class_code
        ).strip().upper()

        if not re.fullmatch(
            r"[A-Z0-9]{2,4}",
            class_code
        ):

            raise ValueError(
                "Invalid class code. "
                "Use 2 to 4 letters or numbers."
            )

        return class_code

    # ============================================================
    # TRAIN NUMBER VALIDATION
    # ============================================================

    def _validate_train_number(
        self,
        train_number: str,
    ) -> str:

        if not train_number or not str(
            train_number
        ).strip():

            raise ValueError(
                "Train number is required."
            )

        train_number = str(
            train_number
        ).strip()

        if not re.fullmatch(
            r"\d{4,6}",
            train_number
        ):

            raise ValueError(
                "Invalid train number. "
                "Use 4 to 6 digits."
            )

        return train_number

    # ============================================================
    # JOURNEY DATE VALIDATION
    # ============================================================

    def _validate_journey_date(
        self,
        journey_date: str,
    ):

        try:

            requested_date = (
                date_type.fromisoformat(
                    journey_date
                )
            )

        except (
            TypeError,
            ValueError,
        ):

            raise ValueError(
                "Invalid date format. "
                "Use YYYY-MM-DD."
            )

        today = date_type.today()

        max_date = (
            today
            + relativedelta(
                months=2
            )
        )

        # --------------------------------------------------------
        # PAST / TODAY
        # --------------------------------------------------------

        if requested_date <= today:

            raise ValueError(
                "Journey date must be after "
                "today's date."
            )

        # --------------------------------------------------------
        # MORE THAN 2 MONTHS
        # --------------------------------------------------------

        if requested_date > max_date:

            raise ValueError(
                "Journey date cannot be more than "
                "2 months from today. "
                f"Maximum allowed date is "
                f"{max_date.isoformat()}."
            )

        return requested_date

    # ============================================================
    # TRAIN ROUTE VALIDATION
    # ============================================================

    # ============================================================
    # TRAIN ROUTE & IDENTITY VALIDATION
    # ============================================================

    # ============================================================
    # TRAIN ROUTE & IDENTITY VALIDATION
    # ============================================================

    def _validate_and_extract_train_route(
        self,
        train,
        requested_from: str,
        requested_to: str,
        provider: str = "railradar",
        *args,
        **kwargs,
    ) -> Tuple[bool, Optional[Any]]:
        """
        Deterministic route validation against actual station sequence.
        Matches canonical station codes (e.g. CSTM / CSMT equivalence).
        Checks embedded stops from journey search first; only calls schedule/details API if route info is missing.
        """
        if not train:
            return False, None

        t_num = str(getattr(train, "train_number", "") or (train.get("train_number") if isinstance(train, dict) else "") or "").strip()
        t_name = str(getattr(train, "train_name", "") or (train.get("train_name") if isinstance(train, dict) else "") or "").strip()
        clean_from = str(requested_from or "").strip().upper()
        clean_to = str(requested_to or "").strip().upper()

        if not t_num or not t_name or not clean_from or not clean_to:
            return False, None

        canonical_from = get_canonical_station_code(clean_from)
        canonical_to = get_canonical_station_code(clean_to)

        prov_name = "ExactCache" if str(provider).lower() == "cache" else ("RailRadar" if str(provider).lower() == "railradar" else "RailCore")

        # Check circuit breaker before attempting provider route validation
        from app.services.train.api_tracker import api_tracker
        if prov_name not in ("ExactCache",) and ((prov_name == "RailRadar" and api_tracker.railradar_rate_limited) or (prov_name == "RailCore" and api_tracker.railcore_rate_limited)):
            print(f"\n{prov_name} route validation skipped: provider unavailable\n")
            return False, None

        # Fetch actual schedule / route stops
        stops = []
        actual_api_origin = "N/A"
        actual_api_destination = "N/A"

        # 1. First inspect if stops/route data is already embedded in journey response
        embedded_stops_raw = None
        raw_train_candidate = kwargs.get("raw_train")
        for candidate_obj in (raw_train_candidate, train):
            if candidate_obj is None:
                continue
            if isinstance(candidate_obj, dict):
                embedded_stops_raw = (
                    candidate_obj.get("stations")
                    or candidate_obj.get("stops")
                    or candidate_obj.get("route")
                )
            else:
                embedded_stops_raw = (
                    getattr(candidate_obj, "stations", None)
                    or getattr(candidate_obj, "stops", None)
                    or getattr(candidate_obj, "route", None)
                )
            if embedded_stops_raw and isinstance(embedded_stops_raw, list):
                break

        if embedded_stops_raw and isinstance(embedded_stops_raw, list):
            for idx, item in enumerate(embedded_stops_raw):
                if isinstance(item, dict):
                    st_obj = item.get("station") if isinstance(item.get("station"), dict) else {}
                    st_code = str(
                        item.get("station_code")
                        or item.get("code")
                        or st_obj.get("code")
                        or ""
                    ).strip().upper()
                    st_name = str(
                        item.get("station_name")
                        or item.get("name")
                        or st_obj.get("name")
                        or st_code
                    ).strip()
                    seq = item.get("sequence", idx + 1)
                    dep = item.get("departure_time") or item.get("departure")
                    arr = item.get("arrival_time") or item.get("arrival")
                    is_halt = item.get("is_stop", item.get("isHalt", True))
                    if st_code:
                        stops.append({
                            "code": st_code,
                            "name": st_name,
                            "sequence": int(seq) if str(seq).isdigit() else (idx + 1),
                            "departure_time": dep,
                            "arrival_time": arr,
                            "is_halt": is_halt,
                        })
                elif hasattr(item, "code"):
                    st_code = str(getattr(item, "code", "")).strip().upper()
                    st_name = str(getattr(item, "name", st_code)).strip()
                    if st_code:
                        stops.append({
                            "code": st_code,
                            "name": st_name,
                            "sequence": idx + 1,
                            "departure_time": getattr(item, "departure_time", None),
                            "arrival_time": getattr(item, "arrival_time", None),
                            "is_halt": True,
                        })
            if stops:
                actual_api_origin = stops[0]["code"]
                actual_api_destination = stops[-1]["code"]

        # 2. If stops not present in journey response, query provider schedule API (live providers only)
        if not stops and prov_name != "ExactCache":
            try:
                if str(provider).lower() == "railradar":
                    sched_resp = self.railradar.get_train_details(t_num)
                    data = (sched_resp or {}).get("data", {})
                    route_data = data.get("route") or data.get("stops") or []
                    actual_api_origin = data.get("source_station_code") or (
                        (route_data[0].get("station", {}).get("code") if isinstance(route_data[0].get("station"), dict) else route_data[0].get("station_code"))
                        if route_data else "N/A"
                    )
                    actual_api_destination = data.get("destination_station_code") or (
                        (route_data[-1].get("station", {}).get("code") if isinstance(route_data[-1].get("station"), dict) else route_data[-1].get("station_code"))
                        if route_data else "N/A"
                    )
                    for idx, r_item in enumerate(route_data):
                        st_obj = r_item.get("station") if isinstance(r_item.get("station"), dict) else {}
                        st_code = str(r_item.get("station_code") or st_obj.get("code") or r_item.get("code") or "").strip().upper()
                        st_name = str(r_item.get("station_name") or st_obj.get("name") or r_item.get("name") or st_code).strip()
                        seq = r_item.get("sequence", idx + 1)
                        dep = r_item.get("departure") or r_item.get("departure_time")
                        arr = r_item.get("arrival") or r_item.get("arrival_time")
                        is_halt = r_item.get("isHalt", r_item.get("is_stop", True))
                        if st_code:
                            stops.append({
                                "code": st_code,
                                "name": st_name,
                                "sequence": int(seq) if str(seq).isdigit() else (idx + 1),
                                "departure_time": dep,
                                "arrival_time": arr,
                                "is_halt": is_halt,
                            })
                else:
                    # Default to RailCore
                    sched_resp = self.railcore.get_train_schedule(t_num)
                    data = (sched_resp or {}).get("data", {})
                    stops_data = data.get("stops") or []
                    actual_api_origin = data.get("source_station_code") or (
                        stops_data[0].get("station_code") if stops_data else "N/A"
                    )
                    actual_api_destination = data.get("destination_station_code") or (
                        stops_data[-1].get("station_code") if stops_data else "N/A"
                    )
                    for idx, s_item in enumerate(stops_data):
                        st_code = str(s_item.get("station_code") or s_item.get("code") or "").strip().upper()
                        st_name = str(s_item.get("station_name") or s_item.get("name") or st_code).strip()
                        seq = s_item.get("sequence", idx + 1)
                        dep = s_item.get("departure_time") or s_item.get("departure")
                        arr = s_item.get("arrival_time") or s_item.get("arrival")
                        is_halt = s_item.get("is_stop", True)
                        if st_code:
                            stops.append({
                                "code": st_code,
                                "name": st_name,
                                "sequence": int(seq) if str(seq).isdigit() else (idx + 1),
                                "departure_time": dep,
                                "arrival_time": arr,
                                "is_halt": is_halt,
                            })
            except (
                RailRadarCircuitOpenError, RailCoreCircuitOpenError,
                RailRadarRateLimitedError, RailCoreRateLimitedError,
                RailRadarServerError, RailCoreServerError,
                RailRadarTimeoutError, RailCoreTimeoutError,
                RailRadarNetworkError, RailCoreNetworkError,
                RailRadarAuthError, RailCoreAuthError,
            ) as exc:
                logger.warning("%s route validation skipped: provider unavailable (%s)", prov_name, exc)
                print(f"\n{prov_name} route validation skipped: provider unavailable\n")
                return False, None
            except Exception as exc:
                err_str = str(exc).lower()
                if any(k in err_str for k in ("rate limit", "429", "circuit", "timeout", "500", "502", "503", "unavailable", "401", "403")):
                    logger.warning("%s route validation skipped: provider unavailable (%s)", prov_name, exc)
                    print(f"\n{prov_name} route validation skipped: provider unavailable\n")
                    return False, None
                logger.debug("Failed to retrieve schedule stops for train %s: %s", t_num, exc)

        # If no stops retrieved, verify route based on train candidate properties or reject
        if not stops:
            if prov_name == "ExactCache":
                src_c = str(getattr(train, "boarding_station_code", "") or getattr(train, "from_station_code", "") or getattr(train, "from_code", "") or (getattr(getattr(train, "source", None), "code", "")) or (train.get("from_code") if isinstance(train, dict) else "") or "").strip().upper()
                dst_c = str(getattr(train, "alighting_station_code", "") or getattr(train, "to_station_code", "") or getattr(train, "to_code", "") or (getattr(getattr(train, "destination", None), "code", "")) or (train.get("to_code") if isinstance(train, dict) else "") or "").strip().upper()
                canon_src = get_canonical_station_code(src_c)
                canon_dst = get_canonical_station_code(dst_c)
                actual_api_origin = getattr(train, "train_origin_station", None) or (train.get("train_origin_station") if isinstance(train, dict) else None) or src_c or "N/A"
                actual_api_destination = getattr(train, "train_destination_station", None) or (train.get("train_destination_station") if isinstance(train, dict) else None) or dst_c or "N/A"
                
                src_match = (src_c == clean_from or canon_src == canonical_from)
                dst_match = (dst_c == clean_to or canon_dst == canonical_to)
                
                if src_match and dst_match and canon_src != canon_dst:
                    origin_found = True
                    dest_found = True
                    order_ok = True
                    is_valid = True
                    orig_idx = getattr(train, "boarding_index", 0) or 0
                    dest_idx = getattr(train, "alighting_index", 1) or 1
                    orig_stop = {"code": src_c or clean_from, "name": getattr(train, "boarding_station_name", None) or clean_from, "departure_time": getattr(train, "departure_time", None)}
                    dest_stop = {"code": dst_c or clean_to, "name": getattr(train, "alighting_station_name", None) or clean_to, "arrival_time": getattr(train, "arrival_time", None)}
                else:
                    origin_found = src_match
                    dest_found = dst_match
                    order_ok = False
                    is_valid = False
                    orig_idx = None
                    dest_idx = None
                    orig_stop = None
                    dest_stop = None
            else:
                origin_found = False
                dest_found = False
                order_ok = False
                is_valid = False
                orig_idx = None
                dest_idx = None
                orig_stop = None
                dest_stop = None
        else:
            orig_idx = None
            dest_idx = None
            orig_stop = None
            dest_stop = None

            for idx, stop_info in enumerate(stops):
                st_code = stop_info.get("code", "").upper()
                canon_code = get_canonical_station_code(st_code)
                if orig_stop is None and (st_code == clean_from or canon_code == canonical_from):
                    orig_idx = idx
                    orig_stop = stop_info
                if (st_code == clean_to or canon_code == canonical_to):
                    dest_idx = idx
                    dest_stop = stop_info

            origin_found = orig_stop is not None
            dest_found = dest_stop is not None
            order_ok = False

            if origin_found and dest_found and orig_idx is not None and dest_idx is not None:
                orig_seq = orig_stop.get("sequence", orig_idx)
                dest_seq = dest_stop.get("sequence", dest_idx)
                if orig_seq < dest_seq and orig_idx < dest_idx:
                    order_ok = True

            is_valid = origin_found and dest_found and order_ok

        # Print Required Step 9 Structured Validation Log
        print("\nTRAIN ROUTE VALIDATION")
        print(f"Train: {t_num} {t_name}")
        print(f"Requested: {clean_from} -> {clean_to}")
        print(f"Normalized: {canonical_from} -> {canonical_to}")
        print(f"Actual API origin: {actual_api_origin}")
        print(f"Actual API destination: {actual_api_destination}")
        print(f"Origin found in route: {'YES' if origin_found else 'NO'}")
        print(f"Destination found in route: {'YES' if dest_found else 'NO'}")
        print(f"Correct station order: {'YES' if order_ok else 'NO'}")
        print(f"Validation: {'ACCEPTED' if is_valid else 'REJECTED'}\n")

        if not is_valid or orig_stop is None or dest_stop is None:
            return False, None

        # Train is valid for this requested pair. Update train response with verified stops & times.
        orig_name = orig_stop.get("name") or clean_from
        dest_name = dest_stop.get("name") or clean_to

        if isinstance(train, dict):
            train["source"] = {"code": clean_from, "name": orig_name}
            train["destination"] = {"code": clean_to, "name": dest_name}
            if orig_stop.get("departure_time") and orig_stop["departure_time"] not in ("00:00", ""):
                train["departure_time"] = orig_stop["departure_time"]
            if dest_stop.get("arrival_time") and dest_stop["arrival_time"] not in ("00:00", ""):
                train["arrival_time"] = dest_stop["arrival_time"]
            train["boarding_station"] = clean_from
            train["boarding_station_code"] = clean_from
            train["boarding_station_name"] = orig_name
            train["alighting_station"] = clean_to
            train["alighting_station_code"] = clean_to
            train["alighting_station_name"] = dest_name
            train["boarding_index"] = orig_idx
            train["alighting_index"] = dest_idx
            train["from_station_code"] = clean_from
            train["to_station_code"] = clean_to
            train["from_station_name"] = orig_name
            train["to_station_name"] = dest_name
            train["from_code"] = clean_from
            train["to_code"] = clean_to
            train["train_origin_station"] = actual_api_origin
            train["train_destination_station"] = actual_api_destination
            train["train_route_summary"] = f"{actual_api_origin} -> ... -> {clean_from} -> ... -> {clean_to} -> ... -> {actual_api_destination}"
            train["actual_origin_station"] = clean_from
            train["actual_destination_station"] = clean_to
            train["actual_train_origin"] = f"{orig_name} ({clean_from})" if clean_from != orig_name else clean_from
            train["actual_train_destination"] = f"{dest_name} ({clean_to})" if clean_to != dest_name else clean_to
            return True, train

        train.source = Station(code=clean_from, name=orig_name)
        train.destination = Station(code=clean_to, name=dest_name)
        
        if orig_stop.get("departure_time") and orig_stop["departure_time"] not in ("00:00", ""):
            train.departure_time = orig_stop["departure_time"]
        if dest_stop.get("arrival_time") and dest_stop["arrival_time"] not in ("00:00", ""):
            train.arrival_time = dest_stop["arrival_time"]

        # Traveler boarding and alighting stations
        train.boarding_station = clean_from
        train.boarding_station_code = clean_from
        train.boarding_station_name = orig_name
        train.alighting_station = clean_to
        train.alighting_station_code = clean_to
        train.alighting_station_name = dest_name
        train.boarding_index = orig_idx
        train.alighting_index = dest_idx

        train.from_station_code = clean_from
        train.to_station_code = clean_to
        train.from_station_name = orig_name
        train.to_station_name = dest_name
        train.from_code = clean_from
        train.to_code = clean_to

        # Train full terminus endpoints & route summary
        train.train_origin_station = actual_api_origin
        train.train_destination_station = actual_api_destination
        train.train_route_summary = f"{actual_api_origin} -> ... -> {clean_from} -> ... -> {clean_to} -> ... -> {actual_api_destination}"

        # Canonical traveler endpoint display
        train.actual_origin_station = clean_from
        train.actual_destination_station = clean_to
        train.actual_train_origin = f"{orig_name} ({clean_from})" if clean_from != orig_name else clean_from
        train.actual_train_destination = f"{dest_name} ({clean_to})" if clean_to != dest_name else clean_to

        return True, train

    def _validate_train_route(
        self,
        train,
        requested_from: str = "",
        requested_to: str = "",
        provider: str = "railcore",
    ) -> bool:
        is_valid, _ = self._validate_and_extract_train_route(
            train, requested_from, requested_to, provider
        )
        return is_valid

    # ============================================================
    # SEARCH TRAINS
    # ============================================================

    def search_trains(
        self,
        from_code: str,
        to_code: str,
        date: str,
        quota_code: str = "GN",
    ):

        # ========================================================
        # VALIDATION FIRST
        #
        # NO API CALL BEFORE THIS POINT
        # ========================================================

        from_code, to_code = (
            self._validate_station_codes(
                from_code,
                to_code,
            )
        )

        quota_code = (
            self._validate_quota_code(
                quota_code
            )
        )

        self._validate_journey_date(
            date
        )

        # ========================================================
        # PROVIDER STATE & TRACKING
        # ========================================================

        from app.services.train.api_tracker import api_tracker

        railradar_status = "UNKNOWN"
        railcore_status = "UNKNOWN"

        # ========================================================
        # 1. RAILRADAR (PRIMARY PROVIDER)
        # ========================================================

        if api_tracker.railradar_rate_limited:
            railradar_status = "CIRCUIT_OPEN"
        else:
            try:
                logger.info(
                    "RailRadar train search: %s -> %s | %s",
                    from_code,
                    to_code,
                    date,
                )

                response = self.railradar.search_trains(
                    from_code=from_code,
                    to_code=to_code,
                )

                if not response.get("success"):
                    raise RailRadarServerError("RailRadar returned an unsuccessful response.")

                data = response.get("data", {})
                trains = data.get("trains", [])

                print(f"\nSEARCH ATTEMPT: {from_code} -> {to_code} | Provider: RailRadar | Status: 200 | Results: {len(trains)}")

                if not trains:
                    railradar_status = "NO_RESULTS"
                    logger.warning("RailRadar returned no trains.")
                else:
                    candidates = []
                    for train in trains:
                        try:
                            norm_train = normalize_railradar_train(train)
                            candidates.append(norm_train)
                        except Exception as e:
                            logger.warning("Skipping malformed RailRadar train: %s", str(e))

                    date_candidates = self._filter_trains_by_date(candidates, date)
                    if not date_candidates:
                        railradar_status = "NO_RESULTS"
                        logger.warning("RailRadar has no trains running on %s.", date)
                    else:
                        ranked_candidates = self._rank_and_limit_trains(date_candidates, limit=len(date_candidates))
                        MAX_SCHEDULE_VALIDATION_CANDIDATES = 5
                        verified_trains = []

                        for cand in ranked_candidates[:MAX_SCHEDULE_VALIDATION_CANDIDATES]:
                            try:
                                is_valid, validated_train = self._validate_and_extract_train_route(
                                    cand, from_code, to_code, "railradar"
                                )
                                if is_valid and validated_train is not None:
                                    verified_trains.append(validated_train)
                                    if len(verified_trains) >= 3:
                                        break
                                else:
                                    logger.warning(
                                        "Rejecting RailRadar train %s: route does not serve %s -> %s in order",
                                        getattr(cand, "train_number", ""),
                                        from_code,
                                        to_code,
                                    )
                            except (RailRadarRateLimitedError, RailRadarCircuitOpenError):
                                raise
                            except Exception as e:
                                logger.warning("Error validating RailRadar train %s: %s", getattr(cand, "train_number", ""), e)

                        if verified_trains:
                            top_trains = self._rank_and_limit_trains(verified_trains, limit=3)
                            railradar_status = "SUCCESS"
                            print(f"\nVALIDATED TRAIN: {top_trains[0].train_number} {top_trains[0].train_name} ({from_code} -> {to_code})\n")
                            for t in top_trains:
                                try:
                                    exact_transport_cache.store_train(
                                        train=t,
                                        from_code=from_code,
                                        to_code=to_code,
                                        date=date,
                                        quota_code=quota_code,
                                    )
                                except Exception as e:
                                    logger.debug("Failed to store exact cache for train %s: %s", getattr(t, "train_number", ""), e)
                            return top_trains
                        else:
                            railradar_status = "NO_RESULTS"

            except RailRadarRateLimitedError:
                railradar_status = "RATE_LIMITED"
                api_tracker.mark_railradar_429()
                print(f"\nSEARCH ATTEMPT: {from_code} -> {to_code} | Provider: RailRadar | Status: 429 (RATE_LIMITED)")
            except RailRadarAuthError:
                railradar_status = "AUTH_ERROR"
                print(f"\nSEARCH ATTEMPT: {from_code} -> {to_code} | Provider: RailRadar | Status: 401/403 (AUTH_ERROR)")
            except RailRadarServerError:
                railradar_status = "SERVER_ERROR"
                print(f"\nSEARCH ATTEMPT: {from_code} -> {to_code} | Provider: RailRadar | Status: 5xx (SERVER_ERROR)")
            except RailRadarTimeoutError:
                railradar_status = "TIMEOUT"
                print(f"\nSEARCH ATTEMPT: {from_code} -> {to_code} | Provider: RailRadar | Status: TIMEOUT")
            except RailRadarCircuitOpenError:
                railradar_status = "CIRCUIT_OPEN"
            except RailRadarNetworkError:
                railradar_status = "NETWORK_ERROR"
                print(f"\nSEARCH ATTEMPT: {from_code} -> {to_code} | Provider: RailRadar | Status: NETWORK_ERROR")
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "rate limit" in err_str:
                    railradar_status = "RATE_LIMITED"
                elif "401" in err_str or "403" in err_str:
                    railradar_status = "AUTH_ERROR"
                elif "404" in err_str or "not found" in err_str:
                    railradar_status = "NO_RESULTS"
                elif any(c in err_str for c in ("500", "502", "503", "504")):
                    railradar_status = "SERVER_ERROR"
                elif "timeout" in err_str:
                    railradar_status = "TIMEOUT"
                elif "network" in err_str or "connection" in err_str:
                    railradar_status = "NETWORK_ERROR"
                else:
                    railradar_status = "SERVER_ERROR"
                print(f"\nSEARCH ATTEMPT: {from_code} -> {to_code} | Provider: RailRadar | Status: {railradar_status}")

        # ========================================================
        # 2. RAILCORE (FALLBACK PROVIDER)
        # ========================================================

        if api_tracker.railcore_rate_limited:
            railcore_status = "CIRCUIT_OPEN"
        else:
            try:
                logger.info(
                    "Trying RailCore fallback: %s -> %s | %s",
                    from_code,
                    to_code,
                    date,
                )

                response = self.railcore.search_trains(
                    from_code=from_code,
                    to_code=to_code,
                    date=date,
                )

                if not response.get("success"):
                    raise RailCoreServerError("RailCore returned an unsuccessful response.")

                data = response.get("data", {})
                trains = data.get("trains", [])

                print(f"\nSEARCH ATTEMPT: {from_code} -> {to_code} | Provider: RailCore | Status: 200 | Results: {len(trains)}")

                if not trains:
                    railcore_status = "NO_RESULTS"
                else:
                    candidates = []
                    for train in trains:
                        try:
                            norm_train = normalize_railcore_train(
                                train=train,
                                from_code=from_code,
                                to_code=to_code,
                            )
                            candidates.append(norm_train)
                        except Exception as e:
                            logger.warning("Skipping malformed RailCore train: %s", str(e))

                    date_candidates = self._filter_trains_by_date(candidates, date)
                    if not date_candidates:
                        railcore_status = "NO_RESULTS"
                        logger.warning("RailCore returned trains, but none run on requested date %s.", date)
                    else:
                        ranked_candidates = self._rank_and_limit_trains(date_candidates, limit=len(date_candidates))
                        MAX_SCHEDULE_VALIDATION_CANDIDATES = 5
                        verified_trains = []

                        for cand in ranked_candidates[:MAX_SCHEDULE_VALIDATION_CANDIDATES]:
                            try:
                                is_valid, validated_train = self._validate_and_extract_train_route(
                                    cand, from_code, to_code, "railcore"
                                )
                                if is_valid and validated_train is not None:
                                    verified_trains.append(validated_train)
                                    if len(verified_trains) >= 3:
                                        break
                                else:
                                    logger.warning(
                                        "Rejecting RailCore train %s: route does not serve %s -> %s in order",
                                        getattr(cand, "train_number", ""),
                                        from_code,
                                        to_code,
                                    )
                            except (RailCoreRateLimitedError, RailCoreCircuitOpenError):
                                raise
                            except Exception as e:
                                logger.warning("Error validating RailCore train %s: %s", getattr(cand, "train_number", ""), e)

                        if verified_trains:
                            top_trains = self._rank_and_limit_trains(verified_trains, limit=3)
                            railcore_status = "SUCCESS"
                            print(f"\nVALIDATED TRAIN: {top_trains[0].train_number} {top_trains[0].train_name} ({from_code} -> {to_code})\n")
                            for t in top_trains:
                                try:
                                    exact_transport_cache.store_train(
                                        train=t,
                                        from_code=from_code,
                                        to_code=to_code,
                                        date=date,
                                        quota_code=quota_code,
                                    )
                                except Exception as e:
                                    logger.debug("Failed to store exact cache for train %s: %s", getattr(t, "train_number", ""), e)
                            return top_trains
                        else:
                            railcore_status = "NO_RESULTS"

            except RailCoreRateLimitedError:
                railcore_status = "RATE_LIMITED"
                api_tracker.mark_railcore_429()
                print(f"\nSEARCH ATTEMPT: {from_code} -> {to_code} | Provider: RailCore | Status: 429 (RATE_LIMITED)")
            except RailCoreAuthError:
                railcore_status = "AUTH_ERROR"
                print(f"\nSEARCH ATTEMPT: {from_code} -> {to_code} | Provider: RailCore | Status: 401/403 (AUTH_ERROR)")
            except RailCoreServerError:
                railcore_status = "SERVER_ERROR"
                print(f"\nSEARCH ATTEMPT: {from_code} -> {to_code} | Provider: RailCore | Status: 5xx (SERVER_ERROR)")
            except RailCoreTimeoutError:
                railcore_status = "TIMEOUT"
                print(f"\nSEARCH ATTEMPT: {from_code} -> {to_code} | Provider: RailCore | Status: TIMEOUT")
            except RailCoreCircuitOpenError:
                railcore_status = "CIRCUIT_OPEN"
            except RailCoreNetworkError:
                railcore_status = "NETWORK_ERROR"
                print(f"\nSEARCH ATTEMPT: {from_code} -> {to_code} | Provider: RailCore | Status: NETWORK_ERROR")
            except Exception as e:
                err_str = str(e).lower()
                if "429" in err_str or "rate limit" in err_str:
                    railcore_status = "RATE_LIMITED"
                elif "401" in err_str or "403" in err_str:
                    railcore_status = "AUTH_ERROR"
                elif "404" in err_str or "not found" in err_str:
                    railcore_status = "NO_RESULTS"
                elif any(c in err_str for c in ("500", "502", "503", "504")):
                    railcore_status = "SERVER_ERROR"
                elif "timeout" in err_str:
                    railcore_status = "TIMEOUT"
                elif "network" in err_str or "connection" in err_str:
                    railcore_status = "NETWORK_ERROR"
                else:
                    railcore_status = "SERVER_ERROR"
                print(f"\nSEARCH ATTEMPT: {from_code} -> {to_code} | Provider: RailCore | Status: {railcore_status}")

        # ========================================================
        # 3. DETERMINISTIC FINAL STATUS EVALUATION & CACHE FALLBACK
        # ========================================================

        # Rule 1: Zero availability when both returned HTTP 200 with 0 trains (clean confirmation of 0 availability)
        if railradar_status == "NO_RESULTS" and railcore_status == "NO_RESULTS":
            raise TrainNoAvailabilityError(
                f"No trains are available between {from_code} and {to_code} on {date}."
            )

        # Rule 1b: Primary was rate-limited or unavailable, but fallback returned HTTP 200 with 0 trains (clean confirmation of 0 availability)
        if railradar_status in ("RATE_LIMITED", "CIRCUIT_OPEN", "SERVER_ERROR", "TIMEOUT", "NETWORK_ERROR", "AUTH_ERROR") and railcore_status == "NO_RESULTS":
            raise TrainNoAvailabilityError(
                f"No trains are available between {from_code} and {to_code} on {date}."
            )

        # Rule 1c: Providers are unavailable / rate-limited -> Check Exact Transport Cache Fallback
        is_provider_unavailable = (
            railcore_status in ("RATE_LIMITED", "CIRCUIT_OPEN", "SERVER_ERROR", "TIMEOUT", "NETWORK_ERROR", "AUTH_ERROR", "UNKNOWN")
            or railradar_status in ("RATE_LIMITED", "CIRCUIT_OPEN", "SERVER_ERROR", "TIMEOUT", "NETWORK_ERROR", "AUTH_ERROR", "UNKNOWN")
        )

        if is_provider_unavailable:
            logger.info("Live providers unavailable (RailRadar: %s, RailCore: %s). Checking exact transport cache fallback.", railradar_status, railcore_status)
            cached_candidates = exact_transport_cache.find_trains(
                from_code=from_code,
                to_code=to_code,
                date=date,
                quota_code=quota_code,
            )

            if cached_candidates:
                validated_cached = []
                for cand in cached_candidates:
                    is_valid, val_train = self._validate_and_extract_train_route(
                        cand, from_code, to_code, provider="cache"
                    )
                    if is_valid and val_train is not None:
                        validated_cached.append(val_train)
                    else:
                        cand_num = getattr(cand, "train_number", None) or (cand.get("train_number") if isinstance(cand, dict) else "")
                        print(f"[EXACT CACHE] REJECTED: train={cand_num} reason=route_validation_failed")
                        logger.warning("[EXACT CACHE] REJECTED: train=%s route validation failed for %s->%s", cand_num, from_code, to_code)

                # Filter by running date
                date_filtered = self._filter_trains_by_date(validated_cached, date)

                if date_filtered:
                    top_cached = self._rank_and_limit_trains(date_filtered, limit=3)
                    for t in top_cached:
                        if isinstance(t, dict):
                            t["data_source"] = "cache"
                            t["provider"] = "cache"
                        else:
                            if hasattr(t, "data_source"):
                                t.data_source = "cache"
                            if hasattr(t, "provider"):
                                t.provider = "cache"

                    first_cached = top_cached[0]
                    first_num = getattr(first_cached, "train_number", None) or (first_cached.get("train_number") if isinstance(first_cached, dict) else "")
                    first_name = getattr(first_cached, "train_name", None) or (first_cached.get("train_name") if isinstance(first_cached, dict) else "")
                    print(f"\n[EXACT CACHE] FALLBACK USED: train={first_num} route={from_code}->{to_code} date={date}\n")
                    logger.info("[EXACT CACHE] FALLBACK USED: train=%s route=%s->%s date=%s", first_num, from_code, to_code, date)
                    return top_cached
                else:
                    for cand in validated_cached:
                        cand_num = getattr(cand, "train_number", None) or (cand.get("train_number") if isinstance(cand, dict) else "")
                        print(f"[EXACT CACHE] REJECTED: train={cand_num} reason=date_filter_failed")
                        logger.warning("[EXACT CACHE] REJECTED: train=%s does not run on %s", cand_num, date)

        # Rule 2: Rate limit / HTTP 429 / Active circuit breaker on queried providers
        if railcore_status in ("RATE_LIMITED", "CIRCUIT_OPEN") or railradar_status in ("RATE_LIMITED", "CIRCUIT_OPEN"):
            raise TrainRateLimitedError(
                "Train providers are currently rate limited (HTTP 429). Please retry shortly."
            )

        # Rule 3: Provider HTTP 5xx server error
        if railcore_status == "SERVER_ERROR" or railradar_status == "SERVER_ERROR":
            raise TrainServerError(
                "Train provider encountered a server error (HTTP 5xx)."
            )

        # Rule 4: Provider timeout
        if railcore_status == "TIMEOUT" or railradar_status == "TIMEOUT":
            raise TrainTimeoutError(
                "Train provider requests timed out."
            )

        # Rule 5: Provider network error
        if railcore_status == "NETWORK_ERROR" or railradar_status == "NETWORK_ERROR":
            raise TrainNetworkError(
                "Train provider network request failed."
            )

        # Rule 6: Auth error
        if railcore_status == "AUTH_ERROR" or railradar_status == "AUTH_ERROR":
            raise TrainAuthError(
                "Train provider authentication failed. Please check API key configuration."
            )

        # Fallback default: zero availability
        raise TrainNoAvailabilityError(
            f"No trains are available between {from_code} and {to_code} on {date}."
        )

    # ============================================================
    # FILTER BY RUNNING DAY
    # ============================================================

    def _filter_trains_by_date(
        self,
        trains,
        date: str,
    ):

        try:

            requested_date = (
                date_type.fromisoformat(
                    date
                )
            )

        except ValueError:

            return []

        day_abbr = requested_date.strftime("%a").lower()
        day_full = requested_date.strftime("%A").lower()

        filtered = []

        for train in trains:

            running_days = (
                train.running_days
                or []
            )

            running_days = [
                str(day).strip().lower()
                for day in running_days
            ]

            # ----------------------------------------------------
            # DATE-AWARE RUNNING-DAY VALIDATION
            # ----------------------------------------------------
            # RailRadar's route endpoint does not receive the journey
            # date, so validate the provider's running-day metadata here.
            # Do not treat missing metadata as a match because that could
            # allow a train that does not run on the requested date.
            normalized_days = set()

            day_aliases = {
                "monday": {"mon", "monday", "1"},
                "tuesday": {"tue", "tues", "tuesday", "2"},
                "wednesday": {"wed", "weds", "wednesday", "3"},
                "thursday": {"thu", "thur", "thurs", "thursday", "4"},
                "friday": {"fri", "friday", "5"},
                "saturday": {"sat", "saturday", "6"},
                "sunday": {"sun", "sunday", "7"},
            }

            for value in running_days:
                value = value.strip().lower()
                if value in {"daily", "all", "everyday", "every day"}:
                    normalized_days.update(day_aliases.keys())
                    continue

                for canonical_day, aliases in day_aliases.items():
                    if value in aliases:
                        normalized_days.add(canonical_day)
                        break

            if day_full in normalized_days:
                filtered.append(train)

        return filtered

    # ============================================================
    # RANK + LIMIT
    # ============================================================

    def _rank_and_limit_trains(
        self,
        trains,
        limit: int = 3,
    ):

        def ranking_key(train):

            if (
                train.duration_minutes
                is None
            ):

                return 999999

            return train.duration_minutes

        sorted_trains = sorted(
            trains,
            key=ranking_key,
        )

        return sorted_trains[:limit]

    # ============================================================
    # FARE ENRICHMENT
    # ============================================================

    def attach_fares_to_selected_trains(
        self,
        trains,
        from_code: str,
        to_code: str,
        date: str,
        quota_code: str = "GN",
    ):
        """
        Rule 1 & Rule 2: Fetch and attach fare options ONLY for the final selected verified journey.
        """
        return self._attach_fare_options(
            trains=trains,
            from_code=from_code,
            to_code=to_code,
            date=date,
            quota_code=quota_code,
        )

    def _attach_fare_options(
        self,
        trains,
        from_code: str,
        to_code: str,
        date: str,
        quota_code: str,
    ):
        if not trains:
            return []

        if api_tracker.railcore_rate_limited:
            self._mark_fares_unavailable(trains, reason="rate_limited")
            return trains

        try:
            response = self.railcore.get_fare_options(
                from_code=from_code,
                to_code=to_code,
                date=date,
                quota_code=quota_code,
            )

            if not (response.get("success") or response.get("status")):
                self._mark_fares_unavailable(trains, reason="provider_error")
                return trains

            data = response.get("data", {}) if isinstance(response.get("data"), dict) else response
            fare_trains = data.get("trains", [])
            fare_lookup = {}
            for item in fare_trains:
                t_num = str(item.get("train_number", ""))
                fare_lookup[t_num] = item.get("fares", [])

            for train in trains:
                t_num = str(train.get("train_number") if isinstance(train, dict) else getattr(train, "train_number", ""))
                fares = fare_lookup.get(t_num, [])
                normalized_fares = []
                for fare in fares:
                    class_code = fare.get("class_code")
                    if not class_code:
                        continue
                    normalized_fares.append(
                        TrainFare(
                            class_code=str(class_code),
                            amount=fare.get("fare"),
                            currency=fare.get("currency", "INR"),
                        )
                    )

                if normalized_fares:
                    if isinstance(train, dict):
                        train["fares"] = [f.model_dump() if hasattr(f, "model_dump") else f for f in normalized_fares]
                        train["classes"] = [f.class_code for f in normalized_fares]
                        train["fare"] = {"status": "available", "amount": normalized_fares[0].amount, "currency": normalized_fares[0].currency}
                    else:
                        train.fares = normalized_fares
                        train.classes = [f.class_code for f in normalized_fares]
                        train.fare = TrainFare(class_code=normalized_fares[0].class_code, amount=normalized_fares[0].amount, currency=normalized_fares[0].currency)
                else:
                    self._mark_train_fare_unavailable(train, reason="not_listed")

            return trains

        except (RailCoreRateLimitedError, RailCoreCircuitOpenError):
            logger.warning("Fare API rate limited (HTTP 429). Keeping valid train options without fare.")
            self._mark_fares_unavailable(trains, reason="rate_limited")
            return trains
        except Exception as e:
            logger.warning("Fare enrichment failed: %s. Keeping valid train options without fare.", str(e))
            self._mark_fares_unavailable(trains, reason="provider_unavailable")
            return trains

    def _mark_train_fare_unavailable(self, train, reason: str = "unavailable"):
        if isinstance(train, dict):
            train["fare"] = {"status": "unavailable", "reason": reason}
            train["fares"] = []
        else:
            train.fare = {"status": "unavailable", "reason": reason}
            train.fares = []

    def _mark_fares_unavailable(self, trains, reason: str = "unavailable"):
        for train in trains:
            self._mark_train_fare_unavailable(train, reason)

    # ============================================================
    # SELECTED TRAIN DETAILS
    # ============================================================

    def get_train_details(
        self,
        train_number: str,
        from_code: str,
        to_code: str,
        date: str,
        class_code: str,
        quota_code: str = "GN",
    ):

        # ========================================================
        # VALIDATION FIRST
        #
        # NO API CALL BEFORE THIS POINT
        # ========================================================

        from_code, to_code = (
            self._validate_station_codes(
                from_code,
                to_code,
            )
        )

        train_number = (
            self._validate_train_number(
                train_number
            )
        )

        class_code = (
            self._validate_class_code(
                class_code
            )
        )

        quota_code = (
            self._validate_quota_code(
                quota_code
            )
        )

        self._validate_journey_date(
            date
        )

        # ========================================================
        # RAILRADAR
        # ========================================================

        try:

            logger.info(
                "RailRadar details: "
                "%s | %s -> %s | %s | %s",
                train_number,
                from_code,
                to_code,
                class_code,
                quota_code,
            )

            fare_response = (
                self.railradar.get_fare(
                    train_number=train_number,
                    journey_date=date,
                    from_code=from_code,
                    to_code=to_code,
                    class_code=class_code,
                    quota_code=quota_code,
                )
            )

            seat_response = (
                self.railradar.get_seats(
                    train_number=train_number,
                    journey_date=date,
                    from_code=from_code,
                    to_code=to_code,
                    class_code=class_code,
                    quota_code=quota_code,
                )
            )

            norm_details = normalize_train_details(
                fare_data=fare_response.get(
                    "data"
                ),
                availability_data=seat_response.get(
                    "data"
                ),
                train_number=train_number,
                from_code=from_code,
                to_code=to_code,
                date=date,
                class_code=class_code,
                quota_code=quota_code,
                provider="railradar",
            )
            try:
                exact_transport_cache.store_train(
                    train=norm_details,
                    from_code=from_code,
                    to_code=to_code,
                    date=date,
                    class_code=class_code,
                    quota_code=quota_code,
                )
            except Exception as ex:
                logger.debug("Failed to store exact details cache: %s", ex)
            return norm_details

        except Exception as e:

            logger.warning(
                "RailRadar details failed "
                "for %s: %s",
                train_number,
                str(e),
            )

        # ========================================================
        # RAILCORE FALLBACK
        # ========================================================

        try:

            logger.info(
                "Trying RailCore details fallback: %s",
                train_number,
            )

            fare_response = (
                self.railcore.get_fare(
                    train_number=train_number,
                    from_code=from_code,
                    to_code=to_code,
                    date=date,
                    class_code=class_code,
                    quota_code=quota_code,
                )
            )

            seat_response = (
                self.railcore.get_seats(
                    train_number=train_number,
                    from_code=from_code,
                    to_code=to_code,
                    date=date,
                    class_code=class_code,
                    quota_code=quota_code,
                )
            )

            norm_details = normalize_train_details(
                fare_data=fare_response.get(
                    "data"
                ),
                availability_data=seat_response.get(
                    "data"
                ),
                train_number=train_number,
                from_code=from_code,
                to_code=to_code,
                date=date,
                class_code=class_code,
                quota_code=quota_code,
                provider="railcore",
            )
            try:
                exact_transport_cache.store_train(
                    train=norm_details,
                    from_code=from_code,
                    to_code=to_code,
                    date=date,
                    class_code=class_code,
                    quota_code=quota_code,
                )
            except Exception as ex:
                logger.debug("Failed to store exact details cache: %s", ex)
            return norm_details

        except Exception as e:

            logger.error(
                "RailCore details failed "
                "for %s: %s",
                train_number,
                str(e),
            )

            # Check exact transport cache fallback for details
            cached_detail = exact_transport_cache.get_exact(
                train_number=train_number,
                from_code=from_code,
                to_code=to_code,
                date=date,
                class_code=class_code,
                quota_code=quota_code,
            )
            if cached_detail:
                print(f"\n[EXACT CACHE] FALLBACK USED: train={train_number} route={from_code}->{to_code} date={date} class={class_code} quota={quota_code}\n")
                logger.info("[EXACT CACHE] FALLBACK USED: train=%s route=%s->%s date=%s", train_number, from_code, to_code, date)
                return cached_detail

            raise TrainProviderUnavailableError(
                "Train details are temporarily unavailable. "
                "Please try again shortly."
            ) from e
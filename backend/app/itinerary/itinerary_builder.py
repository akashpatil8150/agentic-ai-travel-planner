from datetime import datetime, date, timedelta
from typing import Any
import logging
import json

from app.services.llm.llm_client import LLMClient, LLMClientError

from app.state.trip_state import TripState
from app.resolvers.transport_resolver import TransportResolver


logger = logging.getLogger(__name__)


# ============================================================
# TRANSPORT CLASS DEFINITIONS & MAPPINGS
# ============================================================

TRAIN_CLASS_NAMES: dict[str, str] = {
    "SL": "Sleeper Class (SL)",
    "3A": "AC 3 Tier (3A)",
    "2A": "AC 2 Tier (2A)",
    "1A": "AC First Class (1A)",
    "CC": "AC Chair Car (CC)",
    "EC": "Executive Chair Car (EC)",
    "3E": "AC 3 Tier Economy (3E)",
    "2S": "Second Sitting (2S)",
    "EA": "Anubhuti Class (EA)",
    "FC": "First Class (FC)",
}

FLIGHT_CABIN_NAMES: dict[str, str] = {
    "ECONOMY": "Economy Class",
    "PREMIUM_ECONOMY": "Premium Economy Class",
    "BUSINESS": "Business Class",
    "FIRST": "First Class",
}


def format_transport_class_name(class_code: str | None, mode: str = "train") -> str:
    """
    Format internal class codes into clear human-readable names.
    Examples:
        "SL" -> "Sleeper Class (SL)"
        "3A" -> "AC 3 Tier (3A)"
        "ECONOMY" -> "Economy Class"
    """
    if not class_code:
        return "Economy Class" if "flight" in str(mode).lower() else "Sleeper Class (SL)"
    code_clean = str(class_code).strip().upper()
    if "flight" in str(mode).lower():
        return FLIGHT_CABIN_NAMES.get(code_clean, f"{code_clean.title()} Class")
    return TRAIN_CLASS_NAMES.get(code_clean, f"{code_clean} Class")


class ItineraryBuilder:
    """
    Builds a day-wise itinerary from optimized places.

    LLM is used only for intelligent place-to-day allocation.
    Deterministic scheduling remains the final authority.
    """

    def __init__(self):
        self.llm = LLMClient()

    def _llm_plan_places(self, state: TripState, places: list[dict], sightseeing_days: list[int], start_date, destination_name: str) -> dict[int, list[int]]:
        if not places or not sightseeing_days:
            return {}

        compact_places = []
        for index, place in enumerate(places):
            if not isinstance(place, dict):
                continue
            compact_places.append({
                "index": index,
                "name": place.get("name") or place.get("place_name") or "Attraction",
                "category": place.get("category"),
                "duration_minutes": self._get_activity_duration(place),
                "rating": place.get("rating"),
                "latitude": place.get("latitude"),
                "longitude": place.get("longitude"),
            })

        preferences = getattr(state, "preferences", None) or []
        weather = getattr(state, "weather", None) or {}

        system_prompt = """
You are the Itinerary Planning Agent of an Agentic AI Travel Planner.
Allocate VERIFIED places across available sightseeing days.

STRICT RULES:
1. Use ONLY provided places.
2. Never invent or rename a place.
3. Use only valid indexes.
4. Do not repeat places.
5. Respect user preferences.
6. If an arrival day is explicitly listed as a sightseeing day and has a usable arrival window, PRIORITIZE placing exactly one light, nearby, low-effort attraction on that arrival day when a suitable verified place exists.
7. Do not leave an eligible arrival day empty merely to spread places across later days.
8. Never place a heavy, remote, long-duration, adventure, waterfall, trek, wildlife, or similar high-effort attraction on the arrival day.
9. The arrival-day timing window is authoritative. Do not invent an earlier start time.
10. If no suitable light attraction exists for the arrival day, leave it empty and let the deterministic scheduler handle the remaining places.
6. Prefer geographically sensible grouping.
7. Consider activity duration.
8. Never schedule sightseeing during transport.
9. Do not invent times.
10. The deterministic scheduler performs final timing and validation.
11. Return ONLY valid JSON.

Format:
{"days":[{"day":3,"place_indexes":[0,2]}]}
"""

        user_prompt = f"""
Allocate the verified places across the sightseeing days.
Destination: {destination_name}
Trip start: {start_date}
Sightseeing days: {json.dumps(sightseeing_days)}
User preferences: {json.dumps(preferences, ensure_ascii=False)}
Weather: {json.dumps(weather, ensure_ascii=False, default=str, separators=(",", ":"))}
Verified places: {json.dumps(compact_places, ensure_ascii=False, default=str, separators=(",", ":"))}
Return ONLY valid JSON.
"""

        logger.info("ITINERARY LLM request started | destination=%s | places=%s | days=%s", destination_name, len(compact_places), sightseeing_days)
        try:
            response = self.llm.generate(system_prompt=system_prompt, user_prompt=user_prompt, temperature=0.0, max_tokens=500, reasoning_effort="low")
            result = json.loads(response)
        except (LLMClientError, json.JSONDecodeError, TypeError) as exc:
            logger.warning("ITINERARY LLM failed | fallback=deterministic | error=%s", exc)
            return {}
        except Exception as exc:
            logger.exception("Unexpected Itinerary LLM error | fallback=deterministic | error=%s", exc)
            return {}

        if not isinstance(result, dict) or not isinstance(result.get("days"), list):
            logger.warning("ITINERARY LLM returned invalid structure | fallback=deterministic")
            return {}

        valid_days = set(sightseeing_days)
        valid_indexes = {x["index"] for x in compact_places}
        allocation = {}
        used = set()
        for item in result["days"]:
            if not isinstance(item, dict):
                continue
            try:
                day = int(item.get("day"))
            except (TypeError, ValueError):
                continue
            if day not in valid_days or not isinstance(item.get("place_indexes"), list):
                continue
            selected = []
            for index in item["place_indexes"]:
                if isinstance(index, int) and not isinstance(index, bool) and index in valid_indexes and index not in used:
                    selected.append(index); used.add(index)
            if selected:
                allocation[day] = selected

        logger.info("ITINERARY LLM planning completed | allocated_places=%s | allocation=%s", sum(len(v) for v in allocation.values()), allocation)
        return allocation

    def run(self, state: TripState) -> TripState:

        if not isinstance(state, TripState):
            raise TypeError(
                "ItineraryBuilder expects a TripState object."
            )

        if not state.optimization:
            # Fallback optimization dictionary from available state options (BUG-02)
            state.optimization = {
                "best_transport": state.transport_options[0] if state.transport_options else {},
                "best_hotel": state.hotel_options[0] if state.hotel_options else {},
                "best_places": state.place_options if state.place_options else [],
            }

        start_date = state.travel_dates.start
        end_date = state.travel_dates.end
        total_days = max(1, (end_date - start_date).days + 1)
        # Hotel nights are resolved from actual destination arrival and return
        # departure dates below. Never use raw trip dates when outbound travel
        # arrives at the destination on a later calendar day.
        total_nights = 1
        origin_name = (state.origin.city or state.origin.name) if state.origin else "Origin"
        destination_name = (state.destination.city or state.destination.name) if state.destination else "Destination"

        places = state.optimization.get("best_places", [])
        if not places and state.place_options:
            places = state.place_options

        # Filter places: strictly include ONLY accepted/verified places
        clean_places = []
        for p in places:
            ver = p.get("verification") if isinstance(p, dict) else {}
            status = ver.get("status") if isinstance(ver, dict) else None
            if status not in ["verified", "available", "evidence_found"]:
                continue
            clean_places.append(p)

        deduped_places = self._deduplicate_places(clean_places)
        unique_places = self._filter_places_by_quality(deduped_places, destination_name=destination_name)

        # Explicit outbound vs return transport resolution (Never infer from list position)
        outbound_candidate = (
            getattr(state, "outbound_transport", None)
            or (state.recommendations.get("outbound_transport") if isinstance(state.recommendations, dict) else None)
            or (state.optimization.get("best_outbound_transport") if isinstance(state.optimization, dict) else None)
        )
        if not outbound_candidate and isinstance(state.optimization, dict):
            cand = state.optimization.get("best_transport")
            if isinstance(cand, dict) and cand.get("journey_type") != "return":
                outbound_candidate = cand

        if not outbound_candidate and state.transport_options:
            for opt in state.transport_options:
                if isinstance(opt, dict) and opt.get("journey_type") == "outbound":
                    outbound_candidate = opt
                    break
            if not outbound_candidate:
                for opt in state.transport_options:
                    if isinstance(opt, dict) and opt.get("journey_type") != "return":
                        outbound_candidate = opt
                        break
            if not outbound_candidate:
                outbound_candidate = state.transport_options[0]

        return_candidate = (
            getattr(state, "return_transport", None)
            or (state.recommendations.get("return_transport") if isinstance(state.recommendations, dict) else None)
            or (state.optimization.get("best_return_transport") if isinstance(state.optimization, dict) else None)
            or (outbound_candidate.get("return_trip") if isinstance(outbound_candidate, dict) else None)
        )
        if not return_candidate and state.transport_options:
            for opt in state.transport_options:
                if isinstance(opt, dict) and opt.get("journey_type") == "return":
                    return_candidate = opt
                    break

        raw_transport = outbound_candidate or {}
        hotel = getattr(state, "selected_hotel", None) or state.optimization.get("best_hotel") or (state.hotel_options[0] if state.hotel_options else {})

        # Safety check: Verify candidate transport status
        has_verified_transport = False
        transport = None
        if raw_transport and isinstance(raw_transport, dict):
            ver = raw_transport.get("verification")
            status = ver.get("status") if isinstance(ver, dict) else (raw_transport.get("verification_status") or raw_transport.get("status"))
            if status in ["verified", "available", "evidence_found", "not_checked", "pending"] or not status:
                has_verified_transport = True
                transport = raw_transport
            elif not ver and state.transport_options and raw_transport in state.transport_options:
                has_verified_transport = True
                transport = raw_transport
            elif state.transport_options:
                has_verified_transport = True
                transport = raw_transport

        if has_verified_transport and transport:
            outbound_departure = self._extract_transport_datetime(
                transport,
                start_date,
                (
                    "departure_datetime",
                    "departure",
                ),
                (
                    "departure_time",
                ),
            )

            arrival_datetime = self._extract_transport_datetime(
                transport,
                start_date,
                (
                    "arrival_datetime",
                    "arrival",
                ),
                (
                    "arrival_time",
                ),
                reference_datetime=outbound_departure,
            )

            return_departure = self._extract_transport_datetime(
                transport,
                end_date,
                (
                    "return_departure_datetime",
                    "return_departure",
                    "departure_return_time",
                ),
                (
                    "return_departure_time",
                ),
            )
        else:
            outbound_departure = None
            arrival_datetime = None
            return_departure = None

        # -----------------------------------------------------
        # Hotel check-in / check-out timing
        # -----------------------------------------------------

        hotel_check_in = self._extract_datetime(
            hotel,
            (
                "check_in_datetime",
                "check_in",
                "checkin",
            ),
        )

        hotel_check_out = self._extract_datetime(
            hotel,
            (
                "check_out_datetime",
                "check_out",
                "checkout",
            ),
        )

        # -----------------------------------------------------
        # Some transport providers keep the return journey in
        # a nested ``return_trip`` object.
        # -----------------------------------------------------

        return_trip_data = return_candidate if isinstance(return_candidate, dict) else None
        if not return_trip_data and isinstance(transport, dict):
            return_trip_data = transport.get("return_trip") or getattr(state, "return_transport", None)
        elif not return_trip_data and hasattr(transport, "model_dump"):
            transport_data = transport.model_dump(mode="python")
            return_trip_data = transport_data.get("return_trip") or getattr(state, "return_transport", None)

        if not return_trip_data and getattr(state, "return_transport", None):
            return_trip_data = getattr(state, "return_transport", None)

        if return_departure is None and isinstance(return_trip_data, dict):
            return_date = end_date

            journey_date = return_trip_data.get("journey_date")
            if journey_date:
                try:
                    return_date = datetime.fromisoformat(
                        str(journey_date)
                    ).date()
                except ValueError:
                    pass

            return_departure = self._extract_transport_datetime(
                return_trip_data,
                return_date,
                (
                    "departure_datetime",
                    "departure",
                ),
                (
                    "departure_time",
                ),
            )

        # -----------------------------------------------------
        # Keep timing information on state for downstream
        # validation.
        # -----------------------------------------------------

        state.selected_transport = (
            transport
            if (has_verified_transport and isinstance(transport, dict))
            else None
        )

        state.arrival_datetime = arrival_datetime
        state.departure_datetime = return_departure

        state.activity_start_datetime = (
            arrival_datetime + timedelta(hours=2, minutes=30)
            if arrival_datetime
            else None
        )

        state.activity_end_datetime = (
            return_departure - timedelta(hours=3)
            if return_departure
            else None
        )

        # -----------------------------------------------------
        # Transport mode detection for departure buffer
        # -----------------------------------------------------
        is_flight_departure = False
        if isinstance(return_trip_data, dict) and return_trip_data.get("type") == "flight":
            is_flight_departure = True
        elif isinstance(transport, dict) and transport.get("type") == "flight":
            is_flight_departure = True

        departure_buffer_hours = 3.5 if is_flight_departure else 2.5

        # -----------------------------------------------------
        # Extract transport class and fare per traveler
        # -----------------------------------------------------
        pref = getattr(state, "transport_preference", "train") or "train"
        b_cat = getattr(state, "budget_category", None)
        user_selected_class = getattr(state, "selected_class", None) or getattr(state, "travel_class", None)

        outbound_price, outbound_class_code, outbound_class_name = self._select_transport_fare_and_class(
            transport, budget_category=b_cat, default_mode=str(pref), selected_class=user_selected_class
        )
        return_price, return_class_code, return_class_name = self._select_transport_fare_and_class(
            return_trip_data if isinstance(return_trip_data, dict) else transport,
            budget_category=b_cat,
            default_mode=str(pref),
            selected_class=user_selected_class,
        )

        outbound_transport_price = outbound_price
        return_transport_price = return_price

        if isinstance(transport, dict):
            transport["selected_class"] = outbound_class_code
            transport["selected_class_name"] = outbound_class_name
            transport["class_name"] = outbound_class_name
            transport["class_code"] = outbound_class_code
            transport["price"] = outbound_transport_price

            if isinstance(transport.get("return_trip"), dict):
                transport["return_trip"]["selected_class"] = return_class_code
                transport["return_trip"]["selected_class_name"] = return_class_name
                transport["return_trip"]["class_name"] = return_class_name
                transport["return_trip"]["class_code"] = return_class_code
                transport["return_trip"]["price"] = return_transport_price

        import math

        # Extract station info for outbound and return transport
        outbound_orig_st, outbound_orig_code = self._extract_station_info(transport, is_origin=True, default_city=origin_name)
        outbound_dest_st, outbound_dest_code = self._extract_station_info(transport, is_origin=False, default_city=destination_name)

        ret_orig_st, ret_orig_code = self._extract_station_info(
            return_trip_data if isinstance(return_trip_data, dict) else {},
            is_origin=True,
            default_city=destination_name
        )
        ret_dest_st, ret_dest_code = self._extract_station_info(
            return_trip_data if isinstance(return_trip_data, dict) else {},
            is_origin=False,
            default_city=origin_name
        )

        needs_outbound_first_mile_transfer = bool(
            outbound_orig_st
            and outbound_orig_st.lower() not in origin_name.lower()
            and origin_name.lower() not in outbound_orig_st.lower()
        )
        needs_outbound_last_mile_transfer = bool(
            outbound_dest_st
            and outbound_dest_st.lower() not in destination_name.lower()
            and destination_name.lower() not in outbound_dest_st.lower()
        )
        needs_outbound_transfer = needs_outbound_last_mile_transfer
        needs_return_transfer = bool(
            ret_orig_st
            and ret_orig_st.lower() not in destination_name.lower()
            and destination_name.lower() not in ret_orig_st.lower()
        )

        outbound_first_mile_card = None
        if needs_outbound_first_mile_transfer or getattr(state, "first_mile_transfer", None) or (isinstance(transport, dict) and transport.get("first_mile_transfer")):
            trans_mode = "train" if "train" in str(transport.get("type", "")).lower() else "flight"
            hub_label = f"{outbound_orig_st} ({outbound_orig_code})" if outbound_orig_code else outbound_orig_st
            out_fm_data = (
                getattr(state, "first_mile_transfer", None)
                or getattr(state, "metadata", {}).get("first_mile_transfer")
                or (transport.get("first_mile_transfer") if isinstance(transport, dict) else None)
                or {}
            )

            from_pt = out_fm_data.get("from") or origin_name
            to_pt = out_fm_data.get("to") or outbound_orig_code or hub_label
            dist_km = out_fm_data.get("distance_km") or out_fm_data.get("road_distance_km")
            t_time = out_fm_data.get("duration") or out_fm_data.get("estimated_transfer_time")

            if (not dist_km or not t_time) and needs_outbound_first_mile_transfer:
                from app.resolvers.transfer_resolver import TransferResolver
                res_trans = TransferResolver().resolve_transfer(
                    origin_name,
                    hub_label,
                    transport_mode=trans_mode,
                    existing_distance_km=dist_km,
                )
                dist_km = dist_km or res_trans.get("road_distance_km") or res_trans.get("distance_km")
                t_time = t_time or res_trans.get("estimated_transfer_time") or res_trans.get("duration")

            if dist_km or t_time or out_fm_data:
                outbound_first_mile_card = {
                    "from": from_pt,
                    "to": to_pt,
                    "from_code": out_fm_data.get("from_code"),
                    "from_name": out_fm_data.get("from_name") or origin_name,
                    "to_code": out_fm_data.get("to_code") or outbound_orig_code,
                    "to_name": out_fm_data.get("to_name") or outbound_orig_st,
                    "station_code": out_fm_data.get("station_code") or outbound_orig_code,
                    "station_name": out_fm_data.get("station_name") or outbound_orig_st,
                    "hub_name": hub_label,
                    "transfer_point": hub_label,
                    "mode": "road_transfer",
                    "transfer_type": "Road Transfer",
                    "type": "transfer",
                    "road_distance_km": dist_km if dist_km else None,
                    "distance_km": dist_km if dist_km else None,
                    "duration": str(t_time) if (t_time and "None" not in str(t_time)) else None,
                    "estimated_transfer_time": str(t_time) if (t_time and "None" not in str(t_time)) else None,
                }

        outbound_transfer_card = None
        if needs_outbound_last_mile_transfer or getattr(state, "last_mile_transfer", None) or (isinstance(transport, dict) and (transport.get("last_mile_transfer") or transport.get("outbound_transfer"))):
            trans_mode = "train" if "train" in str(transport.get("type", "")).lower() else "flight"
            hub_label = f"{outbound_dest_st} ({outbound_dest_code})" if outbound_dest_code else outbound_dest_st
            out_trans_data = (
                getattr(state, "last_mile_transfer", None)
                or getattr(state, "metadata", {}).get("last_mile_transfer")
                or getattr(state, "outbound_transfer", None)
                or getattr(state, "metadata", {}).get("outbound_transfer")
                or (transport.get("last_mile_transfer") if isinstance(transport, dict) else None)
                or (transport.get("outbound_transfer") if isinstance(transport, dict) else None)
                or (transport.get("transfer") if isinstance(transport, dict) else None)
                or {}
            )

            from_pt = out_trans_data.get("from") or outbound_dest_code or hub_label
            to_pt = out_trans_data.get("to") or destination_name
            dist_km = out_trans_data.get("distance_km") or out_trans_data.get("road_distance_km")
            t_time = out_trans_data.get("duration") or out_trans_data.get("estimated_transfer_time")

            if not dist_km or not t_time:
                from app.resolvers.transfer_resolver import TransferResolver
                res_trans = TransferResolver().resolve_transfer(
                    hub_label,
                    destination_name,
                    transport_mode=trans_mode,
                    existing_distance_km=dist_km,
                )
                dist_km = dist_km or res_trans.get("road_distance_km") or res_trans.get("distance_km")
                t_time = t_time or res_trans.get("estimated_transfer_time") or res_trans.get("duration")

            if dist_km or t_time or out_trans_data:
                outbound_transfer_card = {
                    "from": from_pt,
                    "to": to_pt,
                    "from_code": out_trans_data.get("from_code") or outbound_dest_code,
                    "from_name": out_trans_data.get("from_name") or outbound_dest_st,
                    "to_code": out_trans_data.get("to_code"),
                    "to_name": out_trans_data.get("to_name") or destination_name,
                    "station_code": out_trans_data.get("station_code") or outbound_dest_code,
                    "station_name": out_trans_data.get("station_name") or outbound_dest_st,
                    "hub_name": hub_label,
                    "transfer_point": hub_label,
                    "mode": "road_transfer",
                    "transfer_type": "Road Transfer",
                    "type": "transfer",
                    "road_distance_km": dist_km if dist_km else None,
                    "distance_km": dist_km if dist_km else None,
                    "duration": str(t_time) if (t_time and "None" not in str(t_time)) else None,
                    "estimated_transfer_time": str(t_time) if (t_time and "None" not in str(t_time)) else None,
                }

        return_transfer_card = None
        if needs_return_transfer:
            ret_type = str(return_trip_data.get("type") if isinstance(return_trip_data, dict) else "").lower()
            main_type = str(transport.get("type", "")).lower() if isinstance(transport, dict) else ""
            trans_mode = "flight" if ("flight" in ret_type or "flight" in main_type) else "train"
            hub_label = f"{ret_orig_st} ({ret_orig_code})" if ret_orig_code else ret_orig_st
            ret_trans_data = (
                getattr(state, "return_transfer", None)
                or getattr(state, "metadata", {}).get("return_transfer")
                or (return_trip_data.get("return_transfer") if isinstance(return_trip_data, dict) else None)
                or (return_trip_data.get("transfer") if isinstance(return_trip_data, dict) else None)
                or {}
            )

            from_pt = ret_trans_data.get("from") or destination_name
            to_pt = ret_trans_data.get("to") or ret_orig_code or hub_label
            dist_km = ret_trans_data.get("distance_km") or ret_trans_data.get("road_distance_km")
            t_time = ret_trans_data.get("duration") or ret_trans_data.get("estimated_transfer_time")

            if not dist_km or not t_time:
                from app.resolvers.transfer_resolver import TransferResolver
                res_trans = TransferResolver().resolve_transfer(
                    destination_name,
                    hub_label,
                    transport_mode=trans_mode,
                    existing_distance_km=dist_km,
                )
                dist_km = dist_km or res_trans.get("road_distance_km") or res_trans.get("distance_km")
                t_time = t_time or res_trans.get("estimated_transfer_time") or res_trans.get("duration")

            return_transfer_card = {
                "from": from_pt,
                "to": to_pt,
                "from_code": ret_trans_data.get("from_code"),
                "from_name": ret_trans_data.get("from_name") or destination_name,
                "to_code": ret_trans_data.get("to_code") or ret_orig_code,
                "to_name": ret_trans_data.get("to_name") or ret_orig_st,
                "station_code": ret_trans_data.get("station_code") or ret_orig_code,
                "station_name": ret_trans_data.get("station_name") or ret_orig_st,
                "hub_name": hub_label,
                "transfer_point": hub_label,
                "mode": "road_transfer",
                "transfer_type": "Road Transfer",
                "type": "transfer",
                "road_distance_km": dist_km if dist_km else None,
                "distance_km": dist_km if dist_km else None,
                "duration": str(t_time) if (t_time and "None" not in str(t_time)) else None,
                "estimated_transfer_time": str(t_time) if (t_time and "None" not in str(t_time)) else None,
            }

        needs_return_last_mile_transfer = bool(
            ret_dest_st
            and ret_dest_st.lower() not in origin_name.lower()
            and origin_name.lower() not in ret_dest_st.lower()
        )
        return_last_mile_card = None
        if needs_return_last_mile_transfer or getattr(state, "return_last_mile_transfer", None) or (isinstance(return_trip_data, dict) and (return_trip_data.get("last_mile_transfer") or return_trip_data.get("return_last_mile_transfer"))):
            ret_type = str(return_trip_data.get("type") if isinstance(return_trip_data, dict) else "").lower()
            main_type = str(transport.get("type", "")).lower() if isinstance(transport, dict) else ""
            trans_mode = "flight" if ("flight" in ret_type or "flight" in main_type) else "train"
            hub_label = f"{ret_dest_st} ({ret_dest_code})" if ret_dest_code else ret_dest_st
            ret_lm_data = (
                getattr(state, "return_last_mile_transfer", None)
                or getattr(state, "metadata", {}).get("return_last_mile_transfer")
                or (return_trip_data.get("return_last_mile_transfer") if isinstance(return_trip_data, dict) else None)
                or (return_trip_data.get("last_mile_transfer") if isinstance(return_trip_data, dict) else None)
                or {}
            )

            from_pt = ret_lm_data.get("from") or ret_dest_code or hub_label
            to_pt = ret_lm_data.get("to") or origin_name
            dist_km = ret_lm_data.get("distance_km") or ret_lm_data.get("road_distance_km")
            t_time = ret_lm_data.get("duration") or ret_lm_data.get("estimated_transfer_time")

            if (not dist_km or not t_time) and needs_return_last_mile_transfer:
                from app.resolvers.transfer_resolver import TransferResolver
                res_trans = TransferResolver().resolve_transfer(
                    hub_label,
                    origin_name,
                    transport_mode=trans_mode,
                    existing_distance_km=dist_km,
                )
                dist_km = dist_km or res_trans.get("road_distance_km") or res_trans.get("distance_km")
                t_time = t_time or res_trans.get("estimated_transfer_time") or res_trans.get("duration")

            if dist_km or t_time or ret_lm_data:
                return_last_mile_card = {
                    "from": from_pt,
                    "to": to_pt,
                    "from_code": ret_lm_data.get("from_code") or ret_dest_code,
                    "from_name": ret_lm_data.get("from_name") or ret_dest_st,
                    "to_code": ret_lm_data.get("to_code"),
                    "to_name": ret_lm_data.get("to_name") or origin_name,
                    "station_code": ret_lm_data.get("station_code") or ret_dest_code,
                    "station_name": ret_lm_data.get("station_name") or ret_dest_st,
                    "hub_name": hub_label,
                    "transfer_point": hub_label,
                    "mode": "road_transfer",
                    "transfer_type": "Road Transfer",
                    "type": "transfer",
                    "road_distance_km": dist_km if dist_km else None,
                    "distance_km": dist_km if dist_km else None,
                    "duration": str(t_time) if (t_time and "None" not in str(t_time)) else None,
                    "estimated_transfer_time": str(t_time) if (t_time and "None" not in str(t_time)) else None,
                }

        # Transport mode defaults must be available before selected-hotel transfers.
        outbound_mode = getattr(state, "transport_preference", "train") or "train"
        ret_mode = outbound_mode

        # -----------------------------------------------------
        # Selected Base Hotel transfer override
        # -----------------------------------------------------
        # Once the user selects a hotel, destination-side transfers must
        # terminate at/start from that exact hotel, never the generic city.
        selected_hotel = getattr(state, "selected_hotel", None)

        # The hotel-selection endpoint may persist only a reduced hotel dict
        # (id/name/address). Recover the complete normalized hotel object from
        # state.hotel_options before resolving the transfer, so provider
        # coordinates are not lost between hotel selection and itinerary build.
        if isinstance(selected_hotel, dict):
            selected_hotel_id = selected_hotel.get("hotel_id") or selected_hotel.get("id")
            if selected_hotel_id and isinstance(getattr(state, "hotel_options", None), list):
                for hotel_option in state.hotel_options:
                    if not isinstance(hotel_option, dict):
                        continue
                    option_id = hotel_option.get("hotel_id") or hotel_option.get("id")
                    if str(option_id) == str(selected_hotel_id):
                        enriched_hotel = dict(hotel_option)
                        enriched_hotel.update(selected_hotel)
                        selected_hotel = enriched_hotel
                        break

            hotel_name = selected_hotel.get("hotel_name") or selected_hotel.get("name") or selected_hotel.get("address")
            hotel_coords = self._get_hotel_coordinates(selected_hotel)
            hotel_lat = hotel_coords[0] if hotel_coords else None
            hotel_lon = hotel_coords[1] if hotel_coords else None

            logger.info(
                "SELECTED HOTEL TRANSFER INPUT | hotel=%s | hotel_id=%s | lat=%s | lon=%s",
                hotel_name,
                selected_hotel.get("hotel_id") or selected_hotel.get("id"),
                hotel_lat,
                hotel_lon,
            )

            if hotel_name:
                from app.resolvers.transfer_resolver import TransferResolver
                resolver = TransferResolver()

                arrival_transfer = resolver.resolve_transfer(
                    outbound_dest_st,
                    hotel_name,
                    transport_mode="flight" if "flight" in str(outbound_mode).lower() else "train",
                    lat2=hotel_lat,
                    lon2=hotel_lon,
                )
                logger.info(
                    "SELECTED HOTEL ARRIVAL TRANSFER | %s -> %s | distance_km=%s | duration_minutes=%s | estimated=%s | source=%s",
                    outbound_dest_st,
                    hotel_name,
                    arrival_transfer.get("distance_km"),
                    arrival_transfer.get("duration_minutes"),
                    arrival_transfer.get("estimated_transfer_time"),
                    arrival_transfer.get("source"),
                )
                arrival_transfer.update({
                    "from": outbound_dest_st,
                    "to": hotel_name,
                    "from_name": outbound_dest_st,
                    "to_name": hotel_name,
                    "hotel_id": selected_hotel.get("hotel_id") or selected_hotel.get("id"),
                    "hotel_address": selected_hotel.get("address") or selected_hotel.get("location"),
                    "transfer_purpose": "arrival_to_selected_hotel",
                })
                outbound_transfer_card = arrival_transfer

                departure_transfer = resolver.resolve_transfer(
                    hotel_name,
                    ret_orig_st,
                    transport_mode="flight" if "flight" in str(ret_mode).lower() else "train",
                    lat1=hotel_lat,
                    lon1=hotel_lon,
                )
                logger.info(
                    "SELECTED HOTEL DEPARTURE TRANSFER | %s -> %s | distance_km=%s | duration_minutes=%s | estimated=%s | source=%s",
                    hotel_name,
                    ret_orig_st,
                    departure_transfer.get("distance_km"),
                    departure_transfer.get("duration_minutes"),
                    departure_transfer.get("estimated_transfer_time"),
                    departure_transfer.get("source"),
                )
                departure_transfer.update({
                    "from": hotel_name,
                    "to": ret_orig_st,
                    "from_name": hotel_name,
                    "to_name": ret_orig_st,
                    "hotel_id": selected_hotel.get("hotel_id") or selected_hotel.get("id"),
                    "hotel_address": selected_hotel.get("address") or selected_hotel.get("location"),
                    "transfer_purpose": "selected_hotel_to_return_station",
                })
                return_transfer_card = departure_transfer

        # -----------------------------------------------------
        # Calculate destination arrival and return transfer departure
        # -----------------------------------------------------
        train_arrival_datetime = arrival_datetime
        outbound_transfer_mins = 0
        if outbound_transfer_card:
            outbound_transfer_mins = outbound_transfer_card.get("duration_minutes") or 0
            if not outbound_transfer_mins and outbound_transfer_card.get("estimated_transfer_time"):
                t_str = str(outbound_transfer_card.get("estimated_transfer_time")).replace("~", "").strip()
                try:
                    if "h" in t_str:
                        parts = t_str.split("h")
                        h = int(parts[0].strip())
                        m = int(parts[1].replace("m", "").strip()) if len(parts) > 1 and parts[1].strip() else 0
                        outbound_transfer_mins = h * 60 + m
                    elif "m" in t_str:
                        outbound_transfer_mins = int(t_str.replace("m", "").strip())
                except Exception:
                    outbound_transfer_mins = 0

        if train_arrival_datetime and outbound_transfer_mins > 0:
            destination_arrival_datetime = train_arrival_datetime + timedelta(minutes=outbound_transfer_mins)
        else:
            destination_arrival_datetime = train_arrival_datetime

        # -----------------------------------------------------
        # Resolve the hotel stay from the ACTUAL destination arrival
        # date and the ACTUAL return transport departure date.
        # Example: depart Sep 13, arrive Goa Sep 14 -> hotel check-in Sep 14;
        # return train departs Sep 20 -> hotel checkout Sep 20.
        # -----------------------------------------------------
        hotel_check_in_date = (
            destination_arrival_datetime.date()
            if destination_arrival_datetime
            else (hotel_check_in.date() if hotel_check_in else start_date)
        )
        # Temporary fallback. Final checkout date is resolved after
        # the return transfer duration is known below.
        hotel_check_out_date = (
            return_departure.date()
            if return_departure
            else (hotel_check_out.date() if hotel_check_out else end_date)
        )

        if isinstance(hotel, dict):
            hotel["check_in"] = hotel_check_in_date.isoformat()
            hotel["check_out"] = hotel_check_out_date.isoformat()
            hotel["stay_nights"] = total_nights

        logger.info(
            "Resolved hotel stay | check_in=%s | check_out=%s | nights=%s",
            hotel_check_in_date,
            hotel_check_out_date,
            total_nights,
        )

        train_return_departure_datetime = return_departure
        return_transfer_mins = 0
        if return_transfer_card:
            return_transfer_mins = return_transfer_card.get("duration_minutes") or 0
            if not return_transfer_mins and return_transfer_card.get("estimated_transfer_time"):
                t_str = str(return_transfer_card.get("estimated_transfer_time")).replace("~", "").strip()
                try:
                    if "h" in t_str:
                        parts = t_str.split("h")
                        h = int(parts[0].strip())
                        m = int(parts[1].replace("m", "").strip()) if len(parts) > 1 and parts[1].strip() else 0
                        return_transfer_mins = h * 60 + m
                    elif "m" in t_str:
                        return_transfer_mins = int(t_str.replace("m", "").strip())
                except Exception:
                    return_transfer_mins = 0

        if train_return_departure_datetime and return_transfer_mins > 0:
            # Transfer duration + 60 min boarding buffer.
            # This is the actual time the traveler must leave the destination.
            required_destination_departure_datetime = train_return_departure_datetime - timedelta(minutes=return_transfer_mins + 60)
        else:
            required_destination_departure_datetime = train_return_departure_datetime

        # Hotel checkout follows the actual destination departure date.
        # A long overnight return transfer can therefore move checkout
        # to the previous calendar day.
        if required_destination_departure_datetime:
            hotel_check_out_date = required_destination_departure_datetime.date()

        if hotel_check_out_date <= hotel_check_in_date:
            hotel_check_out_date = hotel_check_in_date + timedelta(days=1)

        total_nights = max(1, (hotel_check_out_date - hotel_check_in_date).days)

        # Extract return arrival datetime
        return_arrival_datetime = None
        if isinstance(return_trip_data, dict) and return_trip_data:
            return_arrival_datetime = self._extract_transport_datetime(
                return_trip_data,
                train_return_departure_datetime.date() if train_return_departure_datetime else end_date,
                (
                    "arrival_datetime",
                    "arrival",
                ),
                (
                    "arrival_time",
                ),
                reference_datetime=train_return_departure_datetime,
            )
        elif isinstance(transport, dict) and transport:
            return_arrival_datetime = self._extract_transport_datetime(
                transport,
                train_return_departure_datetime.date() if train_return_departure_datetime else end_date,
                (
                    "return_arrival_datetime",
                    "return_arrival",
                ),
                (
                    "return_arrival_time",
                ),
                reference_datetime=train_return_departure_datetime,
            )

        return_last_mile_mins = 0
        if return_last_mile_card:
            return_last_mile_mins = return_last_mile_card.get("duration_minutes") or 0
            if not return_last_mile_mins and return_last_mile_card.get("estimated_transfer_time"):
                t_str = str(return_last_mile_card.get("estimated_transfer_time")).replace("~", "").strip()
                try:
                    if "h" in t_str:
                        parts = t_str.split("h")
                        h = int(parts[0].strip())
                        m = int(parts[1].replace("m", "").strip()) if len(parts) > 1 and parts[1].strip() else 0
                        return_last_mile_mins = h * 60 + m
                    elif "m" in t_str:
                        return_last_mile_mins = int(t_str.replace("m", "").strip())
                except Exception:
                    return_last_mile_mins = 0

        if return_arrival_datetime and return_last_mile_mins > 0:
            origin_final_arrival_datetime = return_arrival_datetime + timedelta(minutes=return_last_mile_mins)
        elif return_arrival_datetime:
            origin_final_arrival_datetime = return_arrival_datetime
        else:
            origin_final_arrival_datetime = None

        # Dynamically compute total days considering transport arrival dates
        max_trip_date = end_date
        if return_arrival_datetime and return_arrival_datetime.date() > max_trip_date:
            max_trip_date = return_arrival_datetime.date()
        if origin_final_arrival_datetime and origin_final_arrival_datetime.date() > max_trip_date:
            max_trip_date = origin_final_arrival_datetime.date()
        if destination_arrival_datetime and destination_arrival_datetime.date() > max_trip_date:
            max_trip_date = destination_arrival_datetime.date()

        total_days = max(1, (max_trip_date - start_date).days + 1)
        # total_nights was already resolved from actual destination arrival
        # and return departure above. Do not overwrite it with raw trip dates.

        # Keep timing information on state for downstream validation
        state.selected_transport = (
            transport
            if (has_verified_transport and isinstance(transport, dict))
            else None
        )

        state.arrival_datetime = destination_arrival_datetime
        state.train_arrival_datetime = train_arrival_datetime
        state.departure_datetime = return_departure
        state.destination_departure_datetime = required_destination_departure_datetime
        state.return_arrival_datetime = return_arrival_datetime

        state.activity_start_datetime = (
            destination_arrival_datetime + timedelta(hours=1, minutes=30)
            if destination_arrival_datetime
            else None
        )

        state.activity_end_datetime = (
            required_destination_departure_datetime - timedelta(hours=1)
            if required_destination_departure_datetime
            else None
        )

        # Required Debug logs immediately before itinerary construction:
        out_orig_code_log = (outbound_orig_code or (transport.get("from_station_code") or transport.get("from_code") or transport.get("origin") if isinstance(transport, dict) else "") or "")
        out_dest_code_log = (outbound_dest_code or (transport.get("to_station_code") or transport.get("to_code") or transport.get("destination") if isinstance(transport, dict) else "") or "")
        out_no_log = (transport.get("train_number") or transport.get("flight_number") or "") if isinstance(transport, dict) else ""
        out_name_log = (transport.get("train_name") or transport.get("flight_name") or transport.get("name") or "") if isinstance(transport, dict) else ""
        out_log_str = f"{out_orig_code_log} -> {out_dest_code_log} | {out_no_log} {out_name_log}".strip()

        ret_orig_code_log = (ret_orig_code or (return_trip_data.get("from_station_code") or return_trip_data.get("from_code") or return_trip_data.get("origin") if isinstance(return_trip_data, dict) else "") or "")
        ret_dest_code_log = (ret_dest_code or (return_trip_data.get("to_station_code") or return_trip_data.get("to_code") or return_trip_data.get("destination") if isinstance(return_trip_data, dict) else "") or "")
        ret_no_log = (return_trip_data.get("train_number") or return_trip_data.get("flight_number") or "") if isinstance(return_trip_data, dict) else ""
        ret_name_log = (return_trip_data.get("train_name") or return_trip_data.get("flight_name") or return_trip_data.get("name") or "") if isinstance(return_trip_data, dict) else ""
        ret_log_str = f"{ret_orig_code_log} -> {ret_dest_code_log} | {ret_no_log} {ret_name_log}".strip()

        print(f"\nOUTBOUND INPUT TO ITINERARY: {out_log_str}")
        print(f"RETURN INPUT TO ITINERARY: {ret_log_str}\n")

        # Print & log BUG 3 debug outputs
        print(f"[BUG3 DEBUG] USER ROUTE: Origin: {origin_name} | Destination: {destination_name}")
        print(f"[BUG3 DEBUG] OUTBOUND TRANSPORT: {outbound_orig_st} ({outbound_orig_code or 'N/A'}) -> {outbound_dest_st} ({outbound_dest_code or 'N/A'})")
        if outbound_transfer_card:
            print(f"[BUG3 DEBUG] OUTBOUND TRANSFER: {outbound_transfer_card['from']} -> {outbound_transfer_card['to']}")
        if return_transfer_card:
            print(f"[BUG3 DEBUG] RETURN TRANSFER: {return_transfer_card['from']} -> {return_transfer_card['to']}")
        if isinstance(return_trip_data, dict) and return_trip_data:
            print(f"[BUG3 DEBUG] RETURN TRANSPORT: {ret_orig_st} ({ret_orig_code or 'N/A'}) -> {ret_dest_st} ({ret_dest_code or 'N/A'})")

        logger.info(f"[BUG3 DEBUG] USER ROUTE: Origin: {origin_name} | Destination: {destination_name}")
        logger.info(f"[BUG3 DEBUG] OUTBOUND TRANSPORT: {outbound_orig_st} ({outbound_orig_code}) -> {outbound_dest_st} ({outbound_dest_code})")

        # -----------------------------------------------------
        # Pre-compute sightseeing days and geographic clusters
        # -----------------------------------------------------
        hotel_coords = self._get_place_coordinates(hotel)

        # Pre-compute arrival settlement window and return cutoff time
        arr_win_st, arr_win_en, arr_sightseeing_allowed, arr_reason = self._calculate_arrival_window(
            current_date=destination_arrival_datetime.date() if destination_arrival_datetime else start_date,
            destination_arrival_datetime=destination_arrival_datetime,
            train_arrival_datetime=train_arrival_datetime,
            outbound_departure=outbound_departure,
            outbound_transfer_mins=outbound_transfer_mins,
        )

        ret_cutoff_dt, ret_sightseeing_allowed, ret_reason = self._calculate_return_cutoff(
            current_date=train_return_departure_datetime.date() if train_return_departure_datetime else end_date,
            train_return_departure_datetime=train_return_departure_datetime,
            return_transfer_mins=return_transfer_mins,
            is_flight_departure=is_flight_departure,
        )

        sightseeing_day_numbers = []
        for d_num in range(1, total_days + 1):
            c_date = start_date + timedelta(days=d_num - 1)
            d_st = self._combine_date_time(c_date, 9, 30)
            d_en = self._combine_date_time(c_date, 20, 0)
            d_stat = "full_day"

            if outbound_departure and c_date == outbound_departure.date():
                if destination_arrival_datetime and destination_arrival_datetime.date() == c_date:
                    d_stat = "arrival_day"
                    if arr_sightseeing_allowed and arr_win_st and arr_win_en:
                        d_st = arr_win_st
                        d_en = arr_win_en
                    else:
                        d_st = d_en  # 0 activities
                else:
                    d_stat = "outbound_travel"
                    d_st = d_en
            elif destination_arrival_datetime and c_date < destination_arrival_datetime.date():
                d_stat = "in_transit"
                d_st = d_en
            elif destination_arrival_datetime and c_date == destination_arrival_datetime.date():
                d_stat = "arrival_day"
                if arr_sightseeing_allowed and arr_win_st and arr_win_en:
                    d_st = arr_win_st
                    d_en = arr_win_en
                else:
                    d_st = d_en  # 0 activities
            elif train_return_departure_datetime and c_date == train_return_departure_datetime.date():
                d_stat = "departure_day"
                if ret_sightseeing_allowed and ret_cutoff_dt:
                    d_st = self._combine_date_time(c_date, 9, 30)
                    d_en = min(d_en, ret_cutoff_dt)
                else:
                    d_st = d_en  # 0 activities
            elif train_return_departure_datetime and c_date > train_return_departure_datetime.date():
                d_stat = "post_trip"
                d_st = d_en

            if required_destination_departure_datetime and required_destination_departure_datetime.date() == c_date and d_stat not in ["departure_day", "post_trip"]:
                d_en = min(d_en, required_destination_departure_datetime - timedelta(minutes=60))

            if (d_stat not in ["outbound_travel", "in_transit", "return_arrival", "post_trip"]) and (d_st < d_en):
                sightseeing_day_numbers.append(d_num)

        num_sightseeing_days = max(1, len(sightseeing_day_numbers))

        # LLM decides logical place-to-day allocation.
        # Existing deterministic clustering remains the safety fallback.
        llm_day_allocation = self._llm_plan_places(
            state=state,
            places=unique_places,
            sightseeing_days=sightseeing_day_numbers,
            start_date=start_date,
            destination_name=destination_name,
        )

        deterministic_clusters = self._cluster_and_order_places(
            unique_places,
            num_sightseeing_days,
            hotel_coords=hotel_coords,
        )

        if llm_day_allocation:
            # Deterministic arrival-day safeguard: the LLM may still return an
            # empty arrival day even when a usable window exists. Select one
            # suitable light/nearby verified place so arrival-day behavior is
            # based on actual available time, not LLM preference alone.
            if arr_sightseeing_allowed and sightseeing_day_numbers:
                arrival_day_number = sightseeing_day_numbers[0]
                arrival_alloc = list(llm_day_allocation.get(arrival_day_number, []))
                if not arrival_alloc:
                    suitable_indexes = []
                    for idx, place in enumerate(unique_places):
                        if self._is_light_attraction(place, hotel_coords):
                            suitable_indexes.append(idx)
                    if suitable_indexes:
                        # Prefer the highest optimization score among suitable places.
                        best_idx = max(
                            suitable_indexes,
                            key=lambda i: self._safe_float(unique_places[i].get("optimization_score"))
                        )
                        llm_day_allocation[arrival_day_number] = [best_idx]
                        logger.info(
                            f"[ARRIVAL DAY] LLM left Day {arrival_day_number} empty; "
                            f"assigned one light nearby attraction: {unique_places[best_idx].get('name', 'Activity')}"
                        )

            daily_place_clusters = []
            place_by_index = {i: place for i, place in enumerate(unique_places)}
            for cluster_index, day_number in enumerate(sightseeing_day_numbers):
                llm_places = [
                    place_by_index[i]
                    for i in llm_day_allocation.get(day_number, [])
                    if i in place_by_index
                ]
                if llm_places:
                    daily_place_clusters.append(llm_places)
                elif cluster_index < len(deterministic_clusters):
                    daily_place_clusters.append(deterministic_clusters[cluster_index])

            if len(daily_place_clusters) < num_sightseeing_days:
                for cluster in deterministic_clusters:
                    if len(daily_place_clusters) >= num_sightseeing_days:
                        break
                    if cluster not in daily_place_clusters:
                        daily_place_clusters.append(cluster)

            logger.info("ITINERARY PLANNER: Using LLM-guided place allocation with deterministic fallback.")
        else:
            daily_place_clusters = deterministic_clusters
            logger.info("ITINERARY PLANNER: Using deterministic place allocation because LLM plan was unavailable.")

        # -----------------------------------------------------
        # STRUCTURED ITINERARY DECISION LOGS
        # -----------------------------------------------------
        print("\n==================================================")
        print("ITINERARY DECISION LOGS")
        print("==================================================")

        # 1. ARRIVAL BUFFER LOG
        if destination_arrival_datetime:
            dest_arr_str = destination_arrival_datetime.strftime("%H:%M")
            trans_str = f"{outbound_transfer_mins // 60}h {outbound_transfer_mins % 60:02d}m" if outbound_transfer_mins > 0 else "0m"
            is_overnight_trip = bool(outbound_departure and ((destination_arrival_datetime - outbound_departure).total_seconds() / 3600 >= 8.0 or outbound_departure.date() < destination_arrival_datetime.date()))
            rest_buf_str = "2h" if is_overnight_trip else "1h 30m"
            first_sight_str = arr_win_st.strftime("%H:%M") if (arr_sightseeing_allowed and arr_win_st) else "None (Rest / Arrival Day)"

            print("ITINERARY ARRIVAL BUFFER:")
            print(f"Destination arrival: {dest_arr_str}")
            print(f"Transfer: {trans_str}")
            print(f"Hotel/rest buffer: {rest_buf_str}")
            print(f"First possible sightseeing: {first_sight_str}\n")
            logger.info(f"ITINERARY ARRIVAL BUFFER: Destination arrival: {dest_arr_str} | Transfer: {trans_str} | Rest buffer: {rest_buf_str} | First possible: {first_sight_str}")

        # 2. CLUSTERING LOG
        print("ITINERARY CLUSTERING:")
        print(f"Verified places: {len(unique_places)}")
        print(f"Geographic groups: {len(daily_place_clusters)}\n")
        logger.info(f"ITINERARY CLUSTERING: Verified places: {len(unique_places)} | Geographic groups: {len(daily_place_clusters)}")

        # 3. RETURN CUTOFF LOG
        if train_return_departure_datetime:
            ret_dep_str = train_return_departure_datetime.strftime("%H:%M")
            ret_trans_str = f"{return_transfer_mins // 60}h {return_transfer_mins % 60:02d}m" if return_transfer_mins > 0 else "0m"
            ret_buf_str = f"{120 if is_flight_departure else 60}m station + 45m checkout + 30m safety"
            latest_sight_str = ret_cutoff_dt.strftime("%H:%M") if (ret_sightseeing_allowed and ret_cutoff_dt) else "None (Departure Day)"

            print("ITINERARY RETURN CUTOFF:")
            print(f"Return departure: {ret_dep_str}")
            print(f"Return transfer: {ret_trans_str}")
            print(f"Station/checkout buffer: {ret_buf_str}")
            print(f"Latest sightseeing end: {latest_sight_str}\n")
            logger.info(f"ITINERARY RETURN CUTOFF: Return departure: {ret_dep_str} | Transfer: {ret_trans_str} | Buffer: {ret_buf_str} | Latest end: {latest_sight_str}")

        # -----------------------------------------------------
        # Build realistic day windows.
        # -----------------------------------------------------

        itinerary_days = []
        scheduled_place_ids: set[str] = set()
        scheduled_place_names: set[tuple[str, str]] = set()
        unscheduled_queue: list[dict] = []
        cluster_cursor = 0

        outbound_mode, outbound_name = self._extract_transport_mode_and_name(
            transport,
            origin_name=origin_name,
            destination_name=destination_name,
            transport_pref=getattr(state, "transport_preference", "train"),
            is_return=False,
        ) if has_verified_transport and transport else ("Train", "Train")

        outbound_dep = (transport.get("departure") or transport.get("departure_time")) if isinstance(transport, dict) else None
        outbound_arr = (transport.get("arrival") or transport.get("arrival_time")) if isinstance(transport, dict) else None

        if outbound_dep and "T" in str(outbound_dep):
            outbound_dep_time = str(outbound_dep).split("T")[1][:5]
        else:
            outbound_dep_time = str(outbound_dep)[:5] if outbound_dep else (outbound_departure.strftime("%H:%M") if outbound_departure else "12:00")

        if outbound_arr and "T" in str(outbound_arr):
            outbound_arr_time = str(outbound_arr).split("T")[1][:5]
        else:
            outbound_arr_time = str(outbound_arr)[:5] if outbound_arr else (train_arrival_datetime.strftime("%H:%M") if train_arrival_datetime else "14:15")

        outbound_route_str = (
            f"{outbound_orig_st} ({outbound_orig_code}) -> {outbound_dest_st} ({outbound_dest_code})"
            if outbound_orig_code and outbound_dest_code
            else f"{outbound_orig_st} -> {outbound_dest_st}"
        )

        ret_ver = return_trip_data.get("verification") if isinstance(return_trip_data, dict) and isinstance(return_trip_data.get("verification"), dict) else {}
        ret_ver_status = (
            ret_ver.get("status")
            or (return_trip_data.get("verification_status") if isinstance(return_trip_data, dict) else None)
            or (return_trip_data.get("status") if isinstance(return_trip_data, dict) else None)
        )
        is_ret_verified = bool(
            isinstance(return_trip_data, dict)
            and return_trip_data
            and (ret_ver_status in ["verified", "available", "evidence_found"] or not ret_ver_status)
        )

        ret_mode, ret_name = self._extract_transport_mode_and_name(
            return_trip_data if isinstance(return_trip_data, dict) else (transport if isinstance(transport, dict) else {}),
            origin_name=origin_name,
            destination_name=destination_name,
            transport_pref=getattr(state, "transport_preference", "train"),
            is_return=True,
        ) if has_verified_transport and transport and is_ret_verified else ("Train", "Train")

        ret_dep = (
            return_trip_data.get("departure") or return_trip_data.get("departure_time")
        ) if isinstance(return_trip_data, dict) else None
        if not ret_dep and train_return_departure_datetime:
            ret_dep = train_return_departure_datetime.strftime("%H:%M")

        ret_arr = (
            return_trip_data.get("arrival") or return_trip_data.get("arrival_time")
        ) if isinstance(return_trip_data, dict) else None
        if not ret_arr and return_arrival_datetime:
            ret_arr = return_arrival_datetime.strftime("%H:%M")

        if ret_dep and "T" in str(ret_dep):
            ret_dep_time = str(ret_dep).split("T")[1][:5]
        else:
            ret_dep_time = str(ret_dep)[:5] if ret_dep else (train_return_departure_datetime.strftime("%H:%M") if train_return_departure_datetime else "")

        if ret_arr and "T" in str(ret_arr):
            ret_arr_time = str(ret_arr).split("T")[1][:5]
        else:
            ret_arr_time = str(ret_arr)[:5] if ret_arr else (return_arrival_datetime.strftime("%H:%M") if return_arrival_datetime else "")

        ret_route_str = (
            f"{ret_orig_st} ({ret_orig_code}) -> {ret_dest_st} ({ret_dest_code})"
            if ret_orig_code and ret_dest_code
            else f"{ret_orig_st} -> {ret_dest_st}"
        )

        for day_number in range(1, total_days + 1):
            current_date = start_date + timedelta(days=day_number - 1)

            day_start = self._combine_date_time(current_date, 9, 30)
            day_end = self._combine_date_time(current_date, 20, 0)
            day_status = "full_day"
            travel_constraint = None
            day_transport = None

            # Mutually exclusive travel condition checks strictly anchored to event dates
            is_outbound_dep_day = bool(outbound_departure and current_date == outbound_departure.date())
            is_outbound_arr_day = bool(destination_arrival_datetime and current_date == destination_arrival_datetime.date())
            is_in_transit_day = bool(
                outbound_departure
                and destination_arrival_datetime
                and outbound_departure.date() < current_date < destination_arrival_datetime.date()
            )
            is_return_dep_day = bool(train_return_departure_datetime and current_date == train_return_departure_datetime.date())
            # A long destination-to-station transfer can require leaving the
            # destination on the previous calendar day. That date is a real
            # departure/checkout day, not a false leisure day.
            is_destination_departure_day = bool(
                required_destination_departure_datetime
                and current_date == required_destination_departure_datetime.date()
                and not is_return_dep_day
            )
            is_return_arr_day = bool(
                return_arrival_datetime
                and current_date == return_arrival_datetime.date()
                and (not train_return_departure_datetime or return_arrival_datetime.date() > train_return_departure_datetime.date())
            )
            is_post_trip_day = bool(
                train_return_departure_datetime
                and current_date > train_return_departure_datetime.date()
                and not is_return_arr_day
            )

            # -------------------------------------------------
            # STRUCTURED TRANSPORT EVENT & DAY ASSIGNMENT
            # -------------------------------------------------

            # CASE A: Same-day outbound travel (Departure & Destination Arrival on same calendar date)
            if is_outbound_dep_day and is_outbound_arr_day:
                day_status = "arrival_day"
                if arr_sightseeing_allowed and arr_win_st and arr_win_en:
                    day_start = arr_win_st
                    day_end = arr_win_en
                else:
                    day_start = day_end  # 0 activities (Arrival + Rest)

                if has_verified_transport and transport:
                    self._log_transport_event("Outbound Departure", outbound_departure, start_date, day_number)
                    self._log_transport_event("Train Arrival" if "train" in outbound_mode.lower() else "Flight Arrival", train_arrival_datetime, start_date, day_number)
                    self._log_transport_event("Destination Arrival", destination_arrival_datetime, start_date, day_number)

                    day_transport = {
                        "type": "outbound",
                        "mode": outbound_mode,
                        "name": outbound_name,
                        "class_name": outbound_class_name,
                        "selected_class": outbound_class_code,
                        "user_origin": origin_name,
                        "user_destination": destination_name,
                        "origin_station": outbound_orig_st,
                        "origin_station_code": outbound_orig_code,
                        "destination_station": outbound_dest_st,
                        "destination_station_code": outbound_dest_code,
                        "route": outbound_route_str,
                        "origin": f"{outbound_orig_st} ({outbound_orig_code})" if outbound_orig_code else outbound_orig_st,
                        "destination": f"{outbound_dest_st} ({outbound_dest_code})" if outbound_dest_code else outbound_dest_st,
                        "departure": outbound_dep_time,
                        "arrival": outbound_arr_time,
                        "departure_datetime": outbound_departure.isoformat() if outbound_departure else None,
                        "arrival_datetime": train_arrival_datetime.isoformat() if train_arrival_datetime else None,
                        "destination_arrival": destination_arrival_datetime.strftime("%H:%M") if destination_arrival_datetime else None,
                        "destination_arrival_datetime": destination_arrival_datetime.isoformat() if destination_arrival_datetime else None,
                    }
                    if outbound_first_mile_card:
                        day_transport["first_mile_transfer"] = outbound_first_mile_card
                    if outbound_transfer_card:
                        day_transport["last_mile_transfer"] = outbound_transfer_card
                        day_transport["transfer"] = outbound_transfer_card
                        fm_str = f"Road transfer from {outbound_first_mile_card['from']} to {outbound_first_mile_card['to']} (~{outbound_first_mile_card.get('estimated_transfer_time', '1h')}). " if outbound_first_mile_card else ""
                        travel_constraint = (
                            f"{fm_str}Outbound travel from {outbound_orig_st} ({outbound_orig_code or origin_name}) to {outbound_dest_st} ({outbound_dest_code or destination_name}) "
                            f"on {outbound_name} [{outbound_class_name}] (Departure: {outbound_dep_time}, Train Arrival at {outbound_dest_code}: {outbound_arr_time}). "
                            f"Road transfer from {outbound_transfer_card['from']} to {outbound_transfer_card['to']} (~{outbound_transfer_card.get('estimated_transfer_time', '1h')}). "
                            f"Destination arrival at approximately {destination_arrival_datetime.strftime('%H:%M') if destination_arrival_datetime else '15:00'}."
                        )
                    else:
                        fm_str = f"Road transfer from {outbound_first_mile_card['from']} to {outbound_first_mile_card['to']}. " if outbound_first_mile_card else ""
                        travel_constraint = (
                            f"{fm_str}Outbound travel from {outbound_orig_st} to {outbound_dest_st} on {outbound_name} [{outbound_class_name}] "
                            f"(Departure: {outbound_dep_time}, Arrival: {outbound_arr_time})."
                        )
                else:
                    day_transport = None
                    travel_constraint = (
                        f"Outbound travel from {origin_name} to {destination_name}: "
                        f"Transport could not be verified online. No candidate train/flight available."
                    )

            # CASE B: Overnight outbound departure day (Departs today, arrives next calendar date)
            elif is_outbound_dep_day and not is_outbound_arr_day:
                day_status = "outbound_travel"
                day_start = day_end  # 0 activities on departure day

                if has_verified_transport and transport:
                    self._log_transport_event("Outbound Departure", outbound_departure, start_date, day_number)

                    day_transport = {
                        "type": "outbound",
                        "mode": outbound_mode,
                        "name": outbound_name,
                        "class_name": outbound_class_name,
                        "selected_class": outbound_class_code,
                        "user_origin": origin_name,
                        "user_destination": destination_name,
                        "origin_station": outbound_orig_st,
                        "origin_station_code": outbound_orig_code,
                        "destination_station": outbound_dest_st,
                        "destination_station_code": outbound_dest_code,
                        "route": outbound_route_str,
                        "origin": f"{outbound_orig_st} ({outbound_orig_code})" if outbound_orig_code else outbound_orig_st,
                        "destination": f"{outbound_dest_st} ({outbound_dest_code})" if outbound_dest_code else outbound_dest_st,
                        "departure": outbound_dep_time,
                        "arrival": outbound_arr_time,
                        "departure_datetime": outbound_departure.isoformat() if outbound_departure else None,
                        "arrival_datetime": train_arrival_datetime.isoformat() if train_arrival_datetime else None,
                        "is_overnight": True,
                    }
                    if outbound_first_mile_card:
                        day_transport["first_mile_transfer"] = outbound_first_mile_card
                    if outbound_transfer_card:
                        day_transport["last_mile_transfer"] = outbound_transfer_card
                    arr_day_calc = (train_arrival_datetime.date() - start_date).days + 1 if train_arrival_datetime else 2
                    fm_str = f"Road transfer from {outbound_first_mile_card['from']} to {outbound_first_mile_card['to']} (~{outbound_first_mile_card.get('estimated_transfer_time', '1h')}). " if outbound_first_mile_card else ""
                    travel_constraint = (
                        f"{fm_str}Outbound travel from {outbound_orig_st} ({outbound_orig_code or origin_name}) to {outbound_dest_st} ({outbound_dest_code or destination_name}) "
                        f"on {outbound_name} [{outbound_class_name}] (Departure: {outbound_dep_time}). "
                        f"Overnight journey in transit. Arrival at {outbound_dest_st} ({outbound_dest_code}) on Day {arr_day_calc} at {outbound_arr_time}."
                    )
                else:
                    day_transport = None
                    travel_constraint = (
                        f"Outbound travel from {origin_name} to {destination_name}: "
                        f"Transport could not be verified online. No candidate train/flight available."
                    )

            # CASE C: Multi-day in-transit day
            elif is_in_transit_day:
                day_status = "in_transit"
                day_start = day_end
                travel_constraint = f"In transit on {outbound_name}. Multi-day journey in progress towards {outbound_dest_st} ({outbound_dest_code})."

            # CASE D: Overnight outbound arrival day (Train arrives today, last-mile transfer to destination)
            elif is_outbound_arr_day and not is_outbound_dep_day:
                day_status = "arrival_day"
                if arr_sightseeing_allowed and arr_win_st and arr_win_en:
                    day_start = arr_win_st
                    day_end = arr_win_en
                else:
                    day_start = day_end  # 0 activities (Arrival + Rest)

                if has_verified_transport and transport:
                    self._log_transport_event("Train Arrival" if "train" in outbound_mode.lower() else "Flight Arrival", train_arrival_datetime, start_date, day_number)
                    self._log_transport_event("Destination Arrival", destination_arrival_datetime, start_date, day_number)

                    day_transport = {
                        "type": "outbound_arrival",
                        "mode": outbound_mode,
                        "name": outbound_name,
                        "user_origin": origin_name,
                        "user_destination": destination_name,
                        "origin_station": outbound_orig_st,
                        "origin_station_code": outbound_orig_code,
                        "destination_station": outbound_dest_st,
                        "destination_station_code": outbound_dest_code,
                        "arrival": outbound_arr_time,
                        "arrival_datetime": train_arrival_datetime.isoformat() if train_arrival_datetime else None,
                        "destination_arrival": destination_arrival_datetime.strftime("%H:%M") if destination_arrival_datetime else None,
                        "destination_arrival_datetime": destination_arrival_datetime.isoformat() if destination_arrival_datetime else None,
                    }
                    if outbound_transfer_card:
                        day_transport["transfer"] = outbound_transfer_card
                        travel_constraint = (
                            f"Train arrives at {outbound_dest_st} ({outbound_dest_code}) at {train_arrival_datetime.strftime('%H:%M') if train_arrival_datetime else outbound_arr_time}. "
                            f"Road transfer from {outbound_transfer_card['from']} to {outbound_transfer_card['to']} (~{outbound_transfer_card.get('estimated_transfer_time', '9h')}). "
                            f"Destination arrival at approximately {destination_arrival_datetime.strftime('%H:%M') if destination_arrival_datetime else '22:00'}. Hotel check-in and rest."
                        )
                    else:
                        travel_constraint = (
                            f"Arrival at destination station {outbound_dest_st} ({outbound_dest_code}) at {outbound_arr_time}. Hotel check-in and rest."
                        )

            # CASE E0: Destination departure day before the return transport date.
            elif is_destination_departure_day:
                day_status = "departure_day"
                destination_departure_cutoff = required_destination_departure_datetime - timedelta(minutes=60)
                if destination_departure_cutoff and destination_departure_cutoff > self._combine_date_time(current_date, 11, 30):
                    day_start = self._combine_date_time(current_date, 9, 30)
                    day_end = min(day_end, destination_departure_cutoff)
                else:
                    day_start = day_end

                day_transport = {
                    "type": "return_transfer_departure",
                    "mode": "road",
                    "user_origin": destination_name,
                    "user_destination": origin_name,
                    "departure_datetime": required_destination_departure_datetime.isoformat(),
                    "departure": required_destination_departure_datetime.strftime("%H:%M"),
                }
                if return_transfer_card:
                    day_transport["transfer"] = return_transfer_card
                    day_transport["first_mile_transfer"] = return_transfer_card
                travel_constraint = (
                    f"Traveler leaves {destination_name} by ~{required_destination_departure_datetime.strftime('%H:%M')} "
                    f"to reach {ret_orig_st} ({ret_orig_code}) for the return transport."
                )

            # CASE E: Return departure day (Journey starts today)
            elif is_return_dep_day:
                day_status = "departure_day"
                if ret_sightseeing_allowed and ret_cutoff_dt:
                    day_start = self._combine_date_time(current_date, 9, 30)
                    day_end = min(day_end, ret_cutoff_dt)
                else:
                    day_start = day_end  # 0 activities on departure day

                if has_verified_transport and transport and is_ret_verified:
                    self._log_transport_event("Return Departure", train_return_departure_datetime, start_date, day_number)
                    if return_arrival_datetime and return_arrival_datetime.date() == train_return_departure_datetime.date():
                        self._log_transport_event("Return Arrival", return_arrival_datetime, start_date, day_number)
                        self._log_transport_event("Final Origin Arrival", origin_final_arrival_datetime or return_arrival_datetime, start_date, day_number)

                    day_transport = {
                        "type": "return",
                        "mode": ret_mode,
                        "name": ret_name,
                        "class_name": return_class_name,
                        "selected_class": return_class_code,
                        "user_origin": destination_name,
                        "user_destination": origin_name,
                        "origin_station": ret_orig_st,
                        "origin_station_code": ret_orig_code,
                        "destination_station": ret_dest_st,
                        "destination_station_code": ret_dest_code,
                        "route": ret_route_str,
                        "origin": f"{ret_orig_st} ({ret_orig_code})" if ret_orig_code else ret_orig_st,
                        "destination": f"{ret_dest_st} ({ret_dest_code})" if ret_dest_code else ret_dest_st,
                        "departure": ret_dep_time,
                        "arrival": ret_arr_time,
                        "departure_datetime": train_return_departure_datetime.isoformat() if train_return_departure_datetime else None,
                        "arrival_datetime": return_arrival_datetime.isoformat() if return_arrival_datetime else None,
                        "is_overnight": bool(return_arrival_datetime and return_arrival_datetime.date() > train_return_departure_datetime.date()),
                    }
                    if return_transfer_card:
                        day_transport["first_mile_transfer"] = return_transfer_card
                        day_transport["transfer"] = return_transfer_card
                        travel_constraint = (
                            f"Road transfer from {return_transfer_card['from']} to {return_transfer_card['to']} (~{return_transfer_card.get('estimated_transfer_time', '9h')}). "
                            f"Traveler departs destination by ~{required_destination_departure_datetime.strftime('%H:%M') if required_destination_departure_datetime else '21:30'} to reach {ret_orig_st} ({ret_orig_code}) before {ret_dep_time}. "
                            f"Return train {ret_name} departs {ret_orig_st} at {ret_dep_time} (Arrival at {ret_dest_st}: {ret_arr_time})."
                        )
                    else:
                        travel_constraint = (
                            f"Return travel from {ret_orig_st} to {ret_dest_st} on {ret_name} [{return_class_name}] "
                            f"(Departure: {ret_dep_time}, Arrival: {ret_arr_time})."
                        )
                    if not day_transport["is_overnight"] and return_last_mile_card:
                        day_transport["last_mile_transfer"] = return_last_mile_card
                    elif return_last_mile_card:
                        day_transport["last_mile_transfer"] = return_last_mile_card
                else:
                    day_transport = None
                    travel_constraint = (
                        f"Return travel from {destination_name} to {origin_name}: "
                        f"Transport could not be verified online. Return transport is unavailable."
                    )

            # CASE F: Return overnight arrival day (Train arrives today at origin station)
            elif is_return_arr_day:
                day_status = "return_arrival"
                day_start = day_end  # 0 activities

                if has_verified_transport and transport and is_ret_verified:
                    self._log_transport_event("Return Arrival", return_arrival_datetime, start_date, day_number)
                    self._log_transport_event("Final Origin Arrival", origin_final_arrival_datetime or return_arrival_datetime, start_date, day_number)

                    day_transport = {
                        "type": "return_arrival",
                        "mode": ret_mode,
                        "name": ret_name,
                        "user_origin": destination_name,
                        "user_destination": origin_name,
                        "origin_station": ret_orig_st,
                        "origin_station_code": ret_orig_code,
                        "destination_station": ret_dest_st,
                        "destination_station_code": ret_dest_code,
                        "arrival": ret_arr_time,
                        "arrival_datetime": return_arrival_datetime.isoformat() if return_arrival_datetime else None,
                        "origin_final_arrival": origin_final_arrival_datetime.strftime("%H:%M") if origin_final_arrival_datetime else None,
                        "origin_final_arrival_datetime": origin_final_arrival_datetime.isoformat() if origin_final_arrival_datetime else None,
                    }
                    if return_last_mile_card:
                        day_transport["transfer"] = return_last_mile_card
                        travel_constraint = (
                            f"Return {ret_mode.lower()} arrives at {ret_dest_st} ({ret_dest_code}) at {ret_arr_time}. "
                            f"Road transfer from {return_last_mile_card['from']} to {return_last_mile_card['to']} (~{return_last_mile_card.get('estimated_transfer_time', '1h')}). "
                            f"Final arrival at {origin_name}. Journey completed."
                        )
                    else:
                        travel_constraint = (
                            f"Return {ret_mode.lower()} arrives at {ret_dest_st} ({ret_dest_code}) at {ret_arr_time}. Final arrival at {origin_name}. Journey completed."
                        )

            # CASE G: Post-trip day
            elif is_post_trip_day:
                day_status = "post_trip"
                day_start = day_end
                travel_constraint = "Post-trip. Return journey completed."

            # CASE H: Check if required destination departure occurs during this day (e.g. Day 7 evening transfer before Day 8 morning train)
            if required_destination_departure_datetime and required_destination_departure_datetime.date() == current_date and not is_return_dep_day and not is_post_trip_day:
                day_end = min(day_end, required_destination_departure_datetime - timedelta(minutes=60))
                if return_transfer_card:
                    travel_constraint = (
                        f"Sightseeing concludes by {day_end.strftime('%H:%M')}. "
                        f"Evening/Overnight road transfer to {return_transfer_card['to']} begins by {required_destination_departure_datetime.strftime('%H:%M')} "
                        f"to catch return train departing at {train_return_departure_datetime.strftime('%H:%M') if train_return_departure_datetime else ''}."
                    )

            # =================================================
            # PROXIMITY-BASED SIGHTSEEING ACTIVITY SCHEDULING
            # =================================================

            activities = []
            is_sightseeing_day = (day_number in sightseeing_day_numbers) and (day_start < day_end)

            if is_sightseeing_day:
                candidate_places = []
                # Priority 1: Unscheduled places carried over from previous day
                if unscheduled_queue:
                    candidate_places.extend(unscheduled_queue)
                    unscheduled_queue = []

                # Priority 2: Next geographic cluster from pool
                if cluster_cursor < len(daily_place_clusters):
                    candidate_places.extend(daily_place_clusters[cluster_cursor])
                    cluster_cursor += 1

                # Capacity-aware fallback: an LLM may spread one place across
                # several days even when another verified place can fit today.
                # Supplement the current cluster with remaining places so the
                # deterministic scheduler, not the LLM, remains final authority.
                scheduled_keys = set(scheduled_place_ids) | {
                    f"{n[0]}|{n[1]}" for n in scheduled_place_names
                }
                if len(candidate_places) < 2:
                    for extra in unique_places:
                        extra_pid = str(extra.get("place_id") or "").strip().lower()
                        extra_name = self._normalize_place_name(extra.get("name", "Activity")).lower()
                        extra_city = str(extra.get("city") or destination_name).strip().lower()
                        extra_key = f"{extra_name}|{extra_city}"
                        if extra_pid and extra_pid in scheduled_place_ids:
                            continue
                        if extra_key in scheduled_keys:
                            continue
                        if any(
                            str(c.get("place_id") or "").strip().lower() == extra_pid
                            or self._normalize_place_name(c.get("name", "Activity")).lower() == extra_name
                            for c in candidate_places
                        ):
                            continue
                        candidate_places.append(extra)
                        if len(candidate_places) >= 2:
                            break

                cursor = day_start
                prev_place = None

                # Max daily activities:
                if day_status == "arrival_day":
                    max_daily_activities = 1 if arr_sightseeing_allowed else 0
                elif day_status == "departure_day":
                    if not ret_sightseeing_allowed:
                        max_daily_activities = 0
                    elif (day_end - day_start).total_seconds() / 3600 >= 5.0 and (total_days <= 2 or num_sightseeing_days <= 2):
                        max_daily_activities = 2
                    else:
                        max_daily_activities = 1
                elif num_sightseeing_days <= 2:
                    max_daily_activities = 3 if len(unique_places) > 3 else 2
                else:
                    max_daily_activities = 2

                for place in candidate_places:
                    if len(activities) >= max_daily_activities:
                        unscheduled_queue.append(place)
                        continue

                    # On arrival day or short departure day: strictly require light nearby attraction
                    if day_status == "arrival_day":
                        if not self._is_light_attraction(place, hotel_coords):
                            unscheduled_queue.append(place)
                            continue
                    elif day_status == "departure_day":
                        # If window is short (< 4h available before departure), require light attraction
                        if (day_end - day_start).total_seconds() / 3600 < 4.0:
                            if not self._is_light_attraction(place, hotel_coords):
                                unscheduled_queue.append(place)
                                continue

                    pid = str(place.get("place_id") or "").strip().lower()
                    clean_name = self._normalize_place_name(place.get("name", "Activity"))
                    p_name_lower = clean_name.lower()
                    p_city_lower = str(place.get("city") or destination_name).strip().lower()
                    name_key = (p_name_lower, p_city_lower)

                    # Deduplication check: Never schedule duplicate place across any days
                    if (pid and pid in scheduled_place_ids) or (p_name_lower and name_key in scheduled_place_names):
                        continue

                    transit_min = 0
                    if prev_place is not None:
                        transit_min = self._calculate_transit_minutes(prev_place, place)
                        # Distance sanity check between same-day activities
                        c_prev = self._get_place_coordinates(prev_place)
                        c_curr = self._get_place_coordinates(place)
                        if c_prev and c_curr and self._haversine_distance(c_prev, c_curr) > 12.0:
                            # Too far for same day -> save for next day
                            unscheduled_queue.append(place)
                            continue

                    duration_min = self._get_activity_duration(place)
                    activity_start = cursor + timedelta(minutes=transit_min)

                    # Realistic meal break buffer on full sightseeing days:
                    # If an activity would start during lunchtime (12:00 - 13:45) and an activity was already done in the morning,
                    # add a 45-minute lunch break!
                    if len(activities) >= 1 and (12 <= activity_start.hour < 14):
                        activity_start += timedelta(minutes=45)

                    activity_end = activity_start + timedelta(minutes=duration_min)

                    if activity_end <= day_end and len(activities) < max_daily_activities:
                        dur_hours = duration_min // 60
                        dur_mins = duration_min % 60
                        dur_str = f"{dur_hours}h {dur_mins:02d}m" if dur_hours > 0 else f"{dur_mins} mins"
                        p_coord = self._get_place_coordinates(place)

                        activities.append(
                            {
                                "place_id": place.get("place_id"),
                                "name": clean_name,
                                "date": str(current_date),
                                "start_time": activity_start.strftime("%H:%M"),
                                "duration_minutes": duration_min,
                                "duration": dur_str,
                                "category": place.get("category"),
                                "description": place.get("description") or place.get("formatted"),
                                "estimated_cost": "Not included",
                                "optimization_score": place.get("optimization_score", 0),
                                "latitude": p_coord[0] if p_coord else None,
                                "longitude": p_coord[1] if p_coord else None,
                            }
                        )

                        if pid:
                            scheduled_place_ids.add(pid)
                        if p_name_lower:
                            scheduled_place_names.add(name_key)

                        cursor = activity_end
                        prev_place = place
                    else:
                        # Place cannot fit on current day -> return to unscheduled_queue for next sightseeing day
                        unscheduled_queue.append(place)

                # Debug logging of geographic cluster and inter-place distances
                cluster_label_num = cluster_cursor
                if len(activities) >= 2:
                    dist_descriptions = []
                    for k in range(len(activities) - 1):
                        c_a = (activities[k].get("latitude"), activities[k].get("longitude"))
                        c_b = (activities[k + 1].get("latitude"), activities[k + 1].get("longitude"))
                        if c_a[0] is not None and c_b[0] is not None and c_a[1] is not None and c_b[1] is not None:
                            d_km = self._haversine_distance(c_a, c_b)
                            dist_descriptions.append(f"{d_km:.1f} km ({activities[k]['name']} -> {activities[k + 1]['name']})")
                        else:
                            dist_descriptions.append(f"~2.0 km ({activities[k]['name']} -> {activities[k + 1]['name']})")
                    dist_summary = ", ".join(dist_descriptions)
                    print(f"Day {day_number}:")
                    print(f"Places: {', '.join([a['name'] for a in activities])}")
                    print(f"Approx geographic distance between places: {dist_summary}")
                    print(f"Cluster/group: Cluster {cluster_label_num}")
                    print()
                    logger.info(f"Day {day_number}: Places: {', '.join([a['name'] for a in activities])} | Approx dist: {dist_summary} | Cluster: {cluster_label_num}")
                elif len(activities) == 1:
                    print(f"Day {day_number}:")
                    print(f"Places: {activities[0]['name']}")
                    print(f"Approx geographic distance between places: N/A (Single attraction)")
                    print(f"Cluster/group: Cluster {cluster_label_num}")
                    print()
                    logger.info(f"Day {day_number}: Places: {activities[0]['name']} | Single attraction | Cluster: {cluster_label_num}")

            if not activities and not day_transport and day_status not in ["outbound_travel", "departure_day", "return_arrival", "in_transit", "post_trip"]:
                day_status = "leisure"
                if not travel_constraint:
                    travel_constraint = "Leisure / Rest / Flexible Day — Free time for personal exploration, shopping at local bazaars, sampling regional cuisine, and relaxation."

            # Store current day
            itinerary_days.append(
                {
                    "day": day_number,
                    "date": str(current_date),
                    "status": day_status,
                    "travel_constraint": travel_constraint,
                    "transport": day_transport,
                    "activities": activities,
                }
            )

        # Second pass: If any places remain in unscheduled_queue, assign them ONLY to available full_day sightseeing days that have capacity and are geographically close
        if unscheduled_queue:
            for day_dict in itinerary_days:
                if not unscheduled_queue:
                    break
                d_num = day_dict["day"]
                if d_num not in sightseeing_day_numbers:
                    continue
                d_stat = day_dict["status"]
                # Never backfill hard travel days. A destination-departure day
                # can still contain partial sightseeing before its cutoff.
                if d_stat in ["arrival_day", "outbound_travel", "return_arrival", "in_transit", "post_trip"]:
                    continue

                c_date = start_date + timedelta(days=d_num - 1)
                d_end = self._combine_date_time(c_date, 19, 30)
                if required_destination_departure_datetime and required_destination_departure_datetime.date() == c_date:
                    d_end = min(d_end, required_destination_departure_datetime - timedelta(minutes=60))

                existing_acts = day_dict["activities"]
                max_acts = 2 if num_sightseeing_days > 2 else 3
                if len(existing_acts) >= max_acts:
                    continue

                remaining_queue = []
                for place in unscheduled_queue:
                    if len(existing_acts) >= max_acts:
                        remaining_queue.append(place)
                        continue

                    pid = str(place.get("place_id") or "").strip().lower()
                    clean_name = self._normalize_place_name(place.get("name", "Activity"))
                    p_name_lower = clean_name.lower()
                    p_city_lower = str(place.get("city") or destination_name).strip().lower()
                    name_key = (p_name_lower, p_city_lower)

                    if (pid and pid in scheduled_place_ids) or (p_name_lower and name_key in scheduled_place_names):
                        continue

                    prev_p = existing_acts[-1] if existing_acts else None
                    if prev_p:
                        c_prev = (prev_p.get("latitude"), prev_p.get("longitude"))
                        c_new = self._get_place_coordinates(place)
                        if c_prev[0] is not None and c_new is not None:
                            if self._haversine_distance(c_prev, c_new) > 8.0:
                                # Too far, do not place on this day!
                                remaining_queue.append(place)
                                continue

                    transit_min = self._calculate_transit_minutes(prev_p, place) if prev_p else 0
                    duration_min = self._get_activity_duration(place)

                    if existing_acts:
                        try:
                            last_end_dt = datetime.strptime(f"{existing_acts[-1]['date']} {existing_acts[-1]['start_time']}", "%Y-%m-%d %H:%M") + timedelta(minutes=existing_acts[-1]["duration_minutes"])
                            act_st = last_end_dt + timedelta(minutes=transit_min)
                        except Exception:
                            act_st = self._combine_date_time(c_date, 14, 0)
                    else:
                        act_st = self._combine_date_time(c_date, 9, 30)

                    if len(existing_acts) >= 1 and (12 <= act_st.hour < 14):
                        act_st += timedelta(minutes=45)

                    act_en = act_st + timedelta(minutes=duration_min)

                    if act_en <= d_end:
                        dur_hours = duration_min // 60
                        dur_mins = duration_min % 60
                        dur_str = f"{dur_hours}h {dur_mins:02d}m" if dur_hours > 0 else f"{dur_mins} mins"
                        p_coord = self._get_place_coordinates(place)

                        new_act = {
                            "place_id": place.get("place_id"),
                            "name": clean_name,
                            "date": str(c_date),
                            "start_time": act_st.strftime("%H:%M"),
                            "duration_minutes": duration_min,
                            "duration": dur_str,
                            "category": place.get("category"),
                            "description": place.get("description") or place.get("formatted"),
                            "estimated_cost": "Not included",
                            "optimization_score": place.get("optimization_score", 0),
                            "latitude": p_coord[0] if p_coord else None,
                            "longitude": p_coord[1] if p_coord else None,
                        }
                        existing_acts.append(new_act)
                        if pid:
                            scheduled_place_ids.add(pid)
                        if p_name_lower:
                            scheduled_place_names.add(name_key)
                        if day_dict["status"] == "leisure":
                            day_dict["status"] = "full_day"
                            day_dict["travel_constraint"] = "Full day sightseeing and local exploration"
                    else:
                        remaining_queue.append(place)
                unscheduled_queue = remaining_queue

        # Third pass: Inject Hotel -> Places -> Hotel events
        h_name = (hotel.get("hotel_name") or hotel.get("name") or "Your Hotel") if isinstance(hotel, dict) else "Your Hotel"
        for day_dict in itinerary_days:
            acts = day_dict.get("activities", [])
            d_stat = day_dict.get("status")
            if acts and d_stat not in ["arrival_day", "departure_day"]:
                # If there are activities and it's a full sightseeing day, add hotel departures and returns
                try:
                    first_act_start = datetime.strptime(f"{day_dict['date']} {acts[0]['start_time']}", "%Y-%m-%d %H:%M")
                    dep_dt = first_act_start - timedelta(minutes=30)
                    depart_event = {
                        "place_id": "hotel_departure",
                        "name": f"Depart from {h_name}",
                        "date": str(day_dict["date"]),
                        "start_time": dep_dt.strftime("%H:%M"),
                        "duration_minutes": 30,
                        "duration": "30 mins",
                        "category": "transit",
                        "description": "Head out for the day's sightseeing.",
                        "type": "hotel_transit"
                    }
                    
                    last_act = acts[-1]
                    last_end = datetime.strptime(f"{day_dict['date']} {last_act['start_time']}", "%Y-%m-%d %H:%M") + timedelta(minutes=last_act["duration_minutes"])
                    ret_start = last_end + timedelta(minutes=15)
                    return_event = {
                        "place_id": "hotel_return",
                        "name": f"Return to {h_name}",
                        "date": str(day_dict["date"]),
                        "start_time": ret_start.strftime("%H:%M"),
                        "duration_minutes": 30,
                        "duration": "30 mins",
                        "category": "transit",
                        "description": "Head back to your hotel to relax.",
                        "type": "hotel_transit"
                    }
                    
                    acts.insert(0, depart_event)
                    acts.append(return_event)
                except Exception:
                    pass

        total_unique_verified = len(unique_places)
        usable_days = len(sightseeing_day_numbers)
        total_scheduled_activities = sum(len(d["activities"]) for d in itinerary_days)
        leisure_days = sum(1 for d in itinerary_days if d["status"] == "leisure")

        sightseeing_activities = [
            a
            for d in itinerary_days
            for a in d.get("activities", [])
            if isinstance(a, dict) and a.get("type") != "hotel_transit" and a.get("category") != "transit"
        ]
        all_scheduled_ids = [a.get("place_id") for a in sightseeing_activities if a.get("place_id")]
        all_scheduled_names = [a.get("name") for a in sightseeing_activities if a.get("name")]
        has_duplicate_ids = len(all_scheduled_ids) != len(set(all_scheduled_ids))
        has_duplicate_names = len(all_scheduled_names) != len(set(all_scheduled_names))

        print(f"\n[FINAL ITINERARY SIGHTSEEING SUMMARY]")
        print(f"Total Unique Verified Places: {total_unique_verified}")
        print(f"Usable Sightseeing Days:      {usable_days}")
        print(f"Geographic Clusters Created:  {len(daily_place_clusters)}")
        print(f"Activities Scheduled:         {total_scheduled_activities}")
        print(f"Leisure Days:                 {leisure_days}")
        print(f"Duplicate Places Check:       {'PASSED (0 duplicates)' if not has_duplicate_ids and not has_duplicate_names else 'FAILED'}\n")
        logger.info(f"[SIGHTSEEING SUMMARY] Places: {total_unique_verified} | Days: {usable_days} | Clusters: {len(daily_place_clusters)} | Scheduled: {total_scheduled_activities} | Leisure: {leisure_days}")

        # 4. ITINERARY DAY ALLOCATION LOG
        print("ITINERARY DAY ALLOCATION:")
        for d in itinerary_days:
            acts = d.get("activities", [])
            stat = d.get("status")
            if stat == "outbound_travel":
                print(f"Day {d['day']}: Outbound Journey")
            elif stat == "in_transit":
                print(f"Day {d['day']}: In Transit")
            elif stat == "arrival_day":
                if acts:
                    print(f"Day {d['day']}: Arrival + {acts[0]['name']}")
                else:
                    print(f"Day {d['day']}: Arrival + Rest")
            elif stat == "departure_day":
                if acts:
                    print(f"Day {d['day']}: {acts[0]['name']} + Return Departure")
                else:
                    print(f"Day {d['day']}: Return Preparation & Departure")
            elif stat == "return_arrival":
                print(f"Day {d['day']}: Return Arrival")
            elif stat == "leisure":
                print(f"Day {d['day']}: Leisure / Free Day")
            else:
                act_str = " + ".join([a['name'] for a in acts]) if acts else "Leisure / Free Day"
                print(f"Day {d['day']}: {act_str}")
        print("==================================================\n")

        # =====================================================
        # TRAVELER COUNT
        # =====================================================

        adults = state.travelers.adults if state.travelers else 1
        children = state.travelers.children if state.travelers else 0
        traveler_count = max(1, adults + children)
        print(f"[DEBUG] budget traveler_count: {traveler_count}")

        # Ensure hotel and transport dictionaries preserve names
        if isinstance(hotel, dict):
            h_name = hotel.get("hotel_name") or hotel.get("name")
            if h_name:
                hotel["hotel_name"] = h_name
                hotel["name"] = h_name

        if isinstance(transport, dict):
            if "flight" in str(transport.get("type") or pref).lower():
                f_name = transport.get("flight_name") or transport.get("name")
                if f_name:
                    transport["flight_name"] = f_name
                    transport["name"] = f_name

        # =====================================================
        # COMPLETE BUDGET & COST CALCULATION (BUG-01, BUG-10 to BUG-16, BUG-19)
        # =====================================================

        if has_verified_transport and transport:
            outbound_transport_price = self._extract_single_transport_price(
                transport, target_class=outbound_class_code, budget_category=b_cat
            )
            if outbound_transport_price <= 0 and outbound_price > 0:
                outbound_transport_price = outbound_price

            return_transport_price = (
                self._extract_single_transport_price(
                    return_trip_data, target_class=return_class_code, budget_category=b_cat
                )
                if (isinstance(return_trip_data, dict) and return_trip_data)
                else 0.0
            )
            if return_transport_price <= 0 and return_price > 0 and (isinstance(return_trip_data, dict) and return_trip_data):
                return_transport_price = return_price
        else:
            outbound_transport_price = 0.0
            return_transport_price = 0.0

        total_transport_per_traveler = outbound_transport_price + return_transport_price
        estimated_transport = round(total_transport_per_traveler * traveler_count, 2)

        # Hotel stay calculation (BUG-19)
        raw_hotel_price = self._get_hotel_price(hotel)
        if raw_hotel_price <= 0 and isinstance(hotel, dict):
            # Preserve the selected hotel's provider-backed price even if a
            # downstream normalizer converted the generic price field to 0.
            nightly_fallback = self._safe_float(hotel.get("price_per_night"))
            total_fallback = self._safe_float(
                hotel.get("total_price") or hotel.get("offerRetailRate") or hotel.get("offerInitialPrice")
            )
            if nightly_fallback > 0:
                raw_hotel_price = nightly_fallback * max(1, total_nights)
            elif total_fallback > 0:
                raw_hotel_price = total_fallback
        # Check if rate is per-night or whole stay
        is_per_night = False
        if isinstance(hotel, dict):
            is_per_night = bool(hotel.get("is_per_night") or hotel.get("rate_type") == "nightly")

        if is_per_night:
            hotel_price_per_night = round(raw_hotel_price, 2)
            estimated_hotel = round(hotel_price_per_night * total_nights, 2)
        else:
            hotel_price_per_night = round(raw_hotel_price / total_nights, 2) if total_nights > 0 else round(raw_hotel_price, 2)
            estimated_hotel = round(raw_hotel_price, 2)

        if isinstance(hotel, dict):
            hotel["price_per_night"] = hotel_price_per_night
            hotel["price"] = estimated_hotel
            hotel["cost"] = estimated_hotel
            hotel["total_price"] = estimated_hotel

        estimated_activities = "Not included"
        food_local_transport = "Not included (Self-managed)"

        # Estimated total contains only booked services (transport and hotel)
        estimated_total = round(
            estimated_transport
            + estimated_hotel,
            2,
        )

        budget_limit = (
            float(state.budget.amount)
            if state.budget and state.budget.amount is not None
            else None
        )

        remaining_budget = (
            round(budget_limit - estimated_total, 2)
            if budget_limit is not None
            else None
        )

        # Concise backend budget logging
        logger.info(f"[BUDGET] Selected class: {outbound_class_code}")
        logger.info(f"[BUDGET] Outbound fare/person: {outbound_transport_price:.0f}")
        logger.info(f"[BUDGET] Return fare/person: {return_transport_price:.0f}")
        logger.info(f"[BUDGET] Travelers: {traveler_count}")
        logger.info(f"[BUDGET] Transport total: {estimated_transport:.0f}")
        logger.info(f"[BUDGET] Hotel total: {estimated_hotel:.0f}")
        logger.info(f"[BUDGET] Estimated total: {estimated_total:.0f}")
        if remaining_budget is not None:
            logger.info(f"[BUDGET] Remaining budget: {remaining_budget:.0f}")

        # =====================================================
        # FINAL ITINERARY
        # =====================================================

        state.itinerary = {
            "status": "draft",
            "origin": origin_name,
            "destination": destination_name,
            "start_date": str(start_date),
            "end_date": str(end_date),
            "total_days": total_days,
            "total_nights": total_nights,
            "transport": transport,
            "transfer": outbound_transfer_card,
            "outbound_transfer": outbound_transfer_card,
            "return_transfer": return_transfer_card,
            "hotel": hotel,
            "transport_timing": {
                "outbound_departure": (
                    outbound_departure.isoformat()
                    if outbound_departure
                    else None
                ),
                "train_arrival": (
                    train_arrival_datetime.isoformat()
                    if train_arrival_datetime
                    else None
                ),
                "destination_arrival": (
                    destination_arrival_datetime.isoformat()
                    if destination_arrival_datetime
                    else None
                ),
                "arrival": (
                    destination_arrival_datetime.isoformat()
                    if destination_arrival_datetime
                    else (arrival_datetime.isoformat() if arrival_datetime else None)
                ),
                "train_return_departure": (
                    train_return_departure_datetime.isoformat()
                    if train_return_departure_datetime
                    else None
                ),
                "destination_departure": (
                    required_destination_departure_datetime.isoformat()
                    if required_destination_departure_datetime
                    else None
                ),
                "destination_departure_for_return": (
                    required_destination_departure_datetime.isoformat()
                    if required_destination_departure_datetime
                    else None
                ),
                "return_departure": (
                    train_return_departure_datetime.isoformat()
                    if train_return_departure_datetime
                    else None
                ),
                "return_arrival": (
                    return_arrival_datetime.isoformat()
                    if return_arrival_datetime
                    else None
                ),
                "origin_final_arrival": (
                    origin_final_arrival_datetime.isoformat()
                    if origin_final_arrival_datetime
                    else None
                ),
                "last_mile_transfer_duration_minutes": outbound_transfer_mins,
                "return_transfer_duration_minutes": return_transfer_mins,
                "passenger_boarding_station": outbound_orig_code,
                "passenger_boarding_station_name": outbound_orig_st,
                "passenger_alighting_station": outbound_dest_code,
                "passenger_alighting_station_name": outbound_dest_st,
                "passenger_return_boarding_station": ret_orig_code,
                "passenger_return_boarding_station_name": ret_orig_st,
                "passenger_return_alighting_station": ret_dest_code,
                "passenger_return_alighting_station_name": ret_dest_st,
            },
            "hotel_timing": {
                "check_in": hotel_check_in_date.isoformat(),
                "check_out": hotel_check_out_date.isoformat(),
                "check_out_datetime": (
                    required_destination_departure_datetime.isoformat()
                    if required_destination_departure_datetime
                    else None
                ),
                "check_in_buffer_hours": 2,
                "check_out_buffer_hours": 3,
            },
            "days": itinerary_days,
            "travelers_count": traveler_count,
            "transport_status": "verified" if has_verified_transport else "unavailable",
            "transport_unavailable": not has_verified_transport,
            "transport_unavailable_reason": None if has_verified_transport else "Transport unavailable or could not be verified online for requested route and dates.",
            "transport_class": outbound_class_name if has_verified_transport else "N/A",
            "transport_class_code": outbound_class_code if has_verified_transport else "N/A",
            "return_transport_class": return_class_name if has_verified_transport else "N/A",
            "return_transport_class_code": return_class_code if has_verified_transport else "N/A",
            "outbound_transport_price": outbound_transport_price,
            "return_transport_price": return_transport_price,
            "total_transport_per_traveler": total_transport_per_traveler,
            "estimated_transport": estimated_transport,
            "hotel_nights": total_nights,
            "hotel_price_per_night": hotel_price_per_night,
            "estimated_hotel": estimated_hotel,
            "estimated_activities": estimated_activities,
            "food_local_transport": food_local_transport,
            "calculated_cost": estimated_total,
            "estimated_cost": estimated_total,
            "budget_limit": budget_limit,
            "remaining_budget": remaining_budget,
            "currency": state.budget.currency if state.budget else "INR",
        }

        state.workflow_status = "ITINERARY_BUILT"
        return state

    # =========================================================
    # COMBINE DATE + TIME
    # =========================================================

    @staticmethod
    def _combine_date_time(
        current_date,
        hour: int,
        minute: int,
    ):

        from datetime import datetime

        return datetime.combine(
            current_date,
            datetime.min.time(),
        ).replace(
            hour=hour,
            minute=minute,
        )

    # =========================================================
    # EXTRACT STATION / AIRPORT INFO
    # =========================================================

    @staticmethod
    def _extract_station_info(
        data: Any,
        is_origin: bool,
        default_city: str,
        is_flight: bool = False,
    ) -> tuple[str, str | None]:
        """
        Extract station / airport name and station code from transport dictionary.
        """
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="python")

        if not isinstance(data, dict):
            return default_city, None

        if is_origin:
            code = (
                data.get("boarding_station_code")
                or data.get("boarding_station")
                or data.get("from_station_code")
                or data.get("from_code")
                or data.get("origin_code")
                or data.get("from_airport_code")
                or data.get("origin_airport")
                or data.get("origin_station_code")
            )
            name = (
                data.get("boarding_station_name")
                or data.get("from_station_name")
                or data.get("origin_station_name")
                or data.get("from_name")
                or data.get("from_airport_name")
                or data.get("origin_airport_name")
            )
        else:
            code = (
                data.get("alighting_station_code")
                or data.get("alighting_station")
                or data.get("to_station_code")
                or data.get("to_code")
                or data.get("destination_code")
                or data.get("to_airport_code")
                or data.get("destination_airport")
                or data.get("destination_station_code")
            )
            name = (
                data.get("alighting_station_name")
                or data.get("to_station_name")
                or data.get("destination_station_name")
                or data.get("to_name")
                or data.get("to_airport_name")
                or data.get("destination_airport_name")
            )

        if not name:
            if code:
                name = f"{code} Station" if not is_flight else f"{code} Airport"
            else:
                name = default_city

        return str(name), str(code) if code else None

    # =========================================================
    # EXTRACT TRANSPORT DATETIME
    # =========================================================

    @staticmethod
    def _extract_transport_datetime(
        data: Any,
        fallback_date,
        datetime_keys: tuple[str, ...],
        time_keys: tuple[str, ...],
        reference_datetime=None,
    ):
        """
        Convert provider transport timing into a real datetime.

        Providers may return either a full ISO datetime or a
        time-only value such as ``18:30``. A time-only value is
        combined with the journey date so the itinerary builder
        can correctly identify travel days.
        """

        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="python")

        if not isinstance(data, dict):
            return None

        # Prefer an already-normalized full datetime.
        value = None
        for key in datetime_keys:
            if data.get(key):
                value = data.get(key)
                break

        if value is not None:
            if isinstance(value, datetime):
                return value

            if isinstance(value, str):
                try:
                    parsed = datetime.fromisoformat(
                        value.replace("Z", "+00:00")
                    )
                    if parsed.year != 1900:
                        return parsed
                except ValueError:
                    pass

        # Fall back to provider time-only fields.
        raw_time = None
        for key in time_keys:
            if data.get(key):
                raw_time = str(data.get(key)).strip()
                break

        if not raw_time:
            return None

        parsed_time = None

        try:
            parsed_time = datetime.fromisoformat(
                raw_time.replace("Z", "+00:00")
            )
        except ValueError:
            pass

        if parsed_time is None:
            for fmt in (
                "%H:%M",
                "%H:%M:%S",
                "%I:%M %p",
                "%I:%M:%S %p",
            ):
                try:
                    parsed_time = datetime.strptime(
                        raw_time,
                        fmt,
                    )
                    break
                except ValueError:
                    continue

        if parsed_time is None:
            return None

        result = datetime.combine(
            fallback_date,
            parsed_time.time(),
        )

        # Overnight arrival: if arrival time is earlier than or equal to the
        # reference departure time, it belongs to the next day.
        if reference_datetime and result <= reference_datetime:
            result += timedelta(days=1)

        # Duration-aware multi-day adjustment if duration exists in data
        duration_mins = data.get("duration_minutes") or data.get("duration")
        if duration_mins and reference_datetime:
            dur_int = None
            try:
                dur_int = int(duration_mins)
            except (ValueError, TypeError):
                t_str = str(duration_mins).lower().strip().replace("~", "")
                if "h" in t_str:
                    try:
                        parts = t_str.split("h")
                        h = int(parts[0].strip())
                        m = int(parts[1].replace("m", "").strip()) if len(parts) > 1 and parts[1].strip() else 0
                        dur_int = h * 60 + m
                    except Exception:
                        pass
                elif "m" in t_str:
                    try:
                        dur_int = int(t_str.replace("m", "").strip())
                    except Exception:
                        pass

            if dur_int is not None and dur_int > 0:
                dur_target = reference_datetime + timedelta(minutes=dur_int)
                if dur_target > result:
                    result = dur_target

        return result

    @staticmethod
    def _log_transport_event(
        event_name: str,
        dt: Any,
        trip_start_date: Any,
        assigned_day: int,
    ) -> None:
        """
        Structured debug log for transport day assignment matching master prompt specification.
        Logged to stdout and logger, never exposed in the Streamlit UI.
        """
        if not dt or not trip_start_date:
            return
        if not isinstance(dt, datetime):
            return
        c_date = dt.date()
        calculated_trip_day = (c_date - trip_start_date).days + 1
        dt_str = dt.strftime("%Y-%m-%d %H:%M")
        print("\nTRANSPORT DAY ASSIGNMENT")
        print(f"Event: {event_name}")
        print(f"Datetime: {dt_str}")
        print(f"Calendar Date: {c_date}")
        print(f"Trip Day: {calculated_trip_day}")
        print(f"Assigned Day: {assigned_day}\n")
        logger.info(
            f"TRANSPORT DAY ASSIGNMENT | Event: {event_name} | Datetime: {dt_str} | "
            f"Calendar Date: {c_date} | Trip Day: {calculated_trip_day} | Assigned Day: {assigned_day}"
        )

    # =========================================================
    # EXTRACT DATETIME
    # =========================================================

    @staticmethod
    def _extract_datetime(
        data: Any,
        keys: tuple[str, ...],
    ):

        from datetime import datetime

        if hasattr(
            data,
            "model_dump",
        ):

            data = data.model_dump()

        if not isinstance(
            data,
            dict,
        ):

            return None

        for key in keys:

            value = data.get(
                key
            )

            if not value:
                continue

            if isinstance(
                value,
                datetime,
            ):

                return value

            if isinstance(
                value,
                str,
            ):

                value = value.strip()

                # ISO format
                try:

                    return datetime.fromisoformat(
                        value.replace(
                            "Z",
                            "+00:00",
                        )
                    )

                except ValueError:
                    pass

                # Common formats
                for fmt in (
                    "%Y-%m-%d %H:%M",
                    "%Y-%m-%d %H:%M:%S",
                    "%d-%m-%Y %H:%M",
                    "%Y-%m-%d %I:%M %p",
                    "%d-%m-%Y %I:%M %p",
                ):

                    try:

                        return datetime.strptime(
                            value,
                            fmt,
                        )

                    except ValueError:
                        continue

        return None

    # =========================================================
    # DEDUPLICATE PLACES
    # =========================================================

    @staticmethod
    def _deduplicate_places(
        places: list[dict],
    ) -> list[dict]:

        unique_places = []

        seen_ids = set()
        seen_names = set()

        for place in places:

            if not isinstance(
                place,
                dict,
            ):
                continue

            # -------------------------------------------------
            # PLACE ID
            # -------------------------------------------------

            place_id = place.get(
                "place_id"
            )

            if place_id:

                place_id_key = (
                    str(
                        place_id
                    )
                    .strip()
                    .lower()
                )

                if (
                    place_id_key
                    in seen_ids
                ):
                    continue

            # -------------------------------------------------
            # NAME + CITY
            # -------------------------------------------------

            name = str(
                place.get(
                    "name",
                    "",
                )
            ).strip().lower()

            city = str(
                place.get(
                    "city",
                    "",
                )
            ).strip().lower()

            name_key = (
                name,
                city,
            )

            # -------------------------------------------------
            # If same name + city already exists,
            # skip duplicate.
            # -------------------------------------------------

            if (
                name
                and name_key
                in seen_names
            ):
                continue

            # -------------------------------------------------
            # STORE IDENTIFIERS
            # -------------------------------------------------

            if place_id:

                seen_ids.add(
                    place_id_key
                )

            if name:

                seen_names.add(
                    name_key
                )

            unique_places.append(
                place
            )

        return unique_places

    # =========================================================
    # GEOGRAPHIC COORDINATE & DISTANCE UTILITIES
    # =========================================================

    @staticmethod
    def _get_hotel_coordinates(hotel: Any) -> tuple[float, float] | None:
        """
        Extract hotel coordinates from the selected hotel object.

        Hotel coordinates may exist:
        - directly on the normalized hotel object
        - inside nested location / gps_coordinates
        - inside provider raw_data

        This prevents selected-hotel transfer calculations from losing
        coordinates when the selection endpoint stores a reduced hotel dict.
        """
        if hasattr(hotel, "model_dump"):
            try:
                hotel = hotel.model_dump(mode="python")
            except Exception:
                hotel = hotel.model_dump()

        if not isinstance(hotel, dict):
            return None

        def _valid_pair(lat, lon):
            try:
                if lat is None or lon is None:
                    return None
                lat_f = float(lat)
                lon_f = float(lon)
                if -90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0:
                    return lat_f, lon_f
            except (TypeError, ValueError):
                return None
            return None

        # Direct normalized fields.
        pair = _valid_pair(
            hotel.get("latitude", hotel.get("lat")),
            hotel.get("longitude", hotel.get("lon", hotel.get("lng"))),
        )
        if pair:
            return pair

        # Common nested coordinate structures.
        for key in ("location", "gps_coordinates", "coordinates"):
            value = hotel.get(key)
            if isinstance(value, dict):
                pair = _valid_pair(
                    value.get("latitude", value.get("lat")),
                    value.get("longitude", value.get("lon", value.get("lng"))),
                )
                if pair:
                    return pair

        # LiteAPI/SerpAPI raw provider payload.
        raw = hotel.get("raw_data")
        if isinstance(raw, dict):
            pair = ItineraryBuilder._get_hotel_coordinates(raw)
            if pair:
                return pair

            # Some provider payloads nest the property itself.
            for key in ("hotel", "property", "data"):
                nested = raw.get(key)
                if isinstance(nested, dict):
                    pair = ItineraryBuilder._get_hotel_coordinates(nested)
                    if pair:
                        return pair

        return None

    @staticmethod
    def _get_place_coordinates(place: Any) -> tuple[float, float] | None:
        """
        Extract validated (latitude, longitude) floats from place dictionary or location object.
        """
        if hasattr(place, "model_dump"):
            place = place.model_dump(mode="python")

        if not isinstance(place, dict):
            return None

        # Check direct keys
        lat = place.get("latitude") if place.get("latitude") is not None else place.get("lat")
        lon = (
            place.get("longitude")
            if place.get("longitude") is not None
            else (place.get("lon") if place.get("lon") is not None else place.get("lng"))
        )

        # Check nested location dict
        if lat is None or lon is None:
            loc = place.get("location")
            if isinstance(loc, dict):
                lat = loc.get("latitude") if loc.get("latitude") is not None else loc.get("lat")
                lon = (
                    loc.get("longitude")
                    if loc.get("longitude") is not None
                    else (loc.get("lon") if loc.get("lon") is not None else loc.get("lng"))
                )

        if lat is not None and lon is not None:
            try:
                lat_f = float(lat)
                lon_f = float(lon)
                if -90.0 <= lat_f <= 90.0 and -180.0 <= lon_f <= 180.0:
                    return (lat_f, lon_f)
            except (TypeError, ValueError):
                pass

        return None

    @staticmethod
    def _haversine_distance(coord1: tuple[float, float], coord2: tuple[float, float]) -> float:
        """
        Calculate deterministic great-circle distance in kilometers using the Haversine formula.
        """
        import math
        lat1, lon1 = math.radians(coord1[0]), math.radians(coord1[1])
        lat2, lon2 = math.radians(coord2[0]), math.radians(coord2[1])
        dlat = lat2 - lat1
        dlon = lon2 - lon1
        a = math.sin(dlat / 2.0) ** 2 + math.cos(lat1) * math.cos(lat2) * math.sin(dlon / 2.0) ** 2
        c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
        return 6371.0 * c

    # =========================================================
    # DEDUPLICATION & ATTRACTION CLASSIFICATION HELPERS
    # =========================================================

    @classmethod
    def _deduplicate_places(cls, places: list[dict]) -> list[dict]:
        """
        Deduplicate verified places:
        - Normalize names (clean Hindi/Devanagari, strip punctuation, case insensitive)
        - Detect exact and near-duplicate names in the same locality
        - Detect matching place_id
        - Detect matching coordinates within 0.3 km
        - Preserve the best verified record (highest optimization_score / most complete)
        """
        if not places:
            return []

        deduped: list[dict] = []
        seen_names: set[str] = set()
        seen_ids: set[str] = set()
        seen_coords: list[tuple[tuple[float, float], dict]] = []

        for p in places:
            if not isinstance(p, dict):
                continue

            raw_name = p.get("name") or "Attraction"
            norm_name = cls._normalize_place_name(raw_name).strip().lower()

            pid = str(p.get("place_id") or "").strip().lower()
            coords = cls._get_place_coordinates(p)

            # 1. Check place_id match
            if pid and pid in seen_ids:
                continue

            # 2. Check direct name match
            if norm_name in seen_names:
                continue

            # 3. Check token set match (e.g. "fort aguada" vs "aguada fort")
            norm_tokens = set(norm_name.split())
            is_token_dup = False
            for s_name in seen_names:
                s_tokens = set(s_name.split())
                if norm_tokens and s_tokens and norm_tokens == s_tokens:
                    is_token_dup = True
                    break
            if is_token_dup:
                continue

            # 4. Check coordinate proximity (within 300 meters)
            is_coord_dup = False
            if coords:
                for s_c, s_p in seen_coords:
                    dist_km = cls._haversine_distance(coords, s_c)
                    if dist_km <= 0.3:
                        is_coord_dup = True
                        break
            if is_coord_dup:
                continue

            # Not duplicate: register and keep
            if pid:
                seen_ids.add(pid)
            seen_names.add(norm_name)
            if coords:
                seen_coords.append((coords, p))
            deduped.append(p)

        return deduped

    @classmethod
    def _is_light_attraction(
        cls,
        place: dict,
        hotel_coords: tuple[float, float] | None = None,
    ) -> bool:
        """
        Determine if an attraction is suitable for a light arrival day activity.
        Must satisfy:
        - Short/moderate visit duration (<= 90 mins)
        - Close to accommodation/city center (<= 10.0 km if coords available)
        - Not an intensive/heavy/remote excursion (not waterfall, safari, theme park, water park, trek, wildlife sanctuary)
        """
        if not isinstance(place, dict):
            return False

        name = str(place.get("name") or "").lower()
        category = str(place.get("category") or "").lower()

        # Heavy / remote excursion keywords
        heavy_keywords = (
            "waterfall", "falls", "fall",
            "theme_park", "water_park", "amusement", "adventure", "safari", "trek",
            "national park", "wildlife", "sanctuary", "gorge", "caves"
        )
        if any(k in category or k in name for k in heavy_keywords):
            return False

        # Duration check (must be moderate <= 120 mins)
        duration_mins = cls._get_activity_duration(place)
        if duration_mins > 120:
            return False

        # Distance check from hotel if coords available
        p_coords = cls._get_place_coordinates(place)
        if p_coords and hotel_coords:
            dist = cls._haversine_distance(p_coords, hotel_coords)
            if dist > 10.0:
                return False

        return True

    @classmethod
    def _calculate_arrival_window(
        cls,
        current_date: date,
        destination_arrival_datetime: datetime | None,
        train_arrival_datetime: datetime | None,
        outbound_departure: datetime | None,
        outbound_transfer_mins: int = 0,
        day_end: datetime | None = None,
    ) -> tuple[datetime | None, datetime | None, bool, str]:
        """
        Calculate realistic arrival settlement window and determine whether sightseeing is feasible.

        Formula:
        destination_arrival = train_arrival + last_mile_transfer
        settle_dt = destination_arrival + hotel/luggage/settling_buffer (min 90 mins, or 120 mins if overnight journey)

        If overnight journey and destination_arrival >= 12:00 PM:
        -> Fatigue recovery: Day = Arrival + Hotel + Rest (0 sightseeing).

        If destination_arrival >= 16:30 or settle_dt >= 18:00:
        -> Late arrival: Day = Arrival + Hotel + Rest (0 sightseeing).

        Returns:
            (window_start, window_end, is_sightseeing_allowed, decision_reason)
        """
        if not destination_arrival_datetime:
            return (None, None, False, "No destination arrival time available")

        if day_end is None:
            day_end = cls._combine_date_time(current_date, 18, 30)

        # Check if overnight journey
        is_overnight = False
        if outbound_departure:
            travel_hours = (destination_arrival_datetime - outbound_departure).total_seconds() / 3600
            if travel_hours >= 8.0 or outbound_departure.date() < destination_arrival_datetime.date():
                is_overnight = True

        rest_buffer_mins = 120 if is_overnight else 90
        settle_dt = destination_arrival_datetime + timedelta(minutes=rest_buffer_mins)

        # Case 1: Long overnight journey arriving at or after 12:00 PM (e.g. 12:43 PM arrival)
        if is_overnight and destination_arrival_datetime.time() >= cls._combine_date_time(current_date, 12, 0).time():
            return (
                day_end,
                day_end,
                False,
                f"Overnight journey arrival at {destination_arrival_datetime.strftime('%H:%M')} + {rest_buffer_mins}m rest buffer -> hotel check-in and rest (no sightseeing)",
            )

        # Case 2: Late arrival (>= 16:30) or transfer takes >= 4h
        if destination_arrival_datetime.hour >= 16 or outbound_transfer_mins >= 240 or settle_dt >= day_end:
            return (
                day_end,
                day_end,
                False,
                f"Late destination arrival at {destination_arrival_datetime.strftime('%H:%M')} -> hotel check-in and rest",
            )

        # Case 3: Early / morning arrival (e.g. 08:15 AM)
        if settle_dt.time() < cls._combine_date_time(current_date, 9, 30).time():
            window_start = cls._combine_date_time(current_date, 9, 30)
        elif 12 <= settle_dt.hour < 14:
            window_start = cls._combine_date_time(current_date, 14, 0)
        else:
            window_start = settle_dt

        if window_start >= day_end:
            return (day_end, day_end, False, "Insufficient daylight remaining after settling buffer")

        return (
            window_start,
            day_end,
            True,
            f"Arrival window: {window_start.strftime('%H:%M')} to {day_end.strftime('%H:%M')} (light sightseeing allowed)",
        )

    @classmethod
    def _calculate_return_cutoff(
        cls,
        current_date: date,
        train_return_departure_datetime: datetime | None,
        return_transfer_mins: int = 0,
        is_flight_departure: bool = False,
    ) -> tuple[datetime | None, bool, str]:
        """
        Calculate backward return day cutoff time from return departure.

        Buffer components:
        - Return road transfer: return_transfer_mins
        - Station/Airport buffer: 120 mins (flight) / 60 mins (train)
        - Hotel checkout buffer: 45 mins
        - Safety buffer: 30 mins

        Latest sightseeing end = return_departure - sum(buffers)

        Returns:
            (latest_sightseeing_end, is_sightseeing_allowed, decision_reason)
        """
        if not train_return_departure_datetime:
            return (None, True, "No return departure constraint")

        station_buffer_mins = 120 if is_flight_departure else 60
        checkout_buffer_mins = 45
        safety_buffer_mins = 30
        total_buffer_mins = return_transfer_mins + station_buffer_mins + checkout_buffer_mins + safety_buffer_mins

        latest_sightseeing_end = train_return_departure_datetime - timedelta(minutes=total_buffer_mins)

        # If latest sightseeing end is earlier than 13:00 (e.g. train departs before 16:00 or morning)
        cutoff_threshold = cls._combine_date_time(current_date, 13, 0)
        if latest_sightseeing_end <= cutoff_threshold:
            return (
                latest_sightseeing_end,
                False,
                f"Return departure at {train_return_departure_datetime.strftime('%H:%M')} requires leaving by {latest_sightseeing_end.strftime('%H:%M')} (no sightseeing on departure day)",
            )

        return (
            latest_sightseeing_end,
            True,
            f"Latest sightseeing end: {latest_sightseeing_end.strftime('%H:%M')} (safe buffer before {train_return_departure_datetime.strftime('%H:%M')} departure)",
        )

    # =========================================================
    # GEOGRAPHIC PROXIMITY CLUSTERING
    # =========================================================

    @classmethod
    def _cluster_and_order_places(
        cls,
        places: list[dict],
        num_days: int,
        hotel_coords: tuple[float, float] | None = None,
    ) -> list[list[dict]]:
        """
        Cluster verified places into geographic clusters using deterministic
        proximity clustering (threshold <= 8.0 km), and order places within each cluster
        to minimize backtracking.

        Rules:
        1. Target cluster count is min(len(places), num_days).
        2. Never create empty/fake clusters just to match num_days.
        3. Nearby places (<= 8.0 km apart) are grouped together on the same day when time permits,
           regardless of whether len(places) <= num_days.
        4. Distant places (> 8.0 km apart) remain in separate clusters/days.
        5. Places without coordinates are either grouped by shared locality or placed in separate clusters.
        """
        import math

        if not places or num_days <= 0:
            return []

        # 1. Extract coordinates for each place
        places_with_coords: list[tuple[dict, tuple[float, float]]] = []
        places_without_coords: list[dict] = []

        for p in places:
            coords = cls._get_place_coordinates(p)
            if coords:
                places_with_coords.append((p, coords))
            else:
                places_without_coords.append(p)

        total_places_count = len(places)
        max_places_per_day = 3 if num_days <= 2 and total_places_count > 3 else 2
        MAX_MERGE_DISTANCE_KM = 8.0

        # Fallback if no coordinates available
        if not places_with_coords:
            target_clusters_count = min(total_places_count, num_days)
            base_places_per_day = total_places_count // target_clusters_count
            extra_places = total_places_count % target_clusters_count
            result = []
            idx = 0
            for d in range(target_clusters_count):
                count = base_places_per_day + (1 if d < extra_places else 0)
                result.append(places[idx : idx + count])
                idx += count
            return result

        # Initialize each place with coordinates as its own cluster
        clusters: list[dict] = []
        for p, c in places_with_coords:
            clusters.append({
                "items": [(p, c)],
                "center": c,
            })

        # Agglomerative clustering: merge closest clusters if distance between centroids is <= 8.0 km
        # Continue merging as long as closest pair distance <= MAX_MERGE_DISTANCE_KM and capacity <= max_places_per_day
        while True:
            best_i = -1
            best_j = -1
            min_dist = float("inf")

            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    c1 = clusters[i]
                    c2 = clusters[j]
                    if len(c1["items"]) + len(c2["items"]) > max_places_per_day:
                        continue

                    dist = cls._haversine_distance(c1["center"], c2["center"])
                    if dist <= MAX_MERGE_DISTANCE_KM and dist < min_dist:
                        min_dist = dist
                        best_i = i
                        best_j = j

            if best_i == -1:
                # No more clusters can be merged under 8.0 km threshold and capacity limit
                break

            merged_items = clusters[best_i]["items"] + clusters[best_j]["items"]
            avg_lat = sum(it[1][0] for it in merged_items) / len(merged_items)
            avg_lon = sum(it[1][1] for it in merged_items) / len(merged_items)
            new_cluster = {
                "items": merged_items,
                "center": (avg_lat, avg_lon),
            }

            clusters = [c for idx, c in enumerate(clusters) if idx not in (best_i, best_j)]
            clusters.append(new_cluster)

        # Distribute any places without coordinates
        for p in places_without_coords:
            if clusters and len(clusters) <= num_days:
                smallest = min(clusters, key=lambda c: len(c["items"]))
                if len(smallest["items"]) < max_places_per_day:
                    smallest["items"].append((p, None))
                else:
                    clusters.append({"items": [(p, None)], "center": (0.0, 0.0)})
            else:
                clusters.append({"items": [(p, None)], "center": (0.0, 0.0)})

        # Local 2-opt cluster swap & relocation optimization
        def _cluster_intra_dist(items_list):
            valid_c = [it[1] for it in items_list if it[1] is not None]
            if len(valid_c) <= 1:
                return 0.0
            total_d = 0.0
            for a in range(len(valid_c)):
                for b in range(a + 1, len(valid_c)):
                    total_d += cls._haversine_distance(valid_c[a], valid_c[b])
            return total_d

        improved = True
        iterations = 0
        while improved and iterations < 50:
            improved = False
            iterations += 1
            for i in range(len(clusters)):
                for j in range(i + 1, len(clusters)):
                    items_i = clusters[i]["items"]
                    items_j = clusters[j]["items"]
                    if not items_i or not items_j:
                        continue

                    current_cost = _cluster_intra_dist(items_i) + _cluster_intra_dist(items_j)

                    # Try moving item x from cluster i to cluster j (if capacity permits and distance is close)
                    if len(items_j) < max_places_per_day and len(items_i) > 1:
                        for xi, x in enumerate(items_i):
                            if x[1] is not None and clusters[j]["center"]:
                                if cls._haversine_distance(x[1], clusters[j]["center"]) > MAX_MERGE_DISTANCE_KM:
                                    continue
                            cand_i = [item for idx, item in enumerate(items_i) if idx != xi]
                            cand_j = items_j + [x]
                            new_cost = _cluster_intra_dist(cand_i) + _cluster_intra_dist(cand_j)
                            if new_cost < current_cost - 0.01:
                                clusters[i]["items"] = cand_i
                                clusters[j]["items"] = cand_j
                                current_cost = new_cost
                                improved = True
                                break

                    # Try moving item y from cluster j to cluster i (if capacity permits and distance is close)
                    if len(items_i) < max_places_per_day and len(items_j) > 1 and not improved:
                        for yj, y in enumerate(items_j):
                            if y[1] is not None and clusters[i]["center"]:
                                if cls._haversine_distance(y[1], clusters[i]["center"]) > MAX_MERGE_DISTANCE_KM:
                                    continue
                            cand_j = [item for idx, item in enumerate(items_j) if idx != yj]
                            cand_i = items_i + [y]
                            new_cost = _cluster_intra_dist(cand_i) + _cluster_intra_dist(cand_j)
                            if new_cost < current_cost - 0.01:
                                clusters[i]["items"] = cand_i
                                clusters[j]["items"] = cand_j
                                current_cost = new_cost
                                improved = True
                                break

                    # Try swapping any item x in cluster i with item y in cluster j
                    if not improved:
                        for xi, x in enumerate(items_i):
                            for yj, y in enumerate(items_j):
                                if x[1] and clusters[j]["center"] and cls._haversine_distance(x[1], clusters[j]["center"]) > MAX_MERGE_DISTANCE_KM:
                                    continue
                                if y[1] and clusters[i]["center"] and cls._haversine_distance(y[1], clusters[i]["center"]) > MAX_MERGE_DISTANCE_KM:
                                    continue
                                cand_i = [item for idx, item in enumerate(items_i) if idx != xi] + [y]
                                cand_j = [item for idx, item in enumerate(items_j) if idx != yj] + [x]
                                new_cost = _cluster_intra_dist(cand_i) + _cluster_intra_dist(cand_j)
                                if new_cost < current_cost - 0.01:
                                    clusters[i]["items"] = cand_i
                                    clusters[j]["items"] = cand_j
                                    current_cost = new_cost
                                    improved = True

        # Re-compute centroids after swap optimization
        for cluster in clusters:
            valid_coords = [it[1] for it in cluster["items"] if it[1] is not None]
            if valid_coords:
                avg_lat = sum(c[0] for c in valid_coords) / len(valid_coords)
                avg_lon = sum(c[1] for c in valid_coords) / len(valid_coords)
                cluster["center"] = (avg_lat, avg_lon)

        # Sort clusters logically across days
        # Place the cluster with closest proximity to hotel first (closest attractions on arrival / early days)
        if hotel_coords:
            clusters.sort(key=lambda c: (
                cls._haversine_distance(c["center"], hotel_coords) if c["items"] and c["items"][0][1] else 999.0
            ))
        else:
            clusters.sort(key=lambda c: (c["center"][0], c["center"][1]) if c["items"] and c["items"][0][1] else (0.0, 0.0))

        # Order places within each cluster to minimize backtracking
        ordered_daily_places = []
        for cluster in clusters:
            items = cluster["items"]
            if not items:
                continue

            raw_places = [it[0] for it in items]
            coords_list = [it[1] for it in items]

            ordered_places = cls._order_places_minimizing_backtracking(raw_places, coords_list, hotel_coords)
            ordered_daily_places.append(ordered_places)

        return ordered_daily_places

    @classmethod
    def _order_places_minimizing_backtracking(
        cls,
        places: list[dict],
        coords: list[tuple[float, float] | None],
        hotel_coords: tuple[float, float] | None = None,
    ) -> list[dict]:
        """
        Order places within a single day to minimize total travel distance and eliminate backtracking.
        Uses exact permutation shortest open-path optimization with tiebreak on start point.
        """
        n = len(places)
        if n <= 1:
            return places

        # If any coords are missing, return original sequence
        if any(c is None for c in coords):
            return places

        import itertools

        best_order = list(range(n))
        min_total_dist = float("inf")

        for perm in itertools.permutations(range(n)):
            open_dist = sum(cls._haversine_distance(coords[perm[k]], coords[perm[k + 1]]) for k in range(len(perm) - 1))
            tiebreak_dist = cls._haversine_distance(hotel_coords, coords[perm[0]]) * 0.001 if hotel_coords else 0.0
            total_dist = open_dist + tiebreak_dist

            if total_dist < min_total_dist:
                min_total_dist = total_dist
                best_order = list(perm)

        return [places[idx] for idx in best_order]

    @staticmethod
    def _get_places_for_day(
        places: list[dict],
        day_number: int,
        total_days: int,
    ) -> list[dict]:
        """Legacy fallback place distributor by day slice."""
        if not places or total_days <= 0:
            return []
        total_places = len(places)
        base_places_per_day = total_places // total_days
        extra_places = total_places % total_days
        if day_number <= extra_places:
            places_for_this_day = base_places_per_day + 1
        else:
            places_for_this_day = base_places_per_day
        start_index = (day_number - 1) * base_places_per_day + min(day_number - 1, extra_places)
        end_index = start_index + places_for_this_day
        return places[start_index:end_index]

    # =========================================================
    # TRANSPORT PRICE
    # =========================================================

    # =========================================================
    # DYNAMIC ACTIVITY DURATION (BUG-05)
    # =========================================================

    @staticmethod
    def _get_activity_duration(place: dict) -> int:
        """
        Dynamically calculate realistic visit duration in minutes based on attraction type.
        """
        category = str(place.get("category") or "").lower()
        name = str(place.get("name") or "").lower()

        # Major theme / amusement / adventure / water park
        if any(k in category or k in name for k in ("theme_park", "water_park", "amusement", "adventure", "safari")):
            return 180  # 3 hours

        # Major museums, forts, palaces, heritage complexes, science centres
        if any(k in category or k in name for k in ("museum", "fort", "palace", "zoo", "aquarium", "science", "planetarium", "castle")):
            return 120  # 2 hours

        # Sights, archaeological sites, beaches, large botanical gardens
        if any(k in category or k in name for k in ("sights", "archaeological", "beach", "botanical", "park", "lake")):
            return 75  # 1 hour 15 mins

        # Temples, churches, viewpoints, historical monuments
        if any(k in category or k in name for k in ("temple", "church", "mosque", "viewpoint", "monument", "memorial", "gurudwara")):
            return 60  # 1 hour

        # Public statues, artworks, murals, squares, street art
        if any(k in category or k in name for k in ("statue", "artwork", "mural", "street_art", "square", "chowk")):
            return 35  # 35 mins

        return 60

    # =========================================================
    # ENGLISH PLACE NAME NORMALIZATION (Language Inconsistency)
    # =========================================================

    @staticmethod
    def _normalize_place_name(raw_name: Any) -> str:
        """
        Normalize place name and translate any Hindi/Devanagari text into clean English.
        """
        if not raw_name:
            return "Attraction"
        name = str(raw_name).strip()

        # Check if text contains Devanagari characters
        has_devanagari = any('\u0900' <= char <= '\u097F' for char in name)
        if not has_devanagari:
            return name

        # Direct landmark mapping
        landmark_map = {
            "राष्ट्रपति भवन संग्रहालय": "Rashtrapati Bhavan Museum",
            "राष्ट्रपति भवन": "Rashtrapati Bhavan",
            "राष्ट्रीय विज्ञान केन्द्र": "National Science Centre",
            "राष्ट्रीय विज्ञान केंद्र": "National Science Centre",
            "शंकर का अंतर्राष्ट्रीय गुड़िया संग्रहालय": "Shankar's International Dolls Museum",
            "गुड़िया संग्रहालय": "International Dolls Museum",
            "लाल किला": "Red Fort",
            "कुतुब मीनार": "Qutub Minar",
            "लोटस टेम्पल": "Lotus Temple",
            "कमल मंदिर": "Lotus Temple",
            "अशोक स्तम्भ": "Ashok Stambh",
            "गांधी स्मृति": "Gandhi Smriti",
            "हुमायूँ का मकबरा": "Humayun's Tomb",
            "इंडिया गेट": "India Gate",
            "अक्षरधाम मंदिर": "Akshardham Temple",
            "अक्षरधाम": "Akshardham",
            "जामा मस्जिद": "Jama Masjid",
            "राज घाट": "Raj Ghat",
            "जंतर मंतर": "Jantar Mantar",
            "संसद भवन": "Parliament House",
            "संसद संग्रहालय": "Parliament Museum",
            "राष्ट्रीय संग्रहालय": "National Museum",
            "राष्ट्रीय रेल संग्रहालय": "National Rail Museum",
            "तीनमूर्ति भवन": "Teen Murti Bhavan",
            "तीन मूर्ति भवन": "Teen Murti Bhavan",
            "सफदरजंग का मकबरा": "Safdarjung Tomb",
            "लोधी गार्डन": "Lodhi Garden",
            "चांदनी चौक": "Chandni Chowk",
            "कनॉट प्लेस": "Connaught Place",
            "कालकाजी मंदिर": "Kalkaji Temple",
            "छतरपुर मंदिर": "Chhatarpur Temple",
            "गुरुद्वारा बंगला साहिब": "Gurudwara Bangla Sahib",
            "गुरुद्वारा सीस गंज साहिब": "Gurudwara Sis Ganj Sahib",
        }

        for hi_name, en_name in landmark_map.items():
            if hi_name in name:
                return en_name

        # Keyword-based replacement
        replacements = [
            ("संग्रहालय", "Museum"),
            ("केन्द्र", "Centre"),
            ("केंद्र", "Centre"),
            ("भवन", "Bhavan"),
            ("मंदिर", "Temple"),
            ("किला", "Fort"),
            ("उद्यान", "Park"),
            ("पार्क", "Park"),
            ("स्मारक", "Memorial"),
            ("स्तम्भ", "Stambh"),
            ("मकबरा", "Tomb"),
            ("मस्जिद", "Mosque"),
            ("घाट", "Ghat"),
            ("द्वार", "Gate"),
            ("गेट", "Gate"),
            ("राष्ट्रीय", "National"),
            ("विज्ञान", "Science"),
            ("कला", "Art"),
            ("महल", "Palace"),
            ("झील", "Lake"),
        ]

        trans = name
        for hi, en in replacements:
            trans = trans.replace(hi, f" {en} ")

        import re
        trans = re.sub(r'[\u0900-\u097F]+', '', trans).strip()
        trans = re.sub(r'\s+', ' ', trans).strip()

        return trans if len(trans) > 2 else name

    # =========================================================
    # INTER-PLACE TRANSIT CALCULATION (BUG-06)
    # =========================================================

    @staticmethod
    def _calculate_transit_minutes(prev_place: dict, next_place: dict) -> int:
        """
        Calculate realistic travel time between two consecutive places in minutes.
        """
        if not isinstance(prev_place, dict) or not isinstance(next_place, dict):
            return 25

        lat1 = prev_place.get("lat") or prev_place.get("latitude")
        lon1 = prev_place.get("lon") or prev_place.get("longitude")
        lat2 = next_place.get("lat") or next_place.get("latitude")
        lon2 = next_place.get("lon") or next_place.get("longitude")

        if lat1 is not None and lon1 is not None and lat2 is not None and lon2 is not None:
            try:
                import math
                p1, p2 = math.radians(float(lat1)), math.radians(float(lat2))
                dlat = math.radians(float(lat2) - float(lat1))
                dlon = math.radians(float(lon2) - float(lon1))
                a = math.sin(dlat / 2) ** 2 + math.cos(p1) * math.cos(p2) * math.sin(dlon / 2) ** 2
                c = 2 * math.atan2(math.sqrt(a), math.sqrt(1 - a))
                dist_km = 6371 * c

                if dist_km <= 2.0:
                    return 15
                elif dist_km <= 6.0:
                    return 25
                elif dist_km <= 15.0:
                    return 40
                else:
                    return 55
            except Exception:
                pass

        return 25

    # =========================================================
    # PLACE COST ESTIMATION (BUG-10, BUG-11)
    # =========================================================

    @staticmethod
    def _estimate_place_cost(place: dict) -> float:
        """
        Estimate realistic activity / admission / local amenity fee for a place in INR.
        Deterministic estimates ensure the activities budget is always realistic (BUG 8).
        """
        if not isinstance(place, dict):
            return 50.0

        for key in (
            "price",
            "cost",
            "entry_fee",
            "admission_fee",
            "ticket_price",
            "estimated_cost",
        ):
            val = place.get(key)
            if val is not None:
                try:
                    amt = float(val)
                    if amt > 0:
                        return amt
                except (TypeError, ValueError):
                    pass

        category = str(place.get("category") or "").lower()
        name = str(place.get("name") or "").lower()

        # 1. Adventure & Theme Parks
        if any(k in category or k in name for k in ("theme_park", "water_park", "amusement", "adventure", "safari")):
            return 950.0

        # 2. Major museums, planetariums, science centres
        if any(k in category or k in name for k in ("museum", "science", "planetarium", "gallery", "exhibition")):
            return 200.0

        # 3. Major forts, palaces, archaeological ticketed sites
        if any(k in category or k in name for k in ("fort", "palace", "castle", "archaeological", "heritage")):
            return 150.0

        # 4. Zoos, aquariums, botanical gardens, wildlife
        if any(k in category or k in name for k in ("zoo", "aquarium", "botanical", "wildlife", "sanctuary")):
            return 100.0

        # 5. Beaches, water sports access, viewpoints
        if any(k in category or k in name for k in ("beach", "sea", "viewpoint", "lookout", "island", "lake", "waterfall")):
            return 50.0

        # 6. Temples, churches, shrines, heritage monuments
        if any(k in category or k in name for k in ("temple", "church", "cathedral", "monastery", "mosque", "monument", "memorial", "sights", "artwork", "statue")):
            return 50.0

        # 7. City parks and gardens
        if any(k in category or k in name for k in ("park", "garden")):
            return 30.0

        return 50.0

    # =========================================================
    # TRANSPORT PRICE EXTRACTION (BUG-01, BUG-12)
    # =========================================================

    @staticmethod
    def _extract_transport_mode_and_name(
        transport_data: Any,
        origin_name: str,
        destination_name: str,
        transport_pref: str | None = None,
        is_return: bool = False,
    ) -> tuple[str, str]:
        """
        Deterministically extract the transport mode ('Flight' or 'Train')
        and human-readable transport name ('IndiGo 6E 355', 'Air India AI 2432',
        'Mumbai - Delhi Express', etc.).
        """
        if hasattr(transport_data, "model_dump"):
            transport_data = transport_data.model_dump(mode="python")

        data = transport_data if isinstance(transport_data, dict) else {}

        type_str = str(data.get("type") or "").lower()
        pref_str = str(transport_pref or "").lower()

        is_flight = (
            "flight" in type_str
            or bool(data.get("airline") or data.get("flight_number") or data.get("flight_name"))
            or (pref_str == "flight" and not data.get("train_number") and not data.get("train_name"))
        )

        orig = destination_name if is_return else origin_name
        dest = origin_name if is_return else destination_name

        if is_flight:
            mode = "Flight"
            airline = data.get("airline") or ""
            f_no = data.get("flight_number") or ""
            flight_label = f"{airline} {f_no}".strip()
            name = (
                data.get("flight_name")
                or data.get("name")
                or (flight_label if flight_label else "Transport Unavailable")
            )
        else:
            mode = "Train"
            t_num = data.get("train_number") or ""
            t_name = data.get("train_name") or data.get("name") or ""
            if t_name:
                name = t_name
            elif t_num:
                name = f"Train #{t_num}"
            else:
                name = "Transport Unavailable"

        return mode, name

    @classmethod
    def _select_transport_fare_and_class(
        cls,
        data: Any,
        budget_category: str | None = None,
        default_mode: str = "train",
        selected_class: str | None = None,
    ) -> tuple[float, str, str]:
        """
        Extracts (fare_amount, class_code, class_name) from transport data.
        """
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="python")

        if not isinstance(data, dict):
            if "flight" in default_mode.lower():
                return 4800.0, "ECONOMY", "Economy Class"
            return 1450.0, "SL", "Sleeper Class (SL)"

        is_flight = "flight" in str(data.get("type") or default_mode).lower() or bool(data.get("airline") or data.get("flight_number"))

        # Check for flight cabin class
        if is_flight:
            cabin = selected_class or data.get("cabin_class") or data.get("selected_class") or "ECONOMY"
            c_name = format_transport_class_name(cabin, mode="flight")
            price = cls._extract_single_transport_price(data, target_class=cabin)
            if price <= 0:
                price = 4800.0
            return price, str(cabin).upper(), c_name

        # Resolve explicit or desired class
        target_class = (
            selected_class
            or data.get("selected_class")
            or data.get("class_code")
            or data.get("travel_class")
            or data.get("fare_class")
        )
        if target_class:
            target_class = str(target_class).strip().upper()

        fares = data.get("fares")
        if isinstance(fares, list) and fares:
            valid_fares = []
            for item in fares:
                if isinstance(item, dict):
                    ccode = str(
                        item.get("class_code")
                        or item.get("class")
                        or item.get("travel_class")
                        or item.get("code")
                        or item.get("name")
                        or "SL"
                    ).strip().upper()
                    for amt_key in ("amount", "fare", "price", "fare_amount"):
                        val = item.get(amt_key)
                        if val is not None:
                            try:
                                amt = float(val)
                                if amt > 0:
                                    valid_fares.append((amt, ccode))
                                    break
                            except (TypeError, ValueError):
                                pass

            if valid_fares:
                # 1. If explicit target_class is specified, match it directly!
                if target_class:
                    matched = [f for f in valid_fares if f[1] == target_class]
                    if matched:
                        c_name = format_transport_class_name(matched[0][1], mode="train")
                        return matched[0][0], matched[0][1], c_name

                # 2. If budget is premium and multiple classes available, prefer 3A/2A
                if budget_category == "premium":
                    ac_fares = [f for f in valid_fares if f[1] in ("2A", "3A", "1A", "EC", "CC")]
                    if ac_fares:
                        chosen_amt, chosen_code = ac_fares[0]
                    else:
                        chosen_amt, chosen_code = max(valid_fares, key=lambda x: x[0])
                else:
                    # Budget / standard: Prefer Sleeper (SL) or lowest available fare
                    sl_fares = [f for f in valid_fares if f[1] == "SL"]
                    if sl_fares:
                        chosen_amt, chosen_code = sl_fares[0]
                    else:
                        chosen_amt, chosen_code = min(valid_fares, key=lambda x: x[0])

                c_name = format_transport_class_name(chosen_code, mode="train")
                return chosen_amt, chosen_code, c_name

        # Single fare or explicit class_code
        direct_class = target_class
        if not direct_class and isinstance(data.get("classes"), list) and data["classes"]:
            direct_class = str(data["classes"][0]).strip().upper()
        if not direct_class:
            direct_class = "SL"

        price = cls._extract_single_transport_price(data, target_class=direct_class)
        if price <= 0:
            price = 1450.0

        c_name = format_transport_class_name(direct_class, mode="train")
        return price, str(direct_class).upper(), c_name

    @classmethod
    def _extract_single_transport_price(
        cls,
        data: Any,
        target_class: str | None = None,
        budget_category: str | None = None,
    ) -> float:
        """
        Extract one-way transport fare strictly matching the selected travel class.
        
        Priority:
        1. Explicit matching class in fares list
        2. Explicit selected-class fare field on data
        3. Existing fare dictionary ONLY IF proven to correspond to target_class
        4. Safe default / 0.0 fallback (no blind 1A or generic fare leakage)
        """
        if hasattr(data, "model_dump"):
            data = data.model_dump(mode="python")

        if not isinstance(data, dict):
            return 0.0

        # Resolve target class if not explicitly passed
        if not target_class:
            for key in ("selected_class", "travel_class", "fare_class", "class_code", "cabin_class", "class"):
                val = data.get(key)
                if val and isinstance(val, str) and val.strip():
                    target_class = val.strip().upper()
                    break

        if target_class:
            target_class = str(target_class).strip().upper()

        fares = data.get("fares")

        # 1. Priority 1: Match target class inside fares list
        if target_class and isinstance(fares, list) and fares:
            for item in fares:
                if isinstance(item, dict):
                    ccode = str(
                        item.get("class_code")
                        or item.get("class")
                        or item.get("travel_class")
                        or item.get("code")
                        or item.get("name")
                        or ""
                    ).strip().upper()
                    if ccode == target_class:
                        for amt_key in ("amount", "fare", "price", "fare_amount"):
                            val = item.get(amt_key)
                            if val is not None:
                                try:
                                    amt = float(val)
                                    if amt > 0:
                                        return amt
                                except (TypeError, ValueError):
                                    pass

        # 2. Priority 2: Selected class explicit fare fields on data
        if target_class:
            for key in ("selected_class_fare", "selected_fare", "class_fare"):
                val = data.get(key)
                if val is not None:
                    try:
                        amt = float(val)
                        if amt > 0:
                            return amt
                    except (TypeError, ValueError):
                        pass

        # 3. Priority 3: Existing fare dict ONLY if proven to match target_class or uncontradicted
        fare = data.get("fare")
        if isinstance(fare, dict):
            fare_class = str(
                fare.get("class_code")
                or fare.get("class")
                or fare.get("travel_class")
                or ""
            ).strip().upper()
            if fare_class:
                if not target_class or fare_class == target_class:
                    for amt_key in ("amount", "fare", "price"):
                        amount = fare.get(amt_key)
                        if amount is not None:
                            try:
                                val = float(amount)
                                if val > 0:
                                    return val
                            except (TypeError, ValueError):
                                pass
            else:
                # Generic fare dict without class code
                if not fares or not target_class:
                    for amt_key in ("amount", "fare", "price"):
                        amount = fare.get(amt_key)
                        if amount is not None:
                            try:
                                val = float(amount)
                                if val > 0:
                                    return val
                            except (TypeError, ValueError):
                                pass

        # 4. Direct price fields if no fares list conflict
        if not fares or not target_class:
            for key in ("price", "amount", "fare_amount"):
                val = data.get(key)
                if val is not None:
                    try:
                        amt = float(val)
                        if amt > 0:
                            return amt
                    except (TypeError, ValueError):
                        pass

        # 5. If no target_class was specified, but fares list is present:
        if isinstance(fares, list) and fares and not target_class:
            valid_fares = []
            for item in fares:
                if isinstance(item, dict):
                    for amt_key in ("amount", "fare", "price", "fare_amount"):
                        val = item.get(amt_key)
                        if val is not None:
                            try:
                                parsed = float(val)
                                ccode = str(
                                    item.get("class_code")
                                    or item.get("class")
                                    or item.get("travel_class")
                                    or item.get("code")
                                    or ""
                                ).strip().upper()
                                if parsed > 0:
                                    valid_fares.append((parsed, ccode))
                                    break
                            except (TypeError, ValueError):
                                pass
            if valid_fares:
                if budget_category == "premium":
                    ac_fares = [f for f in valid_fares if f[1] in ("2A", "3A", "1A", "EC", "CC")]
                    if ac_fares:
                        return ac_fares[0][0]
                    return max(valid_fares, key=lambda x: x[0])[0]
                else:
                    sl_fares = [f for f in valid_fares if f[1] == "SL"]
                    if sl_fares:
                        return sl_fares[0][0]
                    return min(valid_fares, key=lambda x: x[0])[0]

        return 0.0

    @classmethod
    def _get_transport_price(
        cls,
        transport: Any,
        target_class: str | None = None,
        budget_category: str | None = None,
    ) -> float:
        """
        Extract total roundtrip transport fare per person (outbound + return), matching target class.
        """
        if hasattr(transport, "model_dump"):
            transport = transport.model_dump(mode="python")

        if not isinstance(transport, dict):
            return 0.0

        t_class = target_class or transport.get("selected_class") or transport.get("class_code")
        outbound = cls._extract_single_transport_price(
            transport, target_class=t_class, budget_category=budget_category
        )
        return_trip = transport.get("return_trip")
        ret_class = (
            (return_trip.get("selected_class") or return_trip.get("class_code"))
            if isinstance(return_trip, dict)
            else None
        ) or t_class
        return_fare = (
            cls._extract_single_transport_price(
                return_trip, target_class=ret_class, budget_category=budget_category
            )
            if isinstance(return_trip, dict)
            else 0.0
        )

        return round(outbound + return_fare, 2)

    # =========================================================
    # HOTEL PRICE
    # =========================================================

    @staticmethod
    def _get_hotel_price(
        hotel: Any,
    ) -> float:

        # -----------------------------------------------------
        # Pydantic model support
        # -----------------------------------------------------

        if hasattr(
            hotel,
            "model_dump",
        ):

            hotel = (
                hotel.model_dump()
            )

        if not isinstance(
            hotel,
            dict,
        ):

            return 0.0

        # -----------------------------------------------------
        # Direct price
        # -----------------------------------------------------

        price = hotel.get(
            "price"
        )

        if price is not None:

            try:

                return float(
                    price
                )

            except (
                TypeError,
                ValueError,
            ):

                pass

        # -----------------------------------------------------
        # Booking-style fallback
        # -----------------------------------------------------

        for key in (
            "offerRetailRate",
            "offerInitialPrice",
            "suggestedSellingPrice",
        ):

            value = hotel.get(
                key
            )

            if isinstance(
                value,
                dict,
            ):

                amount = value.get(
                    "amount"
                )

                if amount is not None:

                    try:

                        return float(
                            amount
                        )

                    except (
                        TypeError,
                        ValueError,
                    ):

                        continue

        return 0.0

    # =========================================================
    # PLACE QUALITY & RELEVANCE FILTER
    # =========================================================

    @classmethod
    def _filter_places_by_quality(
        cls,
        verified_places: list[dict],
        destination_name: str = "",
    ) -> list[dict]:
        """
        Deterministic place quality & destination relevance filter.
        Separates VERIFIED (evidence exists) from RELEVANT (destination-worthy attraction).
        Prioritizes major tourist attractions and filters out ambiguous/minor/low-relevance places.
        """
        accepted = []
        rejected = []

        # Known tourist attraction keywords (positive indicators)
        HIGH_QUALITY_KEYWORDS = {
            "beach", "cove", "coast", "bay", "sea", "ocean",
            "fort", "fortress", "palace", "castle", "monument", "heritage", "citadel", "ruins", "gate", "tomb", "mausoleum", "haveli",
            "waterfall", "falls", "fall", "valley", "pass", "peak", "hill", "lake", "spring", "springs", "sanctuary", "national park", "wildlife", "river", "gorge", "caves", "cave", "plantation", "island", "dune", "viewpoint", "view point", "sunset point", "sunrise point", "cliff",
            "basilica", "cathedral", "church", "temple", "mandir", "gurudwara", "monastery", "ashram", "mosque", "dargah", "shrine", "pagoda", "stupa",
            "museum", "science centre", "science center", "planetarium", "aquarium", "zoo", "botanical garden", "promenade", "lighthouse",
        }

        # Low-relevance / reject keywords & patterns
        CIVIC_OR_COMMERCIAL_KEYWORDS = [
            "gymkhana", "rotary", "lions club", "panchayat", "municipality", "corporation",
            "hospital", "clinic", "dispensary", "pharmacy", "medical",
            "bank", "atm", "branch",
            "school", "college", "institute", "university", "academy", "classes",
            "hostel", "lodge", "hotel", "resort", "homestay", "guest house", "inn",
            "restaurant", "dhaba", "bar", "cafe", "bistro", "bakery", "sweets", "caterers",
            "residency", "apartments", "colony", "nagar", "society", "complex", "building", "tower", "enclave",
            "bus stand", "auto stand", "taxi stand", "railway station", "metro station", "airport", "petrol pump",
            "jewellers", "tailors", "salon", "spa", "parlour", "bazaar", "mart", "supermarket", "store", "shop",
        ]

        PERSONAL_NAME_INDICATORS = [
            "dr.", "dr ", "b.r.", "b. r.", "b.g.", "b. g.", "shri ", "smt ", "chhatrapati", "mahatma", "pandit", "swami", "sant"
        ]

        FAMOUS_SINGLE_WORD_EXCEPTIONS = {
            "aguada", "calangute", "baga", "anjuna", "candolim", "vagator", "colva", "palolem", "dudhsagar",
            "solang", "rohtang", "hadimba", "vashisht", "kullu", "manali", "munnar", "ooty", "kodaikanal",
            "hampi", "rishikesh", "varanasi", "jaipur", "udaipur", "jodhpur", "jaisalmer", "kedarnath", "badrinath"
        }

        # Generic names that can be returned as "verified" by search evidence but
        # are not specific enough to be safe itinerary attractions on their own.
        # Verification proves that something with this name exists; it does not
        # prove that the name identifies a destination-worthy tourist attraction.
        AMBIGUOUS_GENERIC_NAMES = {
            "castle",
            "fort",
            "palace",
            "temple",
            "museum",
            "garden",
            "park",
            "lake",
            "beach",
            "viewpoint",
            "green scarf",
            "gold scarf",
            "scarf",
        }

        AMBIGUOUS_NAME_TERMS = {
            "scarf", "unknown", "unnamed", "landmark", "place", "spot",
        }

        for place in verified_places:
            if not isinstance(place, dict):
                continue

            name = str(place.get("name") or place.get("place_name") or "").strip()
            name_lower = name.lower()
            words = [w for w in name_lower.replace("-", " ").replace("_", " ").split() if w]
            category = str(place.get("category") or "").strip().lower()
            desc = str(place.get("description") or "").strip().lower()

            rejection_reason = None

            # Check 1: Single personal name or ambiguous single-word name.
            # A generic attraction word such as "Castle" is not enough by itself:
            # it must identify a specific place. Famous one-word destinations remain
            # explicitly allow-listed above.
            if len(words) == 1:
                if name_lower not in FAMOUS_SINGLE_WORD_EXCEPTIONS:
                    if name_lower in ["shivaji", "ambedkar", "gandhi", "nehru", "tagore", "tilak", "patel", "bose", "subhash", "bhagat"]:
                        rejection_reason = "Generic statue or personal name without recognized destination attraction status"
                    else:
                        rejection_reason = "Ambiguous single-word name without specific attraction identity"

            # Check 1B: Generic multi-word names such as "Green scarf" are also
            # rejected unless the metadata provides a recognized attraction signal.
            if not rejection_reason and name_lower in AMBIGUOUS_GENERIC_NAMES:
                has_metadata_signal = any(
                    kw in category or kw in desc
                    for kw in HIGH_QUALITY_KEYWORDS
                )
                if not has_metadata_signal:
                    rejection_reason = "Ambiguous generic name without specific tourist attraction identity"

            if not rejection_reason and any(term in words for term in AMBIGUOUS_NAME_TERMS):
                # A generic suffix such as "place", "spot", or "scarf" needs
                # explicit tourist metadata to establish what the attraction is.
                has_metadata_signal = any(
                    kw in category or kw in desc
                    for kw in HIGH_QUALITY_KEYWORDS
                )
                if not has_metadata_signal:
                    rejection_reason = "Ambiguous generic attraction name without supporting tourist metadata"

            # Check 2: Personal name / statue with multiple words but no major attraction status
            if not rejection_reason:
                if any(ind in name_lower for ind in PERSONAL_NAME_INDICATORS):
                    if not any(kw in name_lower for kw in ["museum", "memorial", "fort", "palace", "temple", "church", "sanctuary", "national park"]):
                        rejection_reason = "Generic statue or personal name without recognized destination attraction status"

            # Check 3: Obscure local curiosities & minor spots
            if not rejection_reason:
                if any(obs in name_lower for obs in ["headless nandi", "nandi statue", "broken idol", "local curiosity"]):
                    rejection_reason = "Obscure local curiosity / minor landmark without major tourist significance"
                elif any(p in name_lower for p in ["childrens park", "children park", "child park", "joggers park", "traffic park", "community park", "local park", "recreation ground", "play ground"]):
                    rejection_reason = "Minor local park or neighborhood recreational area"
                elif ("art gallery" in name_lower or "photo studio" in name_lower or "framing" in name_lower) and not any(kw in name_lower for kw in ["national", "state", "heritage", "museum"]):
                    rejection_reason = "Small private gallery or commercial studio without major destination heritage"

            # Check 4: Civic, infrastructure, commercial, or residential
            if not rejection_reason:
                for civ in CIVIC_OR_COMMERCIAL_KEYWORDS:
                    if civ in name_lower:
                        if not any(kw in name_lower for kw in ["museum", "fort", "palace", "temple", "church", "heritage"]):
                            rejection_reason = "Civic, residential, or commercial location not suited for tourist sightseeing"
                            break

            # Check 5: Score calculation
            if not rejection_reason:
                score = 0
                has_tourist_keyword = any(kw in name_lower or kw in category or kw in desc for kw in HIGH_QUALITY_KEYWORDS)
                if has_tourist_keyword:
                    score += 40
                
                # Rating bonus
                rating = place.get("rating")
                try:
                    if rating is not None and float(rating) >= 3.8:
                        score += 20
                except (ValueError, TypeError):
                    pass

                # Multi-word landmark bonus
                if len(words) >= 2:
                    score += 10

                # Verified evidence is already the primary eligibility gate.
                # Do not discard moderate but potentially useful attractions merely
                # because their name lacks one of the keyword matches.
                # The explicit rejection rules above remain the hard safety filter.

            if rejection_reason:
                rejected.append({"place": name, "reason": rejection_reason, "data": place})
            else:
                accepted.append(place)

        print("\nPLACE QUALITY FILTER")
        print("--------------------")
        print(f"Verified places received: {len(verified_places)}")
        print(f"High-quality/relevant places accepted: {len(accepted)}")
        print(f"Rejected for low relevance: {len(rejected)}")

        if rejected:
            print()
            for rej in rejected:
                print(f"Place: {rej['place']}")
                print(f"Reason: {rej['reason']}")
                print()

        print("FINAL ITINERARY PLACES:")
        if accepted:
            for i, p in enumerate(accepted, 1):
                p_name = p.get("name") or p.get("place_name") or "Attraction"
                print(f"{i}. {p_name}")
        else:
            print("No high-quality places available.")
        print()

        return accepted
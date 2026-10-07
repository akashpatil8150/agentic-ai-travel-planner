import json
import logging
from datetime import datetime, timedelta

from app.observability.agent_logger import (
    agent_start,
    agent_success,
    agent_failure,
)

from app.input.transport_schema import (
    TransportSearchRequest,
)

from app.services.transport_service import (
    TransportService,
)

from app.services.llm.llm_client import (
    LLMClient,
    LLMClientError,
)

from app.state.trip_state import (
    TripState,
)


logger = logging.getLogger(__name__)


class TransportAgent:
    """
    Transport Agent.

    Responsibilities:
        1. Read transport requirements from TripState
        2. Use LLM for transport preference reasoning
        3. Search flights/trains through TransportService
        4. Use LLM to evaluate returned transport options
        5. Store transport options in TripState

    Does NOT:
        - call external transport APIs directly
        - resolve airports/stations directly
        - perform HTTP requests
    """

    def __init__(self):

        self.transport_service = (
            TransportService()
        )

        self.llm = LLMClient()

    # ========================================================
    # RUN
    # ========================================================

    def run(
        self,
        state: TripState,
        task: str = "",
    ) -> TripState:

        agent_start_time = agent_start("transport",state,)

        # ====================================================
        # VALIDATE STATE
        # ====================================================

        if not isinstance(
            state,
            TripState,
        ):

            raise TypeError(
                "TransportAgent expects a TripState object."
            )

        if state.origin is None:

            raise ValueError(
                "Origin is required for Transport Agent."
            )

        if state.destination is None:

            raise ValueError(
                "Destination is required for Transport Agent."
            )

        if state.travel_dates is None:

            raise ValueError(
                "Travel dates are required for Transport Agent."
            )

        if state.travelers is None:

            raise ValueError(
                "Traveler information is required "
                "for Transport Agent."
            )

        transport_traveler_count = max(1, (state.travelers.adults or 1) + (state.travelers.children or 0))
        print(f"[DEBUG] transport traveler_count: {transport_traveler_count}")

        # ====================================================
        # EXPLICIT CONFIRMED TRANSPORT SELECTION CHECK
        # ====================================================
        if getattr(state, "outbound_transport", None) and isinstance(state.outbound_transport, dict):
            logger.info("Transport Agent: using user's confirmed transport selection")
            if not state.transport_options:
                state.transport_options = [state.outbound_transport]
            agent_success("transport", state, agent_start_time, status="confirmed_selection")
            return state


        # ====================================================
        # TRANSPORT PREFERENCE
        # ====================================================

        # The user's explicit transport preference is authoritative.
        # Transport mode is strictly "train" or "flight".
        transport_preference = (
            getattr(state, "transport_preference", "train") or "train"
        ).strip().lower()

        transport_type = "train" if transport_preference == "train" else "flight"

        logger.info(
            "Transport preference resolved | preference=%s | search_mode=%s",
            transport_preference,
            transport_type,
        )

        # ====================================================
        # BUILD TRANSPORT REQUEST
        # ====================================================

        # Use the canonical city field for transport search.
        # Geoapify's `name` can be a landmark/business name
        # such as "Delhi Darbar", while transport resolvers
        # require the city name such as "Delhi".
        origin_city = (
            state.origin.city
            or state.origin.name
        )

        destination_city = (
            state.destination.city
            or state.destination.name
        )

        request = TransportSearchRequest(
            origin=origin_city,
            destination=destination_city,
            departure_date=state.travel_dates.start,
            return_date=state.travel_dates.end,
            adults=state.travelers.adults,
            children=state.travelers.children,
            transport_type=transport_type,
        )

        # ====================================================
        # SEARCH TRANSPORT
        # ====================================================

        try:

            result = (
                self.transport_service.search_transport(
                    request,
                    orig_location=state.origin,
                    dest_location=state.destination,
                )
            )

        except ValueError as exc:

            logger.warning(
                "Transport validation failed | error=%s",
                exc,
            )

            agent_failure("transport", state, agent_start_time, exc)

            raise

        except Exception as exc:
            logger.warning(
                "Transport live search failed | error=%s",
                exc,
            )
            result = {
                "flight_options": [],
                "train_options": [],
                "status": "unavailable",
                "reason": "provider_error",
                "error": str(exc),
            }

        # ====================================================
        # STORE RESULTS
        # ====================================================

        state.transport_options = []

        flights = result.get(
            "flight_options",
            [],
        )

        trains = result.get(
            "train_options",
            [],
        )

        first_mile_trans = result.get("first_mile_transfer") or {}
        last_mile_trans = result.get("last_mile_transfer") or {}
        out_trans = result.get("outbound_transfer") or result.get("transfer") or {}
        ret_first_mile = result.get("return_first_mile_transfer") or {}
        ret_last_mile = result.get("return_last_mile_transfer") or {}
        ret_trans = result.get("return_transfer") or {}

        if first_mile_trans:
            state.metadata["first_mile_transfer"] = first_mile_trans
            state.first_mile_transfer = first_mile_trans
        if last_mile_trans:
            state.metadata["last_mile_transfer"] = last_mile_trans
            state.last_mile_transfer = last_mile_trans
        if out_trans:
            state.metadata["outbound_transfer"] = out_trans
            state.outbound_transfer = out_trans
        if ret_first_mile:
            state.metadata["return_first_mile_transfer"] = ret_first_mile
            state.return_first_mile_transfer = ret_first_mile
        if ret_last_mile:
            state.metadata["return_last_mile_transfer"] = ret_last_mile
            state.return_last_mile_transfer = ret_last_mile
        if ret_trans:
            state.metadata["return_transfer"] = ret_trans
            state.return_transfer = ret_trans

        orig_ep = result.get("origin_transport_endpoint") or {}
        dest_ep = result.get("destination_transport_endpoint") or {}
        ret_orig_ep = result.get("return_origin_transport_endpoint") or {}
        ret_dest_ep = result.get("return_destination_transport_endpoint") or {}

        if orig_ep:
            state.metadata["origin_transport_endpoint"] = orig_ep
        if dest_ep:
            state.metadata["destination_transport_endpoint"] = dest_ep
        if ret_orig_ep:
            state.metadata["return_origin_transport_endpoint"] = ret_orig_ep
        if ret_dest_ep:
            state.metadata["return_destination_transport_endpoint"] = ret_dest_ep

        for flight in flights:
            f_dict = flight.model_dump() if hasattr(flight, "model_dump") else (dict(flight) if isinstance(flight, dict) else {})
            if f_dict:
                airline = f_dict.get("airline") or ""
                f_no = f_dict.get("flight_number") or ""
                if airline and f_no:
                    flight_label = f"{airline} {f_no}" if airline.lower() not in f_no.lower() else f_no
                elif airline:
                    flight_label = f"{airline} ({origin_city} - {destination_city})"
                elif f_no:
                    flight_label = f"Flight {f_no}"
                else:
                    flight_label = f"{origin_city} - {destination_city} Flight"

                f_dict["type"] = "flight"
                f_dict["airline"] = airline or f_dict.get("airline") or "Flight"
                f_dict["flight_number"] = f_no or f_dict.get("flight_number")
                f_dict["name"] = f_dict.get("name") or flight_label
                f_dict["flight_name"] = f_dict.get("flight_name") or flight_label
                f_dict["user_origin"] = origin_city
                f_dict["user_destination"] = destination_city
                if first_mile_trans:
                    f_dict["first_mile_transfer"] = first_mile_trans
                if last_mile_trans:
                    f_dict["last_mile_transfer"] = last_mile_trans
                if out_trans:
                    f_dict["outbound_transfer"] = out_trans
                    f_dict["transfer"] = out_trans
                if ret_trans:
                    f_dict["return_transfer"] = ret_trans
                state.transport_options.append(f_dict)

        for train in trains:
            t_dict = train.model_dump() if hasattr(train, "model_dump") else (dict(train) if isinstance(train, dict) else {})
            if t_dict:
                t_name = t_dict.get("train_name") or t_dict.get("name") or f"{origin_city} - {destination_city} Superfast Express"
                t_dict["type"] = "train"
                t_dict["name"] = t_dict.get("name") or t_name
                t_dict["train_name"] = t_dict.get("train_name") or t_name
                t_dict["user_origin"] = origin_city
                t_dict["user_destination"] = destination_city
                if first_mile_trans:
                    t_dict["first_mile_transfer"] = first_mile_trans
                if last_mile_trans:
                    t_dict["last_mile_transfer"] = last_mile_trans
                if out_trans:
                    t_dict["outbound_transfer"] = out_trans
                    t_dict["transfer"] = out_trans
                if ret_trans:
                    t_dict["return_transfer"] = ret_trans
                state.transport_options.append(t_dict)

        if state.transport_options:
            state.outbound_transport = state.transport_options[0]
            ret_data = state.transport_options[0].get("return_trip")
            if isinstance(ret_data, dict) and ret_data:
                if ret_first_mile and "first_mile_transfer" not in ret_data:
                    ret_data["first_mile_transfer"] = ret_first_mile
                    ret_data["return_first_mile_transfer"] = ret_first_mile
                if ret_last_mile and "last_mile_transfer" not in ret_data:
                    ret_data["last_mile_transfer"] = ret_last_mile
                    ret_data["return_last_mile_transfer"] = ret_last_mile
                if ret_trans and "return_transfer" not in ret_data:
                    ret_data["return_transfer"] = ret_trans
                state.return_transport = ret_data
                state.metadata["return_transport"] = ret_data
            else:
                state.return_transport = None
                state.metadata["return_transport"] = None
        else:
            state.outbound_transport = None
            state.return_transport = None
            state.metadata["return_transport"] = None

        # Keep the strategy and status visible in state for downstream
        # option generation / itinerary building.
        state.metadata["transport_preference"] = transport_preference
        state.metadata["transport_search_mode"] = transport_type
        state.metadata["transport_status"] = result.get("transport_status") or ("AVAILABLE" if state.transport_options else "UNAVAILABLE")
        state.metadata["outbound_transport_status"] = result.get("outbound_status")
        state.metadata["return_transport_status"] = result.get("return_status")

        # ====================================================
        # RESULT SUMMARY & STRUCTURED DEBUG LOGS
        # ====================================================

        opt = state.transport_options[0] if state.transport_options else {}
        ret = opt.get("return_trip") if isinstance(opt, dict) else (state.return_transport if isinstance(state.return_transport, dict) else None)
        if not isinstance(ret, dict):
            ret = None

        has_outbound = bool(state.transport_options)
        has_return = bool(ret)

        is_train = opt.get("type") == "train" if has_outbound else False
        num = (opt.get("train_number") if is_train else opt.get("flight_number")) if has_outbound else None
        name = (opt.get("train_name") if is_train else opt.get("flight_name") or opt.get("name")) if has_outbound else None
        sel_out_train_str = f"{num} {name}".strip() if (num or name) else "None"

        st_orig_code = (opt.get("boarding_station_code") or opt.get("boarding_station") or opt.get("actual_origin_station") or opt.get("from_station_code") or opt.get("from_code") or orig_ep.get("code") or (opt.get("source", {}).get("code") if isinstance(opt.get("source"), dict) else None)) if has_outbound else None
        st_dest_code = (opt.get("alighting_station_code") or opt.get("alighting_station") or opt.get("actual_destination_station") or opt.get("to_station_code") or opt.get("to_code") or dest_ep.get("code") or (opt.get("destination_airport", {}).get("code") if isinstance(opt.get("destination_airport"), dict) else None)) if has_outbound else None

        st_orig_name = (opt.get("boarding_station_name") or opt.get("from_station_name") or orig_ep.get("name") or st_orig_code or (opt.get("source", {}).get("name") if isinstance(opt.get("source"), dict) else opt.get("source")) or origin_city) if has_outbound else "N/A"
        st_dest_name = (opt.get("alighting_station_name") or opt.get("to_station_name") or dest_ep.get("name") or st_dest_code or (opt.get("destination_airport", {}).get("name") if isinstance(opt.get("destination_airport"), dict) else opt.get("destination")) or destination_city) if has_outbound else "N/A"

        ret_orig_code = (ret.get("boarding_station_code") or ret.get("boarding_station") or ret.get("actual_origin_station") or ret.get("from_station_code") or ret.get("from_code") or ret_orig_ep.get("code")) if isinstance(ret, dict) else (ret_orig_ep.get("code") if ret else None)
        ret_dest_code = (ret.get("alighting_station_code") or ret.get("alighting_station") or ret.get("actual_destination_station") or ret.get("to_station_code") or ret.get("to_code") or ret_dest_ep.get("code")) if isinstance(ret, dict) else (ret_dest_ep.get("code") if ret else None)

        ret_orig_name = (ret.get("boarding_station_name") or ret.get("from_station_name") or ret_orig_ep.get("name") or ret_orig_code) if isinstance(ret, dict) else (ret_orig_ep.get("name") if ret else "N/A")
        ret_dest_name = (ret.get("alighting_station_name") or ret.get("to_station_name") or ret_dest_ep.get("name") or ret_dest_code) if isinstance(ret, dict) else (ret_dest_ep.get("name") if ret else "N/A")

        out_train_orig = (opt.get("train_origin_station") or st_orig_code) if has_outbound else "N/A"
        out_train_dest = (opt.get("train_destination_station") or st_dest_code) if has_outbound else "N/A"
        ret_train_orig = (ret.get("train_origin_station") if isinstance(ret, dict) else None) or ret_orig_code or "N/A"
        ret_train_dest = (ret.get("train_destination_station") if isinstance(ret, dict) else None) or ret_dest_code or "N/A"

        cand_orig_display = orig_ep.get("code", st_orig_code or origin_city) if orig_ep else origin_city

        out_first_mile_display = (
            f"{first_mile_trans.get('from')} -> {first_mile_trans.get('to')}"
            if (has_outbound and first_mile_trans and first_mile_trans.get("has_transfer"))
            else (
                f"{origin_city} -> {st_orig_code or st_orig_name}"
                if (has_outbound and st_orig_code and origin_city.strip().lower() != str(st_orig_code).strip().lower())
                else "None"
            )
        )
        out_last_mile_display = (
            f"{last_mile_trans.get('from')} -> {last_mile_trans.get('to')}"
            if (has_outbound and last_mile_trans and last_mile_trans.get("has_transfer"))
            else (
                f"{st_dest_code or st_dest_name} -> {destination_city}"
                if (has_outbound and st_dest_code and destination_city.strip().lower() != str(st_dest_code).strip().lower())
                else ("None" if not (has_outbound and out_trans and out_trans.get("has_transfer")) else f"{out_trans.get('from')} -> {out_trans.get('to')}")
            )
        )

        act_out_route_str = f"{st_orig_code or st_orig_name} -> {st_dest_code or st_dest_name}" if (has_outbound and st_orig_code and st_dest_code) else "None"

        ret_num = ret.get("train_number") if isinstance(ret, dict) else None
        ret_name = ret.get("train_name") if isinstance(ret, dict) else (ret.get("name") if isinstance(ret, dict) else None)
        sel_ret_train_str = f"{ret_num} {ret_name}".strip() if (ret_num or ret_name) else "None"
        act_ret_route_str = f"{ret_orig_code or ret_orig_name} -> {ret_dest_code or ret_dest_name}" if (has_return and ret_orig_code and ret_dest_code and ret_orig_code != "None") else "None"

        ret_first_mile_display = (
            f"{ret_first_mile.get('from')} -> {ret_first_mile.get('to')}"
            if (has_return and ret_first_mile and ret_first_mile.get("has_transfer"))
            else (
                f"{destination_city} -> {ret_orig_code or ret_orig_name}"
                if (has_return and ret_orig_code and destination_city.strip().lower() != str(ret_orig_code).strip().lower() and ret_orig_code != "None")
                else (f"{ret_trans.get('from')} -> {ret_trans.get('to')}" if (has_return and ret_trans and ret_trans.get("has_transfer")) else "None")
            )
        )
        ret_last_mile_display = (
            f"{ret_last_mile.get('from')} -> {ret_last_mile.get('to')}"
            if (has_return and ret_last_mile and ret_last_mile.get("has_transfer"))
            else (
                f"{ret_dest_code or ret_dest_name} -> {origin_city}"
                if (has_return and ret_dest_code and origin_city.strip().lower() != str(ret_dest_code).strip().lower() and ret_dest_code != "None")
                else "None"
            )
        )

        from app.services.train.api_tracker import api_tracker
        from app.observability.metrics import observability_metrics

        primary_status = "429 Rate Limited (Circuit Breaker Active)" if api_tracker.railradar_rate_limited else ("200 OK" if api_tracker.railradar_requests > 0 else "Available")
        fallback_used = "Yes" if (api_tracker.railcore_journey_requests > 0 or api_tracker.railradar_rate_limited or (has_outbound and opt.get("provider") == "railcore")) else "No"

        logger.debug(
            "Transport route debug: user_route=%s->%s primary=%s (%s) fallback=%s (used=%s) outbound=%s return=%s",
            origin_city, destination_city, "RailRadar", primary_status, "RailCore", fallback_used, sel_out_train_str, sel_ret_train_str
        )

        outbound_route_str = f"{st_orig_code or origin_city} → {st_dest_code or destination_city}" if has_outbound else f"{origin_city} → {destination_city}"
        outbound_train_str = sel_out_train_str if sel_out_train_str != "None" else (f"{opt.get('carrier_name', '')} {opt.get('flight_number', '')}".strip() or "N/A")
        
        return_route_str = f"{ret_orig_code or destination_city} → {ret_dest_code or origin_city}" if (has_return and ret_orig_code and ret_dest_code and ret_orig_code != "None") else None
        return_train_str = sel_ret_train_str if (has_return and sel_ret_train_str != "None") else None

        candidates_count = len(state.transport_options) or len(trains) or len(flights)
        search_result_str = "VALID_TRAIN_FOUND" if (trains or (has_outbound and opt.get("type") == "train")) else ("VALID_FLIGHT_FOUND" if (flights or (has_outbound and opt.get("type") == "flight")) else "NO_RESULTS")

        observability_metrics.print_transport_summary(
            outbound_route=outbound_route_str,
            outbound_train=outbound_train_str,
            return_route=return_route_str,
            return_train=return_train_str,
            candidates_count=candidates_count,
            api_calls=None,
            cache_hits=None,
            cache_misses=None,
            rate_limited=api_tracker.is_rate_limited(),
            search_result=search_result_str,
        )

        agent_status = (
            "success"
            if state.transport_options
            else (
                "unavailable"
                if result.get("status") == "unavailable"
                or result.get("transport_status") == "UNAVAILABLE"
                else "no_results"
            )
        )

        agent_success(
            "transport",
            state,
            agent_start_time,
            status=agent_status,
        )

        logger.info(
            "Transport Agent completed | "
            "mode=%s | flights=%s | trains=%s | total=%s",
            transport_type,
            len(flights),
            len(trains),
            len(state.transport_options),
        )

        return state
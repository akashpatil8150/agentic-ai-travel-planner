import json
import logging
from datetime import datetime, timedelta

from app.state.trip_state import TripState

from app.observability.agent_logger import (
    agent_start,
    agent_success,
    agent_failure,
)

from app.services.hotel.hotel_schema import (
    HotelSearchRequest,
)

from app.services.hotel.hotel_service import (
    HotelService,
)

from app.services.llm.llm_client import (
    LLMClient,
    LLMClientError,
)


logger = logging.getLogger(__name__)


class HotelAgent:
    """
    Hotel Agent.

    Responsibilities:
        1. Validate TripState
        2. Create HotelSearchRequest
        3. Call HotelService
        4. Use LLM to evaluate hotel options
        5. Rank hotels according to user preferences
        6. Store hotel options in TripState

    HotelAgent does NOT:
        - call LiteAPI directly
        - call SerpAPI directly
        - normalize provider responses
        - perform HTTP requests

    Provider logic remains inside HotelService.
    """

    def __init__(self):

        self.hotel_service = HotelService()

        # ====================================================
        # CENTRAL LLM CLIENT
        # ====================================================

        self.llm = LLMClient()

    @staticmethod
    def _parse_datetime(value, base_date=None, reference_datetime=None):
        """Parse common provider datetime representations safely."""
        if isinstance(value, datetime):
            return value
        if not value:
            return None
        raw = str(value).strip()
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
        for fmt in (
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%dT%H:%M",
            "%Y-%m-%dT%H:%M:%S",
            "%H:%M",
            "%H:%M:%S",
        ):
            try:
                parsed = datetime.strptime(raw, fmt)
                if fmt.startswith("%H"):
                    if base_date is None:
                        return None
                    parsed = datetime.combine(base_date, parsed.time())
                    if reference_datetime and parsed <= reference_datetime:
                        parsed += timedelta(days=1)
                return parsed
            except ValueError:
                continue
        return None

    # =====================================================
    # RUN HOTEL AGENT
    # =====================================================

    def run(
        self,
        state: TripState,
        task: str = "",
    ) -> TripState:

        agent_start_time = agent_start("hotel", state)

        logger.info(
            "Hotel Agent started"
        )

        # =================================================
        # VALIDATE STATE
        # =================================================

        if not isinstance(
            state,
            TripState,
        ):

            exc = TypeError(
                "HotelAgent expects a TripState object."
            )
            agent_failure("hotel", state, agent_start_time, exc)
            raise exc

        # =================================================
        # VALIDATE DESTINATION
        # =================================================

        if state.destination is None:

            exc = ValueError(
                "Destination is required for hotel search."
            )
            agent_failure("hotel", state, agent_start_time, exc)
            raise exc

        # =================================================
        # VALIDATE TRAVEL DATES
        # =================================================

        if state.travel_dates is None:

            exc = ValueError(
                "Travel dates are required for hotel search."
            )
            agent_failure("hotel", state, agent_start_time, exc)
            raise exc

        # =================================================
        # VALIDATE TRAVELERS
        # =================================================

        if state.travelers is None:

            exc = ValueError(
                "Traveler information is required "
                "for hotel search."
            )
            agent_failure("hotel", state, agent_start_time, exc)
            raise exc

        # =================================================
        # CREATE HOTEL REQUEST (FINAL DESTINATION ONLY)
        # =================================================

        dest_city = (state.destination.city or state.destination.name or "").strip()
        if not dest_city:
            dest_city = str(state.destination.name).strip()

        logger.info("Hotel search location: %s", dest_city)
        print(f"\nHotel search location: {dest_city}")

        try:
            checkin_date = state.travel_dates.start
            checkout_date = state.travel_dates.end

            transport = state.outbound_transport or state.selected_transport
            if not transport and state.transport_options:
                transport = state.transport_options[0]

            if hasattr(transport, "model_dump"):
                transport = transport.model_dump(mode="python")

            # Resolve hotel dates from the actual transport journey, not the
            # user-entered trip dates. Time-only provider fields are anchored
            # to the journey date and overnight arrivals roll to the next day.
            if isinstance(transport, dict):
                journey_date = transport.get("journey_date") or state.travel_dates.start
                if isinstance(journey_date, str):
                    try:
                        journey_date = datetime.fromisoformat(journey_date).date()
                    except ValueError:
                        journey_date = state.travel_dates.start

                arr_value = (
                    transport.get("arrival_datetime")
                    or transport.get("arrival")
                    or transport.get("arrival_time")
                )
                dep_value = (
                    transport.get("departure_datetime")
                    or transport.get("departure")
                    or transport.get("departure_time")
                )

                dep_dt = self._parse_datetime(
                    dep_value,
                    base_date=journey_date,
                )

                # Prefer a provider-supplied full arrival datetime.
                arr_dt = self._parse_datetime(
                    transport.get("arrival_datetime"),
                    base_date=journey_date,
                    reference_datetime=dep_dt,
                )

                # If the Pydantic transport model dropped arrival_datetime,
                # reconstruct the real arrival from departure + duration.
                # This is critical for multi-day journeys such as
                # 18 Sep 08:05 -> 20 Sep 03:00.
                if not arr_dt and dep_dt:
                    duration_mins = transport.get("duration_minutes")
                    if duration_mins is not None:
                        try:
                            arr_dt = dep_dt + timedelta(minutes=int(duration_mins))
                        except (TypeError, ValueError):
                            arr_dt = None

                # Final fallback for providers that only expose arrival time.
                if not arr_dt:
                    arr_dt = self._parse_datetime(
                        arr_value,
                        base_date=journey_date,
                        reference_datetime=dep_dt,
                    )

                if arr_dt:
                    checkin_date = arr_dt.date()

                logger.info(
                    "Hotel arrival date resolution | journey_date=%s | "
                    "departure=%s | arrival_raw=%s | duration_minutes=%s | "
                    "resolved_arrival=%s | checkin=%s",
                    journey_date,
                    dep_dt,
                    arr_value,
                    transport.get("duration_minutes"),
                    arr_dt,
                    checkin_date,
                )

                # Return transport can be nested or stored separately in TripState.
                return_trip = transport.get("return_trip") or getattr(state, "return_transport", None)
                if hasattr(return_trip, "model_dump"):
                    return_trip = return_trip.model_dump(mode="python")

                if isinstance(return_trip, dict):
                    return_date = return_trip.get("journey_date") or state.travel_dates.end
                    if isinstance(return_date, str):
                        try:
                            return_date = datetime.fromisoformat(return_date).date()
                        except ValueError:
                            return_date = state.travel_dates.end
                    dep_value = (
                        return_trip.get("departure_datetime")
                        or return_trip.get("departure")
                        or return_trip.get("departure_time")
                    )
                    dep_dt = self._parse_datetime(dep_value, base_date=return_date)
                    if dep_dt:
                        # Resolve the actual destination departure for the return journey.
                        # A long transfer can move hotel checkout to the previous calendar day.
                        return_transfer = (
                            (return_trip.get("return_transfer") if isinstance(return_trip, dict) else None)
                            or (return_trip.get("transfer") if isinstance(return_trip, dict) else None)
                            or getattr(state, "return_transfer", None)
                            or getattr(state, "metadata", {}).get("return_transfer")
                            or {}
                        )
                        transfer_mins = return_transfer.get("duration_minutes") or 0 if isinstance(return_transfer, dict) else 0
                        if not transfer_mins and isinstance(return_transfer, dict):
                            raw_transfer = return_transfer.get("estimated_transfer_time")
                            if raw_transfer:
                                text = str(raw_transfer).replace("~", "").strip()
                                try:
                                    if "h" in text:
                                        parts = text.split("h")
                                        transfer_mins = int(parts[0].strip()) * 60
                                        if len(parts) > 1 and parts[1].strip():
                                            transfer_mins += int(parts[1].replace("m", "").strip())
                                    elif "m" in text:
                                        transfer_mins = int(text.replace("m", "").strip())
                                except (TypeError, ValueError):
                                    transfer_mins = 0
                        hotel_departure_dt = (
                            dep_dt - timedelta(minutes=int(transfer_mins) + 60)
                            if transfer_mins > 0
                            else dep_dt
                        )
                        checkout_date = hotel_departure_dt.date()
            elif getattr(state, "return_transport", None):
                return_trip = state.return_transport
                if hasattr(return_trip, "model_dump"):
                    return_trip = return_trip.model_dump(mode="python")
                if isinstance(return_trip, dict):
                    return_date = return_trip.get("journey_date") or state.travel_dates.end
                    if isinstance(return_date, str):
                        try:
                            return_date = datetime.fromisoformat(return_date).date()
                        except ValueError:
                            return_date = state.travel_dates.end
                    dep_value = return_trip.get("departure_datetime") or return_trip.get("departure") or return_trip.get("departure_time")
                    dep_dt = self._parse_datetime(dep_value, base_date=return_date)
                    if dep_dt:
                        # Resolve the actual destination departure for the return journey.
                        # A long transfer can move hotel checkout to the previous calendar day.
                        return_transfer = (
                            (return_trip.get("return_transfer") if isinstance(return_trip, dict) else None)
                            or (return_trip.get("transfer") if isinstance(return_trip, dict) else None)
                            or getattr(state, "return_transfer", None)
                            or getattr(state, "metadata", {}).get("return_transfer")
                            or {}
                        )
                        transfer_mins = return_transfer.get("duration_minutes") or 0 if isinstance(return_transfer, dict) else 0
                        if not transfer_mins and isinstance(return_transfer, dict):
                            raw_transfer = return_transfer.get("estimated_transfer_time")
                            if raw_transfer:
                                text = str(raw_transfer).replace("~", "").strip()
                                try:
                                    if "h" in text:
                                        parts = text.split("h")
                                        transfer_mins = int(parts[0].strip()) * 60
                                        if len(parts) > 1 and parts[1].strip():
                                            transfer_mins += int(parts[1].replace("m", "").strip())
                                    elif "m" in text:
                                        transfer_mins = int(text.replace("m", "").strip())
                                except (TypeError, ValueError):
                                    transfer_mins = 0
                        hotel_departure_dt = (
                            dep_dt - timedelta(minutes=int(transfer_mins) + 60)
                            if transfer_mins > 0
                            else dep_dt
                        )
                        checkout_date = hotel_departure_dt.date()

            if checkout_date <= checkin_date:
                checkout_date = checkin_date + timedelta(days=1)

            logger.info(
                "HOTEL DATE FINAL | checkin=%s | checkout=%s | nights=%s",
                checkin_date,
                checkout_date,
                (checkout_date - checkin_date).days,
            )

            logger.info(
                "Resolved hotel stay dates | checkin=%s | checkout=%s | nights=%s",
                checkin_date,
                checkout_date,
                (checkout_date - checkin_date).days,
            )

            rooms_needed = max(1, (state.travelers.adults + 1) // 2)
            hotel_request = HotelSearchRequest(

                city=dest_city,

                country_code="IN",

                checkin=checkin_date,

                checkout=checkout_date,

                adults=state.travelers.adults,

                children=state.travelers.children,

                rooms=rooms_needed,

                currency="INR",

                max_hotels=5,
            )

        except ValueError as exc:

            logger.warning(
                "Hotel request validation failed | "
                "error=%s",
                exc,
            )

            state.hotel_options = []

            agent_success(
                "hotel",
                state,
                agent_start_time,
                status="invalid_request",
            )
            return state

        # =================================================
        # LOG REQUEST
        # =================================================

        logger.info(
            "Hotel search request created | "
            "city=%s | checkin=%s | checkout=%s | "
            "adults=%s | children=%s | rooms=%s",
            hotel_request.city,
            hotel_request.checkin,
            hotel_request.checkout,
            hotel_request.adults,
            hotel_request.children,
            hotel_request.rooms,
        )

        # =================================================
        # SEARCH HOTELS
        # =================================================

        try:

            response = (
                self.hotel_service.search_hotels(
                    hotel_request
                )
            )

        except ValueError as exc:

            state.hotel_options = []

            logger.warning(
                "Hotel Agent search validation failed | error=%s",
                exc,
            )
            agent_success(
                "hotel",
                state,
                agent_start_time,
                status="unavailable",
            )
            return state

        except Exception as exc:

            logger.warning(
                "Hotel Agent search failed | "
                "error=%s",
                exc,
            )

            state.hotel_options = []

            agent_failure("hotel", state, agent_start_time, exc)
            return state

        # =================================================
        # STORE RESULTS
        # =================================================

        hotels = response.hotels or []

        # Stamp the resolved stay dates on every normalized hotel option so
        # downstream selection, itinerary building and pricing use the same
        # hotel stay window. Do not overwrite provider data when it already
        # contains a meaningful value.
        for hotel in hotels:
            if hasattr(hotel, "model_dump"):
                hotel_dict = hotel.model_dump(mode="python")
                hotel_dict.setdefault("check_in", checkin_date)
                hotel_dict.setdefault("check_out", checkout_date)
            elif isinstance(hotel, dict):
                hotel.setdefault("check_in", checkin_date)
                hotel.setdefault("check_out", checkout_date)

        state.hotel_options = hotels

        # =================================================
        # NO RESULTS
        # =================================================

        if not hotels:

            logger.info(
                "Hotel Agent completed | "
                "no hotels returned"
            )

            agent_success(
                "hotel",
                state,
                agent_start_time,
                status="no_results",
            )
            return state

        # =================================================
        # LLM HOTEL EVALUATION
        # =================================================

        logger.info(
            "Starting LLM hotel evaluation | "
            "hotels=%s",
            len(hotels),
        )

        # =================================================
        # BUILD SMALL LLM PAYLOAD
        # =================================================
        #
        # IMPORTANT:
        # Do NOT send raw_data to the LLM.
        #
        # raw_data can contain huge provider payloads,
        # offer IDs, rate IDs and nested objects.
        #
        # The LLM only needs decision-making information.
        # =================================================

        hotel_data = []

        for index, hotel in enumerate(
            hotels,
            start=1,
        ):

            if hasattr(
                hotel,
                "model_dump",
            ):

                hotel_dict = hotel.model_dump()

            elif isinstance(
                hotel,
                dict,
            ):

                hotel_dict = hotel

            else:

                hotel_dict = {
                    "hotel_name": str(hotel)
                }

            data = {
                "index": index,

                "hotel_name": hotel_dict.get(
                    "hotel_name"
                ),

                "rating": hotel_dict.get(
                    "rating"
                ),

                "address": hotel_dict.get(
                    "address"
                ),

                "room_name": hotel_dict.get(
                    "room_name"
                ),

                "board_name": hotel_dict.get(
                    "board_name"
                ),

                "price": hotel_dict.get(
                    "price"
                ),

                "currency": hotel_dict.get(
                    "currency"
                ),

                "taxes": hotel_dict.get(
                    "taxes"
                ),

                "cancellation": hotel_dict.get(
                    "cancellation"
                ),

                "cancellation_deadline": (
                    hotel_dict.get(
                        "cancellation_deadline"
                    )
                ),

                "provider": hotel_dict.get(
                    "provider"
                ),
            }

            hotel_data.append(
                data
            )

        # =================================================
        # USER PREFERENCES
        # =================================================

        preferences = (
            state.preferences
            or []
        )

        # =================================================
        # USER BUDGET
        # =================================================

        budget = None

        if state.budget is not None:

            budget = {
                "amount": state.budget.amount,
                "currency": state.budget.currency,
            }

        # =================================================
        # SYSTEM PROMPT
        # =================================================

        system_prompt = """
You are the Hotel Selection Agent
of an Agentic AI Travel Planner.

Your task is to rank the provided hotels
according to the user's preferences and budget.

IMPORTANT RULES:

1. Do not invent information.
2. Use only the provided hotel data.
3. Prefer hotels matching the user's preferences.
4. Consider price and rating when available.
5. Do not modify hotel information.
6. Return ONLY valid JSON.

Required JSON format:

{
    "ranked_indices": [1, 2, 3],
    "reason": "short explanation"
}

The ranked_indices must contain valid hotel
indices from the provided options.
"""

        # =================================================
        # USER PROMPT
        # =================================================

        user_prompt = f"""
Evaluate and rank these hotel options.

Supervisor task:
{task}

Destination:
{dest_city}

Check-in:
{checkin_date}

Check-out:
{checkout_date}

Travelers:
Adults = {state.travelers.adults}
Children = {state.travelers.children}

Budget:
{json.dumps(budget)}

User preferences:
{json.dumps(preferences)}

Hotel options:
{json.dumps(
    hotel_data,
    default=str,
    separators=(",", ":"),
)}

Return ONLY valid JSON.

Rank the hotels from best to worst.
"""

        # =================================================
        # CALL LLM
        # =================================================

        try:

            llm_response = self.llm.generate(

                system_prompt=system_prompt,

                user_prompt=user_prompt,

                temperature=0.0,

                max_tokens=500,

                reasoning_effort="low",
            )

        except LLMClientError as exc:

            logger.warning(
                "Hotel LLM evaluation failed. "
                "Keeping original hotel order. "
                "error=%s",
                exc,
            )

            agent_success(
                "hotel",
                state,
                agent_start_time,
                status="success_llm_fallback",
            )
            return state

        # =================================================
        # PARSE LLM RESPONSE
        # =================================================

        try:

            decision = json.loads(
                llm_response
            )

        except json.JSONDecodeError as exc:

            logger.warning(
                "Hotel LLM returned invalid JSON. "
                "Keeping original hotel order. "
                "error=%s",
                exc,
            )

            agent_success(
                "hotel",
                state,
                agent_start_time,
                status="success_llm_fallback",
            )
            return state

        # =================================================
        # VALIDATE RESPONSE TYPE
        # =================================================

        if not isinstance(
            decision,
            dict,
        ):

            logger.warning(
                "Hotel LLM returned invalid response type. "
                "Keeping original hotel order."
            )

            agent_success(
                "hotel",
                state,
                agent_start_time,
                status="success_llm_fallback",
            )
            return state

        # =================================================
        # EXTRACT RANKING
        # =================================================

        ranked_indices = (
            decision.get(
                "ranked_indices",
                [],
            )
        )

        if not isinstance(
            ranked_indices,
            list,
        ):

            logger.warning(
                "Hotel LLM returned invalid ranking."
            )

            agent_success(
                "hotel",
                state,
                agent_start_time,
                status="success_llm_fallback",
            )
            return state

        # =================================================
        # VALIDATE RANKING
        # =================================================

        valid_indices = []

        for index in ranked_indices:

            if (
                isinstance(index, int)
                and not isinstance(index, bool)
                and 1 <= index <= len(hotels)
            ):

                if index not in valid_indices:

                    valid_indices.append(
                        index
                    )

        # =================================================
        # ADD OMITTED HOTELS
        # =================================================

        for index in range(
            1,
            len(hotels) + 1,
        ):

            if index not in valid_indices:

                valid_indices.append(
                    index
                )

        # =================================================
        # APPLY RANKING
        # =================================================

        ranked_hotels = [
            hotels[index - 1]
            for index in valid_indices
        ]

        state.hotel_options = (
            ranked_hotels
        )

        # =================================================
        # LLM REASON
        # =================================================

        reason = decision.get(
            "reason",
            "Hotels ranked according to "
            "user preferences and budget.",
        )

        # Keep log short
        if not isinstance(
            reason,
            str,
        ):

            reason = str(reason)

        logger.info(
            "Hotel LLM ranking completed | "
            "ranking=%s | reason=%s",
            valid_indices,
            reason,
        )

        # =================================================
        # FINAL LOG
        # =================================================

        logger.info(
            "Hotel Agent completed | "
            "status=%s | provider=%s | hotels=%s",
            response.status,
            response.provider,
            len(state.hotel_options),
        )

        agent_success(
            "hotel",
            state,
            agent_start_time,
            status="success",
        )

        return state

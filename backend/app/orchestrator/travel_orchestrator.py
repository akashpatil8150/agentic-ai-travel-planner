import asyncio
import logging
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Literal, Optional, TypedDict, Union

from langgraph.graph import StateGraph, START, END

from app.state.trip_state import TripState

from app.agents.transport_agent import TransportAgent
from app.agents.hotel_agent import HotelAgent
from app.agents.places_agent import PlacesAgent
from app.agents.weather_agent import WeatherAgent
from app.agents.verification_agent import VerificationAgent
from app.agents.supervisor_agent import SupervisorAgent

from app.aggregation.result_aggregator import ResultAggregator

from app.engines.constraint_engine import ConstraintEngine
from app.engines.optimization_engine import OptimizationEngine

from app.itinerary.itinerary_builder import ItineraryBuilder

from app.validation.itinerary_validator import (
    ItineraryValidator,
)
from app.services.hotel.hotel_normalizer import HotelNormalizer


logger = logging.getLogger(__name__)


# ============================================================
# LANGGRAPH STATE
# ============================================================

class TravelGraphState(TypedDict, total=False):
    """
    Internal state used by LangGraph.

    TripState remains the main application state.
    LangGraph controls only workflow execution.
    """

    trip_state: TripState

    selected_agents: List[str]

    agent_tasks: Dict[str, str]

    execution_mode: Literal[
        "parallel",
        "sequential",
    ]

    supervisor_reason: str

    workflow_error: str


# ============================================================
# TRAVEL ORCHESTRATOR
# ============================================================

class TravelOrchestrator:
    """
    LangGraph-based Travel Orchestrator.

    Supports two planning modes.

    ------------------------------------------------------------
    MODE 1: FULL PIPELINE
    ------------------------------------------------------------

        Supervisor
             ↓
        Transport
        Hotel
        Places
        Weather
             ↓
        Verification
             ↓
        Aggregation
             ↓
        Constraints
             ↓
        Optimization
             ↓
        Itinerary
             ↓
        Validator


    ------------------------------------------------------------
    MODE 2: TWO-PHASE USER SELECTION
    ------------------------------------------------------------

        Phase 1
        Supervisor
             ↓
        Transport + Hotel
             ↓
        Travel Options
             ↓
        USER SELECTION

        Phase 2
        Selected Transport + Hotel
             ↓
        Places + Weather
             ↓
        Verification
             ↓
        Aggregation
             ↓
        Constraints
             ↓
        Optimization
             ↓
        Itinerary
             ↓
        Validator
    """

    # ========================================================
    # INIT
    # ========================================================

    def __init__(self):

        # ----------------------------------------------------
        # SPECIALIZED AGENTS
        # ----------------------------------------------------

        self.transport_agent = TransportAgent()

        self.hotel_agent = HotelAgent()

        self.places_agent = PlacesAgent()

        self.weather_agent = WeatherAgent()

        self.verification_agent = VerificationAgent()

        # ----------------------------------------------------
        # SUPERVISOR
        # ----------------------------------------------------

        self.supervisor_agent = SupervisorAgent()

        # ----------------------------------------------------
        # AGGREGATOR
        # ----------------------------------------------------

        self.result_aggregator = ResultAggregator()

        # ----------------------------------------------------
        # ENGINES
        # ----------------------------------------------------

        self.constraint_engine = ConstraintEngine()

        self.optimization_engine = OptimizationEngine()

        # ----------------------------------------------------
        # ITINERARY
        # ----------------------------------------------------

        self.itinerary_builder = ItineraryBuilder()

        self.itinerary_validator = ItineraryValidator()

        # ----------------------------------------------------
        # AGENT REGISTRY
        # ----------------------------------------------------

        self.agent_registry = {
            "transport": self._run_transport,
            "hotel": self._run_hotel,
            "places": self._run_places,
            "weather": self._run_weather,
        }

        # ----------------------------------------------------
        # BUILD GRAPH
        # ----------------------------------------------------

        self.graph = self._build_graph()

        logger.info(
            "TravelOrchestrator initialized with LangGraph"
        )

    # ========================================================
    # BUILD FULL GRAPH
    # ========================================================

    def _build_graph(self):

        workflow = StateGraph(
            TravelGraphState
        )

        # ----------------------------------------------------
        # NODES
        # ----------------------------------------------------

        workflow.add_node(
            "supervisor",
            self._supervisor_node,
        )

        workflow.add_node(
            "execute_agents",
            self._execute_agents_node,
        )

        workflow.add_node(
            "verification",
            self._verification_node,
        )

        workflow.add_node(
            "aggregation",
            self._aggregation_node,
        )

        workflow.add_node(
            "constraints",
            self._constraints_node,
        )

        workflow.add_node(
            "optimization",
            self._optimization_node,
        )

        workflow.add_node(
            "itinerary",
            self._itinerary_node,
        )

        workflow.add_node(
            "validator",
            self._validator_node,
        )

        # ----------------------------------------------------
        # EDGES
        # ----------------------------------------------------

        workflow.add_edge(
            START,
            "supervisor",
        )

        workflow.add_edge(
            "supervisor",
            "execute_agents",
        )

        workflow.add_edge(
            "execute_agents",
            "verification",
        )

        workflow.add_edge(
            "verification",
            "aggregation",
        )

        workflow.add_edge(
            "aggregation",
            "constraints",
        )

        # ----------------------------------------------------
        # CONSTRAINT ROUTING
        # ----------------------------------------------------

        workflow.add_conditional_edges(
            "constraints",
            self._constraint_router,
            {
                "continue": "optimization",
                "stop": END,
            },
        )

        # ----------------------------------------------------
        # OPTIMIZATION -> ITINERARY
        # ----------------------------------------------------

        workflow.add_edge(
            "optimization",
            "itinerary",
        )

        workflow.add_edge(
            "itinerary",
            "validator",
        )

        # ----------------------------------------------------
        # VALIDATION ROUTING
        # ----------------------------------------------------

        workflow.add_conditional_edges(
            "validator",
            self._validation_router,
            {
                "valid": END,
                "invalid": END,
            },
        )

        return workflow.compile()

    # ========================================================
    # PUBLIC FULL RUN
    # ========================================================

    async def run(
        self,
        state: TripState,
    ) -> TripState:

        if not isinstance(
            state,
            TripState,
        ):
            raise TypeError(
                "Orchestrator expects a TripState object."
            )

        logger.info(
            "Travel orchestration started | "
            "user_id=%s | origin=%s | destination=%s",
            state.user_id,
            state.origin.name,
            state.destination.name,
        )

        state.workflow_status = (
            "SUPERVISOR_RUNNING"
        )

        initial_graph_state: TravelGraphState = {

            "trip_state": state,

            "selected_agents": [],

            "agent_tasks": {},

            "execution_mode": "parallel",

            "supervisor_reason": "",

            "workflow_error": "",
        }

        try:

            final_graph_state = await self.graph.ainvoke(
                initial_graph_state
            )

        except Exception as exc:

            logger.exception(
                "LangGraph workflow failed"
            )

            state.errors.append(
                {
                    "stage": "langgraph",
                    "error": str(exc),
                }
            )

            state.workflow_status = (
                "WORKFLOW_FAILED"
            )

            return state

        final_state = final_graph_state.get(
            "trip_state"
        )

        if not isinstance(
            final_state,
            TripState,
        ):
            raise TypeError(
                "LangGraph did not return TripState."
            )

        logger.info(
            "Travel orchestration completed | "
            "status=%s",
            final_state.workflow_status,
        )

        return final_state

    # ========================================================
    # NEW FEATURE
    # PHASE 1
    # GENERATE TRAVEL OPTIONS
    # ========================================================

    # ========================================================
    # PUBLIC API
    # GENERATE OPTIONS
    # ========================================================

    async def generate_options(
        self,
        state: TripState,
    ) -> TripState:
        """Public API used by trip_routes.py."""
        return await self.generate_travel_options(state)

    async def generate_travel_options(
        self,
        state: TripState,
    ) -> TripState:
        """
        Phase 1 of user-selectable planning.

        Only Transport + Hotel agents are executed.

        Places and Weather are intentionally NOT executed here.

        Result:
            state.transport_options
            state.hotel_options
            state.metadata["travel_options"]
        """

        if not isinstance(
            state,
            TripState,
        ):
            raise TypeError(
                "Expected TripState object."
            )

        logger.info(
            "================================================"
        )

        logger.info(
            "PHASE 1 | GENERATING TRAVEL OPTIONS"
        )

        logger.info(
            "================================================"
        )

        state.workflow_status = (
            "OPTIONS_GENERATING"
        )

        # Preserve an already confirmed user transport selection.
        confirmed_outbound = state.outbound_transport or state.selected_transport
        confirmed_return = state.return_transport
        confirmed_selected = state.selected_transport

        # ----------------------------------------------------
        # RUN TRANSPORT + HOTEL
        # ----------------------------------------------------

        try:

            transport_task = (
                "Find the best available transport "
                "options for this trip. Return multiple "
                "feasible options with reliable pricing "
                "and availability information."
            )

            hotel_task = (
                "Find the best available hotels for this "
                "trip. Consider budget, dates, location, "
                "rating and user preferences. Return "
                "multiple suitable hotel options."
            )

            transport_job = asyncio.to_thread(
                self._run_transport,
                state,
                transport_task,
            )

            transport_result = await transport_job

            # ------------------------------------------------
            # TRANSPORT RESULT
            # ------------------------------------------------

            if isinstance(
                transport_result,
                Exception,
            ):

                logger.error(
                    "Phase 1 Transport failed | error=%s",
                    transport_result,
                )

                state.transport_options = []

                state.errors.append(
                    {
                        "stage": "phase1_transport",
                        "error": str(
                            transport_result
                        ),
                    }
                )

            else:

                if confirmed_outbound is not None:
                    state.outbound_transport = confirmed_outbound
                    state.selected_transport = confirmed_selected or confirmed_outbound
                    state.transport_options = [confirmed_outbound]
                else:
                    state = transport_result

                if confirmed_return is not None:
                    state.return_transport = confirmed_return
                    if state.transport_options and isinstance(state.transport_options[0], dict):
                        state.transport_options[0]["return_trip"] = confirmed_return

            hotel_job = asyncio.to_thread(
                self._run_hotel,
                state,
                hotel_task,
            )

            hotel_result = await hotel_job

            # ------------------------------------------------
            # HOTEL RESULT
            # ------------------------------------------------

            if isinstance(
                hotel_result,
                Exception,
            ):

                logger.error(
                    "Phase 1 Hotel failed | error=%s",
                    hotel_result,
                )

                state.hotel_options = []

                state.errors.append(
                    {
                        "stage": "phase1_hotel",
                        "error": str(
                            hotel_result
                        ),
                    }
                )

            else:

                state.hotel_options = (
                    hotel_result.hotel_options
                )

        except Exception as exc:

            logger.exception(
                "Phase 1 agent execution failed"
            )

            state.errors.append(
                {
                    "stage": "phase1_agents",
                    "error": str(exc),
                }
            )

            state.workflow_status = (
                "OPTIONS_GENERATION_FAILED"
            )

            return state

        # ----------------------------------------------------
        # GENERATE HOTEL OPTIONS
        # ----------------------------------------------------

        hotel_options = (
            self._build_hotel_options(
                state
            )
        )

        # ----------------------------------------------------
        # SAVE OPTIONS
        # ----------------------------------------------------

        state.hotel_options = hotel_options

        state.metadata[
            "options_count"
        ] = len(hotel_options)

        state.metadata[
            "options_status"
        ] = "ready"

        state.workflow_status = (
            "AWAITING_HOTEL_SELECTION"
        )

        logger.info(
            "Phase 1 completed | "
            "transport=%s | hotels=%s",
            len(state.transport_options),
            len(hotel_options),
        )

        return state

    @staticmethod
    def _parse_datetime(value, base_date=None, reference_datetime=None):
        if isinstance(value, datetime):
            return value
        if not value:
            return None
        raw = str(value).strip()
        try:
            return datetime.fromisoformat(raw.replace("Z", "+00:00"))
        except ValueError:
            pass
        for fmt in ("%Y-%m-%d %H:%M", "%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M", "%Y-%m-%dT%H:%M:%S", "%H:%M", "%H:%M:%S"):
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

    # ========================================================
    # BUILD HOTEL OPTIONS
    # ========================================================

    def _build_hotel_options(
        self,
        state: TripState,
    ) -> List[dict]:
        """Build up to 3 real, distinct hotel choices using budget + rating."""
        hotels = self._serialize_options(state.hotel_options)
        if not hotels:
            return []

        unique = []
        seen_ids = set()
        try:
            from datetime import datetime, timedelta
            checkin_date = state.travel_dates.start
            checkout_date = state.travel_dates.end
            
            transport = state.outbound_transport or state.selected_transport
            if not transport and state.transport_options:
                transport = state.transport_options[0]

            if hasattr(transport, "model_dump"):
                transport = transport.model_dump(mode="python")

            if isinstance(transport, dict):
                journey_date = transport.get("journey_date") or state.travel_dates.start
                if isinstance(journey_date, str):
                    try:
                        journey_date = datetime.fromisoformat(journey_date).date()
                    except ValueError:
                        journey_date = state.travel_dates.start
                dep_value = transport.get("departure_datetime") or transport.get("departure") or transport.get("departure_time")
                arr_value = transport.get("arrival_datetime") or transport.get("arrival") or transport.get("arrival_time")
                dep_dt = self._parse_datetime(dep_value, base_date=journey_date)
                arr_dt = self._parse_datetime(arr_value, base_date=journey_date, reference_datetime=dep_dt)
                if arr_dt:
                    checkin_date = arr_dt.date()

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
                        # Long destination -> return-station transfers can
                        # require hotel departure on the previous calendar day.
                        transfer = (
                            return_trip.get("return_transfer")
                            or return_trip.get("transfer")
                            or getattr(state, "return_transfer", None)
                            or getattr(state, "metadata", {}).get("return_transfer")
                            or {}
                        )
                        transfer_mins = transfer.get("duration_minutes") or 0 if isinstance(transfer, dict) else 0
                        if not transfer_mins and isinstance(transfer, dict):
                            raw_transfer = transfer.get("estimated_transfer_time")
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

            nights = max(1, (checkout_date - checkin_date).days)
        except Exception:
            nights = 1

        for hotel in hotels:
            hid = str(hotel.get("hotel_id") or hotel.get("id") or "").strip()
            if not hid or hid in seen_ids:
                continue
            seen_ids.add(hid)
            item = dict(hotel)
            total_price = self._get_hotel_price(item)
            item["hotel_id"] = hid
            item["id"] = hid
            item["price"] = round(total_price, 2)
            item["check_in"] = checkin_date
            item["check_out"] = checkout_date
            item["stay_nights"] = nights
            item["price_per_night"] = round(total_price / nights, 2) if total_price > 0 else 0.0
            rating = HotelNormalizer._normalize_rating(item.get("rating"))
            item["rating"] = rating
            unique.append(item)

        if not unique:
            return []

        budget = None
        try:
            budget = float(state.budget.amount) if state.budget and state.budget.amount is not None else None
        except Exception:
            pass

        budget_fit = [h for h in unique if h.get("price", 0) > 0 and (budget is None or h["price"] <= budget)]
        pool = budget_fit or [h for h in unique if h.get("price", 0) > 0] or unique

        cheapest = min(pool, key=lambda h: float(h.get("price") or float("inf")))

        max_price = max(float(h.get("price") or 0) for h in pool) or 1.0
        def value_score(h):
            price = float(h.get("price") or 0)
            rating = float(h.get("rating") or 0)
            price_score = 1.0 - min(price / max_price, 1.0)
            rating_score = min(max(rating / 5.0, 0.0), 1.0)
            return 0.65 * rating_score + 0.35 * price_score

        best_value = max(pool, key=lambda h: (value_score(h), float(h.get("rating") or 0), -float(h.get("price") or 0)))
        best_rated = max(pool, key=lambda h: (float(h.get("rating") or 0), -float(h.get("price") or 0)))

        roles = [
            ("BUDGET-FRIENDLY", cheapest),
            ("BEST VALUE", best_value),
            ("BEST RATED", best_rated),
        ]

        options = []
        used = set()
        for role, hotel in roles:
            hid = str(hotel.get("hotel_id") or hotel.get("id"))
            if hid in used:
                continue
            used.add(hid)
            item = dict(hotel)
            item["selection_role"] = role
            item["budget_category"] = role.lower().replace("-", "_").replace(" ", "_")
            item["tier"] = role
            item["budget_fit"] = bool(budget is None or item.get("price", 0) <= budget)
            options.append(item)

        if len(options) < min(3, len(pool)):
            remaining = [h for h in pool if str(h.get("hotel_id") or h.get("id")) not in used]
            remaining.sort(key=lambda h: (-float(h.get("rating") or 0), float(h.get("price") or float("inf"))))
            for hotel in remaining:
                hid = str(hotel.get("hotel_id") or hotel.get("id"))
                item = dict(hotel)
                item["selection_role"] = "RECOMMENDED"
                item["budget_category"] = "recommended"
                item["tier"] = "RECOMMENDED"
                item["budget_fit"] = bool(budget is None or item.get("price", 0) <= budget)
                options.append(item)
                used.add(hid)
                if len(options) >= 3:
                    break

        logger.info("Hotel options selected | real=%s | returned=%s | budget=%s", len(unique), len(options[:3]), budget)
        return options[:3]

    # ========================================================
    # PHASE 2
    # APPLY USER SELECTION
    # ========================================================

    async def continue_after_hotel_selection(
        self,
        state: TripState,
        hotel_id: str | None = None,
    ) -> TripState:
        """
        Phase 2 of user-selectable planning.
        The user selects one generated hotel option.
        Then only the selected hotel is used for the remaining workflow.
        Places + Weather are executed here.
        """

        if not isinstance(
            state,
            TripState,
        ):
            raise TypeError(
                "Expected TripState object."
            )

        logger.info(
            "================================================"
        )

        logger.info(
            "PHASE 2 | APPLYING HOTEL SELECTION"
        )

        logger.info(
            "================================================"
        )

        hotel_options = state.hotel_options

        if not hotel_options:
            raise ValueError(
                "No hotel options available. "
                "Run generate_travel_options() first."
            )

        if hotel_id is None:
            if state.selected_hotel:
                hotel_id = state.selected_hotel.get("hotel_id") or state.selected_hotel.get("id")

        if not hotel_id:
            raise ValueError(
                "No hotel_id provided."
            )

        # ----------------------------------------------------
        # FIND SELECTED HOTEL
        # ----------------------------------------------------

        selected_hotel = None

        for option in hotel_options:
            opt_id = str(option.get("hotel_id") or option.get("id"))
            if opt_id == str(hotel_id):
                selected_hotel = option
                break

        if selected_hotel is None:
            raise ValueError(
                f"Invalid hotel_id: {hotel_id}"
            )

        # ----------------------------------------------------
        # SAVE USER SELECTION
        # ----------------------------------------------------

        state.selected_hotel = selected_hotel
        state.hotel_options = [selected_hotel]
        if not isinstance(state.selected_options, dict):
            state.selected_options = {}
        state.selected_options["hotel"] = selected_hotel

        # ----------------------------------------------------
        # CLEAR OLD DOWNSTREAM RESULTS
        # ----------------------------------------------------

        state.place_options = []
        state.weather = {}
        state.verification = {}
        state.recommendations = {}
        state.constraints = {}
        state.optimization = {}
        state.itinerary = {}
        state.validation = {}

        state.arrival_datetime = None
        state.departure_datetime = None
        state.activity_start_datetime = None
        state.activity_end_datetime = None

        state.workflow_status = (
            "HOTEL_SELECTED"
        )

        logger.info(
            "User hotel selected | "
            "hotel_id=%s",
            hotel_id,
        )

        # ----------------------------------------------------
        # RUN PLACES + WEATHER
        # ----------------------------------------------------

        try:

            places_task = (
                "Find diverse attractions and activities "
                "for the selected travel plan. Prioritize "
                "user preferences, destination relevance "
                "and enough unique places for the complete "
                "trip duration."
            )

            weather_task = (
                "Retrieve destination weather information "
                "for the complete travel period."
            )

            places_job = asyncio.to_thread(
                self._run_places,
                state,
                places_task,
            )

            weather_job = asyncio.to_thread(
                self._run_weather,
                state,
                weather_task,
            )

            places_result, weather_result = (
                await asyncio.gather(
                    places_job,
                    weather_job,
                    return_exceptions=True,
                )
            )

            # ------------------------------------------------
            # PLACES
            # ------------------------------------------------

            if isinstance(
                places_result,
                Exception,
            ):

                logger.error(
                    "Places Agent failed | error=%s",
                    places_result,
                )

                state.place_options = []

                state.errors.append(
                    {
                        "stage": "phase2_places",
                        "error": str(
                            places_result
                        ),
                    }
                )

            else:

                state = places_result

            # ------------------------------------------------
            # WEATHER
            # ------------------------------------------------

            if isinstance(
                weather_result,
                Exception,
            ):

                logger.error(
                    "Weather Agent failed | error=%s",
                    weather_result,
                )

                state.weather = {}

                state.errors.append(
                    {
                        "stage": "phase2_weather",
                        "error": str(
                            weather_result
                        ),
                    }
                )

            else:

                state = weather_result

        except Exception as exc:

            logger.exception(
                "Phase 2 agent execution failed"
            )

            state.errors.append(
                {
                    "stage": "phase2_agents",
                    "error": str(exc),
                }
            )

            state.workflow_status = (
                "PHASE2_AGENTS_FAILED"
            )

            return state

        # ----------------------------------------------------
        # VERIFICATION
        # ----------------------------------------------------

        state.workflow_status = (
            "VERIFICATION_RUNNING"
        )

        try:

            state = await asyncio.to_thread(
                self.verification_agent.run,
                state,
            )

        except Exception as exc:

            logger.exception(
                "Phase 2 Verification failed"
            )

            state.verification = {
                "status": "unavailable",
                "error": str(exc),
            }

            state.errors.append(
                {
                    "stage": "phase2_verification",
                    "error": str(exc),
                }
            )

        # ----------------------------------------------------
        # AGGREGATION
        # ----------------------------------------------------

        state.workflow_status = (
            "RESULTS_AGGREGATING"
        )

        try:

            state = (
                self.result_aggregator.aggregate(
                    state
                )
            )

        except Exception as exc:

            logger.exception(
                "Phase 2 aggregation failed"
            )

            state.errors.append(
                {
                    "stage": "phase2_aggregation",
                    "error": str(exc),
                }
            )

            state.workflow_status = (
                "RESULT_AGGREGATION_FAILED"
            )

            return state

        # ----------------------------------------------------
        # CONSTRAINTS
        # ----------------------------------------------------

        state.workflow_status = (
            "CONSTRAINT_VALIDATION"
        )

        try:

            state = (
                self.constraint_engine.run(
                    state
                )
            )

        except Exception as exc:

            logger.exception(
                "Phase 2 constraints failed"
            )

            state.errors.append(
                {
                    "stage": "phase2_constraints",
                    "error": str(exc),
                }
            )

            state.workflow_status = (
                "CONSTRAINT_VALIDATION_FAILED"
            )

            return state

        # ----------------------------------------------------
        # STOP IF CONSTRAINTS FAIL
        # ----------------------------------------------------

        if not state.constraints.get(
            "overall_valid",
            False,
        ):

            state.workflow_status = (
                "CONSTRAINTS_FAILED"
            )

            logger.warning(
                "Selected option failed constraints"
            )

            return state

        # ----------------------------------------------------
        # OPTIMIZATION
        # ----------------------------------------------------

        state.workflow_status = (
            "OPTIMIZATION_RUNNING"
        )

        try:

            state = (
                self.optimization_engine.run(
                    state
                )
            )

        except Exception as exc:

            logger.exception(
                "Phase 2 optimization failed"
            )

            state.errors.append(
                {
                    "stage": "phase2_optimization",
                    "error": str(exc),
                }
            )

            state.workflow_status = (
                "OPTIMIZATION_FAILED"
            )

            return state

        # ----------------------------------------------------
        # ITINERARY
        # ----------------------------------------------------

        state.workflow_status = (
            "ITINERARY_BUILDING"
        )

        try:

            state = (
                self.itinerary_builder.run(
                    state
                )
            )

        except Exception as exc:

            logger.exception(
                "Phase 2 itinerary failed"
            )

            state.errors.append(
                {
                    "stage": "phase2_itinerary",
                    "error": str(exc),
                }
            )

            state.workflow_status = (
                "ITINERARY_BUILD_FAILED"
            )

            return state

        # ----------------------------------------------------
        # VALIDATION
        # ----------------------------------------------------

        state.workflow_status = (
            "VALIDATION_RUNNING"
        )

        try:

            state = (
                self.itinerary_validator.run(
                    state
                )
            )

            if state.validation.get(
                "valid",
                False,
            ):

                state.workflow_status = (
                    "ITINERARY_VALIDATED"
                )

            else:

                state.workflow_status = (
                    "VALIDATION_FAILED"
                )

        except Exception as exc:

            logger.exception(
                "Phase 2 validation failed"
            )

            state.errors.append(
                {
                    "stage": "phase2_validation",
                    "error": str(exc),
                }
            )

            state.workflow_status = (
                "VALIDATION_FAILED"
            )

        logger.info(
            "================================================"
        )

        logger.info(
            "PHASE 2 COMPLETED | status=%s",
            state.workflow_status,
        )

        logger.info(
            "================================================"
        )

        return state

    # ========================================================
    # NODE 1
    # SUPERVISOR
    # ========================================================

    def _supervisor_node(
        self,
        graph_state: TravelGraphState,
    ) -> TravelGraphState:

        state = graph_state[
            "trip_state"
        ]

        logger.info(
            "========================================"
        )

        logger.info(
            "LANGGRAPH | SUPERVISOR"
        )

        logger.info(
            "========================================"
        )

        state.workflow_status = (
            "SUPERVISOR_RUNNING"
        )

        try:

            plan = (
                self.supervisor_agent.run(
                    state
                )
            )

            selected_agents = []

            agent_tasks = {}

            # ------------------------------------------------
            # EXTRACT TASKS
            # ------------------------------------------------

            for task_item in plan.tasks:

                agent_name = (
                    task_item.agent
                )

                if (
                    agent_name
                    not in self.agent_registry
                ):

                    logger.warning(
                        "Supervisor selected unknown "
                        "agent=%s. Ignoring.",
                        agent_name,
                    )

                    continue

                if (
                    agent_name
                    in selected_agents
                ):

                    continue

                selected_agents.append(
                    agent_name
                )

                agent_tasks[
                    agent_name
                ] = task_item.task

            # ------------------------------------------------
            # SAFE FALLBACK
            # ------------------------------------------------

            if not selected_agents:

                logger.warning(
                    "Supervisor selected no agents. "
                    "Using deterministic fallback."
                )

                selected_agents = [
                    "transport",
                    "hotel",
                    "places",
                    "weather",
                ]

                agent_tasks = {

                    "transport":
                        "Find suitable transport "
                        "options for the trip.",

                    "hotel":
                        "Find suitable accommodation "
                        "matching trip dates and budget.",

                    "places":
                        "Find relevant attractions "
                        "matching user preferences.",

                    "weather":
                        "Retrieve weather information "
                        "for destination and dates.",
                }

            execution_mode = (
                plan.execution_mode
            )

            graph_state[
                "selected_agents"
            ] = selected_agents

            graph_state[
                "agent_tasks"
            ] = agent_tasks

            graph_state[
                "execution_mode"
            ] = execution_mode

            graph_state[
                "supervisor_reason"
            ] = plan.reason

            state.workflow_status = (
                "AGENTS_RUNNING"
            )

            logger.info(
                "Supervisor plan generated | "
                "agents=%s | mode=%s | reason=%s",
                selected_agents,
                execution_mode,
                plan.reason,
            )

            for agent_name in selected_agents:

                logger.info(
                    "Supervisor task | "
                    "agent=%s | task=%s",
                    agent_name,
                    agent_tasks.get(
                        agent_name,
                        "",
                    ),
                )

            return graph_state

        except Exception as exc:

            logger.exception(
                "Supervisor node failed"
            )

            selected_agents = [
                "transport",
                "hotel",
                "places",
                "weather",
            ]

            agent_tasks = {

                "transport":
                    "Find suitable transport options.",

                "hotel":
                    "Find suitable hotels.",

                "places":
                    "Find suitable places and activities.",

                "weather":
                    "Retrieve destination weather.",
            }

            graph_state[
                "selected_agents"
            ] = selected_agents

            graph_state[
                "agent_tasks"
            ] = agent_tasks

            graph_state[
                "execution_mode"
            ] = "parallel"

            graph_state[
                "supervisor_reason"
            ] = (
                "Fallback plan because Supervisor failed."
            )

            graph_state[
                "workflow_error"
            ] = str(exc)

            state.workflow_status = (
                "AGENTS_RUNNING"
            )

            return graph_state

    # ========================================================
    # NODE 2
    # EXECUTE SELECTED AGENTS
    # ========================================================

    async def _execute_agents_node(
        self,
        graph_state: TravelGraphState,
    ) -> TravelGraphState:

        state = graph_state[
            "trip_state"
        ]

        selected_agents = (
            graph_state.get(
                "selected_agents",
                [],
            )
        )

        agent_tasks = (
            graph_state.get(
                "agent_tasks",
                {},
            )
        )

        execution_mode = (
            graph_state.get(
                "execution_mode",
                "parallel",
            )
        )

        logger.info(
            "LangGraph executing agents | "
            "agents=%s | mode=%s",
            selected_agents,
            execution_mode,
        )

        if not selected_agents:

            logger.warning(
                "No agents selected."
            )

            return graph_state

        # ----------------------------------------------------
        # PARALLEL
        # ----------------------------------------------------

        if execution_mode == "parallel":

            jobs = []

            for agent_name in selected_agents:

                runner = (
                    self.agent_registry.get(
                        agent_name
                    )
                )

                if runner is None:

                    continue

                task = (
                    agent_tasks.get(
                        agent_name,
                        "",
                    )
                )

                jobs.append(
                    asyncio.to_thread(
                        runner,
                        state,
                        task,
                    )
                )

            results = await asyncio.gather(
                *jobs,
                return_exceptions=True,
            )

        # ----------------------------------------------------
        # SEQUENTIAL
        # ----------------------------------------------------

        else:

            results = []

            for agent_name in selected_agents:

                runner = (
                    self.agent_registry.get(
                        agent_name
                    )
                )

                if runner is None:

                    continue

                task = (
                    agent_tasks.get(
                        agent_name,
                        "",
                    )
                )

                try:

                    result = await asyncio.to_thread(
                        runner,
                        state,
                        task,
                    )

                    results.append(
                        result
                    )

                except Exception as exc:

                    results.append(
                        exc
                    )

        # ----------------------------------------------------
        # RESULTS
        # ----------------------------------------------------

        for index, agent_name in enumerate(
            selected_agents
        ):

            if index >= len(
                results
            ):

                continue

            result = results[index]

            if isinstance(
                result,
                Exception,
            ):

                logger.error(
                    "%s Agent failed | error=%s",
                    agent_name,
                    result,
                )

                self._clear_agent_result(
                    state,
                    agent_name,
                )

                state.errors.append(
                    {
                        "stage":
                            f"{agent_name}_agent",

                        "error":
                            str(result),
                    }
                )

                continue

            logger.info(
                "%s Agent completed successfully",
                agent_name,
            )

        logger.info(
            "LangGraph agent execution completed | "
            "transport=%s | hotels=%s | "
            "places=%s | weather=%s",
            len(
                state.transport_options
            ),
            len(
                state.hotel_options
            ),
            len(
                state.place_options
            ),
            bool(
                state.weather
            ),
        )

        return graph_state

    # ========================================================
    # NODE 3
    # VERIFICATION
    # ========================================================

    async def _verification_node(
        self,
        graph_state: TravelGraphState,
    ) -> TravelGraphState:

        state = graph_state[
            "trip_state"
        ]

        logger.info(
            "LangGraph | Verification Agent"
        )

        state.workflow_status = (
            "VERIFICATION_RUNNING"
        )

        try:

            state = await asyncio.to_thread(
                self.verification_agent.run,
                state,
            )

            logger.info(
                "Verification completed | status=%s",
                state.verification.get(
                    "status"
                ),
            )

        except Exception as exc:

            logger.exception(
                "Verification Agent failed"
            )

            state.verification = {

                "status":
                    "unavailable",

                "error":
                    str(exc),
            }

            state.errors.append(
                {
                    "stage":
                        "verification",

                    "error":
                        str(exc),
                }
            )

        graph_state[
            "trip_state"
        ] = state

        return graph_state

    # ========================================================
    # NODE 4
    # AGGREGATION
    # ========================================================

    def _aggregation_node(
        self,
        graph_state: TravelGraphState,
    ) -> TravelGraphState:

        state = graph_state[
            "trip_state"
        ]

        logger.info(
            "LangGraph | Result Aggregator"
        )

        try:

            state = (
                self.result_aggregator.aggregate(
                    state
                )
            )

            state.workflow_status = (
                "RESULTS_AGGREGATED"
            )

        except Exception as exc:

            logger.exception(
                "Result Aggregator failed"
            )

            state.errors.append(
                {
                    "stage":
                        "result_aggregation",

                    "error":
                        str(exc),
                }
            )

            state.workflow_status = (
                "RESULT_AGGREGATION_FAILED"
            )

            graph_state[
                "workflow_error"
            ] = str(exc)

        graph_state[
            "trip_state"
        ] = state

        return graph_state

    # ========================================================
    # NODE 5
    # CONSTRAINTS
    # ========================================================

    def _constraints_node(
        self,
        graph_state: TravelGraphState,
    ) -> TravelGraphState:

        state = graph_state[
            "trip_state"
        ]

        logger.info(
            "LangGraph | Constraint Engine"
        )

        try:

            state = (
                self.constraint_engine.run(
                    state
                )
            )

        except Exception as exc:

            logger.exception(
                "Constraint Engine failed"
            )

            state.errors.append(
                {
                    "stage":
                        "constraints",

                    "error":
                        str(exc),
                }
            )

            state.workflow_status = (
                "CONSTRAINT_VALIDATION_FAILED"
            )

            graph_state[
                "workflow_error"
            ] = str(exc)

            graph_state[
                "trip_state"
            ] = state

            return graph_state

        if not state.constraints.get(
            "overall_valid",
            False,
        ):

            logger.warning(
                "Hard constraints failed"
            )

            state.workflow_status = (
                "CONSTRAINTS_FAILED"
            )

        else:

            logger.info(
                "Constraints passed"
            )

            state.workflow_status = (
                "CONSTRAINTS_PASSED"
            )

        graph_state[
            "trip_state"
        ] = state

        return graph_state

    # ========================================================
    # CONSTRAINT ROUTER
    # ========================================================

    def _constraint_router(
        self,
        graph_state: TravelGraphState,
    ) -> str:

        state = graph_state[
            "trip_state"
        ]

        if not state.constraints.get(
            "overall_valid",
            False,
        ):

            return "stop"

        return "continue"

    # ========================================================
    # NODE 6
    # OPTIMIZATION
    # ========================================================

    def _optimization_node(
        self,
        graph_state: TravelGraphState,
    ) -> TravelGraphState:

        state = graph_state[
            "trip_state"
        ]

        logger.info(
            "LangGraph | Optimization Engine"
        )

        try:

            state = (
                self.optimization_engine.run(
                    state
                )
            )

            state.workflow_status = (
                "OPTIMIZATION_COMPLETED"
            )

        except Exception as exc:

            logger.exception(
                "Optimization Engine failed"
            )

            state.errors.append(
                {
                    "stage":
                        "optimization",

                    "error":
                        str(exc),
                }
            )

            state.workflow_status = (
                "OPTIMIZATION_FAILED"
            )

            graph_state[
                "workflow_error"
            ] = str(exc)

        graph_state[
            "trip_state"
        ] = state

        return graph_state

    # ========================================================
    # NODE 7
    # ITINERARY
    # ========================================================

    def _itinerary_node(
        self,
        graph_state: TravelGraphState,
    ) -> TravelGraphState:

        state = graph_state[
            "trip_state"
        ]

        logger.info(
            "LangGraph | Itinerary Builder"
        )

        try:

            state = (
                self.itinerary_builder.run(
                    state
                )
            )

            state.workflow_status = (
                "ITINERARY_BUILT"
            )

        except Exception as exc:

            logger.exception(
                "Itinerary Builder failed"
            )

            state.errors.append(
                {
                    "stage":
                        "itinerary",

                    "error":
                        str(exc),
                }
            )

            state.workflow_status = (
                "ITINERARY_BUILD_FAILED"
            )

            graph_state[
                "workflow_error"
            ] = str(exc)

        graph_state[
            "trip_state"
        ] = state

        return graph_state

    # ========================================================
    # NODE 8
    # VALIDATOR
    # ========================================================

    def _validator_node(
        self,
        graph_state: TravelGraphState,
    ) -> TravelGraphState:

        state = graph_state[
            "trip_state"
        ]

        logger.info(
            "LangGraph | Itinerary Validator"
        )

        try:

            state = (
                self.itinerary_validator.run(
                    state
                )
            )

            if state.validation.get(
                "valid",
                False,
            ):

                state.workflow_status = (
                    "ITINERARY_VALIDATED"
                )

            else:

                state.workflow_status = (
                    "VALIDATION_FAILED"
                )

        except Exception as exc:

            logger.exception(
                "Itinerary Validator failed"
            )

            state.errors.append(
                {
                    "stage":
                        "validation",

                    "error":
                        str(exc),
                }
            )

            state.workflow_status = (
                "VALIDATION_FAILED"
            )

        graph_state[
            "trip_state"
        ] = state

        return graph_state

    # ========================================================
    # VALIDATION ROUTER
    # ========================================================

    def _validation_router(
        self,
        graph_state: TravelGraphState,
    ) -> str:

        state = graph_state[
            "trip_state"
        ]

        if state.validation.get(
            "valid",
            False,
        ):

            return "valid"

        return "invalid"

    # ========================================================
    # CLEAR AGENT RESULT
    # ========================================================

    @staticmethod
    def _clear_agent_result(
        state: TripState,
        agent_name: str,
    ):

        if agent_name == "transport":

            state.transport_options = []

        elif agent_name == "hotel":

            state.hotel_options = []

        elif agent_name == "places":

            state.place_options = []

        elif agent_name == "weather":

            state.weather = {}

    # ========================================================
    # TRANSPORT AGENT
    # ========================================================

    def _run_transport(
        self,
        state: TripState,
        task: str = "",
    ) -> TripState:

        logger.info(
            "Transport Agent started | task=%s",
            task,
        )

        result = (
            self.transport_agent.run(
                state,
                task=task,
            )
        )

        logger.info(
            "Transport Agent completed | "
            "options=%s",
            len(
                result.transport_options
            ),
        )

        return result

    # ========================================================
    # HOTEL AGENT
    # ========================================================

    def _run_hotel(
        self,
        state: TripState,
        task: str = "",
    ) -> TripState:

        logger.info(
            "Hotel Agent started | task=%s",
            task,
        )

        result = (
            self.hotel_agent.run(
                state,
                task=task,
            )
        )

        logger.info(
            "Hotel Agent completed | "
            "options=%s",
            len(
                result.hotel_options
            ),
        )

        return result

    # ========================================================
    # PLACES AGENT
    # ========================================================

    def _run_places(
        self,
        state: TripState,
        task: str = "",
    ) -> TripState:

        logger.info(
            "Places Agent started | task=%s",
            task,
        )

        result = (
            self.places_agent.run(
                state,
                task=task,
            )
        )

        logger.info(
            "Places Agent completed | "
            "options=%s",
            len(
                result.place_options
            ),
        )

        return result

    # ========================================================
    # WEATHER AGENT
    # ========================================================

    def _run_weather(
        self,
        state: TripState,
        task: str = "",
    ) -> TripState:

        logger.info(
            "Weather Agent started | task=%s",
            task,
        )

        result = (
            self.weather_agent.run(
                state
            )
        )

        logger.info(
            "Weather Agent completed"
        )

        return result

    # ========================================================
    # SERIALIZE OPTIONS
    # ========================================================

    @staticmethod
    def _serialize_options(
        options,
    ) -> List[dict]:

        serialized = []

        for option in options:

            if option is None:

                continue

            if hasattr(
                option,
                "model_dump",
            ):

                option = (
                    option.model_dump()
                )

            elif hasattr(
                option,
                "dict",
            ):

                option = (
                    option.dict()
                )

            if isinstance(
                option,
                dict,
            ):

                serialized.append(
                    option
                )

        return serialized

    # ========================================================
    # TRANSPORT PRICE
    # ========================================================

    @staticmethod
    def _extract_single_transport_price(
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
            data = data.model_dump()
        if not isinstance(data, dict):
            return 0.0

        # Resolve target class if not given
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
                                parsed = TravelOrchestrator._safe_float(val)
                                if parsed > 0:
                                    return parsed

        # 2. Priority 2: Selected class explicit fare fields on data
        if target_class:
            for key in ("selected_class_fare", "selected_fare", "class_fare"):
                val = data.get(key)
                if val is not None:
                    parsed = TravelOrchestrator._safe_float(val)
                    if parsed > 0:
                        return parsed

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
                        val = fare.get(amt_key)
                        if val is not None:
                            parsed = TravelOrchestrator._safe_float(val)
                            if parsed > 0:
                                return parsed
            else:
                # Generic fare dict without class code
                if not fares or not target_class:
                    for amt_key in ("amount", "fare", "price"):
                        val = fare.get(amt_key)
                        if val is not None:
                            parsed = TravelOrchestrator._safe_float(val)
                            if parsed > 0:
                                return parsed

        # 4. Direct price fields if no fares list conflict
        if not fares or not target_class:
            for field in ("price", "amount", "fare_amount"):
                val = data.get(field)
                if val is not None:
                    parsed = TravelOrchestrator._safe_float(val)
                    if parsed > 0:
                        return parsed

        # 5. If no target_class was specified, but fares list is present:
        if isinstance(fares, list) and fares and not target_class:
            valid_fares = []
            for item in fares:
                if isinstance(item, dict):
                    for amt_key in ("amount", "fare", "price", "fare_amount"):
                        val = item.get(amt_key)
                        if val is not None:
                            parsed = TravelOrchestrator._safe_float(val)
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

    @staticmethod
    def _get_transport_price(
        transport,
        state: TripState = None,
        selected_class: str = None,
    ) -> float:
        """Return one-way fare plus nested return-trip fare when present, matching selected class."""
        if hasattr(transport, "model_dump"):
            transport = transport.model_dump()
        if not isinstance(transport, dict):
            return 0.0

        # Resolve target class from parameter, transport, or state
        target_class = selected_class
        if not target_class and isinstance(transport, dict):
            for key in ("selected_class", "travel_class", "fare_class", "class_code", "cabin_class", "class"):
                val = transport.get(key)
                if val and isinstance(val, str) and val.strip():
                    target_class = val.strip().upper()
                    break

        b_cat = getattr(state, "budget_category", None) if state else None

        if not target_class and state is not None:
            for attr in ("selected_class", "travel_class", "class_code"):
                val = getattr(state, attr, None)
                if val and isinstance(val, str) and val.strip():
                    target_class = val.strip().upper()
                    break
            if not target_class and isinstance(getattr(state, "preferences", None), list):
                for p in state.preferences:
                    if isinstance(p, str):
                        p_up = p.strip().upper()
                        if p_up in ("SL", "3A", "2A", "1A", "3E", "CC", "EC", "2S", "FC", "ECONOMY", "PREMIUM_ECONOMY", "BUSINESS", "FIRST"):
                            target_class = p_up
                            break

        outbound_price = TravelOrchestrator._extract_single_transport_price(
            transport, target_class=target_class, budget_category=b_cat
        )

        return_trip = transport.get("return_trip")
        ret_class = None
        if isinstance(return_trip, dict):
            for key in ("selected_class", "travel_class", "fare_class", "class_code", "cabin_class", "class"):
                val = return_trip.get(key)
                if val and isinstance(val, str) and val.strip():
                    ret_class = val.strip().upper()
                    break
        if not ret_class:
            ret_class = target_class

        return_price = (
            TravelOrchestrator._extract_single_transport_price(
                return_trip, target_class=ret_class, budget_category=b_cat
            )
            if isinstance(return_trip, dict)
            else 0.0
        )

        return outbound_price + return_price

    # ========================================================
    # HOTEL PRICE
    # ========================================================

    @staticmethod
    def _get_hotel_price(
        hotel,
    ) -> float:

        if hotel is None:

            return 0.0

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

        for field in [
            "price",
            "offerRetailRate",
            "offerInitialPrice",
            "suggestedSellingPrice",
        ]:

            value = hotel.get(
                field
            )

            if value is None:

                continue

            if isinstance(
                value,
                dict,
            ):

                value = value.get(
                    "amount"
                )

            parsed = (
                TravelOrchestrator
                ._safe_float(value)
            )

            if parsed > 0:

                return parsed

        return 0.0

    # ========================================================
    # SAFE FLOAT
    # ========================================================

    @staticmethod
    def _safe_float(
        value,
    ) -> float:

        try:

            if isinstance(
                value,
                str,
            ):

                cleaned = (
                    value
                    .replace(
                        ",",
                        "",
                    )
                    .replace(
                        "₹",
                        "",
                    )
                    .strip()
                )

                return float(
                    cleaned
                )

            return float(
                value
            )

        except (
            TypeError,
            ValueError,
        ):

            return 0.0


# ============================================================
# HELPER
# ============================================================

async def run_travel_planner(
    state: TripState,
) -> TripState:

    orchestrator = (
        TravelOrchestrator()
    )

    return await orchestrator.run(
        state
    )
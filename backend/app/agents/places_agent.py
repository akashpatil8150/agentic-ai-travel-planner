import json
import logging

from app.state.trip_state import TripState

from app.services.places.places_service import (
    PlacesService,
    PlacesAPIError,
    PlacesServiceError,
)

from app.services.llm.llm_client import (
    LLMClient,
    LLMClientError,
)

from app.observability.agent_logger import (
    agent_start,
    agent_success,
    agent_failure,
)


logger = logging.getLogger(__name__)


class PlacesAgent:
    """
    Places Agent.

    Flow:

        TripState
            ↓
        PlacesService
            ↓
        Geoapify
            ↓
        Provider places
            ↓
        Agent-level deduplication
            ↓
        Unique normalized places
            ↓
        LLM preference ranking
            ↓
        TripState.place_options

    Important:

    - The LLM can ONLY rank existing places.
    - The LLM cannot create or invent places.
    - Provider retrieval is intentionally larger than final output.
    - Final output is limited to 5 ranked places.
    """

    # =========================================================
    # CONFIGURATION
    # =========================================================

    PROVIDER_RADIUS = 30000

    DEFAULT_PROVIDER_LIMIT = 25

    DEFAULT_MAX_RESULTS = 10

    # Maximum ranked place inventory passed to verification/scheduling.
    MAX_RESULTS = 18

    # =========================================================
    # INIT
    # =========================================================

    def __init__(self):

        self.places_service = PlacesService()

        self.llm_client = LLMClient()

    # =========================================================
    # RUN
    # =========================================================

    def run(
        self,
        state: TripState,
        task: str = "",
    ) -> TripState:

        agent_start_time = agent_start("places", state)

        logger.info(
            "Places Agent started"
        )

        # =====================================================
        # STATE VALIDATION
        # =====================================================

        if not isinstance(
            state,
            TripState,
        ):

            exc = TypeError(
                "PlacesAgent expects a TripState object."
            )
            agent_failure("places", state, agent_start_time, exc)
            raise exc

        # =====================================================
        # DESTINATION VALIDATION
        # =====================================================

        if state.destination is None:

            exc = ValueError(
                "Destination is required "
                "for Places Agent."
            )
            agent_failure("places", state, agent_start_time, exc)
            raise exc

        # =====================================================
        # COORDINATE VALIDATION
        # =====================================================

        latitude = (
            state.destination.latitude
        )

        longitude = (
            state.destination.longitude
        )

        if (
            latitude is None
            or longitude is None
        ):

            exc = ValueError(
                "Destination coordinates are required "
                "for Places Agent."
            )
            agent_failure("places", state, agent_start_time, exc)
            raise exc

        # =====================================================
        # PROVIDER SEARCH
        # =====================================================

        # IMPORTANT:
        #
        # Do NOT return early when preferences are empty.
        #
        # PlacesService already has a fallback mechanism
        # that uses default sightseeing categories:
        #
        # attraction
        # park
        # museum
        #
        # This allows the Places Agent to find places even
        # when the user has not provided preferences.

        total_days = 1
        if (
            state.travel_dates
            and state.travel_dates.start
            and state.travel_dates.end
        ):
            total_days = max(
                1,
                (
                    state.travel_dates.end
                    - state.travel_dates.start
                ).days + 1,
            )

        # Dynamically scale places needed for the trip duration
        # (e.g. 2 days -> 8 places, 5 days -> 17 places, 10 days -> 32 places)
        # Keep enough place alternatives for the itinerary scheduler while
        # bounding the final ranked inventory at 18 places.
        target_places = max(
            6,
            min(self.MAX_RESULTS, total_days * 3 + 2),
        )

        # Retrieve a broader provider pool than the final ranked inventory.
        provider_limit = min(30, max(25, target_places + 8))

        try:

            logger.info(
                "Searching places through PlacesService | "
                "radius=%s | limit=%s | preferences=%s | target_places=%s",
                self.PROVIDER_RADIUS,
                provider_limit,
                state.preferences,
                target_places,
            )

            updated_state = (
                self.places_service.search_for_trip(
                    state=state,
                    radius=self.PROVIDER_RADIUS,
                    limit=provider_limit,
                )
            )

        except ValueError as exc:

            logger.warning(
                "Places validation error | error=%s",
                exc,
            )

            state.place_options = []
            agent_failure("places", state, agent_start_time, exc)

            raise

        except PlacesAPIError as exc:

            logger.error(
                "Places provider error | error=%s",
                exc,
            )

            state.place_options = []
            agent_failure("places", state, agent_start_time, exc)

            raise

        except PlacesServiceError as exc:

            logger.error(
                "Places service error | error=%s",
                exc,
            )

            state.place_options = []
            agent_failure("places", state, agent_start_time, exc)

            raise

        # =====================================================
        # PROVIDER RESULTS
        # =====================================================

        places = list(
            updated_state.place_options or []
        )

        logger.info(
            "PlacesService returned places | count=%s",
            len(places),
        )

        # =====================================================
        # NO RESULTS
        # =====================================================

        if not places:

            logger.info(
                "No places found for destination."
            )

            state.place_options = []
            agent_success("places", state, agent_start_time, status="no_results")

            return state

        # =====================================================
        # AGENT-LEVEL DEDUPLICATION
        # =====================================================

        unique_places = (
            self._deduplicate_places(
                places
            )
        )

        logger.info(
            "Places deduplication completed | "
            "provider_places=%s | unique_places=%s",
            len(places),
            len(unique_places),
        )

        # =====================================================
        # NO UNIQUE RESULTS
        # =====================================================

        if not unique_places:

            logger.info(
                "No unique places found after deduplication."
            )

            state.place_options = []

            return state

        # =====================================================
        # LLM RANKING
        # =====================================================

        logger.info(
            "Starting LLM place ranking | "
            "unique_places=%s | preferences=%s",
            len(unique_places),
            state.preferences,
        )

        try:

            ranked_places = (
                self._rank_places(
                    places=unique_places,
                    preferences=state.preferences or [],
                    task=task,
                    max_results=target_places,
                )
            )

            state.place_options = (
                ranked_places
            )

            logger.info(
                "Places Agent completed successfully | "
                "provider_places=%s | "
                "unique_places=%s | "
                "ranked_places=%s",
                len(places),
                len(unique_places),
                len(ranked_places),
            )

            agent_success(
                "places",
                state,
                agent_start_time,
                status="success",
            )

            return state

        except LLMClientError as exc:
            logger.warning(
                "Places LLM ranking failed | using heuristic ranking | error=%s",
                exc,
            )
            state.place_options = self._heuristic_rank(unique_places, state.preferences or [])[:target_places]
            agent_success(
                "places",
                state,
                agent_start_time,
                status="success_heuristic_fallback",
            )
            return state

        except Exception as exc:
            logger.exception(
                "Unexpected Places LLM error | using heuristic ranking | error=%s",
                exc,
            )
            state.place_options = self._heuristic_rank(unique_places, state.preferences or [])[:target_places]
            agent_success(
                "places",
                state,
                agent_start_time,
                status="success_heuristic_fallback",
            )
            return state

    @staticmethod
    def _heuristic_rank(places: list[dict], preferences: list[str]) -> list[dict]:
        prefs = [str(p).lower().strip() for p in preferences if p]

        def place_score(p: dict) -> float:
            score = 0.0
            name = str(p.get("name") or "").lower()
            desc = str(p.get("description") or "").lower()
            cat = str(p.get("category") or "").lower()
            combined = f"{name} {desc} {cat}"

            # Iconic / prominent description bonus
            if p.get("description"):
                score += 50.0

            # Preference match bonus
            for pref in prefs:
                if pref in combined:
                    score += 30.0

            # Rating bonus
            try:
                r = float(p.get("rating", 0))
                score += r * 5.0
            except (ValueError, TypeError):
                pass

            # Proximity bonus (closer than 30km preferred)
            dist = p.get("distance_meters")
            if isinstance(dist, (int, float)) and dist > 0:
                if dist < 15000:
                    score += 15.0
                elif dist < 30000:
                    score += 10.0

            return score

        return sorted(places, key=place_score, reverse=True)

    # =========================================================
    # DEDUPLICATE PLACES
    # =========================================================

    @staticmethod
    def _deduplicate_places(
        places: list[dict],
    ) -> list[dict]:

        """
        Remove duplicate places.

        Priority:

        1. place_id
        2. normalized name + city

        This protects the LLM from receiving multiple
        representations of the same real-world place.
        """

        unique_places = []

        seen_place_ids = set()

        seen_name_city = set()

        for place in places:

            if not isinstance(
                place,
                dict,
            ):
                continue

            # -------------------------------------------------
            # PLACE ID DEDUPLICATION
            # -------------------------------------------------

            place_id = place.get(
                "place_id"
            )

            if place_id:

                normalized_place_id = str(
                    place_id
                ).strip().lower()

                if normalized_place_id in seen_place_ids:
                    continue

                seen_place_ids.add(
                    normalized_place_id
                )

            # -------------------------------------------------
            # NAME + CITY DEDUPLICATION
            # -------------------------------------------------

            name = str(
                place.get("name") or ""
            ).strip().lower()

            city = str(
                place.get("city") or ""
            ).strip().lower()

            if name:

                name_city_key = (
                    name,
                    city,
                )

                if (
                    name_city_key
                    in seen_name_city
                ):
                    continue

                seen_name_city.add(
                    name_city_key
                )

            # -------------------------------------------------
            # KEEP PLACE
            # -------------------------------------------------

            unique_places.append(
                place
            )

        return unique_places

    # =========================================================
    # LLM RANKING
    # =========================================================

    def _rank_places(
        self,
        places: list[dict],
        preferences: list[str],
        task: str = "",
        max_results: int = 15,
    ) -> list[dict]:

        # =====================================================
        # COMPACT PAYLOAD
        # =====================================================

        # Do NOT send complete provider response.
        #
        # This keeps LLM token usage low.

        compact_places = []

        for index, place in enumerate(
            places
        ):

            compact_places.append(
                {
                    "index": index,
                    "name": place.get(
                        "name"
                    ),
                    "category": place.get(
                        "category"
                    ),
                    "address": place.get(
                        "address"
                    ),
                    "city": place.get(
                        "city"
                    ),
                    "distance_meters": place.get(
                        "distance_meters"
                    ),
                }
            )

        # =====================================================
        # SYSTEM PROMPT
        # =====================================================

        system_prompt = f"""
You are a travel place-ranking assistant.

Your job is to rank the provided places according to
the user's preferences, supervisor task, and general tourist relevance.

STRICT RULES:

1. Use ONLY the provided places.
2. Never invent a place.
3. Never create a new place.
4. Never change a place name.
5. Never return an index that does not exist.
6. Prioritize famous, iconic tourist attractions, heritage sites, monuments, scenic viewpoints, major beaches/parks, and cultural landmarks over mundane local spots.
7. Deprioritize or avoid generic, minor, or non-touristy places.
8. Prefer places matching the user's preferences.
9. Consider geographical spread and diversity when several places are similar.
10. Return up to {max_results} places in ranked order.
11. Return ONLY valid JSON.
12. Do not provide explanations.

Required JSON format:

{{
    "selected_indexes": [0, 2, 4]
}}
"""

        # =====================================================
        # USER PROMPT
        # =====================================================

        user_prompt = (
            "Supervisor task:\n"
            + task
            + "\n\n"
            + "User preferences:\n"
            + json.dumps(
                preferences,
                ensure_ascii=False,
            )
            + "\n\n"
            + "Available places:\n"
            + json.dumps(
                compact_places,
                ensure_ascii=False,
            )
            + "\n\n"
            + f"Select up to {max_results} best matching places "
            + "in ranked order."
        )

        # =====================================================
        # LLM CALL
        # =====================================================

        logger.info(
            "LLM request started for Places Agent | "
            "places=%s | target_max=%s",
            len(compact_places),
            max_results,
        )

        response = (
            self.llm_client.generate(

                system_prompt=system_prompt,

                user_prompt=user_prompt,

                temperature=0.0,

                max_tokens=800,

                reasoning_effort="low",
            )
        )

        logger.info(
            "Places LLM response received"
        )

        # =====================================================
        # PARSE RESPONSE
        # =====================================================

        try:

            result = json.loads(
                response
            )

        except json.JSONDecodeError as exc:

            logger.error(
                "Places LLM returned invalid JSON | "
                "response=%s",
                response,
            )

            raise LLMClientError(
                "Places LLM returned invalid JSON."
            ) from exc

        # =====================================================
        # GET INDEXES
        # =====================================================

        selected_indexes = (
            result.get(
                "selected_indexes"
            )
        )

        if not isinstance(
            selected_indexes,
            list,
        ):

            raise LLMClientError(
                "Places LLM returned invalid "
                "selected_indexes."
            )

        # =====================================================
        # VALIDATE INDEXES
        # =====================================================

        valid_indexes = []

        for index in selected_indexes:

            # -------------------------------------------------
            # INTEGER CHECK
            # -------------------------------------------------

            if not isinstance(
                index,
                int,
            ):
                continue

            # -------------------------------------------------
            # NEGATIVE INDEX
            # -------------------------------------------------

            if index < 0:
                continue

            # -------------------------------------------------
            # OUT OF RANGE
            # -------------------------------------------------

            if index >= len(places):
                continue

            # -------------------------------------------------
            # DUPLICATE INDEX
            # -------------------------------------------------

            if index in valid_indexes:
                continue

            valid_indexes.append(
                index
            )

        # =====================================================
        # MAX RESULTS
        # =====================================================

        valid_indexes = (
            valid_indexes[
                :max_results
            ]
        )

        # =====================================================
        # EMPTY RESULT
        # =====================================================

        if not valid_indexes:

            raise LLMClientError(
                "Places LLM selected no valid places."
            )

        # =====================================================
        # FINAL PLACES
        # =====================================================

        ranked_places = [
            places[index]
            for index in valid_indexes
        ]

        logger.info(
            "Places LLM ranking completed | "
            "selected=%s",
            len(ranked_places),
        )

        return ranked_places
from datetime import date
from typing import Any

from app.state.trip_state import TripState


class ConstraintEngine:
    """
    Deterministic constraint validation for TripState.

    Checks:
        - Budget
        - Travel dates
        - Travelers
        - Preferences
        - Resource availability
    """

    def run(self, state: TripState) -> TripState:

        if not isinstance(state, TripState):
            raise TypeError(
                "ConstraintEngine expects a TripState object."
            )

        constraints = {
            "budget": {},
            "dates": {},
            "travelers": {},
            "preferences": {},
            "availability": {},
            "overall_valid": True,
            "errors": [],
            "warnings": [],
        }

        # =====================================================
        # 1. DATE CONSTRAINT
        # =====================================================

        start_date = state.travel_dates.start
        end_date = state.travel_dates.end

        date_valid = True

        if end_date < start_date:
            date_valid = False
            constraints["errors"].append(
                "End date cannot be before start date."
            )

        if end_date == start_date:
            constraints["warnings"].append(
                "Trip duration is 0 nights."
            )

        constraints["dates"] = {
            "valid": date_valid,
            "start": str(start_date),
            "end": str(end_date),
            "duration_days": (
                end_date - start_date
            ).days + 1,
        }

        # =====================================================
        # 2. TRAVELER CONSTRAINT
        # =====================================================

        adults = state.travelers.adults
        children = state.travelers.children

        traveler_count = adults + children

        traveler_valid = (
            adults >= 1
            and traveler_count > 0
        )

        constraints["travelers"] = {
            "valid": traveler_valid,
            "adults": adults,
            "children": children,
            "total": traveler_count,
        }

        if not traveler_valid:
            constraints["errors"].append(
                "At least one traveler is required."
            )

        # =====================================================
        # 3. PREFERENCE CONSTRAINT
        # =====================================================

        preferences = state.preferences

        constraints["preferences"] = {
            "valid": True,
            "requested": preferences,
            "count": len(preferences),
        }

        # =====================================================
        # 4. AVAILABILITY CONSTRAINT
        # =====================================================

        transport_available = bool(
            state.transport_options
        )

        hotel_available = bool(
            state.hotel_options
        )

        places_available = bool(
            state.place_options
        )

        constraints["availability"] = {
            "transport": transport_available,
            "hotel": hotel_available,
            "places": places_available,
            "weather": bool(state.weather),
        }

        if not transport_available:
            constraints["warnings"].append(
                "No transport options available."
            )

        if not hotel_available:
            constraints["warnings"].append(
                "No hotel options available."
            )

        if not places_available:
            constraints["warnings"].append(
                "No activity/place options available."
            )

        # =====================================================
        # 5. BUDGET CONSTRAINT
        # =====================================================

        budget_limit = state.budget.amount

        budget_result = self._check_budget(
            state,
            budget_limit,
        )

        constraints["budget"] = budget_result

        if (
            budget_limit is not None
            and budget_result["valid"] is False
        ):
            constraints["warnings"].append(
                "Estimated available options exceed the budget."
            )

        # =====================================================
        # 6. OVERALL STATUS
        # =====================================================

        hard_errors = constraints["errors"]

        constraints["overall_valid"] = (
            len(hard_errors) == 0
        )

        # =====================================================
        # STORE IN TRIP STATE
        # =====================================================

        state.constraints = constraints

        state.workflow_status = (
            "CONSTRAINTS_VALIDATED"
        )

        return state

    # =========================================================
    # BUDGET CHECK
    # =========================================================

    def _check_budget(
        self,
        state: TripState,
        budget_limit: float | None,
    ) -> dict[str, Any]:

        if budget_limit is None:
            return {
                "valid": True,
                "limit": None,
                "currency": state.budget.currency,
                "estimated_transport": None,
                "estimated_hotel": None,
                "estimated_total": None,
                "remaining": None,
                "message": "No budget limit provided.",
            }

        # =====================================================
        # TRAVELER COUNT
        # =====================================================

        adults = state.travelers.adults
        children = state.travelers.children

        traveler_count = adults + children

        # =====================================================
        # CHEAPEST TRANSPORT
        # =====================================================

        transport_prices = []

        for option in state.transport_options:

            price = self._extract_transport_price(
                option
            )

            if price is not None:
                transport_prices.append(price)

        if transport_prices:

            cheapest_transport_per_person = min(
                transport_prices
            )

            estimated_transport = (
                cheapest_transport_per_person
                * traveler_count
            )

        else:

            cheapest_transport_per_person = 0.0
            estimated_transport = 0.0

        # =====================================================
        # CHEAPEST HOTEL
        # =====================================================

        hotel_prices = []

        for option in state.hotel_options:

            price = self._extract_hotel_price(
                option
            )

            if price is not None:
                hotel_prices.append(price)

        if hotel_prices:

            cheapest_hotel = min(
                hotel_prices
            )

        else:

            cheapest_hotel = 0.0

        # =====================================================
        # ESTIMATED TOTAL
        # =====================================================

        estimated_total = (
            estimated_transport
            + cheapest_hotel
        )

        remaining = (
            budget_limit
            - estimated_total
        )

        # =====================================================
        # RESULT
        # =====================================================

        return {
            "valid": estimated_total <= budget_limit,
            "limit": budget_limit,
            "currency": state.budget.currency,

            "traveler_count": traveler_count,

            "cheapest_transport_per_person": (
                cheapest_transport_per_person
            ),

            "estimated_transport": (
                estimated_transport
            ),

            "estimated_hotel": (
                cheapest_hotel
            ),

            "estimated_total": (
                estimated_total
            ),

            "remaining": (
                remaining
            ),
        }

    # =========================================================
    # TRANSPORT PRICE
    # =========================================================

    @staticmethod
    def _extract_single_fare(
        data: Any,
        target_class: str | None = None,
    ) -> float | None:
        if not isinstance(data, dict):
            return None

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

        # 1. Match in fares list first if target_class given
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
                                    parsed = float(val)
                                    if parsed > 0:
                                        return parsed
                                except (TypeError, ValueError):
                                    pass

        # 2. Selected class explicit fare fields
        if target_class:
            for key in ("selected_class_fare", "selected_fare", "class_fare"):
                val = data.get(key)
                if val is not None:
                    try:
                        parsed = float(val)
                        if parsed > 0:
                            return parsed
                    except (TypeError, ValueError):
                        pass

        # 3. Fare object ONLY if matching target_class or uncontradicted
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
                            try:
                                parsed = float(val)
                                if parsed > 0:
                                    return parsed
                            except (TypeError, ValueError):
                                pass
            else:
                if not fares or not target_class:
                    for amt_key in ("amount", "fare", "price"):
                        val = fare.get(amt_key)
                        if val is not None:
                            try:
                                parsed = float(val)
                                if parsed > 0:
                                    return parsed
                            except (TypeError, ValueError):
                                pass

        # 4. Direct price fields if no fares list conflict
        if not fares or not target_class:
            for key in ("price", "amount", "fare_amount"):
                value = data.get(key)
                if value is not None:
                    try:
                        val = float(value)
                        if val > 0:
                            return val
                    except (TypeError, ValueError):
                        continue

        # 5. Default selection if fares present but no target_class
        if isinstance(fares, list) and fares and not target_class:
            amounts = []
            for item in fares:
                if isinstance(item, dict):
                    for amt_key in ("amount", "fare", "price", "fare_amount"):
                        val = item.get(amt_key)
                        if val is not None:
                            try:
                                amt = float(val)
                                if amt > 0:
                                    amounts.append(amt)
                                    break
                            except (TypeError, ValueError):
                                pass
            if amounts:
                return min(amounts)

        return None

    @staticmethod
    def _extract_transport_price(
        option: Any,
    ) -> float | None:
        if hasattr(option, "model_dump"):
            option = option.model_dump()

        if not isinstance(option, dict):
            return None

        outbound = ConstraintEngine._extract_single_fare(option) or 0.0
        return_trip = option.get("return_trip")
        return_fare = ConstraintEngine._extract_single_fare(return_trip) or 0.0 if return_trip else 0.0

        total = outbound + return_fare
        return total if total > 0 else None

    # =========================================================
    # HOTEL PRICE
    # =========================================================

    @staticmethod
    def _extract_hotel_price(
        option: Any,
    ) -> float | None:

        # -----------------------------------------------------
        # Pydantic model support
        # -----------------------------------------------------

        if hasattr(option, "model_dump"):
            option = option.model_dump()

        if not isinstance(option, dict):
            return None

        # -----------------------------------------------------
        # Direct price
        # -----------------------------------------------------

        price = option.get("price")

        if price is not None:

            try:
                return float(price)

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

            value = option.get(key)

            if isinstance(value, dict):

                amount = value.get("amount")

                if amount is not None:

                    try:
                        return float(amount)

                    except (
                        TypeError,
                        ValueError,
                    ):
                        continue

        return None
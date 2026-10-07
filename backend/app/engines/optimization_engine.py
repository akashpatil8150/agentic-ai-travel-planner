from typing import Any

from app.state.trip_state import TripState


class OptimizationEngine:
    """
    Ranks travel options using deterministic scoring.

    Priority:
        1. Budget
        2. Verification
        3. User preferences
        4. Duration / quality
    """

    def run(self, state: TripState) -> TripState:

        if not isinstance(state, TripState):
            raise TypeError(
                "OptimizationEngine expects a TripState object."
            )

        # =====================================================
        if not state.constraints:
            try:
                from app.engines.constraint_engine import ConstraintEngine
                state = ConstraintEngine().run(state)
            except Exception:
                state.constraints = {"status": "passed"}

        # =====================================================
        # OPTIMIZE EACH CATEGORY
        # =====================================================

        transport = self._rank_transport(
            state.transport_options,
            state.budget.amount,
            state.preferences,
        )

        if getattr(state, "selected_hotel", None):
            hotels = [state.selected_hotel]
        else:
            hotels = self._rank_hotels(
                state.hotel_options,
                state.budget.amount,
                state.preferences,
            )

        places = self._rank_places(
            state.place_options,
            state.preferences,
        )

        # =====================================================
        # REMOVE DUPLICATE PLACES
        # =====================================================

        unique_places = self._deduplicate_places(
            places
        )

        # =====================================================
        # DYNAMIC PLACE LIMIT
        # =====================================================

        total_days = (
            state.travel_dates.end
            - state.travel_dates.start
        ).days + 1

        # Keep enough places for the trip duration.
        # Sightseeing capacity: up to 3 activities per day.
        required_places = max(
            6,
            total_days * 3,
        )

        best_places = unique_places[
            :required_places
        ]

        # =====================================================
        # SEPARATE AND RANK OUTBOUND AND RETURN TRANSPORT
        # =====================================================
        outbound_options = [
            t for t in state.transport_options
            if isinstance(t, dict) and t.get("journey_type") == "outbound"
        ]
        return_options = [
            t for t in state.transport_options
            if isinstance(t, dict) and t.get("journey_type") == "return"
        ]

        if not outbound_options and getattr(state, "outbound_transport", None):
            outbound_options = [state.outbound_transport]
        if not return_options and getattr(state, "return_transport", None):
            return_options = [state.return_transport]

        if not outbound_options and state.transport_options:
            outbound_options = [t for t in state.transport_options if isinstance(t, dict) and t.get("journey_type") != "return"]
            if not outbound_options:
                outbound_options = state.transport_options

        best_outbound = outbound_options[0] if outbound_options else (transport[0] if transport else None)
        best_return = return_options[0] if return_options else None

        # =====================================================
        # BUILD OPTIMIZATION RESULT
        # =====================================================

        state.optimization = {
            "status": "optimized",

            "transport": transport,
            "outbound_transport": best_outbound,
            "return_transport": best_return,

            "hotels": hotels,

            "places": unique_places,

            "best_transport": best_outbound,
            "best_outbound_transport": best_outbound,
            "best_return_transport": best_return,

            "best_hotel": (
                hotels[0]
                if hotels
                else None
            ),

            "hotel_anchor": self._extract_hotel_anchor(state.selected_hotel) if getattr(state, "selected_hotel", None) else None,

            "best_places": best_places,

            "scoring_method": (
                "deterministic_weighted_score"
            ),
        }

        state.workflow_status = (
            "OPTIONS_OPTIMIZED"
        )

        return state

    @staticmethod
    def _extract_hotel_anchor(hotel: Any) -> dict | None:
        """Return selected hotel's coordinates as the optimization anchor."""
        if hasattr(hotel, "model_dump"):
            hotel = hotel.model_dump()
        if not isinstance(hotel, dict):
            return None
        lat = hotel.get("latitude", hotel.get("lat"))
        lon = hotel.get("longitude", hotel.get("lon", hotel.get("lng")))
        try:
            if lat is None or lon is None:
                return None
            lat, lon = float(lat), float(lon)
            if not (-90 <= lat <= 90 and -180 <= lon <= 180):
                return None
            return {"hotel_id": hotel.get("hotel_id") or hotel.get("id"), "latitude": lat, "longitude": lon}
        except (TypeError, ValueError):
            return None

    # =========================================================
    # OPTION NORMALIZATION
    # =========================================================

    @staticmethod
    def _to_dict(
        option: Any,
    ) -> dict:
        """
        Convert an option into a dictionary.

        Supports:
            - normal dictionaries
            - Pydantic v2 models
            - objects that can be converted using dict()
        """

        if isinstance(option, dict):
            return dict(option)

        # -----------------------------------------------------
        # Pydantic v2
        # -----------------------------------------------------

        if hasattr(option, "model_dump"):
            return option.model_dump()

        # -----------------------------------------------------
        # Generic fallback
        # -----------------------------------------------------

        try:
            return dict(option)

        except (TypeError, ValueError):
            raise TypeError(
                "Optimization option must be a dictionary "
                "or a Pydantic model."
            )

    # =========================================================
    # TRANSPORT
    # =========================================================

    def _rank_transport(
        self,
        options: list[dict],
        budget: float | None,
        preferences: list[str],
    ) -> list[dict]:

        ranked = []
        prices = []

        # =====================================================
        # FIND PRICE RANGE
        # =====================================================

        for option in options:

            price = self._transport_price(
                option
            )

            if price is not None:
                prices.append(price)

        max_price = (
            max(prices)
            if prices
            else 1
        )

        min_price = (
            min(prices)
            if prices
            else 0
        )

        # =====================================================
        # SCORE EACH TRANSPORT OPTION
        # =====================================================

        for option in options:

            option = self._to_dict(
                option
            )

            price = self._transport_price(
                option
            )

            score = 0.0

            # -------------------------------------------------
            # PRICE SCORE (BUG-09: Budget Optimization)
            # -------------------------------------------------

            price_weight = 0.65 if (budget is not None and budget < 40000) else 0.50

            if price is not None:

                if max_price == min_price:
                    price_score = 100

                else:
                    price_score = (
                        (
                            max_price - price
                        )
                        / (
                            max_price - min_price
                        )
                    ) * 100

                score += price_score * price_weight

            # -------------------------------------------------
            # STOPS
            # -------------------------------------------------

            stops = option.get(
                "stops",
                0,
            )

            try:
                stops = int(stops)

            except (
                TypeError,
                ValueError,
            ):
                stops = 0

            stop_score = max(
                0,
                100 - (stops * 25),
            )

            score += stop_score * 0.25

            # -------------------------------------------------
            # VERIFICATION
            # -------------------------------------------------

            verification = option.get(
                "verification",
                {},
            )

            if (
                isinstance(
                    verification,
                    dict,
                )
                and verification.get("status")
                == "verified"
            ):
                score += 25

            # -------------------------------------------------
            # FINAL SCORE
            # -------------------------------------------------

            option["optimization_score"] = round(
                score,
                2,
            )

            ranked.append(option)

        # =====================================================
        # SORT
        # =====================================================

        ranked.sort(
            key=lambda x: x.get(
                "optimization_score",
                0,
            ),
            reverse=True,
        )

        return ranked

    # =========================================================
    # HOTELS
    # =========================================================

    def _rank_hotels(
        self,
        options: list[dict],
        budget: float | None,
        preferences: list[str],
    ) -> list[dict]:

        ranked = []
        prices = []

        # =====================================================
        # FIND PRICE RANGE
        # =====================================================

        for option in options:

            price = self._hotel_price(
                option
            )

            if price is not None:
                prices.append(price)

        max_price = (
            max(prices)
            if prices
            else 1
        )

        min_price = (
            min(prices)
            if prices
            else 0
        )

        # =====================================================
        # SCORE EACH HOTEL
        # =====================================================

        for option in options:

            option = self._to_dict(
                option
            )

            price = self._hotel_price(
                option
            )

            score = 0.0

            # -------------------------------------------------
            # PRICE (BUG-09: Budget Optimization)
            # -------------------------------------------------

            hotel_price_weight = 0.60 if (budget is not None and budget < 40000) else 0.45

            if price is not None:

                if max_price == min_price:
                    price_score = 100

                else:
                    price_score = (
                        (
                            max_price - price
                        )
                        / (
                            max_price - min_price
                        )
                    ) * 100

                score += price_score * hotel_price_weight

            # -------------------------------------------------
            # RATING
            # -------------------------------------------------

            rating = option.get(
                "rating"
            )

            try:
                rating = float(rating)

            except (
                TypeError,
                ValueError,
            ):
                rating = None

            if rating is not None:

                # Normalize to 0-100 scale: 10-point scale if rating > 5, 5-point scale otherwise
                if rating > 5.0:
                    rating_score = min(
                        rating * 10.0,
                        100.0,
                    )
                else:
                    rating_score = min(
                        rating * 20.0,
                        100.0,
                    )

                score += rating_score * 0.30

            # -------------------------------------------------
            # CANCELLATION
            # -------------------------------------------------

            cancellation = str(
                option.get(
                    "cancellation",
                    "",
                )
            ).lower()

            if "refund" in cancellation:
                score += 15

            # -------------------------------------------------
            # VERIFICATION
            # -------------------------------------------------

            verification = option.get(
                "verification",
                {},
            )

            if (
                isinstance(
                    verification,
                    dict,
                )
                and verification.get("status")
                == "verified"
            ):
                score += 10

            # -------------------------------------------------
            # FINAL SCORE
            # -------------------------------------------------

            option["optimization_score"] = round(
                score,
                2,
            )

            ranked.append(option)

        # =====================================================
        # SORT
        # =====================================================

        ranked.sort(
            key=lambda x: x.get(
                "optimization_score",
                0,
            ),
            reverse=True,
        )

        return ranked

    # =========================================================
    # PLACES
    # =========================================================

    def _rank_places(
        self,
        options: list[dict],
        preferences: list[str],
    ) -> list[dict]:

        ranked = []

        preferences_lower = [
            str(p).lower()
            for p in preferences
        ]

        # =====================================================
        # SCORE EACH PLACE
        # =====================================================

        for option in options:

            option = self._to_dict(
                option
            )

            score = 0.0

            # -------------------------------------------------
            # NAME / CATEGORY MATCH
            # -------------------------------------------------

            searchable_text = " ".join(
                [
                    str(
                        option.get(
                            "name",
                            "",
                        )
                    ),
                    str(
                        option.get(
                            "category",
                            "",
                        )
                    ),
                    str(
                        option.get(
                            "type",
                            "",
                        )
                    ),
                    str(
                        option.get(
                            "description",
                            "",
                        )
                    ),
                ]
            ).lower()

            matched_preferences = []

            for preference in preferences_lower:

                if preference in searchable_text:

                    matched_preferences.append(
                        preference
                    )

                    score += 20

            # -------------------------------------------------
            # RATING
            # -------------------------------------------------

            rating = option.get(
                "rating"
            )

            try:
                rating = float(rating)

            except (
                TypeError,
                ValueError,
            ):
                rating = None

            if rating is not None:

                score += min(
                    rating * 10,
                    50,
                )

            # -------------------------------------------------
            # VERIFICATION
            # -------------------------------------------------

            verification = option.get(
                "verification",
                {},
            )

            ver_status = (
                verification.get("status")
                if isinstance(verification, dict)
                else None
            )

            # Strictly exclude any place that is not verified / accepted
            if ver_status not in ["verified", "available", "evidence_found"]:
                continue

            score += 30

            # -------------------------------------------------
            # MATCHED PREFERENCES
            # -------------------------------------------------

            option["matched_preferences"] = (
                matched_preferences
            )

            # -------------------------------------------------
            # FINAL SCORE
            # -------------------------------------------------

            option["optimization_score"] = round(
                score,
                2,
            )

            ranked.append(option)

        # =====================================================
        # SORT
        # =====================================================

        ranked.sort(
            key=lambda x: x.get(
                "optimization_score",
                0,
            ),
            reverse=True,
        )

        return ranked

    # =========================================================
    # PLACE DEDUPLICATION
    # =========================================================

    @staticmethod
    def _deduplicate_places(
        places: list[dict],
    ) -> list[dict]:
        """
        Remove duplicate places by normalized name.

        Places are already ranked before this method runs,
        so the first occurrence is always the highest-ranked
        version of that place.
        """

        unique_places = {}

        for place in places:

            name = str(
                place.get(
                    "name",
                    "",
                )
            ).strip().lower()

            if not name:
                continue

            if name in unique_places:
                continue

            unique_places[name] = place

        return list(
            unique_places.values()
        )

    # =========================================================
    # PRICE HELPERS
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
    def _transport_price(
        option: Any,
    ) -> float | None:
        option = OptimizationEngine._to_dict(
            option
        )
        if not isinstance(option, dict):
            return None

        outbound_price = OptimizationEngine._extract_single_fare(option) or 0.0
        return_trip = option.get("return_trip")
        return_price = OptimizationEngine._extract_single_fare(return_trip) or 0.0 if return_trip else 0.0

        total_price = outbound_price + return_price
        return total_price if total_price > 0 else None

    # =========================================================
    # HOTEL PRICE
    # =========================================================

    @staticmethod
    def _hotel_price(
        option: Any,
    ) -> float | None:

        option = OptimizationEngine._to_dict(
            option
        )

        try:
            return float(
                option.get(
                    "price"
                )
            )

        except (
            TypeError,
            ValueError,
        ):
            return None
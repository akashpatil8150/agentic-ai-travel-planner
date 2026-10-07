from datetime import datetime, date, timedelta

from app.state.trip_state import TripState


class ItineraryValidator:
    """
    Validates the generated itinerary.

    Checks:
        - Itinerary exists
        - Dates are valid
        - Number of days
        - Activities
        - Duplicate activities
        - Activity timing
        - Activity duration
        - Budget
        - Transport
        - Hotel
        - Cost consistency
    """

    def run(
        self,
        state: TripState,
    ) -> TripState:

        if not isinstance(
            state,
            TripState,
        ):
            raise TypeError(
                "ItineraryValidator expects a TripState object."
            )

        errors = []
        warnings = []

        itinerary = state.itinerary

        # =====================================================
        # 1. ITINERARY EXISTS
        # =====================================================

        if not itinerary:

            errors.append(
                "Itinerary is empty."
            )

            return self._store_result(
                state,
                errors,
                warnings,
            )

        # =====================================================
        # 2. DATES
        # =====================================================

        start_date = (
            state.travel_dates.start
        )

        end_date = (
            state.travel_dates.end
        )

        itinerary_start = (
            itinerary.get(
                "start_date"
            )
        )

        itinerary_end = (
            itinerary.get(
                "end_date"
            )
        )

        if str(start_date) != str(
            itinerary_start
        ):

            errors.append(
                "Itinerary start date does not match trip start date."
            )

        if str(end_date) != str(
            itinerary_end
        ):

            errors.append(
                "Itinerary end date does not match trip end date."
            )

        # =====================================================
        # 3. DAYS
        # =====================================================

        days = itinerary.get(
            "days",
            [],
        )

        # Base trip duration comes from the user's selected dates.
        expected_days = (
            end_date - start_date
        ).days + 1

        # A return journey can arrive after the configured trip end date.
        # In that case, the itinerary builder may legitimately create an
        # additional return-arrival day based on the actual transport
        # arrival date.
        transport_timing = itinerary.get(
            "transport_timing",
            {},
        )

        return_arrival = None

        if isinstance(transport_timing, dict):
            return_arrival = self._parse_datetime(
                transport_timing.get("return_arrival")
            )

            if return_arrival:
                transport_end_date = return_arrival.date()

                if transport_end_date > end_date:
                    expected_days = (
                        transport_end_date - start_date
                    ).days + 1

        if len(days) != expected_days:

            errors.append(
                f"Expected {expected_days} itinerary days, "
                f"but found {len(days)}."
            )

        # =====================================================
        # 4. ACTIVITY VALIDATION
        # =====================================================

        activity_names = set()

        activity_ids = set()

        total_activities = 0

        for day in days:

            if not isinstance(
                day,
                dict,
            ):

                errors.append(
                    "Invalid itinerary day format."
                )

                continue

            activities = day.get(
                "activities",
                [],
            )

            if not isinstance(
                activities,
                list,
            ):

                errors.append(
                    "Activities must be a list."
                )

                continue

            for activity in activities:

                if not isinstance(
                    activity,
                    dict,
                ):

                    errors.append(
                        "Invalid activity format."
                    )

                    continue

                # Hotel routing events are itinerary logistics, not sightseeing places.
                is_transit_event = (
                    activity.get("type") == "hotel_transit"
                    or activity.get("category") == "transit"
                )

                if not is_transit_event:
                    total_activities += 1

                name = activity.get(
                    "name"
                )

                if not name:

                    errors.append(
                        "Activity name is missing."
                    )

                    continue

                # =================================================
                # DUPLICATE CHECK
                # =================================================

                normalized_name = (
                    str(name)
                    .strip()
                    .lower()
                )

                place_id = activity.get(
                    "place_id"
                )

                normalized_place_id = None

                if place_id:

                    normalized_place_id = (
                        str(place_id)
                        .strip()
                        .lower()
                    )

                duplicate_found = False

                # Hotel departure/return routing events can repeat every day.
                # They must not participate in sightseeing-place uniqueness checks.
                if is_transit_event:
                    continue

                # -------------------------------------------------
                # Check by place_id
                # -------------------------------------------------

                if (
                    normalized_place_id
                    and normalized_place_id
                    in activity_ids
                ):

                    duplicate_found = True

                # -------------------------------------------------
                # Check by name
                # -------------------------------------------------

                if (
                    normalized_name
                    in activity_names
                ):

                    duplicate_found = True

                # -------------------------------------------------
                # Duplicate is a WARNING
                # NOT a validation ERROR
                # -------------------------------------------------

                if duplicate_found:

                    warnings.append(
                        f"Duplicate activity found: {name}"
                    )

                    # Continue validation of the activity
                    # instead of stopping here.
                    #
                    # This ensures that timing, duration,
                    # etc. are still validated.

                else:

                    # -------------------------------------------------
                    # Store identity
                    # -------------------------------------------------

                    activity_names.add(
                        normalized_name
                    )

                    if normalized_place_id:

                        activity_ids.add(
                            normalized_place_id
                        )

                # =================================================
                # TIME CHECK
                # =================================================

                start_time = activity.get(
                    "start_time"
                )

                if not start_time:

                    errors.append(
                        f"Start time missing for activity: {name}"
                    )

                # =================================================
                # DURATION CHECK
                # =================================================

                duration = activity.get(
                    "duration_minutes"
                )

                if duration is None:

                    errors.append(
                        f"Duration missing for activity: {name}"
                    )

                else:

                    try:

                        duration = int(
                            duration
                        )

                        if duration <= 0:

                            errors.append(
                                f"Invalid duration for activity: {name}"
                            )

                    except (
                        TypeError,
                        ValueError,
                    ):

                        errors.append(
                            f"Invalid duration for activity: {name}"
                        )

        # =====================================================
        # 5. TRANSPORT TIMING VALIDATION
        # =====================================================

        self._validate_transport_timing(
            state,
            itinerary,
            days,
            errors,
            warnings,
        )

        # =====================================================
        # 5. EMPTY ITINERARY WARNING
        # =====================================================

        if total_activities == 0:

            warnings.append(
                "No activities were added to the itinerary."
            )

        # =====================================================
        # 6. TRANSPORT CHECK
        # =====================================================

        transport = itinerary.get(
            "transport"
        )

        if not transport:

            warnings.append(
                "No transport selected."
            )

        # =====================================================
        # 7. HOTEL CHECK
        # =====================================================

        hotel = itinerary.get(
            "hotel"
        )

        if not hotel:

            warnings.append(
                "No hotel selected."
            )
        else:
            # Hotel stay must be based on actual destination arrival and
            # return departure dates, not the raw trip start date.
            hotel_timing = itinerary.get("hotel_timing", {})
            hotel_check_in = self._parse_date(
                hotel_timing.get("check_in") if isinstance(hotel_timing, dict) else None
            )
            hotel_check_out = self._parse_date(
                hotel_timing.get("check_out") if isinstance(hotel_timing, dict) else None
            )
            hotel_nights = itinerary.get("hotel_nights")

            transport_timing = itinerary.get("transport_timing", {})
            destination_arrival = self._parse_datetime(
                transport_timing.get("destination_arrival") or transport_timing.get("arrival")
                if isinstance(transport_timing, dict) else None
            )
            return_departure = self._parse_datetime(
                transport_timing.get("return_departure")
                if isinstance(transport_timing, dict) else None
            )
            destination_departure_for_return = self._parse_datetime(
                transport_timing.get("destination_departure_for_return")
                or transport_timing.get("destination_departure")
                if isinstance(transport_timing, dict) else None
            )

            if hotel_check_in and destination_arrival:
                if hotel_check_in != destination_arrival.date():
                    errors.append(
                        "Hotel check-in date does not match destination arrival date."
                    )

            expected_checkout_date = (
                destination_departure_for_return.date()
                if destination_departure_for_return
                else (return_departure.date() if return_departure else None)
            )

            if hotel_check_out and expected_checkout_date:
                if hotel_check_out != expected_checkout_date:
                    errors.append(
                        "Hotel check-out date does not match actual destination departure date for the return journey."
                    )

            if hotel_check_in and hotel_check_out:
                calculated_nights = (hotel_check_out - hotel_check_in).days
                try:
                    if hotel_nights is not None and int(hotel_nights) != calculated_nights:
                        errors.append(
                            "Hotel night count does not match check-in/check-out dates."
                        )
                except (TypeError, ValueError):
                    errors.append("Invalid hotel night count.")

        # =====================================================
        # 8. BUDGET CHECK
        # =====================================================

        estimated_cost = itinerary.get(
            "estimated_cost",
            0,
        )

        budget_limit = (
            state.budget.amount
        )

        try:

            estimated_cost = float(
                estimated_cost or 0
            )

        except (
            TypeError,
            ValueError,
        ):

            errors.append(
                "Invalid estimated itinerary cost."
            )

            estimated_cost = 0.0

        # -----------------------------------------------------
        # Budget exceeded
        # -----------------------------------------------------

        if (
            budget_limit is not None
            and estimated_cost > budget_limit
        ):

            errors.append(
                "Itinerary exceeds the configured budget."
            )

        # =====================================================
        # 9. COST CONSISTENCY CHECK
        # =====================================================

        estimated_transport = itinerary.get(
            "estimated_transport"
        )

        estimated_hotel = itinerary.get(
            "estimated_hotel"
        )

        if (
            estimated_transport is not None
            and estimated_hotel is not None
        ):

            try:

                calculated_total = (
                    float(
                        estimated_transport
                    )
                    +
                    float(
                        estimated_hotel
                    )
                )

                if abs(
                    calculated_total
                    - estimated_cost
                ) > 0.01:

                    errors.append(
                        "Estimated itinerary cost does not match "
                        "transport + hotel cost."
                    )

            except (
                TypeError,
                ValueError,
            ):

                errors.append(
                    "Invalid transport or hotel cost."
                )

        # =====================================================
        # 10. STORE RESULT
        # =====================================================

        return self._store_result(
            state,
            errors,
            warnings,
        )

    # =========================================================
    # TRANSPORT TIMING VALIDATION
    # =========================================================

    @staticmethod
    def _validate_transport_timing(
        state: TripState,
        itinerary: dict,
        days: list,
        errors: list[str],
        warnings: list[str],
    ) -> None:
        """Validate activities against actual transport timing.

        Rules:
            - Outbound travel day should not contain sightseeing.
            - Arrival day starts only after arrival + 2 hours.
            - Return/departure day ends 3 hours before departure.
            - Activity duration must fit inside the allowed window.
        """

        timing = itinerary.get(
            "transport_timing",
            {},
        )

        if not isinstance(timing, dict) or not timing:
            warnings.append(
                "Transport timing information is unavailable; "
                "transport-time activity validation was skipped."
            )
            return

        outbound = ItineraryValidator._parse_datetime(
            timing.get("outbound_departure")
        )
        arrival = ItineraryValidator._parse_datetime(
            timing.get("arrival")
        )
        return_departure = ItineraryValidator._parse_datetime(
            timing.get("return_departure")
        )

        # If none of the actual timestamps are available, do not
        # incorrectly fail an itinerary built from incomplete
        # provider data.
        if not outbound and not arrival and not return_departure:
            warnings.append(
                "Transport timestamps could not be parsed; "
                "transport-time activity validation was skipped."
            )
            return

        arrival_buffer = (
            arrival + timedelta(hours=2)
            if arrival
            else None
        )

        departure_buffer = (
            return_departure - timedelta(hours=3)
            if return_departure
            else None
        )

        for day in days:
            if not isinstance(day, dict):
                continue

            day_date = ItineraryValidator._parse_date(
                day.get("date")
            )

            if not day_date:
                warnings.append(
                    "Could not parse itinerary day date for "
                    "transport timing validation."
                )
                continue

            activities = day.get(
                "activities",
                [],
            )

            if not isinstance(activities, list):
                continue

            for activity in activities:
                if not isinstance(activity, dict):
                    continue

                name = activity.get(
                    "name",
                    "Activity",
                )
                # Hotel/station transfers are logistics, not sightseeing.
                # They must not be evaluated against sightseeing timing windows.
                is_transit_event = (
                    activity.get("type") == "hotel_transit"
                    or activity.get("category") == "transit"
                )

                if is_transit_event:
                    continue

                start_time = activity.get(
                    "start_time"
                )

                duration = activity.get(
                    "duration_minutes"
                )

                if not start_time or duration is None:
                    continue

                activity_start = (
                    ItineraryValidator._combine_date_time(
                        day_date,
                        start_time,
                    )
                )

                if not activity_start:
                    warnings.append(
                        f"Could not parse activity time for: {name}"
                    )
                    continue

                try:
                    duration_minutes = int(duration)
                except (TypeError, ValueError):
                    continue

                activity_end = (
                    activity_start
                    + timedelta(
                        minutes=duration_minutes
                    )
                )

                # -------------------------------------------------
                # OUTBOUND JOURNEY DAY
                # -------------------------------------------------

                if outbound:
                    if day_date == outbound.date():
                        errors.append(
                            f"Activity '{name}' is scheduled on "
                            f"the outbound travel day "
                            f"({outbound.date()})."
                        )

                    elif (
                        day_date < outbound.date()
                        and arrival
                    ):
                        errors.append(
                            f"Activity '{name}' is scheduled before "
                            f"destination arrival."
                        )

                # -------------------------------------------------
                # ARRIVAL DAY
                # -------------------------------------------------

                if (
                    arrival_buffer
                    and day_date == arrival_buffer.date()
                    and activity_start < arrival_buffer
                ):
                    errors.append(
                        f"Activity '{name}' starts before the "
                        f"arrival/check-in buffer ends "
                        f"({arrival_buffer.strftime('%H:%M')})."
                    )

                # -------------------------------------------------
                # RETURN / DEPARTURE DAY
                # -------------------------------------------------

                if (
                    departure_buffer
                    and day_date == departure_buffer.date()
                    and activity_end > departure_buffer
                ):
                    errors.append(
                        f"Activity '{name}' ends after the "
                        f"return-departure safety buffer "
                        f"({departure_buffer.strftime('%H:%M')})."
                    )

                # -------------------------------------------------
                # DIRECT JOURNEY OVERLAP
                # -------------------------------------------------

                if outbound and activity_start < outbound:
                    errors.append(
                        f"Activity '{name}' overlaps outbound "
                        f"transport timing."
                    )

                if (
                    return_departure
                    and activity_end > return_departure
                ):
                    errors.append(
                        f"Activity '{name}' overlaps return "
                        f"transport timing."
                    )

    @staticmethod
    def _parse_date(value) -> date | None:
        if isinstance(value, date):
            return value

        if not value:
            return None

        try:
            return date.fromisoformat(
                str(value)[:10]
            )
        except (TypeError, ValueError):
            return None

    @staticmethod
    def _parse_datetime(value) -> datetime | None:
        if isinstance(value, datetime):
            return value

        if not value:
            return None

        raw = str(value).strip()

        try:
            return datetime.fromisoformat(
                raw.replace("Z", "+00:00")
            ).replace(tzinfo=None)
        except ValueError:
            pass

        formats = (
            "%Y-%m-%d %H:%M",
            "%Y-%m-%d %H:%M:%S",
            "%Y-%m-%d %I:%M %p",
            "%Y-%m-%dT%I:%M %p",
            "%d-%m-%Y %H:%M",
            "%d-%m-%Y %I:%M %p",
        )

        for fmt in formats:
            try:
                return datetime.strptime(
                    raw,
                    fmt,
                )
            except ValueError:
                continue

        return None

    @staticmethod
    def _combine_date_time(
        day_date: date,
        value,
    ) -> datetime | None:
        if isinstance(value, datetime):
            return value.replace(tzinfo=None)

        raw = str(value).strip()

        formats = (
            "%H:%M",
            "%H:%M:%S",
            "%I:%M %p",
            "%I:%M%p",
        )

        for fmt in formats:
            try:
                parsed_time = datetime.strptime(
                    raw,
                    fmt,
                ).time()

                return datetime.combine(
                    day_date,
                    parsed_time,
                )
            except ValueError:
                continue

        parsed_datetime = (
            ItineraryValidator._parse_datetime(raw)
        )

        if parsed_datetime:
            return parsed_datetime

        return None

    # =========================================================
    # STORE VALIDATION RESULT
    # =========================================================

    @staticmethod
    def _store_result(
        state: TripState,
        errors: list[str],
        warnings: list[str],
    ) -> TripState:

        valid = len(errors) == 0

        state.validation = {

            "valid": valid,

            "errors": errors,

            "warnings": warnings,

            "error_count": len(errors),

            "warning_count": len(warnings),
        }

        if valid:

            state.workflow_status = (
                "ITINERARY_VALIDATED"
            )

        else:

            state.workflow_status = (
                "VALIDATION_FAILED"
            )

        return state
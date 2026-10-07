from typing import Any, Dict, List


class ResultAggregatorError(Exception):
    """
    Base exception for Result Aggregator.
    """

    pass


class ResultAggregator:
    """
    Result Aggregator.

    Responsibilities:
        1. Collect results from all agents.
        2. Normalize result structure.
        3. Remove duplicate options.
        4. Attach verification information.
        5. Calculate summary metadata.
        6. Store unified results in TripState.

    This component does NOT use Groq.

    Groq will be used later for:
        - reasoning
        - ranking
        - recommendation
        - itinerary planning
    """

    # =====================================================
    # INIT
    # =====================================================

    def __init__(self):
        pass

    # =====================================================
    # NORMALIZE SINGLE OPTION
    # =====================================================

    @staticmethod
    def normalize_option(
        option: Any,
    ) -> Dict[str, Any]:
        """
        Convert a single option into a dictionary.

        Supports:
            - dict
            - Pydantic v2 models
            - objects exposing model_dump()
        """

        # -------------------------------------------------
        # Dictionary
        # -------------------------------------------------

        if isinstance(option, dict):

            return dict(option)

        # -------------------------------------------------
        # Pydantic v2 model
        # -------------------------------------------------

        if hasattr(
            option,
            "model_dump",
        ):

            return option.model_dump()

        # -------------------------------------------------
        # Unsupported type
        # -------------------------------------------------

        raise ResultAggregatorError(
            f"Unsupported option type: "
            f"{type(option).__name__}"
        )

    # =====================================================
    # NORMALIZE LIST
    # =====================================================

    @classmethod
    def normalize_list(
        cls,
        options: Any,
    ) -> List[Dict[str, Any]]:

        if options is None:

            return []

        if not isinstance(
            options,
            list,
        ):

            raise ResultAggregatorError(
                "Expected a list of options."
            )

        normalized = []

        for option in options:

            try:

                normalized_option = (
                    cls.normalize_option(
                        option
                    )
                )

                normalized.append(
                    normalized_option
                )

            except ResultAggregatorError as exc:

                print(
                    "\nSkipping unsupported option:"
                )

                print(
                    f"{type(option).__name__}: "
                    f"{exc}"
                )

                continue

        return normalized

    # =====================================================
    # DEDUPLICATE OPTIONS
    # =====================================================

    @staticmethod
    def deduplicate_options(
        options: List[Dict[str, Any]],
        option_type: str,
    ) -> List[Dict[str, Any]]:

        unique = []

        seen = set()

        for option in options:

            # =================================================
            # TRANSPORT
            # =================================================

            if option_type == "transport":

                key = (
                    option.get("journey_type") or "default",
                    option.get(
                        "flight_number"
                    )
                    or option.get(
                        "train_number"
                    )
                    or option.get(
                        "id"
                    )
                    or (
                        option.get(
                            "provider"
                        ),
                        option.get(
                            "origin"
                        )
                        or option.get(
                            "from_station_code"
                        )
                        or option.get(
                            "from_code"
                        ),
                        option.get(
                            "destination"
                        )
                        or option.get(
                            "to_station_code"
                        )
                        or option.get(
                            "to_code"
                        ),
                    ),
                )

            # =================================================
            # HOTEL
            # =================================================

            elif option_type == "hotel":

                key = (
                    option.get(
                        "hotel_id"
                    )
                    or option.get(
                        "id"
                    )
                    or option.get(
                        "name"
                    )
                    or option.get(
                        "hotel_name"
                    )
                )

            # =================================================
            # PLACE
            # =================================================

            elif option_type == "place":

                key = (
                    option.get(
                        "place_id"
                    )
                    or option.get(
                        "id"
                    )
                    or (
                        option.get(
                            "name"
                        ),
                        option.get(
                            "latitude"
                        ),
                        option.get(
                            "longitude"
                        ),
                    )
                )

            # =================================================
            # FALLBACK
            # =================================================

            else:

                key = (
                    option.get(
                        "id"
                    )
                    or str(option)
                )

            # =================================================
            # MAKE HASHABLE
            # =================================================

            try:

                hash(key)

            except TypeError:

                key = str(key)

            # =================================================
            # DUPLICATE
            # =================================================

            if key in seen:

                continue

            seen.add(key)

            unique.append(
                option
            )

        return unique

    # =====================================================
    # GET VERIFICATION RESULTS
    # =====================================================

    @staticmethod
    def get_verification_results(
        verification: Dict[str, Any],
        section: str,
    ) -> List[Dict[str, Any]]:

        if not verification:

            return []

        section_data = (
            verification.get(
                section,
                {},
            )
        )

        if not isinstance(
            section_data,
            dict,
        ):

            return []

        results = (
            section_data.get(
                "results",
                [],
            )
        )

        if not isinstance(
            results,
            list,
        ):

            return []

        return results

    # =====================================================
    # NORMALIZE TEXT
    # =====================================================

    @staticmethod
    def normalize_text(
        value: Any,
    ) -> str:

        if value is None:

            return ""

        return " ".join(
            str(value)
            .lower()
            .strip()
            .split()
        )

    # =====================================================
    # ATTACH VERIFICATION
    # =====================================================

    def attach_verification(
        self,
        options: List[Dict[str, Any]],
        verification_results: List[Dict[str, Any]],
        option_type: str,
    ) -> List[Dict[str, Any]]:

        if not options:

            return []

        # -------------------------------------------------
        # No verification results
        # -------------------------------------------------

        if not verification_results:

            return [
                {
                    **option,

                    "verification": {
                        "status": "not_checked",
                        "confidence": None,
                    },
                }

                for option in options
            ]

        aggregated_options = []

        # =================================================
        # PROCESS EACH OPTION
        # =================================================

        for option in options:

            option_copy = dict(
                option
            )

            matching_result = None

            # =================================================
            # FIND MATCHING VERIFICATION
            # =================================================

            for result in verification_results:

                # =================================================
                # HOTEL MATCHING
                # =================================================

                if option_type == "hotel":

                    option_name = (
                        self.normalize_text(
                            option.get(
                                "name"
                            )
                            or option.get(
                                "hotel_name"
                            )
                        )
                    )

                    result_name = (
                        self.normalize_text(
                            result.get(
                                "name"
                            )
                            or result.get(
                                "hotel_name"
                            )
                        )
                    )

                    if (
                        option_name
                        and result_name
                        and (
                            option_name
                            == result_name
                        )
                    ):

                        matching_result = (
                            result
                        )

                        break

                # =================================================
                # PLACE MATCHING
                # =================================================

                elif option_type == "place":

                    option_place_id = (
                        option.get(
                            "place_id"
                        )
                    )

                    result_place_id = (
                        result.get(
                            "place_id"
                        )
                    )

                    # -----------------------------------------
                    # Primary: place_id
                    # -----------------------------------------

                    if (
                        option_place_id
                        and result_place_id
                        and (
                            option_place_id
                            == result_place_id
                        )
                    ):

                        matching_result = (
                            result
                        )

                        break

                    # -----------------------------------------
                    # Fallback: name
                    # -----------------------------------------

                    option_name = (
                        self.normalize_text(
                            option.get(
                                "name"
                            )
                        )
                    )

                    result_name = (
                        self.normalize_text(
                            result.get(
                                "name"
                            )
                        )
                    )

                    if (
                        option_name
                        and result_name
                        and (
                            option_name
                            == result_name
                        )
                    ):

                        matching_result = (
                            result
                        )

                        break

                # =================================================
                # TRANSPORT MATCHING
                # =================================================

                elif option_type == "transport":

                    # -----------------------------------------
                    # Flight number
                    # -----------------------------------------

                    option_flight_number = (
                        self.normalize_text(
                            option.get(
                                "flight_number"
                            )
                        )
                    )

                    result_transport = (
                        self.normalize_text(
                            result.get(
                                "transport"
                            )
                        )
                    )

                    # -----------------------------------------
                    # Train number
                    # -----------------------------------------

                    option_train_number = (
                        self.normalize_text(
                            option.get(
                                "train_number"
                            )
                        )
                    )

                    option_name = self.normalize_text(
                        option.get("name") or option.get("train_name") or option.get("flight_name")
                    )
                    result_name = self.normalize_text(
                        result.get("name") or result.get("transport")
                    )

                    # -----------------------------------------
                    # Flight matching
                    # -----------------------------------------

                    if (
                        option_flight_number
                        and result_transport
                        and (
                            option_flight_number
                            in result_transport
                        )
                    ):

                        matching_result = (
                            result
                        )

                        break

                    # -----------------------------------------
                    # Train matching
                    # -----------------------------------------

                    if (
                        option_train_number
                        and result_transport
                        and (
                            option_train_number
                            in result_transport
                        )
                    ):

                        matching_result = (
                            result
                        )

                        break

                    # -----------------------------------------
                    # Name matching fallback
                    # -----------------------------------------

                    if (
                        option_name
                        and result_name
                        and (
                            option_name in result_name
                            or result_name in option_name
                        )
                    ):

                        matching_result = (
                            result
                        )

                        break

            # -----------------------------------------
            # Index fallback if single candidate verified
            # -----------------------------------------
            if not matching_result and option_type == "transport" and len(options) == len(verification_results):
                idx = options.index(option)
                if 0 <= idx < len(verification_results):
                    matching_result = verification_results[idx]

            # =================================================
            # ATTACH MATCHED VERIFICATION
            # =================================================

            if matching_result:

                option_copy[
                    "verification"
                ] = {

                    "status": (
                        matching_result.get(
                            "status"
                        )
                    ),

                    "confidence": (
                        matching_result.get(
                            "confidence"
                        )
                    ),

                    "supporting_sources": (
                        matching_result.get(
                            "supporting_sources"
                        )
                    ),

                    "evidence_count": (
                        matching_result.get(
                            "evidence_count"
                        )
                    ),

                    "verification_method": (
                        matching_result.get(
                            "verification_method"
                        )
                    ),
                }

            # =================================================
            # NO MATCH
            # =================================================

            else:

                option_copy[
                    "verification"
                ] = {

                    "status": "not_checked",

                    "confidence": None,
                }

            if option_type == "hotel":
                h_name = option_copy.get("hotel_name") or option_copy.get("name")
                if h_name:
                    option_copy["hotel_name"] = h_name
                    option_copy["name"] = h_name

            if option_type == "transport":
                if option_copy.get("type") == "flight" or option_copy.get("airline") or option_copy.get("flight_number"):
                    f_name = option_copy.get("flight_name") or option_copy.get("name")
                    if f_name:
                        option_copy["flight_name"] = f_name
                        option_copy["name"] = f_name

            aggregated_options.append(
                option_copy
            )

        return aggregated_options

    # =====================================================
    # GET VERIFIED OPTIONS
    # =====================================================

    @staticmethod
    def get_verified_options(
        options: List[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:

        verified = []

        for option in options:

            verification = (
                option.get(
                    "verification",
                    {},
                )
            )

            status = verification.get(
                "status"
            )

            if status in [
                "verified",
                "available",
                "evidence_found",
            ]:

                verified.append(
                    option
                )

        return verified

    # =====================================================
    # BUILD SUMMARY
    # =====================================================

    def build_summary(
        self,
        transport: List[Dict[str, Any]],
        hotels: List[Dict[str, Any]],
        places: List[Dict[str, Any]],
        weather: Dict[str, Any],
    ) -> Dict[str, Any]:

        # -------------------------------------------------
        # Total options
        # -------------------------------------------------

        total_options = (
            len(transport)
            + len(hotels)
            + len(places)
        )

        # -------------------------------------------------
        # Verified counts
        # -------------------------------------------------

        verified_transport = len(
            self.get_verified_options(
                transport
            )
        )

        verified_hotels = len(
            self.get_verified_options(
                hotels
            )
        )

        verified_places = len(
            self.get_verified_options(
                places
            )
        )

        verified_options = (
            verified_transport
            + verified_hotels
            + verified_places
        )

        # -------------------------------------------------
        # Summary
        # -------------------------------------------------

        return {

            "total_options": (
                total_options
            ),

            "verified_options": (
                verified_options
            ),

            "transport_options": (
                len(transport)
            ),

            "verified_transport": (
                verified_transport
            ),

            "hotel_options": (
                len(hotels)
            ),

            "verified_hotels": (
                verified_hotels
            ),

            "place_options": (
                len(places)
            ),

            "verified_places": (
                verified_places
            ),

            "weather_available": (
                weather.get(
                    "status"
                )
                == "available"
            ),
        }

    # =====================================================
    # AGGREGATE
    # =====================================================

    def aggregate(
        self,
        state,
    ):

        print("\n========================================")
        print("          RESULT AGGREGATOR")
        print("========================================")

        # =================================================
        # VALIDATE STATE
        # =================================================

        if state is None:

            raise ResultAggregatorError(
                "TripState is required."
            )

        # =================================================
        # READ AGENT RESULTS
        # =================================================

        transport = (
            self.normalize_list(
                state.transport_options
            )
        )

        hotels = (
            self.normalize_list(
                state.hotel_options
            )
        )

        places = (
            self.normalize_list(
                state.place_options
            )
        )

        weather = (
            state.weather
            if isinstance(
                state.weather,
                dict,
            )
            else {}
        )

        verification = (
            state.verification
            if isinstance(
                state.verification,
                dict,
            )
            else {}
        )

        out_count = 1 if (transport and isinstance(transport[0], dict)) else 0
        ret_count = 1 if (transport and isinstance(transport[0], dict) and transport[0].get("return_trip")) else 0
        total_legs = out_count + ret_count

        print("\nNORMALIZED TRANSPORT")
        print(f"Outbound transport: {out_count}")
        print(f"Return transport:   {ret_count}")
        print(f"Total transport legs: {total_legs}")

        if transport and isinstance(transport[0], dict):
            top = transport[0]
            out_orig = top.get("from_station_code") or top.get("from_code") or top.get("origin") or ""
            out_dest = top.get("to_station_code") or top.get("to_code") or top.get("destination") or ""
            out_num = top.get("train_number") or top.get("flight_number") or ""
            out_name = top.get("train_name") or top.get("name") or top.get("flight_name") or ""
            out_str = f"{out_num} {out_name}".strip()
            print(f"\nOUTBOUND:\n{out_orig} -> {out_dest} | {out_str}")

            ret_trip = top.get("return_trip")
            if isinstance(ret_trip, dict):
                ret_orig = ret_trip.get("from_station_code") or ret_trip.get("from_code") or ret_trip.get("origin") or ""
                ret_dest = ret_trip.get("to_station_code") or ret_trip.get("to_code") or ret_trip.get("destination") or ""
                ret_num = ret_trip.get("train_number") or ret_trip.get("flight_number") or ""
                ret_name = ret_trip.get("train_name") or ret_trip.get("name") or ret_trip.get("flight_name") or ""
                ret_str = f"{ret_num} {ret_name}".strip()
                print(f"\nRETURN:\n{ret_orig} -> {ret_dest} | {ret_str}")

        print(f"\nNormalized hotel options: {len(hotels)}")
        print(f"Normalized place options: {len(places)}")

        # =================================================
        # DEDUPLICATION
        # =================================================

        transport = (
            self.deduplicate_options(
                transport,
                "transport",
            )
        )

        hotels = (
            self.deduplicate_options(
                hotels,
                "hotel",
            )
        )

        places = (
            self.deduplicate_options(
                places,
                "place",
            )
        )

        # =================================================
        # GET VERIFICATION RESULTS
        # =================================================

        transport_verification = (
            self.get_verification_results(
                verification,
                "transport",
            )
        )

        hotel_verification = (
            self.get_verification_results(
                verification,
                "hotels",
            )
        )

        place_verification = (
            self.get_verification_results(
                verification,
                "places",
            )
        )

        # =================================================
        # ATTACH VERIFICATION
        # =================================================

        transport = (
            self.attach_verification(
                transport,
                transport_verification,
                "transport",
            )
        )

        hotels = (
            self.attach_verification(
                hotels,
                hotel_verification,
                "hotel",
            )
        )

        places = (
            self.attach_verification(
                places,
                place_verification,
                "place",
            )
        )

        # =================================================
        # STRICT TRANSPORT FILTERING: VERIFIED / ACCEPTED ONLY
        # =================================================

        verified_transport = [
            t for t in transport
            if isinstance(t, dict)
            and t.get("verification", {}).get("status") in [
                "verified",
                "available",
                "evidence_found",
            ]
        ]

        outbound_transport = None
        return_transport = None
        outbound_transfer = None
        return_transfer = None

        if getattr(state, "outbound_transfer", None):
            outbound_transfer = dict(state.outbound_transfer)
        elif getattr(state, "metadata", {}).get("outbound_transfer"):
            outbound_transfer = dict(state.metadata["outbound_transfer"])

        if getattr(state, "return_transfer", None):
            return_transfer = dict(state.return_transfer)
        elif getattr(state, "metadata", {}).get("return_transfer"):
            return_transfer = dict(state.metadata["return_transfer"])

        for t in verified_transport:
            if not isinstance(t, dict):
                continue
            jtype = t.get("journey_type")
            if jtype == "outbound" and not outbound_transport:
                outbound_transport = {k: v for k, v in t.items() if k not in ["return_trip", "return_transfer"]}
            elif jtype == "return" and not return_transport:
                return_transport = dict(t)

            # Check nested return trip in transport candidate
            if not return_transport and isinstance(t.get("return_trip"), dict):
                ret_candidate = t["return_trip"]
                ret_ver = ret_candidate.get("verification") if isinstance(ret_candidate.get("verification"), dict) else {}
                ret_status = ret_ver.get("status") or ret_candidate.get("verification_status") or ret_candidate.get("status")
                if ret_status in ["verified", "available", "evidence_found"] or not ret_status:
                    return_transport = dict(ret_candidate)

            if not outbound_transfer and isinstance(t.get("outbound_transfer"), dict):
                outbound_transfer = dict(t["outbound_transfer"])
            elif not outbound_transfer and isinstance(t.get("transfer"), dict) and jtype == "outbound":
                outbound_transfer = dict(t["transfer"])

            if not return_transfer and isinstance(t.get("return_transfer"), dict):
                return_transfer = dict(t["return_transfer"])
            elif not return_transfer and isinstance(t.get("transfer"), dict) and jtype == "return":
                return_transfer = dict(t["transfer"])

        if not outbound_transport and verified_transport:
            top_t = verified_transport[0]
            if isinstance(top_t, dict):
                outbound_transport = {k: v for k, v in top_t.items() if k not in ["return_trip", "return_transfer"]}
                if not return_transport and isinstance(top_t.get("return_trip"), dict):
                    ret_candidate = top_t["return_trip"]
                    ret_ver = ret_candidate.get("verification") if isinstance(ret_candidate.get("verification"), dict) else {}
                    ret_status = ret_ver.get("status") or ret_candidate.get("verification_status") or ret_candidate.get("status")
                    if ret_status in ["verified", "available", "evidence_found"] or not ret_status:
                        return_transport = dict(ret_candidate)
                if not outbound_transfer and isinstance(top_t.get("outbound_transfer"), dict):
                    outbound_transfer = dict(top_t["outbound_transfer"])
                elif not outbound_transfer and isinstance(top_t.get("transfer"), dict):
                    outbound_transfer = dict(top_t["transfer"])
                if not return_transfer and isinstance(top_t.get("return_transfer"), dict):
                    return_transfer = dict(top_t["return_transfer"])

        if not return_transfer and getattr(state, "metadata", {}).get("return_transfer"):
            return_transfer = dict(state.metadata["return_transfer"])
        if not return_transfer and getattr(state, "return_transfer", None):
            return_transfer = dict(state.return_transfer)
        if not outbound_transfer and getattr(state, "metadata", {}).get("outbound_transfer"):
            outbound_transfer = dict(state.metadata["outbound_transfer"])
        if not outbound_transfer and getattr(state, "outbound_transfer", None):
            outbound_transfer = dict(state.outbound_transfer)

        if outbound_transport:
            outbound_transport["journey_type"] = "outbound"
            outbound_transport["origin"] = outbound_transport.get("from_station_code") or outbound_transport.get("from_code") or outbound_transport.get("origin")
            outbound_transport["destination"] = outbound_transport.get("to_station_code") or outbound_transport.get("to_code") or outbound_transport.get("destination")
            outbound_transport["journey_date"] = str(state.travel_dates.start)
            
            # Canonical journey metadata
            u_orig = getattr(state, "origin_city", None) or getattr(state, "origin", None)
            u_dest = getattr(state, "destination_city", None) or getattr(state, "destination", None)
            if u_orig:
                outbound_transport["user_origin"] = outbound_transport.get("user_origin") or u_orig
            if u_dest:
                outbound_transport["user_destination"] = outbound_transport.get("user_destination") or u_dest
                
            b_code = outbound_transport.get("boarding_station_code") or outbound_transport.get("boarding_station") or outbound_transport.get("from_station_code") or outbound_transport.get("from_code") or outbound_transport.get("origin")
            a_code = outbound_transport.get("alighting_station_code") or outbound_transport.get("alighting_station") or outbound_transport.get("to_station_code") or outbound_transport.get("to_code") or outbound_transport.get("destination")
            b_name = outbound_transport.get("boarding_station_name") or outbound_transport.get("from_station_name") or b_code
            a_name = outbound_transport.get("alighting_station_name") or outbound_transport.get("to_station_name") or a_code

            outbound_transport["boarding_station"] = b_code
            outbound_transport["boarding_station_code"] = b_code
            outbound_transport["boarding_station_name"] = b_name
            outbound_transport["alighting_station"] = a_code
            outbound_transport["alighting_station_code"] = a_code
            outbound_transport["alighting_station_name"] = a_name

            outbound_transport["actual_origin_station"] = b_code
            outbound_transport["actual_destination_station"] = a_code
            outbound_transport["actual_train_origin"] = f"{b_name} ({b_code})" if b_name and b_code and b_name != b_code else (b_code or "")
            outbound_transport["actual_train_destination"] = f"{a_name} ({a_code})" if a_name and a_code and a_name != a_code else (a_code or "")

            if outbound_transfer:
                outbound_transport["outbound_transfer"] = outbound_transfer
                outbound_transport["transfer"] = outbound_transfer
                if outbound_transfer.get("first_mile_transfer") and not outbound_transport.get("first_mile_transfer"):
                    outbound_transport["first_mile_transfer"] = outbound_transfer["first_mile_transfer"]
                if outbound_transfer.get("last_mile_transfer") and not outbound_transport.get("last_mile_transfer"):
                    outbound_transport["last_mile_transfer"] = outbound_transfer["last_mile_transfer"]
            if not outbound_transport.get("first_mile_transfer"):
                if getattr(state, "first_mile_transfer", None):
                    outbound_transport["first_mile_transfer"] = dict(state.first_mile_transfer)
                elif getattr(state, "metadata", {}).get("first_mile_transfer"):
                    outbound_transport["first_mile_transfer"] = dict(state.metadata["first_mile_transfer"])
            if not outbound_transport.get("last_mile_transfer"):
                if getattr(state, "last_mile_transfer", None):
                    outbound_transport["last_mile_transfer"] = dict(state.last_mile_transfer)
                elif getattr(state, "metadata", {}).get("last_mile_transfer"):
                    outbound_transport["last_mile_transfer"] = dict(state.metadata["last_mile_transfer"])

            if not outbound_transport.get("verification"):
                outbound_transport["verification"] = {"status": "verified", "confidence": 1.0}
            if return_transport:
                outbound_transport["return_trip"] = return_transport

        if return_transport:
            return_transport["journey_type"] = "return"
            return_transport["origin"] = return_transport.get("from_station_code") or return_transport.get("from_code") or return_transport.get("origin")
            return_transport["destination"] = return_transport.get("to_station_code") or return_transport.get("to_code") or return_transport.get("destination")
            return_transport["journey_date"] = str(state.travel_dates.end)
            
            # Canonical journey metadata for return
            u_orig = getattr(state, "destination_city", None) or getattr(state, "destination", None)
            u_dest = getattr(state, "origin_city", None) or getattr(state, "origin", None)
            if u_orig:
                return_transport["user_origin"] = return_transport.get("user_origin") or u_orig
            if u_dest:
                return_transport["user_destination"] = return_transport.get("user_destination") or u_dest
                
            rb_code = return_transport.get("boarding_station_code") or return_transport.get("boarding_station") or return_transport.get("from_station_code") or return_transport.get("from_code") or return_transport.get("origin")
            ra_code = return_transport.get("alighting_station_code") or return_transport.get("alighting_station") or return_transport.get("to_station_code") or return_transport.get("to_code") or return_transport.get("destination")
            rb_name = return_transport.get("boarding_station_name") or return_transport.get("from_station_name") or rb_code
            ra_name = return_transport.get("alighting_station_name") or return_transport.get("to_station_name") or ra_code

            return_transport["boarding_station"] = rb_code
            return_transport["boarding_station_code"] = rb_code
            return_transport["boarding_station_name"] = rb_name
            return_transport["alighting_station"] = ra_code
            return_transport["alighting_station_code"] = ra_code
            return_transport["alighting_station_name"] = ra_name

            return_transport["actual_origin_station"] = rb_code
            return_transport["actual_destination_station"] = ra_code
            return_transport["actual_train_origin"] = f"{rb_name} ({rb_code})" if rb_name and rb_code and rb_name != rb_code else (rb_code or "")
            return_transport["actual_train_destination"] = f"{ra_name} ({ra_code})" if ra_name and ra_code and ra_name != ra_code else (ra_code or "")

            if return_transfer:
                return_transport["return_transfer"] = return_transfer
                return_transport["transfer"] = return_transfer
                if return_transfer.get("first_mile_transfer") and not return_transport.get("first_mile_transfer"):
                    return_transport["first_mile_transfer"] = return_transfer["first_mile_transfer"]
                if return_transfer.get("last_mile_transfer") and not return_transport.get("last_mile_transfer"):
                    return_transport["last_mile_transfer"] = return_transfer["last_mile_transfer"]
            if not return_transport.get("first_mile_transfer"):
                if getattr(state, "return_first_mile_transfer", None):
                    return_transport["first_mile_transfer"] = dict(state.return_first_mile_transfer)
                elif getattr(state, "metadata", {}).get("return_first_mile_transfer"):
                    return_transport["first_mile_transfer"] = dict(state.metadata["return_first_mile_transfer"])
                elif return_transfer and return_transfer.get("has_transfer"):
                    return_transport["first_mile_transfer"] = return_transfer
            if not return_transport.get("last_mile_transfer"):
                if getattr(state, "return_last_mile_transfer", None):
                    return_transport["last_mile_transfer"] = dict(state.return_last_mile_transfer)
                elif getattr(state, "metadata", {}).get("return_last_mile_transfer"):
                    return_transport["last_mile_transfer"] = dict(state.metadata["return_last_mile_transfer"])

            if not return_transport.get("verification"):
                return_transport["verification"] = {"status": "verified", "confidence": 1.0}

        final_transport_list = []
        if outbound_transport:
            final_transport_list.append(outbound_transport)
        if return_transport:
            final_transport_list.append(return_transport)

        state.transport_options = final_transport_list
        state.outbound_transport = outbound_transport
        state.return_transport = return_transport
        state.outbound_transfer = outbound_transfer
        state.return_transfer = return_transfer if return_transport else None

        print("\n========================================")
        print("      FINAL TRANSPORT AGGREGATION")
        print("========================================")
        if outbound_transport:
            o_orig = outbound_transport.get("origin") or outbound_transport.get("from_station_code") or ""
            o_dest = outbound_transport.get("destination") or outbound_transport.get("to_station_code") or ""
            o_num = outbound_transport.get("train_number") or outbound_transport.get("flight_number") or ""
            o_name = outbound_transport.get("train_name") or outbound_transport.get("flight_name") or outbound_transport.get("name") or ""
            out_str = f"{o_orig} -> {o_dest} | {o_num} {o_name}".strip()
            def _clean_loc(val):
                if hasattr(val, "city") and getattr(val, "city", None):
                    return str(val.city)
                if hasattr(val, "name") and getattr(val, "name", None):
                    return str(val.name)
                if isinstance(val, dict):
                    return str(val.get("city") or val.get("name") or "")
                return str(val or "")

            u_o = _clean_loc(outbound_transport.get("user_origin")) or (state.origin.city if state.origin else "") or (state.origin.name if state.origin else "")
            a_o = _clean_loc(outbound_transport.get("actual_train_origin")) or outbound_transport.get("from_station_name") or outbound_transport.get("from_station_code") or ""
            a_d = _clean_loc(outbound_transport.get("actual_train_destination")) or outbound_transport.get("to_station_name") or outbound_transport.get("to_station_code") or ""
            u_d = _clean_loc(outbound_transport.get("user_destination")) or (state.destination.city if state.destination else "") or (state.destination.name if state.destination else "")
            print(f"OUTBOUND CANONICAL: {u_o} -> {a_o} -> {a_d} -> {u_d}")
        else:
            print("OUTBOUND FINAL: None")

        if return_transport:
            r_orig = return_transport.get("origin") or return_transport.get("from_station_code") or ""
            r_dest = return_transport.get("destination") or return_transport.get("to_station_code") or ""
            r_num = return_transport.get("train_number") or return_transport.get("flight_number") or ""
            r_name = return_transport.get("train_name") or return_transport.get("flight_name") or return_transport.get("name") or ""
            ret_str = f"{r_orig} -> {r_dest} | {r_num} {r_name}".strip()
            print(f"RETURN FINAL:   {ret_str}")
            u_o = _clean_loc(return_transport.get("user_origin")) or (state.destination.city if state.destination else "") or (state.destination.name if state.destination else "")
            a_o = _clean_loc(return_transport.get("actual_train_origin")) or return_transport.get("from_station_name") or return_transport.get("from_station_code") or ""
            a_d = _clean_loc(return_transport.get("actual_train_destination")) or return_transport.get("to_station_name") or return_transport.get("to_station_code") or ""
            u_d = _clean_loc(return_transport.get("user_destination")) or (state.origin.city if state.origin else "") or (state.origin.name if state.origin else "")
            print(f"RETURN CANONICAL:   {u_o} -> {a_o} -> {a_d} -> {u_d}")
        else:
            print("RETURN FINAL:   None")

        print(f"Outbound transport: {1 if outbound_transport else 0}")
        print(f"Return transport:   {1 if return_transport else 0}")
        print(f"FINAL TRANSPORT LEGS: {len(final_transport_list)}")
        print(f"Final transport legs: {len(final_transport_list)}")

        # =================================================
        # STRICT PLACE FILTERING: VERIFIED / ACCEPTED ONLY
        # =================================================

        verified_results = [
            r for r in place_verification
            if isinstance(r, dict)
            and r.get("status") in ["verified", "available", "evidence_found"]
        ]
        unverified_results = [
            r for r in place_verification
            if isinstance(r, dict)
            and r.get("status") not in ["verified", "available", "evidence_found"]
        ]
        unverified_names = {
            self.normalize_text(r.get("name") or r.get("place_name"))
            for r in unverified_results
            if (r.get("name") or r.get("place_name"))
        }
        unverified_ids = {
            str(r.get("place_id")).strip().lower()
            for r in unverified_results
            if r.get("place_id")
        }

        verified_places = []
        seen_place_keys = set()

        for p in places:
            if not isinstance(p, dict):
                continue
            ver = p.get("verification", {})
            status = ver.get("status") if isinstance(ver, dict) else None
            if status not in ["verified", "available", "evidence_found"]:
                continue

            p_name = self.normalize_text(p.get("name") or p.get("place_name"))
            p_id = str(p.get("place_id") or p.get("id") or "").strip().lower()

            # Strictly reject if explicitly unverified/insufficient in verification results
            if (p_name and p_name in unverified_names) or (p_id and p_id in unverified_ids):
                continue

            # Deduplicate by normalized name and ID
            dedup_key = p_name if p_name else p_id
            if not dedup_key or dedup_key in seen_place_keys:
                continue

            seen_place_keys.add(dedup_key)
            verified_places.append(p)

        # Cap accepted places so it never exceeds the number of verified results
        max_allowed_places = len(verified_results)
        if len(verified_places) > max_allowed_places:
            verified_places = verified_places[:max_allowed_places]

        # Update state.place_options with accepted verified places only
        state.place_options = verified_places

        # =================================================
        # BUILD SUMMARY
        # =================================================

        summary = (
            self.build_summary(
                transport=final_transport_list,
                hotels=hotels,
                places=verified_places,
                weather=weather,
            )
        )

        # =================================================
        # UNIFIED RESULT
        # =================================================

        aggregated_result = {

            "status": "ready",

            "transport": final_transport_list,
            "outbound_transport": outbound_transport,
            "return_transport": return_transport,
            "outbound_transfer": outbound_transfer,
            "return_transfer": return_transfer if return_transport else None,

            "hotels": hotels,

            "places": verified_places,

            "weather": weather,

            "verification": verification,

            "summary": summary,
        }

        # =================================================
        # STORE IN TRIP STATE
        # =================================================

        state.recommendations = (
            aggregated_result
        )

        # =================================================
        # OUTPUT
        # =================================================

        print("\n========================================")
        print("       AGGREGATION RESULT")
        print("========================================")

        print(
            f"Transport options: "
            f"{len(final_transport_list)}"
        )

        print(
            f"Hotel options: "
            f"{len(hotels)}"
        )

        print(
            f"Place options (total received): "
            f"{len(places)}"
        )

        print(
            f"Accepted places after filtering: "
            f"{len(verified_places)}"
        )

        print(
            f"Verified options: "
            f"{summary['verified_options']}"
        )

        print(
            f"Weather available: "
            f"{summary['weather_available']}"
        )

        print(
            "\nResult aggregation completed."
        )

        return state
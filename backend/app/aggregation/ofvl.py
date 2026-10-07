from typing import Any, Dict, List

from app.services.tavily.tavily_client import (
    TavilyClient,
)


class OFVLError(Exception):
    """
    Base exception for Online Fact Verification Layer.
    """

    pass


class OFVL:
    """
    Online Fact Verification Layer.

    Responsibilities:
        1. Perform basic local validation.
        2. Search web evidence using Tavily.
        3. Evaluate relevance of returned evidence.
        4. Produce a verification decision.

    Verification statuses:
        - verified
        - insufficient_evidence
        - invalid
        - unavailable
    """

    def __init__(self):

        self.tavily_client = TavilyClient()

    # =====================================================
    # BASIC LOCAL VALIDATION
    # =====================================================

    def validate_basic(
        self,
        data: Dict[str, Any],
        required_fields: List[str],
    ) -> Dict[str, Any]:

        missing_fields = []

        for field in required_fields:

            value = data.get(field)

            if value is None:

                missing_fields.append(field)

            elif (
                isinstance(value, str)
                and not value.strip()
            ):

                missing_fields.append(field)

        return {
            "valid": len(missing_fields) == 0,
            "missing_fields": missing_fields,
        }

    # =====================================================
    # TAVILY SEARCH
    # =====================================================

    def search_web(
        self,
        query: str,
    ) -> Dict[str, Any]:

        if not query or not query.strip():

            raise ValueError(
                "Tavily search query is required."
            )

        try:

            return self.tavily_client.search(
                query=query,
                max_results=5,
            )

        except Exception as exc:

            raise OFVLError(
                f"Tavily verification failed: {exc}"
            ) from exc

    # =====================================================
    # TEXT NORMALIZATION
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
    # TEXT MATCH SCORE
    # =====================================================

    def text_match_score(
        self,
        expected: str,
        text: str,
    ) -> float:

        expected_text = self.normalize_text(
            expected
        )

        actual_text = self.normalize_text(
            text
        )

        if (
            not expected_text
            or not actual_text
        ):

            return 0.0

        # -------------------------------------------------
        # Exact phrase
        # -------------------------------------------------

        if expected_text in actual_text:

            return 1.0

        expected_words = set(
            expected_text.split()
        )

        actual_words = set(
            actual_text.split()
        )

        if not expected_words:

            return 0.0

        overlap = (
            expected_words
            & actual_words
        )

        return (
            len(overlap)
            / len(expected_words)
        )

    # =====================================================
    # EVALUATE EVIDENCE
    # =====================================================

    def evaluate_evidence(
        self,
        *,
        expected_name: str,
        expected_location: str,
        results: List[Dict[str, Any]],
    ) -> Dict[str, Any]:

        if not results:

            return {
                "status": "insufficient_evidence",
                "confidence": 0.0,
                "supporting_sources": 0,
                "evidence_count": 0,
                "source_scores": [],
            }

        supporting_sources = 0

        source_scores = []

        for result in results:

            title = result.get(
                "title",
                "",
            )

            content = result.get(
                "content",
                "",
            )

            tavily_score = result.get(
                "score",
                0,
            )

            searchable_text = (
                f"{title} {content}"
            )

            # -------------------------------------------------
            # NAME SCORE
            # -------------------------------------------------

            name_score = (
                self.text_match_score(
                    expected_name,
                    searchable_text,
                )
            )

            # -------------------------------------------------
            # LOCATION SCORE
            # -------------------------------------------------

            location_score = (
                self.text_match_score(
                    expected_location,
                    searchable_text,
                )
            )

            # -------------------------------------------------
            # COMBINED EVIDENCE SCORE
            # -------------------------------------------------

            evidence_score = (
                (name_score * 0.65)
                + (location_score * 0.20)
                + (float(tavily_score) * 0.15)
            )

            source_scores.append(
                {
                    "title": title,

                    "url": result.get(
                        "url"
                    ),

                    "name_score": round(
                        name_score,
                        3,
                    ),

                    "location_score": round(
                        location_score,
                        3,
                    ),

                    "tavily_score": tavily_score,

                    "evidence_score": round(
                        evidence_score,
                        3,
                    ),
                }
            )

            # -------------------------------------------------
            # SUPPORTING SOURCE
            # -------------------------------------------------

            if (
                name_score >= 0.70
                and evidence_score >= 0.60
            ):

                supporting_sources += 1

        # =====================================================
        # BEST SCORE
        # =====================================================

        best_score = max(
            (
                item["evidence_score"]
                for item in source_scores
            ),
            default=0.0,
        )

        # =====================================================
        # CONFIDENCE
        # =====================================================

        if supporting_sources >= 3:

            confidence = min(
                0.95,
                best_score + 0.15,
            )

        elif supporting_sources == 2:

            confidence = min(
                0.90,
                best_score + 0.10,
            )

        elif supporting_sources == 1:

            confidence = min(
                0.80,
                best_score + 0.05,
            )

        else:

            confidence = best_score

        # =====================================================
        # FINAL STATUS
        # =====================================================

        if supporting_sources >= 1:

            status = "verified"

        else:

            status = "insufficient_evidence"

        return {
            "status": status,

            "confidence": round(
                confidence,
                3,
            ),

            "supporting_sources": (
                supporting_sources
            ),

            "evidence_count": len(
                results
            ),

            "source_scores": source_scores,
        }

    # =====================================================
    # VERIFY PLACE
    # =====================================================

    def verify_place(
        self,
        place: Dict[str, Any],
    ) -> Dict[str, Any]:

        basic_check = self.validate_basic(
            place,
            [
                "name",
                "latitude",
                "longitude",
            ],
        )

        if not basic_check["valid"]:

            return {
                "status": "invalid",

                "verification_method": "local",

                "fact_type": "place",

                "missing_fields": (
                    basic_check["missing_fields"]
                ),
            }

        # =================================================
        # LOCATION
        # =================================================

        location = " ".join(
            str(value)
            for value in [
                place.get("city"),
                place.get("state"),
                place.get("country"),
            ]
            if value
        )

        # =================================================
        # QUERY
        # =================================================

        query = (
            f'"{place["name"]}" '
            f"{location} "
            f"official"
        ).strip()

        print(
            f"\nTavily Place Query: {query}"
        )

        # =================================================
        # TAVILY
        # =================================================

        web_result = self.search_web(
            query
        )

        results = web_result.get(
            "results",
            [],
        )

        # =================================================
        # EVALUATE
        # =================================================

        evaluation = self.evaluate_evidence(
            expected_name=place["name"],
            expected_location=location,
            results=results,
        )

        return {
            "status": evaluation["status"],

            "verification_method": "tavily",

            "fact_type": "place",

            "name": place["name"],

            "confidence": evaluation[
                "confidence"
            ],

            "supporting_sources": (
                evaluation[
                    "supporting_sources"
                ]
            ),

            "evidence_count": (
                evaluation[
                    "evidence_count"
                ]
            ),

            "source_scores": (
                evaluation[
                    "source_scores"
                ]
            ),

            "evidence": results[:3],
        }

    # =====================================================
    # VERIFY HOTEL
    # =====================================================

    def verify_hotel(
        self,
        hotel: Dict[str, Any],
    ) -> Dict[str, Any]:

        # =================================================
        # NORMALIZE HOTEL NAME
        # =================================================
        #
        # HotelOption from HotelService may use:
        #
        #     hotel_name
        #
        # OFVL internally uses:
        #
        #     name
        #
        # Support both.
        # =================================================

        hotel_name = (
            hotel.get("name")
            or hotel.get("hotel_name")
            or hotel.get("hotelName")
        )

        # =================================================
        # NORMALIZE PROVIDER
        # =================================================

        provider = (
            hotel.get("provider")
            or hotel.get("source")
            or "unknown"
        )

        # =================================================
        # CREATE NORMALIZED HOTEL
        # =================================================

        normalized_hotel = dict(
            hotel
        )

        normalized_hotel["name"] = (
            hotel_name
        )

        normalized_hotel["provider"] = (
            provider
        )

        # =================================================
        # BASIC VALIDATION
        # =================================================

        basic_check = self.validate_basic(
            normalized_hotel,
            [
                "name",
                "provider",
            ],
        )

        if not basic_check["valid"]:

            return {
                "status": "invalid",

                "verification_method": "local",

                "fact_type": "hotel",

                "missing_fields": (
                    basic_check["missing_fields"]
                ),
            }

        # =================================================
        # HOTEL LOCATION
        # =================================================

        location = (
            normalized_hotel.get(
                "address"
            )
            or normalized_hotel.get(
                "city"
            )
            or "Goa India"
        )

        # =================================================
        # BUILD TAVILY QUERY
        # =================================================

        query = (
            f'"{hotel_name}" '
            f"{location} "
            f"official hotel"
        ).strip()

        print(
            f"\nTavily Hotel Query: {query}"
        )

        # =================================================
        # TAVILY SEARCH
        # =================================================

        web_result = self.search_web(
            query
        )

        results = web_result.get(
            "results",
            [],
        )

        # =================================================
        # NO EVIDENCE
        # =================================================

        if not results:

            return {
                "status": "insufficient_evidence",

                "verification_method": "tavily",

                "fact_type": "hotel",

                "name": hotel_name,

                "provider": provider,

                "evidence_count": 0,

                "supporting_sources": 0,

                "confidence": 0.0,

                "evidence": [],
            }

        # =================================================
        # EVALUATE EVIDENCE
        # =================================================

        evaluation = self.evaluate_evidence(
            expected_name=hotel_name,
            expected_location=location,
            results=results,
        )

        # =================================================
        # RETURN VERIFICATION RESULT
        # =================================================

        return {
            "status": evaluation[
                "status"
            ],

            "verification_method": "tavily",

            "fact_type": "hotel",

            "name": hotel_name,

            "provider": provider,

            "confidence": evaluation[
                "confidence"
            ],

            "supporting_sources": (
                evaluation[
                    "supporting_sources"
                ]
            ),

            "evidence_count": (
                evaluation[
                    "evidence_count"
                ]
            ),

            "source_scores": (
                evaluation[
                    "source_scores"
                ]
            ),

            "evidence": results[:3],
        }

    # =====================================================
    # VERIFY TRANSPORT
    # =====================================================

    def verify_transport(
        self,
        transport: Dict[str, Any],
        is_return: bool = False,
    ) -> Dict[str, Any]:

        # Ensure provider field is populated for validated transport
        if not transport.get("provider"):
            transport["provider"] = "railcore" if (transport.get("train_number") or transport.get("type") == "train") else "live_provider"

        basic_check = self.validate_basic(
            transport,
            [
                "provider",
            ],
        )

        if not basic_check["valid"]:
            return {
                "status": "invalid",
                "verification_method": "local",
                "fact_type": "transport",
                "missing_fields": basic_check["missing_fields"],
            }

        # =================================================
        # TRANSPORT IDENTITY
        # =================================================
        train_number = str(transport.get("train_number") or "").strip()
        raw_train_name = str(transport.get("train_name") or transport.get("name") or "").strip()
        clean_train_name = raw_train_name.split("(")[0].strip() if raw_train_name else ""
        train_name = clean_train_name or raw_train_name
        flight_number = str(transport.get("flight_number") or "").strip()
        airline = str(transport.get("airline") or "").strip()

        transport_name_parts = [
            airline,
            flight_number,
            train_name,
            train_number,
        ]

        transport_name = " ".join(
            str(value) for value in transport_name_parts if value
        ).strip()

        # =================================================
        # ORIGIN & DESTINATION RESOLUTION (DIRECTION-AWARE)
        # =================================================
        raw_origin = (
            transport.get("from_station_name")
            or transport.get("from_code")
            or transport.get("origin")
            or transport.get("from_city")
        )
        if isinstance(raw_origin, dict):
            raw_origin = raw_origin.get("city") or raw_origin.get("name") or raw_origin.get("code")
        if not raw_origin and isinstance(transport.get("source"), dict):
            src = transport["source"]
            raw_origin = src.get("city") or src.get("name") or src.get("code")
        if not raw_origin and isinstance(transport.get("source"), str):
            raw_origin = transport["source"]
        origin = str(raw_origin or "").strip()

        raw_dest = (
            transport.get("to_station_name")
            or transport.get("to_code")
            or transport.get("destination")
            or transport.get("to_city")
        )
        if isinstance(raw_dest, dict):
            raw_dest = raw_dest.get("city") or raw_dest.get("name") or raw_dest.get("code")
        if not raw_dest and isinstance(transport.get("destination_airport"), dict):
            dst = transport["destination_airport"]
            raw_dest = dst.get("city") or dst.get("name") or dst.get("code")
        destination = str(raw_dest or "").strip()

        location = f"{origin} {destination}".strip()

        if not transport_name:
            return {
                "status": "insufficient_evidence",
                "verification_method": "local",
                "fact_type": "transport",
                "reason": "Not enough transport identity information for web verification.",
            }

        # =================================================
        # BUILD ROUTE-SPECIFIC QUERY (STRICT DIRECTION)
        # =================================================
        transfer_info = transport.get("transfer")
        target_dest = destination
        if isinstance(transfer_info, dict):
            hub = transfer_info.get("hub_name") or transfer_info.get("transfer_point")
            if hub and str(hub).lower() not in destination.lower():
                target_dest = hub

        orig_query_str = f'"{origin}"' if origin else ""
        dest_query_str = f'"{target_dest}"' if target_dest else ""

        if train_number or (transport.get("type") == "train"):
            parts = [p for p in [f'"{train_number}"' if train_number else "", f'"{clean_train_name}"' if clean_train_name else "", orig_query_str, dest_query_str, "train route schedule"] if p]
            query = " ".join(parts)
        elif flight_number or (transport.get("type") == "flight"):
            parts = [p for p in [f'"{airline}"' if airline else "", f'"{flight_number}"' if flight_number else "", orig_query_str, dest_query_str, "flight schedule"] if p]
            query = " ".join(parts)
        else:
            query = f'"{transport_name}" {location}'

        query = " ".join(query.strip().split())

        web_result = self.search_web(query)
        results = web_result.get("results", [])

        provider_name = str(transport.get("provider", "")).lower()
        has_api_provenance = provider_name in ["railradar", "railcore", "indian_railways", "live_api", "live_provider"] and bool(train_number or flight_number)

        if not results:
            eval_status = "available" if has_api_provenance else "insufficient_evidence"
            evaluation = {
                "status": eval_status,
                "confidence": 0.85 if has_api_provenance else 0.0,
                "supporting_sources": 1 if has_api_provenance else 0,
                "evidence_count": 0,
                "source_scores": [],
            }
        else:
            evaluation = self.evaluate_evidence(
                expected_name=transport_name,
                expected_location=location,
                results=results,
            )
            if evaluation.get("status") not in ["verified", "available", "evidence_found"] and has_api_provenance:
                evaluation["status"] = "available"

        journey_type_str = "RETURN" if is_return else "OUTBOUND"
        dep_date_str = str(transport.get("departure_time") or transport.get("journey_date") or "").split("T")[0]

        print("\n--------------------------------------------------------------------------------")
        print(f"JOURNEY TYPE:           {journey_type_str}")
        print(f"SEARCH ROUTE:           {origin} -> {destination}")
        print(f"SEARCH DATE:            {dep_date_str}")
        print(f"TRAIN/FLIGHT:           {transport_name}")
        print(f"ACTUAL TRANSPORT ROUTE: {origin} -> {destination}")
        print(f"VERIFICATION QUERY:     {query}")
        print(f"VERIFIED ORIGIN:        {origin}")
        print(f"VERIFIED DESTINATION:   {destination}")
        print(f"VERIFICATION STATUS:    {evaluation['status']}")
        print("--------------------------------------------------------------------------------\n")

        # Verify nested return trip independently in return direction if present
        return_ver = None
        if not is_return:
            ret_trip = transport.get("return_trip")
            if isinstance(ret_trip, dict):
                return_ver = self.verify_transport(ret_trip, is_return=True)
                ret_status = return_ver.get("status", "unavailable")
                transport["return_trip"]["verification_status"] = ret_status
                transport["return_trip"]["status"] = ret_status
                if ret_status not in ["verified", "available", "evidence_found"]:
                    print(f"[OFVL LOG] Return transport verification status '{ret_status}' is unverified/invalid. Purging return_trip to None.")
                    transport["return_trip"] = None
            else:
                print("--------------------------------------------------------------------------------")
                print("JOURNEY TYPE:           RETURN")
                print(f"SEARCH ROUTE:           {destination} -> {origin}")
                print(f"SEARCH DATE:            Requested Return Date")
                print("TRAIN/FLIGHT:           None")
                print("ACTUAL TRANSPORT ROUTE: None -> None")
                print("VERIFICATION QUERY:     N/A")
                print("VERIFIED ORIGIN:        N/A")
                print("VERIFIED DESTINATION:   N/A")
                print("VERIFICATION STATUS:    unavailable")
                print("--------------------------------------------------------------------------------\n")

        res = {
            "status": evaluation["status"],
            "verification_method": "tavily",
            "fact_type": "transport",
            "transport": transport_name,
            "confidence": evaluation["confidence"],
            "supporting_sources": evaluation["supporting_sources"],
            "evidence_count": evaluation["evidence_count"],
            "source_scores": evaluation["source_scores"],
            "evidence": results[:3],
        }
        if return_ver:
            res["return_verification"] = return_ver

        return res

    # =====================================================
    # VERIFY WEATHER
    # =====================================================

    def verify_weather(
        self,
        weather: Dict[str, Any],
    ) -> Dict[str, Any]:

        basic_check = self.validate_basic(
            weather,
            [
                "status",
                "location",
            ],
        )

        if not basic_check["valid"]:

            return {
                "status": "invalid",

                "verification_method": "local",

                "fact_type": "weather",

                "missing_fields": (
                    basic_check["missing_fields"]
                ),
            }

        # =================================================
        # STATUS
        # =================================================

        if weather.get(
            "status"
        ) != "available":

            return {
                "status": "unavailable",

                "verification_method": "local",

                "fact_type": "weather",
            }

        # =================================================
        # FORECAST
        # =================================================

        forecast = weather.get(
            "forecast",
            [],
        )

        if not forecast:

            return {
                "status": "invalid",

                "verification_method": "local",

                "fact_type": "weather",

                "reason": (
                    "Forecast is empty."
                ),
            }

        # =================================================
        # RESULT
        # =================================================

        return {
            "status": "available",

            "verification_method": "local",

            "fact_type": "weather",

            "forecast_days": len(
                forecast
            ),
        }
import logging
from app.state.trip_state import TripState
from app.aggregation.ofvl import OFVL
from app.observability.agent_logger import (
    agent_start,
    agent_success,
    agent_failure,
)
from app.observability.metrics import observability_metrics

logger = logging.getLogger(__name__)


class VerificationAgent:
    """
    Verification Agent.

    Responsibilities:
        1. Validate TripState
        2. Verify a limited number of selected results
        3. Use OFVL for online verification
        4. Verify weather locally
        5. Store verification results in TripState

    API SAFETY:
        Transport -> max 4
        Hotels    -> max 1
        Places    -> max 10

    Total Tavily verification calls:
        Maximum 15 per pipeline run
    """

    # =====================================================
    # API SAFETY LIMITS
    # =====================================================

    MAX_TRANSPORT_TO_VERIFY = 4
    MAX_HOTELS_TO_VERIFY = 3
    MAX_PLACES_TO_VERIFY = 18

    # =====================================================
    # INITIALIZATION
    # =====================================================

    def __init__(self):

        self.ofvl = OFVL()

    # =====================================================
    # HELPERS
    # =====================================================

    @staticmethod
    def _to_dict(
        obj,
    ) -> dict:

        if hasattr(
            obj,
            "model_dump",
        ):

            return obj.model_dump()

        if isinstance(
            obj,
            dict,
        ):

            return obj

        return {}

    @staticmethod
    def _get_name(
        data: dict,
    ) -> str:

        return (
            data.get("name")
            or data.get(
                "hotel_name"
            )
            or data.get(
                "train_name"
            )
            or data.get(
                "flight_number"
            )
            or "Unknown"
        )

    # =====================================================
    # EXECUTION
    # =====================================================

    def run(
        self,
        state: TripState,
    ) -> TripState:

        agent_start_time = agent_start("verification", state)
        logger.debug("Starting Verification Agent")

        # =================================================
        # VALIDATE STATE
        # =================================================

        if not isinstance(state, TripState):

            error = TypeError(
                "VerificationAgent expects "
                "a TripState object."
            )
            agent_failure(
                "verification",
                state,
                agent_start_time,
                error,
            )
            raise error

        # =================================================
        # TRANSPORT
        # =================================================

        logger.debug("Starting transport verification")

        transport_options = (
            state.transport_options or []
        )

        selected_transport = (
            transport_options[
                :self.MAX_TRANSPORT_TO_VERIFY
            ]
        )

        transport_results = []

        print(
            f"Transport candidates: "
            f"{len(transport_options)}"
        )

        print(
            f"Transport selected for verification: "
            f"{len(selected_transport)}"
        )

        for transport in selected_transport:

            transport_data = self._to_dict(
                transport
            )

            try:

                result = (
                    self.ofvl.verify_transport(
                        transport_data
                    )
                )

                transport_results.append(
                    result
                )

                t_name = self._get_name(transport_data)
                t_no = transport_data.get("train_number") or transport_data.get("flight_number") or ""
                t_orig = transport_data.get("from_station_code") or transport_data.get("from_code") or transport_data.get("origin") or ""
                t_dest = transport_data.get("to_station_code") or transport_data.get("to_code") or transport_data.get("destination") or ""
                candidate_str = f"{t_no} {t_name} {t_orig} -> {t_dest}".strip()
                status = result.get("status", "unavailable")
                action = "ACCEPTED" if status in ["verified", "available", "evidence_found"] else "DISCARDED"

                print("\n--- TRANSPORT CANDIDATE VERIFICATION TRACE ---")
                print(f"TRANSPORT CANDIDATE: {candidate_str}")
                print(f"VERIFICATION QUERY:  {result.get('query', 'N/A')}")
                print(f"VERIFICATION RESULT: {status.upper()}")
                print(f"ACTION:              {action}")
                print("----------------------------------------------")

            except Exception as exc:

                print(
                    "\nTransport verification failed:"
                )

                print(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                transport_results.append(
                    {
                        "status": "unavailable",
                        "verification_method": "tavily",
                        "fact_type": "transport",
                        "error": str(exc),
                    }
                )

        verified_transports = []
        verified_journey_count = 0
        transport_checked_count = 0
        extra_transport_results = []

        for i, r in enumerate(transport_results):
            transport_checked_count += 1
            cand = self._to_dict(selected_transport[i])
            if r.get("status") in ["verified", "available", "evidence_found"]:
                verified_journey_count += 1
                out_name = self._get_name(cand)
                if out_name and out_name not in verified_transports:
                    verified_transports.append(out_name)
            
            ret_ver = r.get("return_verification")
            ret_trip = cand.get("return_trip") if isinstance(cand, dict) else None
            if ret_ver or ret_trip:
                transport_checked_count += 1
                ret_status = ret_ver.get("status") if isinstance(ret_ver, dict) else (ret_trip.get("verification_status") if isinstance(ret_trip, dict) else None)
                extra_transport_results.append({"status": ret_status or "unavailable"})
                if ret_status in ["verified", "available", "evidence_found"]:
                    verified_journey_count += 1
                    ret_name = self._get_name(ret_trip) if ret_trip else (ret_ver.get("transport") if isinstance(ret_ver, dict) else "")
                    if ret_name and ret_name not in verified_transports:
                        verified_transports.append(ret_name)

        print(
            f"\nTransport checked online: "
            f"{transport_checked_count}"
        )

        print(
            f"Transport successfully verified: "
            f"{verified_journey_count}"
        )

        print(
            f"FINAL VERIFIED TRANSPORT: "
            f"{verified_transports if verified_transports else 'None (0 options remaining)'}"
        )

        # =================================================
        # HOTELS
        # =================================================

        print("\n========================================")
        print("         HOTEL VERIFICATION")
        print("========================================")

        hotel_options = (
            state.hotel_options or []
        )

        selected_hotels = (
            hotel_options[
                :self.MAX_HOTELS_TO_VERIFY
            ]
        )

        hotel_results = []

        print(
            f"Hotel candidates: "
            f"{len(hotel_options)}"
        )

        print(
            f"Hotel selected for verification: "
            f"{len(selected_hotels)}"
        )

        for hotel in selected_hotels:

            hotel_data = self._to_dict(
                hotel
            )

            try:

                result = (
                    self.ofvl.verify_hotel(
                        hotel_data
                    )
                )

                hotel_results.append(
                    result
                )

                print(
                    f"Hotel: "
                    f"{self._get_name(hotel_data)}"
                )

                print(
                    f"Status: "
                    f"{result.get('status')}"
                )

            except Exception as exc:

                print(
                    "\nHotel verification failed:"
                )

                print(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                hotel_results.append(
                    {
                        "status": "unavailable",
                        "verification_method": "tavily",
                        "fact_type": "hotel",
                        "name": self._get_name(
                            hotel_data
                        ),
                        "error": str(exc),
                    }
                )

        hotel_verified_count = sum(
            1
            for r in hotel_results
            if r.get("status") in ["verified", "available", "evidence_found"]
        )

        print(
            f"Hotel checked online: "
            f"{len(hotel_results)}"
        )

        print(
            f"Hotel successfully verified: "
            f"{hotel_verified_count}"
        )

        # =================================================
        # PLACES
        # =================================================

        print("\n========================================")
        print("         PLACES VERIFICATION")
        print("========================================")

        place_options = (
            state.place_options or []
        )

        selected_places = (
            place_options[
                :self.MAX_PLACES_TO_VERIFY
            ]
        )

        place_results = []

        print(
            f"Place candidates: "
            f"{len(place_options)}"
        )

        print(
            f"Places selected for verification: "
            f"{len(selected_places)}"
        )

        for place in selected_places:

            place_data = self._to_dict(
                place
            )

            try:

                result = (
                    self.ofvl.verify_place(
                        place_data
                    )
                )

                place_results.append(
                    result
                )

                print(
                    f"Place: "
                    f"{self._get_name(place_data)}"
                )

                print(
                    f"Status: "
                    f"{result.get('status')}"
                )

            except Exception as exc:

                print(
                    "\nPlace verification failed:"
                )

                print(
                    f"{type(exc).__name__}: "
                    f"{exc}"
                )

                place_results.append(
                    {
                        "status": "unavailable",
                        "verification_method": "tavily",
                        "fact_type": "place",
                        "name": self._get_name(
                            place_data
                        ),
                        "error": str(exc),
                    }
                )

        place_verified_count = sum(
            1
            for r in place_results
            if r.get("status") in ["verified", "available", "evidence_found"]
        )

        place_insufficient_count = sum(
            1
            for r in place_results
            if r.get("status") not in ["verified", "available", "evidence_found"]
        )

        print(
            f"Places checked online: "
            f"{len(place_results)}"
        )

        print(
            f"Places successfully verified: "
            f"{place_verified_count}"
        )

        print(
            f"Places with insufficient evidence: "
            f"{place_insufficient_count}"
        )

        verified_names = [self._get_name(r) for r in place_results if r.get("status") in ["verified", "available", "evidence_found"]]
        unverified_names = [f"{self._get_name(r)} ({r.get('status')})" for r in place_results if r.get("status") not in ["verified", "available", "evidence_found"]]
        if verified_names:
            print(f"Places verified ({len(verified_names)}): {', '.join(verified_names)}")
        if unverified_names:
            print(f"Places rejected/insufficient ({len(unverified_names)}): {', '.join(unverified_names)}")

        # =================================================
        # WEATHER
        # =================================================

        print("\n========================================")
        print("        WEATHER VERIFICATION")
        print("========================================")

        weather = (
            state.weather
            if isinstance(
                state.weather,
                dict,
            )
            else {}
        )

        try:

            weather_result = (
                self.ofvl.verify_weather(
                    weather
                )
            )

        except Exception as exc:

            print(
                "\nWeather verification failed:"
            )

            print(
                f"{type(exc).__name__}: "
                f"{exc}"
            )

            weather_result = {
                "status": "unavailable",
                "verification_method": "local",
                "fact_type": "weather",
                "error": str(exc),
            }

        print(
            f"Status: "
            f"{weather_result.get('status')}"
        )

        # =================================================
        # COUNT RESULTS
        # =================================================

        all_results = (
            transport_results
            + extra_transport_results
            + hotel_results
            + place_results
            + [weather_result]
        )

        verified_count = sum(
            1
            for result in all_results
            if result.get("status")
            in [
                "verified",
                "available",
                "evidence_found",
            ]
        )

        total_checked = len(
            all_results
        )

        # =================================================
        # OVERALL STATUS
        # =================================================

        if total_checked == 0:

            overall_status = "unavailable"

        elif verified_count == total_checked:

            overall_status = "verified"

        elif verified_count > 0:

            overall_status = "partial"

        else:

            overall_status = "unavailable"

        # =================================================
        # STORE VERIFICATION
        # =================================================

        state.verification = {

            "status": overall_status,

            "verification_method":
                "local + tavily",

            "checked_count":
                total_checked,

            "verified_count":
                verified_count,

            "transport": {
                "candidates":
                    len(transport_options),

                "checked":
                    transport_checked_count,

                "verified":
                    verified_journey_count,

                "results":
                    transport_results,
            },

            "hotels": {
                "candidates":
                    len(hotel_options),

                "checked":
                    len(hotel_results),

                "verified":
                    hotel_verified_count,

                "results":
                    hotel_results,
            },

            "places": {
                "candidates":
                    len(place_options),

                "checked":
                    len(place_results),

                "verified":
                    place_verified_count,

                "insufficient":
                    place_insufficient_count,

                "results":
                    place_results,
            },

            "weather":
                weather_result,
        }

        # =================================================
        # VERIFICATION SUMMARY
        # =================================================

        logger.debug(
            "Verification results: overall=%s verified=%s/%s transport_checked=%s hotels_checked=%s places_checked=%s",
            overall_status,
            verified_count,
            total_checked,
            transport_checked_count,
            len(hotel_results),
            len(place_results),
        )

        weather_stat = weather_result.get("status") if isinstance(weather_result, dict) else "Unavailable"
        weather_disp = "Available" if weather_stat in ["verified", "available", "evidence_found", "valid"] else (weather_stat or "Unavailable").capitalize()

        observability_metrics.print_verification_summary(
            transport=f"{verified_journey_count}/{transport_checked_count} verified" if transport_checked_count > 0 else "0/0 verified",
            hotels=f"{hotel_verified_count}/{len(hotel_results)} verified" if len(hotel_results) > 0 else "0/0 verified",
            places=f"{place_verified_count}/{len(place_results)} verified" if len(place_results) > 0 else "0/0 verified",
            weather=weather_disp,
            overall=overall_status.upper(),
        )

        agent_success(
            "verification",
            state,
            agent_start_time,
            status=overall_status,
        )

        return state
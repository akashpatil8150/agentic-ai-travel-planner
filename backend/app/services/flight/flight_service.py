import logging
from typing import Any

from app.services.flight.booking_client import BookingFlightClient
from app.services.flight.flight_normalizer import FlightNormalizer
from app.services.flight.flight_schema import (
    FlightResponse,
    FlightSearchRequest,
)
from app.services.flight.serpapi_client import SerpApiFlightClient


logger = logging.getLogger("travel_planner")


class FlightService:
    MAX_RESULTS = 5

    def __init__(self):
        self.serp_client = SerpApiFlightClient()
        self.booking_client = BookingFlightClient()
        self.normalizer = FlightNormalizer()

        self._selected_tokens: dict[int, dict[str, Any]] = {}

    def search_flights(
        self,
        request: FlightSearchRequest,
    ) -> list[FlightResponse]:

        # Request is already validated by Pydantic.
        # No provider call happens before this point.

        self._selected_tokens.clear()

        try:
            logger.info("Flight provider: SerpAPI PRIMARY")

            response = self.serp_client.search_flights(
                from_code=request.from_code,
                to_code=request.to_code,
                depart_date=request.date.isoformat(),
                return_date=(
                    request.return_date.isoformat()
                    if request.return_date
                    else None
                ),
                travel_class=self._get_serp_travel_class(
                    request.cabin_class
                ),
                currency=request.currency,
            )

            raw_flights = self._get_serp_flights(response)

            flights = []

            for raw_index, raw in enumerate(
                raw_flights,
                start=1,
            ):
                normalized = (
                    self.normalizer.normalize_serpapi_flight(
                        raw,
                        flight_id=raw_index,
                        currency=request.currency,
                        cabin_class=request.cabin_class,
                    )
                )

                if normalized is not None:
                    flights.append(normalized)

            flights = self._prepare_results(flights)

            if flights:
                self._store_serpapi_tokens(
                    flights=flights,
                    raw_flights=raw_flights,
                )

                logger.info(
                    "SerpAPI PRIMARY SUCCESS | count=%s",
                    len(flights),
                )

                return flights

            logger.warning(
                "SerpAPI returned no usable flights"
            )

        except ValueError:
            raise

        except Exception as exc:
            logger.warning(
                "SerpAPI PRIMARY FAILED | %s",
                exc,
            )

        # --------------------------------------------------------
        # Booking fallback
        # --------------------------------------------------------

        try:
            logger.info(
                "Flight provider: Booking SECONDARY"
            )

            from_id = self._resolve_booking_destination(
                request.from_code
            )

            to_id = self._resolve_booking_destination(
                request.to_code
            )

            response = self.booking_client.search_flights(
                from_id=from_id,
                to_id=to_id,
                depart_date=request.date.isoformat(),
                return_date=(
                    request.return_date.isoformat()
                    if request.return_date
                    else None
                ),
                adults=request.adults,
                children=request.children,
                cabin_class=request.cabin_class,
                currency_code=request.currency,
            )

            raw_flights = self._get_booking_flights(response)

            flights = []

            for raw_index, raw in enumerate(
                raw_flights,
                start=1,
            ):
                normalized = (
                    self.normalizer.normalize_booking_flight(
                        raw,
                        flight_id=raw_index,
                    )
                )

                if normalized is not None:
                    flights.append(normalized)

            flights = self._prepare_results(flights)

            if flights:
                self._store_booking_tokens(
                    flights=flights,
                    raw_flights=raw_flights,
                )

                logger.info(
                    "Booking SECONDARY SUCCESS | count=%s",
                    len(flights),
                )

                return flights

            logger.warning(
                "Booking returned no usable flights"
            )

        except Exception as exc:
            logger.error(
                "Booking SECONDARY FAILED | %s",
                exc,
            )

        raise RuntimeError(
            "No flights available from primary or secondary provider"
        )

    @staticmethod
    def _get_serp_flights(response: dict) -> list[dict]:
        if not isinstance(response, dict):
            return []

        flights = []

        for key in ("best_flights", "other_flights"):
            value = response.get(key)

            if isinstance(value, list):
                flights.extend(
                    item
                    for item in value
                    if isinstance(item, dict)
                )

        return flights

    @staticmethod
    def _get_booking_flights(response: dict) -> list[dict]:
        if not isinstance(response, dict):
            return []

        data = response.get("data")

        if isinstance(data, list):
            return [
                item for item in data
                if isinstance(item, dict)
            ]

        if isinstance(data, dict):
            for key in (
                "flightOffers",
                "flights",
                "offers",
                "results",
            ):
                value = data.get(key)

                if isinstance(value, list):
                    return [
                        item for item in value
                        if isinstance(item, dict)
                    ]

        for key in (
            "flights",
            "flightOffers",
            "offers",
            "results",
        ):
            value = response.get(key)

            if isinstance(value, list):
                return [
                    item for item in value
                    if isinstance(item, dict)
                ]

        return []

    def _prepare_results(
        self,
        flights: list[FlightResponse],
    ) -> list[FlightResponse]:

        valid = []

        for flight in flights:
            if not flight:
                continue

            if not flight.source.code:
                continue

            if not flight.destination.code:
                continue

            if (
                flight.source.code.upper()
                == flight.destination.code.upper()
            ):
                continue

            if not flight.departure_time:
                continue

            if not flight.arrival_time:
                continue

            valid.append(flight)

        valid = self.normalizer.remove_duplicates(valid)
        valid = self.normalizer.limit_results(
            valid,
            self.MAX_RESULTS,
        )

        for index, flight in enumerate(valid, start=1):
            flight.id = index

        return valid

    def _store_serpapi_tokens(
        self,
        flights: list[FlightResponse],
        raw_flights: list[dict],
    ):
        self._selected_tokens.clear()

        for flight, raw in zip(flights, raw_flights):
            if not isinstance(raw, dict):
                continue

            token = raw.get("booking_token")

            self._selected_tokens[flight.id] = {
                "provider": "serpapi",
                "token": token,
            }

    def _store_booking_tokens(
        self,
        flights: list[FlightResponse],
        raw_flights: list[dict],
    ):
        self._selected_tokens.clear()

        for flight, raw in zip(flights, raw_flights):
            if not isinstance(raw, dict):
                continue

            token = (
                raw.get("token")
                or raw.get("provider_token")
                or raw.get("flight_token")
            )

            self._selected_tokens[flight.id] = {
                "provider": "booking",
                "token": token,
            }

    def _resolve_booking_destination(
        self,
        airport_code: str,
    ) -> str:

        response = self.booking_client.search_destination(
            airport_code
        )

        if not isinstance(response, dict):
            raise RuntimeError(
                "Invalid Booking destination response"
            )

        data = response.get("data")

        if isinstance(data, list):
            for item in data:
                if not isinstance(item, dict):
                    continue

                destination_id = (
                    item.get("id")
                    or item.get("entityId")
                    or item.get("searchId")
                )

                if destination_id:
                    return str(destination_id)

        if isinstance(data, dict):
            destination_id = (
                data.get("id")
                or data.get("entityId")
                or data.get("searchId")
            )

            if destination_id:
                return str(destination_id)

        raise RuntimeError(
            f"Booking destination not found for {airport_code}"
        )

    @staticmethod
    def _get_serp_travel_class(
        cabin_class: str,
    ) -> int:

        mapping = {
            "ECONOMY": 1,
            "PREMIUM_ECONOMY": 2,
            "BUSINESS": 3,
            "FIRST": 4,
        }

        value = cabin_class.strip().upper()

        if value not in mapping:
            raise ValueError(
                f"Unsupported cabin class: {cabin_class}"
            )

        return mapping[value]

    def get_selected_flight_details(
        self,
        flight_id: int,
        request: FlightSearchRequest,
    ):

        token_data = self._selected_tokens.get(flight_id)

        if not token_data:
            raise ValueError(
                "Selected flight not found. "
                "Please search flights again."
            )

        provider = token_data.get("provider")
        token = token_data.get("token")

        if not token:
            raise RuntimeError(
                "Selected flight does not have a provider token"
            )

        if provider == "serpapi":
            return self.serp_client.get_selected_flight(
                departure_token=token,
                from_code=request.from_code,
                to_code=request.to_code,
                depart_date=request.date.isoformat(),
                return_date=(
                    request.return_date.isoformat()
                    if request.return_date
                    else None
                ),
                travel_class=self._get_serp_travel_class(
                    request.cabin_class
                ),
                currency=request.currency,
            )

        if provider == "booking":
            return self.booking_client.get_flight_details(
                token=token,
                currency_code=request.currency,
            )

        raise ValueError(
            f"Unsupported provider: {provider}"
        )

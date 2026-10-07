from typing import Any

from app.services.flight.flight_schema import (
    FlightAirport,
    FlightFare,
    FlightResponse,
)


class FlightNormalizer:

    @staticmethod
    def normalize_serpapi_flight(
        flight: dict[str, Any],
        flight_id: int,
        currency: str = "INR",
        cabin_class: str = "ECONOMY",
    ) -> FlightResponse | None:

        if not isinstance(flight, dict):
            return None

        segments = flight.get("flights")

        if not isinstance(segments, list) or not segments:
            return None

        first = segments[0]
        last = segments[-1]

        if not isinstance(first, dict) or not isinstance(last, dict):
            return None

        departure = first.get("departure_airport") or {}
        arrival = last.get("arrival_airport") or {}

        if not isinstance(departure, dict) or not isinstance(arrival, dict):
            return None

        from_code = departure.get("id")
        to_code = arrival.get("id")

        if not from_code or not to_code:
            return None

        from_code = str(from_code).upper()
        to_code = str(to_code).upper()

        if from_code == to_code:
            return None

        source = FlightAirport(
            code=from_code,
            name=departure.get("name"),
            city=departure.get("city"),
        )

        destination = FlightAirport(
            code=to_code,
            name=arrival.get("name"),
            city=arrival.get("city"),
        )

        duration_minutes = None
        duration = flight.get("total_duration")

        if duration is not None:
            try:
                duration_minutes = int(duration)
            except (TypeError, ValueError):
                pass

        stops = max(len(segments) - 1, 0)

        fare = None
        price = flight.get("price")

        if price is not None:
            try:
                fare = FlightFare(
                    amount=float(price),
                    currency=currency.upper(),
                )
            except (TypeError, ValueError):
                pass

        airline = (
            first.get("airline")
            or flight.get("airline")
            or first.get("airline_name")
            or flight.get("airline_name")
            or first.get("carrier")
            or first.get("name")
        )
        flight_number = (
            first.get("flight_number")
            or flight.get("flight_number")
            or first.get("flight_no")
            or first.get("number")
        )

        airline_str = str(airline).strip() if airline else None
        f_no_str = str(flight_number).strip() if flight_number else None

        if airline_str and f_no_str:
            if airline_str.lower() in f_no_str.lower():
                flight_label = f_no_str
            else:
                flight_label = f"{airline_str} {f_no_str}"
        elif airline_str:
            flight_label = f"{airline_str} ({from_code} - {to_code})"
        elif f_no_str:
            flight_label = f"Flight {f_no_str}"
        else:
            flight_label = f"{from_code} - {to_code} Flight"

        return FlightResponse(
            id=flight_id,
            airline=airline_str,
            flight_number=f_no_str,
            name=flight_label,
            flight_name=flight_label,
            source=source,
            destination=destination,
            departure_time=departure.get("time"),
            arrival_time=arrival.get("time"),
            duration_minutes=duration_minutes,
            stops=stops,
            cabin_class=cabin_class.upper(),
            fare=fare,
            provider="serpapi",
        )

    @staticmethod
    def normalize_booking_flight(
        flight: dict[str, Any],
        flight_id: int,
    ) -> FlightResponse | None:

        if not isinstance(flight, dict):
            return None

        segments = flight.get("segments")

        if not isinstance(segments, list) or not segments:
            return None

        first_segment = segments[0]
        last_segment = segments[-1]

        if not isinstance(first_segment, dict) or not isinstance(last_segment, dict):
            return None

        first_legs = first_segment.get("legs")
        last_legs = last_segment.get("legs")

        if not isinstance(first_legs, list) or not first_legs:
            return None

        if not isinstance(last_legs, list) or not last_legs:
            return None

        first_leg = first_legs[0]
        last_leg = last_legs[-1]

        if not isinstance(first_leg, dict) or not isinstance(last_leg, dict):
            return None

        airline = None
        carriers_data = first_leg.get("carriersData", [])

        if isinstance(carriers_data, list) and carriers_data:
            carrier = carriers_data[0]
            if isinstance(carrier, dict):
                airline = carrier.get("name") or carrier.get("carrierName")

        if not airline:
            airline = (
                first_leg.get("carrierName")
                or first_leg.get("airlineName")
                or first_leg.get("operatingCarrierName")
                or first_segment.get("carrier")
                or flight.get("carrier")
            )

        flight_info = first_leg.get("flightInfo", {})
        flight_number = None

        if isinstance(flight_info, dict):
            flight_number = flight_info.get("flightNumber") or flight_info.get("number")

        if not flight_number:
            flight_number = first_leg.get("flightNumber") or first_segment.get("flightNumber")

        departure_airport = first_segment.get("departureAirport") or {}
        arrival_airport = last_segment.get("arrivalAirport") or {}

        if not isinstance(departure_airport, dict):
            departure_airport = {}

        if not isinstance(arrival_airport, dict):
            arrival_airport = {}

        from_code = departure_airport.get("code")
        to_code = arrival_airport.get("code")

        if not from_code or not to_code:
            return None

        from_code = str(from_code).upper()
        to_code = str(to_code).upper()

        if from_code == to_code:
            return None

        source = FlightAirport(
            code=from_code,
            name=departure_airport.get("name"),
            city=departure_airport.get("cityName"),
        )

        destination = FlightAirport(
            code=to_code,
            name=arrival_airport.get("name"),
            city=arrival_airport.get("cityName"),
        )

        departure_time = first_segment.get("departureTime")
        arrival_time = last_segment.get("arrivalTime")

        if not departure_time or not arrival_time:
            return None

        duration_minutes = None
        total_time = first_segment.get("totalTime")

        if total_time is not None:
            try:
                duration_minutes = int(float(total_time) / 60)
            except (TypeError, ValueError):
                pass

        total_legs = 0

        for segment in segments:
            if not isinstance(segment, dict):
                continue

            segment_legs = segment.get("legs", [])

            if isinstance(segment_legs, list):
                total_legs += len(segment_legs)

        stops = max(total_legs - 1, 0)

        fare = None
        price_breakdown = flight.get("priceBreakdown", {})

        if isinstance(price_breakdown, dict):
            total = price_breakdown.get("total", {})

            if isinstance(total, dict):
                units = total.get("units")
                nanos = total.get("nanos", 0)
                currency = total.get("currencyCode", "INR")

                if units is not None:
                    try:
                        amount = (
                            float(units)
                            + float(nanos or 0) / 1_000_000_000
                        )

                        fare = FlightFare(
                            amount=amount,
                            currency=str(currency or "INR").upper(),
                        )
                    except (TypeError, ValueError):
                        pass

        cabin_class = first_leg.get("cabinClass") or "ECONOMY"

        airline_str = str(airline).strip() if airline else None
        f_no_str = str(flight_number).strip() if flight_number is not None else None

        if airline_str and f_no_str:
            if airline_str.lower() in f_no_str.lower():
                flight_label = f_no_str
            else:
                flight_label = f"{airline_str} {f_no_str}"
        elif airline_str:
            flight_label = f"{airline_str} ({from_code} - {to_code})"
        elif f_no_str:
            flight_label = f"Flight {f_no_str}"
        else:
            flight_label = f"{from_code} - {to_code} Flight"

        return FlightResponse(
            id=flight_id,
            airline=airline_str,
            flight_number=f_no_str,
            name=flight_label,
            flight_name=flight_label,
            source=source,
            destination=destination,
            departure_time=departure_time,
            arrival_time=arrival_time,
            duration_minutes=duration_minutes,
            stops=stops,
            cabin_class=str(cabin_class).upper(),
            fare=fare,
            provider="booking",
        )

    @staticmethod
    def remove_duplicates(
        flights: list[FlightResponse],
    ) -> list[FlightResponse]:

        unique = []
        seen = set()

        for flight in flights:
            key = (
                flight.airline,
                flight.flight_number,
                flight.source.code,
                flight.destination.code,
                flight.departure_time,
                flight.arrival_time,
                flight.provider,
            )

            if key in seen:
                continue

            seen.add(key)
            unique.append(flight)

        return unique

    @staticmethod
    def limit_results(
        flights: list[FlightResponse],
        limit: int = 5,
    ) -> list[FlightResponse]:

        if limit < 1:
            raise ValueError("limit must be at least 1")

        return flights[:limit]

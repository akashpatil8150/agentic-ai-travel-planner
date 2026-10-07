from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from app.input.transport_schema import (
    TransportSearchRequest,
)

from app.services.flight.flight_schema import (
    FlightSearchRequest,
)

from app.resolvers.airport_resolver import (
    AirportResolver,
)

from app.resolvers.station_resolver import (
    StationResolver,
)

from app.resolvers.transport_resolver import (
    TransportResolver,
)

from app.resolvers.transport_access_resolver import (
    TransportAccessResolver,
)

from app.services.flight.flight_service import (
    FlightService,
)

from app.services.train.train_service import (
    TrainService,
)


# ============================================================
# TIME PARSER
# ============================================================

def _parse_time(value: str | None):
    """
    Parse common provider time formats into a datetime object.
    """

    if not value:
        return None

    value = str(value).strip()

    try:
        return datetime.fromisoformat(
            value.replace("Z", "+00:00")
        )

    except ValueError:
        pass

    for fmt in (
        "%H:%M",
        "%H:%M:%S",
        "%I:%M %p",
        "%I:%M:%S %p",
    ):

        try:
            return datetime.strptime(
                value,
                fmt,
            )

        except ValueError:
            continue

    return None


# ============================================================
# NORMALIZE TRANSPORT TIMING
# ============================================================

def _normalize_transport_timing(
    options,
    journey_date,
):
    """
    Preserve provider time fields and add deterministic
    full datetime fields.

    This is required because current train results can
    contain time-only values such as '21:54' and '09:00',
    while the itinerary engine needs to know whether
    arrival happens on the same day or the next day.
    """

    if not options:
        return options

    normalized = []

    for option in options:

        # ----------------------------------------------------
        # Convert Pydantic model / dict into dictionary
        # ----------------------------------------------------

        if hasattr(
            option,
            "model_dump",
        ):

            data = option.model_dump(
                mode="python"
            )

            original = option

        elif isinstance(
            option,
            dict,
        ):

            data = dict(option)

            original = option

        else:

            normalized.append(
                option
            )

            continue

        # ----------------------------------------------------
        # Provider timing fields
        # ----------------------------------------------------

        departure_raw = data.get(
            "departure_time"
        )

        arrival_raw = data.get(
            "arrival_time"
        )

        duration = data.get(
            "duration_minutes"
        )

        departure_dt = _parse_time(
            departure_raw
        )

        arrival_dt = _parse_time(
            arrival_raw
        )

        # ----------------------------------------------------
        # Departure datetime
        # ----------------------------------------------------

        departure_full = None
        if departure_dt is not None:
            if departure_dt.year > 2000:
                departure_full = departure_dt
            else:
                departure_full = datetime.combine(
                    journey_date,
                    departure_dt.time(),
                )
            data["departure_datetime"] = (
                departure_full.isoformat()
            )

        # ----------------------------------------------------
        # Arrival datetime
        # ----------------------------------------------------

        if arrival_dt is not None and departure_full is not None:
            if arrival_dt.year > 2000:
                arrival_full = arrival_dt
            else:
                arrival_full = datetime.combine(
                    journey_date,
                    arrival_dt.time(),
                )
                # Overnight journey: arrival time is earlier than or equal to departure time
                if arrival_full <= departure_full:
                    arrival_full += timedelta(days=1)
                if duration is not None:
                    try:
                        dur_mins = int(duration)
                        dur_arr = departure_full + timedelta(minutes=dur_mins)
                        if dur_arr.date() > arrival_full.date():
                            arrival_full = dur_arr
                    except (TypeError, ValueError):
                        pass
            data["arrival_datetime"] = (
                arrival_full.isoformat()
            )
            if data.get("arrival_time") and "T" in str(data.get("arrival_time")):
                data["arrival_time"] = arrival_full.isoformat()
        elif arrival_dt is not None:
            if arrival_dt.year > 2000:
                arrival_full = arrival_dt
            else:
                arrival_full = datetime.combine(
                    journey_date,
                    arrival_dt.time(),
                )
            data["arrival_datetime"] = (
                arrival_full.isoformat()
            )
            if data.get("arrival_time") and "T" in str(data.get("arrival_time")):
                data["arrival_time"] = arrival_full.isoformat()
        elif duration is not None and departure_full is not None:
            try:
                arrival_full = (
                    departure_full
                    + timedelta(
                        minutes=int(
                            duration
                        )
                    )
                )
                data["arrival_datetime"] = (
                    arrival_full.isoformat()
                )
                if data.get("arrival_time") and "T" in str(data.get("arrival_time")):
                    data["arrival_time"] = arrival_full.isoformat()
            except (
                TypeError,
                ValueError,
            ):
                pass

        # ----------------------------------------------------
        # Journey date
        # ----------------------------------------------------

        data["journey_date"] = (
            journey_date.isoformat()
        )

        # ----------------------------------------------------
        # Extract station codes and names
        # ----------------------------------------------------
        src = data.get("source")
        dst = data.get("destination")
        if isinstance(src, dict):
            data["from_code"] = data.get("from_code") or src.get("code")
            data["from_station_code"] = data.get("from_station_code") or src.get("code")
            data["from_station_name"] = data.get("from_station_name") or src.get("name")
        elif hasattr(src, "code"):
            data["from_code"] = data.get("from_code") or getattr(src, "code", None)
            data["from_station_code"] = data.get("from_station_code") or getattr(src, "code", None)
            data["from_station_name"] = data.get("from_station_name") or getattr(src, "name", None)

        if isinstance(dst, dict):
            data["to_code"] = data.get("to_code") or dst.get("code")
            data["to_station_code"] = data.get("to_station_code") or dst.get("code")
            data["to_station_name"] = data.get("to_station_name") or dst.get("name")
        elif hasattr(dst, "code"):
            data["to_code"] = data.get("to_code") or getattr(dst, "code", None)
            data["to_station_code"] = data.get("to_station_code") or getattr(dst, "code", None)
            data["to_station_name"] = data.get("to_station_name") or getattr(dst, "name", None)

        # Passenger boarding and alighting stations
        b_code = data.get("boarding_station_code") or data.get("boarding_station") or data.get("from_station_code") or data.get("from_code")
        a_code = data.get("alighting_station_code") or data.get("alighting_station") or data.get("to_station_code") or data.get("to_code")
        b_name = data.get("boarding_station_name") or data.get("from_station_name") or b_code
        a_name = data.get("alighting_station_name") or data.get("to_station_name") or a_code

        data["boarding_station"] = b_code
        data["boarding_station_code"] = b_code
        data["boarding_station_name"] = b_name
        data["alighting_station"] = a_code
        data["alighting_station_code"] = a_code
        data["alighting_station_name"] = a_name

        data["actual_origin_station"] = b_code
        data["actual_destination_station"] = a_code

        if not data.get("train_origin_station"):
            data["train_origin_station"] = b_code
        if not data.get("train_destination_station"):
            data["train_destination_station"] = a_code

        if not data.get("actual_train_origin"):
            data["actual_train_origin"] = f"{b_name} ({b_code})" if b_name and b_code and b_name != b_code else (b_code or "")
        if not data.get("actual_train_destination"):
            data["actual_train_destination"] = f"{a_name} ({a_code})" if a_name and a_code and a_name != a_code else (a_code or "")

        normalized.append(data)

    return normalized


# ============================================================
# TRANSPORT SERVICE
# ============================================================

class TransportService:
    """
    Coordinates flight and train search.

    Responsibilities:

        1. Resolve city names for flights
        2. Resolve city names for trains
        3. Convert cities to airport/station codes
        4. Delegate flight search
        5. Delegate train search
        6. Return combined transport results

    Optimization:

        - Try the primary railway station pair first.
        - Only try another station combination when the
          previous combination returns no trains.
        - Prevent unnecessary RailCore API calls.
    """

    def __init__(self):

        # ----------------------------------------------------
        # Flight dependencies
        # ----------------------------------------------------

        self.airport_resolver = (
            AirportResolver()
        )

        self.flight_service = (
            FlightService()
        )

        # ----------------------------------------------------
        # Train dependencies
        # ----------------------------------------------------

        self.station_resolver = (
            StationResolver()
        )

        self.train_service = (
            TrainService()
        )

        self.access_resolver = (
            TransportAccessResolver()
        )

    # ========================================================
    # SEARCH TRANSPORT
    # ========================================================

    def search_transport(
        self,
        request: TransportSearchRequest,
        orig_location: Any = None,
        dest_location: Any = None,
    ) -> dict:

        # ----------------------------------------------------
        # Always return a dictionary.
        # This prevents NoneType.get() errors in the
        # TransportAgent.
        # ----------------------------------------------------

        result = {
            "flight_options": [],
            "train_options": [],
        }

        # ====================================================
        # FLIGHT SEARCH
        # ====================================================

        dep_date_str = (
            request.departure_date.isoformat()
            if hasattr(request.departure_date, "isoformat")
            else str(request.departure_date)
        )
        ret_date_str = (
            request.return_date.isoformat()
            if request.return_date and hasattr(request.return_date, "isoformat")
            else (str(request.return_date) if request.return_date else None)
        )

        # ====================================================
        # FLIGHT SEARCH
        # ====================================================

        if request.transport_type in (
            "flight",
            "both",
        ):
            flight_res = self.access_resolver.resolve_and_validate(
                user_origin=request.origin,
                user_destination=request.destination,
                transport_type="flight",
                departure_date=dep_date_str,
                return_date=ret_date_str,
                train_service=self.train_service,
                flight_service=self.flight_service,
                adults=request.adults or 1,
                children=request.children or 0,
                orig_location=orig_location,
                dest_location=dest_location,
            )

            result["flight_options"] = _normalize_transport_timing(
                flight_res["outbound_options"],
                request.departure_date,
            )

            if ret_date_str and flight_res.get("return_options"):
                norm_ret = _normalize_transport_timing(
                    flight_res["return_options"],
                    request.return_date,
                )
                result["return_options"] = norm_ret
                result["flight_options"] = self._attach_return_trips(
                    result["flight_options"],
                    norm_ret,
                    request.return_date,
                    user_origin=request.origin,
                    user_destination=request.destination,
                    return_first_mile=flight_res.get("return_first_mile_transfer"),
                    return_last_mile=flight_res.get("return_last_mile_transfer"),
                    return_transfer=flight_res.get("return_transfer"),
                )

            if flight_res.get("outbound_transfer"):
                result["flight_transfer"] = flight_res["outbound_transfer"]
                result["transfer"] = flight_res["outbound_transfer"]

            result["user_origin"] = request.origin
            result["user_destination"] = request.destination
            result["origin_transport_endpoint"] = flight_res["origin_transport_endpoint"]
            result["destination_transport_endpoint"] = flight_res["destination_transport_endpoint"]
            result["return_origin_transport_endpoint"] = flight_res.get("return_origin_transport_endpoint")
            result["return_destination_transport_endpoint"] = flight_res.get("return_destination_transport_endpoint")
            result["first_mile_transfer"] = flight_res.get("first_mile_transfer")
            result["last_mile_transfer"] = flight_res.get("last_mile_transfer")
            result["outbound_transfer"] = flight_res["outbound_transfer"]
            result["return_first_mile_transfer"] = flight_res.get("return_first_mile_transfer")
            result["return_last_mile_transfer"] = flight_res.get("return_last_mile_transfer")
            result["return_transfer"] = flight_res["return_transfer"]

        # ====================================================
        # TRAIN SEARCH
        # ====================================================

        if request.transport_type in (
            "train",
            "both",
        ):
            train_res = self.access_resolver.resolve_and_validate(
                user_origin=request.origin,
                user_destination=request.destination,
                transport_type="train",
                departure_date=dep_date_str,
                return_date=ret_date_str,
                train_service=self.train_service,
                flight_service=self.flight_service,
                adults=request.adults or 1,
                children=request.children or 0,
                orig_location=orig_location,
                dest_location=dest_location,
            )

            unique_trains = {}
            for train in train_res["outbound_options"]:
                train_number = getattr(train, "train_number", None) if hasattr(train, "train_number") else (train.get("train_number") if isinstance(train, dict) else None)
                departure_time = getattr(train, "departure_time", None) if hasattr(train, "departure_time") else (train.get("departure_time") if isinstance(train, dict) else None)
                unique_trains[(train_number, departure_time)] = train

            result["train_options"] = _normalize_transport_timing(
                list(unique_trains.values()),
                request.departure_date,
            )

            if ret_date_str and train_res.get("return_options"):
                norm_ret = _normalize_transport_timing(
                    train_res["return_options"],
                    request.return_date,
                )
                result["return_options"] = norm_ret
                result["train_options"] = self._attach_return_trips(
                    result["train_options"],
                    norm_ret,
                    request.return_date,
                    user_origin=request.origin,
                    user_destination=request.destination,
                    return_first_mile=train_res.get("return_first_mile_transfer"),
                    return_last_mile=train_res.get("return_last_mile_transfer"),
                    return_transfer=train_res.get("return_transfer"),
                )

            if train_res.get("outbound_transfer"):
                result["train_transfer"] = train_res["outbound_transfer"]
                result["transfer"] = train_res["outbound_transfer"]

            result["user_origin"] = request.origin
            result["user_destination"] = request.destination
            result["origin_transport_endpoint"] = train_res.get("origin_transport_endpoint")
            result["destination_transport_endpoint"] = train_res.get("destination_transport_endpoint")
            result["return_origin_transport_endpoint"] = train_res.get("return_origin_transport_endpoint")
            result["return_destination_transport_endpoint"] = train_res.get("return_destination_transport_endpoint")
            result["actual_train_origin"] = train_res.get("actual_train_origin")
            result["actual_train_destination"] = train_res.get("actual_train_destination")
            result["return_actual_train_origin"] = train_res.get("return_actual_train_origin")
            result["return_actual_train_destination"] = train_res.get("return_actual_train_destination")
            result["first_mile_transfer"] = train_res.get("first_mile_transfer")
            result["last_mile_transfer"] = train_res.get("last_mile_transfer")
            result["outbound_transfer"] = train_res.get("outbound_transfer")
            result["return_first_mile_transfer"] = train_res.get("return_first_mile_transfer")
            result["return_last_mile_transfer"] = train_res.get("return_last_mile_transfer")
            result["return_transfer"] = train_res.get("return_transfer")
            result["outbound_status"] = train_res.get("outbound_status")
            result["return_status"] = train_res.get("return_status")
            result["transport_status"] = train_res.get("transport_status")

        # ====================================================
        # ATTACH TRANSFER / FIRST-MILE / LAST-MILE INFO
        # ====================================================
        if "transfer" not in result and (result.get("flight_options") or result.get("train_options")):
            transfer_info = TransportResolver.get_transfer_info(
                request.origin, request.destination, mode=request.transport_type
            )
            if transfer_info:
                result["transfer"] = transfer_info

        # ====================================================
        # ATTACH TRANSFERS TO TRANSPORT OPTIONS
        # ====================================================
        transfer_info = result.get("outbound_transfer") or result.get("transfer")
        first_mile = result.get("first_mile_transfer")
        last_mile = result.get("last_mile_transfer")
        ret_transfer_info = result.get("return_transfer")

        for opt in result.get("flight_options", []):
            if isinstance(opt, dict):
                opt["user_origin"] = request.origin
                opt["user_destination"] = request.destination
                if first_mile:
                    opt["first_mile_transfer"] = first_mile
                if last_mile:
                    opt["last_mile_transfer"] = last_mile
                if transfer_info and "transfer" not in opt:
                    opt["transfer"] = transfer_info
                    opt["outbound_transfer"] = transfer_info
                if ret_transfer_info and "return_transfer" not in opt:
                    opt["return_transfer"] = ret_transfer_info

        for opt in result.get("train_options", []):
            if isinstance(opt, dict):
                opt["user_origin"] = request.origin
                opt["user_destination"] = request.destination
                if first_mile:
                    opt["first_mile_transfer"] = first_mile
                if last_mile:
                    opt["last_mile_transfer"] = last_mile
                if transfer_info and "transfer" not in opt:
                    opt["transfer"] = transfer_info
                    opt["outbound_transfer"] = transfer_info
                if ret_transfer_info and "return_transfer" not in opt:
                    opt["return_transfer"] = ret_transfer_info

        return result


    # ========================================================
    # RETURN FLIGHT SEARCH
    # ========================================================

    def _search_return_flights(
        self,
        request: TransportSearchRequest,
    ):
        """
        Search the reverse flight route
        on the return date.
        """

        route = (
            self.airport_resolver.resolve_route(
                origin=request.destination,
                destination=request.origin,
            )
        )

        return_request = FlightSearchRequest(
            from_code=route[
                "origin"
            ]["code"],

            to_code=route[
                "destination"
            ]["code"],

            date=request.return_date,

            adults=request.adults,

            children=request.children,

            cabin_class="ECONOMY",

            currency="INR",
        )

        return (
            self.flight_service.search_flights(
                return_request
            )
        )

    # ========================================================
    # RETURN TRAIN SEARCH
    # ========================================================

    def _search_return_trains(
        self,
        request: TransportSearchRequest,
    ):
        """
        Search the reverse train route
        on the return date.
        """

        route = (
            self.station_resolver.resolve_route(
                origin=request.destination,
                destination=request.origin,
            )
        )

        origin_stations = (
            route[
                "origin"
            ]["stations"]
        )

        destination_stations = (
            route[
                "destination"
            ]["stations"]
        )

        for origin_station in origin_stations:

            for destination_station in destination_stations:

                try:

                    trains = (
                        self.train_service.search_trains(
                            from_code=origin_station[
                                "code"
                            ],

                            to_code=destination_station[
                                "code"
                            ],

                            date=request.return_date.isoformat(),
                        )
                    )

                    if not trains:
                        continue

                    return (
                        _normalize_transport_timing(
                            trains,
                            request.return_date,
                        )
                    )

                except Exception as error:

                    print(
                        "Return train search failed: "
                        f"{type(error).__name__}: "
                        f"{error}"
                    )

                    continue

        return []

    # ========================================================
    # ATTACH RETURN TRIPS
    # ========================================================

    @staticmethod
    def _attach_return_trips(
        outbound_options,
        return_options,
        return_date,
        user_origin=None,
        user_destination=None,
        return_first_mile=None,
        return_last_mile=None,
        return_transfer=None,
    ):
        """
        Attach a real return journey when one is available.
        """

        if (
            not outbound_options
            or not return_options
        ):

            return outbound_options

        enriched = []

        for index, outbound in enumerate(
            outbound_options
        ):

            return_option = (
                return_options[
                    index
                    % len(return_options)
                ]
            )

            # ------------------------------------------------
            # Outbound data
            # ------------------------------------------------

            if hasattr(
                outbound,
                "model_dump",
            ):

                data = outbound.model_dump(
                    mode="python"
                )

            elif isinstance(
                outbound,
                dict,
            ):

                data = dict(
                    outbound
                )

            else:

                enriched.append(
                    outbound
                )

                continue

            # ------------------------------------------------
            # Return data
            # ------------------------------------------------

            if hasattr(
                return_option,
                "model_dump",
            ):

                return_data = (
                    return_option.model_dump(
                        mode="python"
                    )
                )

            elif isinstance(
                return_option,
                dict,
            ):

                return_data = dict(
                    return_option
                )

            else:

                return_data = {}

            if return_data:
                if user_destination and "user_origin" not in return_data:
                    return_data["user_origin"] = user_destination
                if user_origin and "user_destination" not in return_data:
                    return_data["user_destination"] = user_origin
                if return_first_mile and "first_mile_transfer" not in return_data:
                    return_data["first_mile_transfer"] = return_first_mile
                    return_data["return_first_mile_transfer"] = return_first_mile
                if return_last_mile and "last_mile_transfer" not in return_data:
                    return_data["last_mile_transfer"] = return_last_mile
                    return_data["return_last_mile_transfer"] = return_last_mile
                if return_transfer and "return_transfer" not in return_data:
                    return_data["return_transfer"] = return_transfer
                    return_data["transfer"] = return_transfer

            # ------------------------------------------------
            # Attach return trip
            # ------------------------------------------------

            data[
                "return_trip"
            ] = return_data

            data[
                "return_journey_date"
            ] = (
                return_date.isoformat()
                if hasattr(
                    return_date,
                    "isoformat",
                )
                else str(
                    return_date
                )
            )

            enriched.append(
                data
            )

        return enriched
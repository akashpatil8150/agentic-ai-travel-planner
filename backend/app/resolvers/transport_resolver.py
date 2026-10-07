from typing import Optional, Dict, Any

from app.resolvers.airport_resolver import (
    AirportResolver,
    AirportResolverError,
)
from app.resolvers.station_resolver import (
    StationResolver,
    StationResolverError,
)


# ============================================================
# EXCEPTION
# ============================================================

class TransportResolverError(Exception):
    pass


from app.resolvers.india_locations import (
    resolve_stations_for_location,
    resolve_airports_for_location,
    get_location_entry,
)


class TransportResolverError(Exception):
    pass


class TransportResolver:

    def __init__(self):
        self.airport_resolver = AirportResolver()
        self.station_resolver = StationResolver()

    # ========================================================
    # GET TRANSFER INFO (First-Mile / Last-Mile)
    # Dynamic calculation based on location & station/airport coordinates
    # ========================================================

    @staticmethod
    def get_transfer_info(
        origin: str,
        destination: str,
        mode: str = "train",
    ) -> Optional[Dict[str, Any]]:
        """
        Detects if either origin or destination requires first-mile or last-mile
        road transfer because direct station/airport is at a nearby hub.
        Calculates road distance and duration dynamically.
        """
        orig_clean = str(origin).strip()
        dest_clean = str(destination).strip()
        is_flight = "flight" in str(mode).lower()

        # Resolve candidates
        if is_flight:
            orig_candidates = resolve_airports_for_location(orig_clean)
            dest_candidates = resolve_airports_for_location(dest_clean)
            transport_term = "Airport"
        else:
            orig_candidates = resolve_stations_for_location(orig_clean)
            dest_candidates = resolve_stations_for_location(dest_clean)
            transport_term = "Station"

        dest_candidate = dest_candidates[0] if dest_candidates else None
        orig_candidate = orig_candidates[0] if orig_candidates else None

        dest_has_transfer = False
        dest_transfer_data = None
        if dest_candidate and dest_candidate.get("distance_km", 0) > 15:
            dest_has_transfer = True
            hub_name = dest_candidate.get("city") or dest_candidate["name"]
            transfer_pt = f"{dest_candidate['name']} ({dest_candidate['code']})"
            road_km = dest_candidate["distance_km"]
            time_str = dest_candidate["estimated_transfer_time"]
            dest_transfer_data = {
                "transfer_point": transfer_pt,
                "hub_city": hub_name,
                "road_distance_km": road_km,
                "estimated_transfer_time": time_str,
                "transfer_mode": "Cab / Taxi / Bus",
                "notes": f"Road transfer between {hub_name} {transport_term} and {dest_clean.title()}.",
            }

        orig_has_transfer = False
        orig_transfer_data = None
        if orig_candidate and orig_candidate.get("distance_km", 0) > 15:
            orig_has_transfer = True
            hub_name = orig_candidate.get("city") or orig_candidate["name"]
            transfer_pt = f"{orig_candidate['name']} ({orig_candidate['code']})"
            road_km = orig_candidate["distance_km"]
            time_str = orig_candidate["estimated_transfer_time"]
            orig_transfer_data = {
                "transfer_point": transfer_pt,
                "hub_city": hub_name,
                "road_distance_km": road_km,
                "estimated_transfer_time": time_str,
                "transfer_mode": "Cab / Taxi / Bus",
                "notes": f"Road transfer between {orig_clean.title()} and {hub_name} {transport_term}.",
            }

        if dest_has_transfer and orig_has_transfer:
            return {
                "has_transfer": True,
                "transfer_type": "both",
                "hub_name": f"{orig_transfer_data['hub_city']} / {dest_transfer_data['hub_city']}",
                "transfer_point": f"First-mile: {orig_transfer_data['transfer_point']} | Last-mile: {dest_transfer_data['transfer_point']}",
                "road_distance_km": orig_transfer_data["road_distance_km"] + dest_transfer_data["road_distance_km"],
                "estimated_transfer_time": f"{orig_transfer_data['estimated_transfer_time']} (first-mile) + {dest_transfer_data['estimated_transfer_time']} (last-mile)",
                "transfer_mode": dest_transfer_data["transfer_mode"],
                "first_mile": orig_transfer_data,
                "last_mile": dest_transfer_data,
                "description": f"First-mile transfer from {orig_clean.title()} to {orig_transfer_data['transfer_point']} ({orig_transfer_data['road_distance_km']} km, {orig_transfer_data['estimated_transfer_time']}) and last-mile transfer from {dest_transfer_data['transfer_point']} to {dest_clean.title()} ({dest_transfer_data['road_distance_km']} km, {dest_transfer_data['estimated_transfer_time']}).",
            }

        if dest_has_transfer:
            return {
                "has_transfer": True,
                "transfer_type": "last_mile",
                "hub_name": dest_transfer_data["hub_city"],
                "transfer_point": dest_transfer_data["transfer_point"],
                "hub_city": dest_transfer_data["hub_city"],
                "target_city": dest_clean.title(),
                "road_distance_km": dest_transfer_data["road_distance_km"],
                "estimated_transfer_time": dest_transfer_data["estimated_transfer_time"],
                "transfer_mode": dest_transfer_data["transfer_mode"],
                "notes": dest_transfer_data.get("notes"),
                "description": f"Last-mile transfer from {dest_transfer_data['transfer_point']} to {dest_clean.title()}: {dest_transfer_data['road_distance_km']} km (Estimated transfer time: {dest_transfer_data['estimated_transfer_time']} via {dest_transfer_data['transfer_mode']}).",
            }

        if orig_has_transfer:
            return {
                "has_transfer": True,
                "transfer_type": "first_mile",
                "hub_name": orig_transfer_data["hub_city"],
                "transfer_point": orig_transfer_data["transfer_point"],
                "hub_city": orig_transfer_data["hub_city"],
                "target_city": orig_clean.title(),
                "road_distance_km": orig_transfer_data["road_distance_km"],
                "estimated_transfer_time": orig_transfer_data["estimated_transfer_time"],
                "transfer_mode": orig_transfer_data["transfer_mode"],
                "notes": orig_transfer_data.get("notes"),
                "description": f"First-mile transfer from {orig_clean.title()} to {orig_transfer_data['transfer_point']}: {orig_transfer_data['road_distance_km']} km (Estimated transfer time: {orig_transfer_data['estimated_transfer_time']} via {orig_transfer_data['transfer_mode']}).",
            }

        return None


    # ========================================================
    # RESOLVE
    # ========================================================

    def resolve(
        self,
        origin: str,
        destination: str,
    ):
        if not isinstance(origin, str):
            raise TypeError("Origin must be a string.")

        origin = origin.strip()
        if not origin:
            raise ValueError("Origin cannot be empty.")

        if not isinstance(destination, str):
            raise TypeError("Destination must be a string.")

        destination = destination.strip()
        if not destination:
            raise ValueError("Destination cannot be empty.")

        if origin.lower() == destination.lower():
            raise ValueError("Origin and destination cannot be the same.")

        try:
            origin_result = self.airport_resolver.resolve(origin)
        except AirportResolverError as error:
            raise TransportResolverError(
                f"Could not resolve origin '{origin}': {error}"
            ) from error

        try:
            destination_result = self.airport_resolver.resolve(destination)
        except AirportResolverError as error:
            raise TransportResolverError(
                f"Could not resolve destination '{destination}': {error}"
            ) from error

        transfer_info = self.get_transfer_info(origin, destination)

        return {
            "origin": origin_result,
            "destination": destination_result,
            "transfer": transfer_info,
        }
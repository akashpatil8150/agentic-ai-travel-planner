from typing import Dict, List, Optional, Tuple
from app.resolvers.india_locations import resolve_stations_for_location


class StationResolverError(Exception):
    """Raised when railway stations cannot be resolved."""
    pass


class StationResolver:
    """
    Resolves city/location names to railway station candidates.

    Delegates dynamically to india_locations spatial discovery.
    """

    def resolve(
        self,
        location: str,
        geo_coords: Optional[Tuple[float, float]] = None,
    ) -> List[dict]:
        """
        Return all known railway stations for a city or nearest railheads if direct stations do not exist.
        """
        if not isinstance(location, str):
            raise TypeError("Location must be a string")

        location = location.strip()
        if not location:
            raise ValueError("Location cannot be empty")

        stations = resolve_stations_for_location(location, geo_coords=geo_coords)

        # Never fabricate a station code from arbitrary user text.
        return [station.copy() for station in stations]

    def resolve_codes(
        self,
        location: str,
        geo_coords: Optional[Tuple[float, float]] = None,
    ) -> List[str]:
        """
        Return only railway station codes.
        """
        stations = self.resolve(location, geo_coords=geo_coords)
        return [station["code"] for station in stations]

    def resolve_route(
        self,
        origin: str,
        destination: str,
        orig_coords: Optional[Tuple[float, float]] = None,
        dest_coords: Optional[Tuple[float, float]] = None,
    ) -> dict:
        """
        Resolve origin and destination into railway station candidates.
        """
        if not isinstance(origin, str):
            raise TypeError("Origin must be a string")

        if not isinstance(destination, str):
            raise TypeError("Destination must be a string")

        origin = origin.strip()
        destination = destination.strip()

        if not origin:
            raise ValueError("Origin cannot be empty")

        if not destination:
            raise ValueError("Destination cannot be empty")

        if origin.lower() == destination.lower():
            raise ValueError("Origin and destination cannot be the same")

        origin_stations = self.resolve(origin, geo_coords=orig_coords)
        destination_stations = self.resolve(destination, geo_coords=dest_coords)

        return {
            "origin": {
                "location": origin,
                "stations": origin_stations,
            },
            "destination": {
                "location": destination,
                "stations": destination_stations,
            },
        }
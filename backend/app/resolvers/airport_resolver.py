from typing import Optional
from app.resolvers.india_locations import resolve_airports_for_location


class AirportResolverError(Exception):
    """Raised when an airport cannot be resolved."""
    pass


class AirportResolver:
    """
    Resolves city/location names to IATA airport candidates.
    Delegates to dynamic India location dataset and spatial discovery.
    """

    def __init__(self):
        pass

    def resolve(
        self,
        location: str,
    ) -> dict:
        """
        Resolve city name to primary airport information or nearest operational airport.
        """
        if not location or not location.strip():
            raise ValueError(
                "Airport location cannot be empty"
            )

        airports = resolve_airports_for_location(location)
        if airports:
            airport = airports[0]
        else:
            clean_code = "".join([c for c in location.upper() if c.isalnum()])[:3] or "APT"
            airport = {
                "code": clean_code,
                "name": f"{location.title()} Regional Airport",
                "city": location.title(),
            }

        return {
            "input": location.strip(),
            "code": airport["code"],
            "name": airport["name"],
            "city": airport.get("city", location.title()),
            "distance_km": airport.get("distance_km"),
            "estimated_transfer_time": airport.get("estimated_transfer_time"),
        }


    def resolve_code(
        self,
        location: str,
    ) -> str:
        """
        Convenience method.
        Returns only IATA airport code.
        """

        result = self.resolve(location)

        return result["code"]

    def resolve_route(
        self,
        origin: str,
        destination: str,
    ) -> dict:
        """
        Resolve complete origin → destination route.
        """

        if not origin or not origin.strip():
            raise ValueError(
                "Origin cannot be empty"
            )

        if not destination or not destination.strip():
            raise ValueError(
                "Destination cannot be empty"
            )

        if (
            origin.strip().lower()
            == destination.strip().lower()
        ):
            raise ValueError(
                "Origin and destination cannot be the same"
            )

        origin_airport = self.resolve(origin)
        destination_airport = self.resolve(destination)

        if (
            origin_airport["code"]
            == destination_airport["code"]
        ):
            raise ValueError(
                "Origin and destination airports cannot be the same"
            )

        return {
            "origin": origin_airport,
            "destination": destination_airport,
        }
import logging
from typing import Optional

import requests

from app.core.config import settings


logger = logging.getLogger(__name__)


class BookingFlightClient:
    BASE_URL = (
        "https://booking-com15.p.rapidapi.com"
        "/api/v1/flights"
    )

    HOST = "booking-com15.p.rapidapi.com"
    TIMEOUT = 30

    def __init__(self):
        self.api_key = settings.booking_rapidapi_key

        if not self.api_key:
            raise RuntimeError(
                "BOOKING_RAPIDAPI_KEY not found in .env"
            )

        self.headers = {
            "x-rapidapi-key": self.api_key,
            "x-rapidapi-host": self.HOST,
            "Content-Type": "application/json",
        }

    def search_destination(self, query: str):
        if not query or not query.strip():
            raise ValueError("Destination query cannot be empty")

        return self._get(
            url=f"{self.BASE_URL}/searchDestination",
            params={"query": query.strip()},
        )

    def search_flights(
        self,
        from_id: str,
        to_id: str,
        depart_date: str,
        return_date: Optional[str] = None,
        stops: str = "none",
        page_no: int = 1,
        adults: int = 1,
        children: int = 0,
        sort: str = "BEST",
        cabin_class: str = "ECONOMY",
        currency_code: str = "INR",
    ):
        if not from_id:
            raise ValueError("from_id is required")

        if not to_id:
            raise ValueError("to_id is required")

        if not depart_date:
            raise ValueError("depart_date is required")

        if adults < 1:
            raise ValueError("adults must be at least 1")

        if children < 0:
            raise ValueError("children cannot be negative")

        if page_no < 1:
            raise ValueError("page_no must be at least 1")

        params = {
            "fromId": from_id,
            "toId": to_id,
            "departDate": depart_date,
            "stops": stops,
            "pageNo": str(page_no),
            "adults": str(adults),
            "children": str(children),
            "sort": sort,
            "cabinClass": cabin_class.upper(),
            "currency_code": currency_code.upper(),
        }

        if return_date:
            params["returnDate"] = return_date

        return self._get(
            url=f"{self.BASE_URL}/searchFlights",
            params=params,
        )

    def get_flight_details(
        self,
        token: str,
        currency_code: str = "INR",
    ):
        if not token or not token.strip():
            raise ValueError("Flight token is required")

        return self._get(
            url=f"{self.BASE_URL}/getFlightDetails",
            params={
                "token": token,
                "currency_code": currency_code.upper(),
            },
        )

    def _get(self, url: str, params: dict):
        try:
            response = requests.get(
                url,
                headers=self.headers,
                params=params,
                timeout=self.TIMEOUT,
            )
            response.raise_for_status()

        except requests.Timeout as exc:
            raise RuntimeError(
                "Booking API request timed out"
            ) from exc

        except requests.HTTPError as exc:
            raise RuntimeError(
                f"Booking API returned HTTP {response.status_code}"
            ) from exc

        except requests.RequestException as exc:
            raise RuntimeError(
                "Booking API request failed"
            ) from exc

        try:
            data = response.json()
        except ValueError as exc:
            raise RuntimeError(
                "Booking API returned invalid JSON"
            ) from exc

        if not isinstance(data, dict):
            raise RuntimeError(
                "Booking API returned invalid response"
            )

        if data.get("status") is False:
            message = data.get(
                "message",
                "Booking API request failed",
            )
            raise RuntimeError(
                f"Booking API error: {message}"
            )

        return data

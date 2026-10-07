import logging
import os
from typing import Any, Optional

import serpapi
from dotenv import load_dotenv


logger = logging.getLogger("travel_planner")

load_dotenv()


class SerpApiFlightClient:
    TRAVEL_CLASS_MAP = {
        1: "1",
        2: "2",
        3: "3",
        4: "4",
    }

    def __init__(self):
        self.api_key = os.getenv("SERP_API_KEY")

        if not self.api_key:
            raise RuntimeError(
                "SERP_API_KEY not found in .env"
            )

        self.client = serpapi.Client(api_key=self.api_key)

    def search_flights(
        self,
        from_code: str,
        to_code: str,
        depart_date: str,
        return_date: Optional[str] = None,
        travel_class: int = 1,
        currency: str = "INR",
    ) -> dict[str, Any]:

        self._validate_common(
            from_code=from_code,
            to_code=to_code,
            depart_date=depart_date,
            travel_class=travel_class,
            currency=currency,
        )

        from_code = from_code.strip().upper()
        to_code = to_code.strip().upper()
        depart_date = depart_date.strip()
        currency = currency.strip().upper()

        params = {
            "engine": "google_flights",
            "departure_id": from_code,
            "arrival_id": to_code,
            "outbound_date": depart_date,
            "travel_class": self.TRAVEL_CLASS_MAP[travel_class],
            "currency": currency,
            "hl": "en",
        }

        if return_date:
            params["type"] = "1"
            params["return_date"] = return_date.strip()
        else:
            params["type"] = "2"

        try:
            response = self.client.search(params)
            response = dict(response)
        except Exception as exc:
            logger.error("SerpAPI flight search failed | %s", exc)
            raise RuntimeError(
                "SerpAPI flight search failed"
            ) from exc

        self._validate_response(response)

        return response

    def get_selected_flight(
        self,
        departure_token: str,
        from_code: str,
        to_code: str,
        depart_date: str,
        return_date: Optional[str] = None,
        travel_class: int = 1,
        currency: str = "INR",
    ) -> dict[str, Any]:

        if not departure_token or not departure_token.strip():
            raise ValueError("departure_token is required")

        self._validate_common(
            from_code=from_code,
            to_code=to_code,
            depart_date=depart_date,
            travel_class=travel_class,
            currency=currency,
        )

        from_code = from_code.strip().upper()
        to_code = to_code.strip().upper()
        depart_date = depart_date.strip()
        currency = currency.strip().upper()

        params = {
            "engine": "google_flights",
            "departure_id": from_code,
            "arrival_id": to_code,
            "outbound_date": depart_date,
            "travel_class": self.TRAVEL_CLASS_MAP[travel_class],
            "currency": currency,
            "hl": "en",
            "departure_token": departure_token.strip(),
        }

        if return_date:
            params["type"] = "1"
            params["return_date"] = return_date.strip()
        else:
            params["type"] = "2"

        try:
            response = self.client.search(params)
            response = dict(response)
        except Exception as exc:
            logger.error(
                "SerpAPI selected flight request failed | %s",
                exc,
            )
            raise RuntimeError(
                "SerpAPI selected flight request failed"
            ) from exc

        self._validate_response(response)

        return response

    def _validate_common(
        self,
        from_code: str,
        to_code: str,
        depart_date: str,
        travel_class: int,
        currency: str,
    ):
        if not from_code:
            raise ValueError("from_code is required")

        if not to_code:
            raise ValueError("to_code is required")

        if not depart_date:
            raise ValueError("depart_date is required")

        if from_code.strip().upper() == to_code.strip().upper():
            raise ValueError(
                "From and To airports cannot be the same"
            )

        if travel_class not in self.TRAVEL_CLASS_MAP:
            raise ValueError(
                "travel_class must be between 1 and 4"
            )

        if not currency:
            raise ValueError("currency is required")

    @staticmethod
    def _validate_response(response: dict):
        if not isinstance(response, dict):
            raise RuntimeError(
                "SerpAPI returned invalid response"
            )

        if response.get("error"):
            raise RuntimeError(
                f"SerpAPI error: {response.get('error')}"
            )

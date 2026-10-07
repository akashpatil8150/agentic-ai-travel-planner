"""
API client for the existing FastAPI backend.

This module ONLY talks to the backend over HTTP. It contains no itinerary
generation, business rules, or agent logic.
"""

import os
from typing import Any

import requests


API_BASE_URL = os.environ.get(
    "API_BASE_URL",
    "http://localhost:8000",
).rstrip("/")

AUTH_TIMEOUT_SECONDS = 30
PLAN_TIMEOUT_SECONDS = 180


class ApiError(Exception):
    """Raised for backend HTTP or network failures."""

    def __init__(self, message: str, status_code: int = None):
        super().__init__(message)
        self.message = message
        self.status_code = status_code


def _extract_error_message(response: requests.Response, fallback: str) -> str:
    """Extract useful FastAPI/Pydantic error text without exposing raw HTML."""
    try:
        data = response.json()
    except (ValueError, requests.exceptions.JSONDecodeError):
        return fallback

    if not isinstance(data, dict):
        return fallback

    detail = data.get("detail")

    if isinstance(detail, str) and detail.strip():
        return detail.strip()

    if isinstance(detail, list):
        messages = []
        for item in detail:
            if isinstance(item, dict):
                loc_list = [
                    str(value)
                    for value in item.get("loc", [])
                    if value != "body"
                ]
                loc = " -> ".join(loc_list)
                msg = item.get("msg") or item.get("message")
                if msg:
                    messages.append(f"{loc}: {msg}" if loc else str(msg))
            elif isinstance(item, str) and item.strip():
                messages.append(item.strip())
        if messages:
            return "; ".join(messages)

    if isinstance(detail, dict):
        message = detail.get("message") or detail.get("error")
        if message:
            return str(message)

    message = data.get("message") or data.get("error")
    return str(message) if message else fallback


def _request(
    method: str,
    path: str,
    *,
    json_body: dict = None,
    headers: dict = None,
    timeout: int = AUTH_TIMEOUT_SECONDS,
) -> requests.Response:
    """Shared HTTP request helper with consistent network error handling."""
    if not isinstance(path, str) or not path.startswith("/"):
        raise ApiError("Invalid API path.")

    try:
        return requests.request(
            method=method.upper(),
            url=f"{API_BASE_URL}{path}",
            json=json_body,
            headers=headers,
            timeout=timeout,
        )
    except requests.exceptions.Timeout as exc:
        raise ApiError(
            "The server took too long to respond. Please try again."
        ) from exc
    except requests.exceptions.ConnectionError as exc:
        raise ApiError(
            "Could not reach the travel planning server. "
            "Please check that the backend is running."
        ) from exc
    except requests.exceptions.RequestException as exc:
        raise ApiError(
            "Something went wrong while contacting the server."
        ) from exc


def _post(
    path: str,
    json_body: dict,
    headers: dict = None,
    timeout: int = AUTH_TIMEOUT_SECONDS,
) -> requests.Response:
    return _request(
        "POST",
        path,
        json_body=json_body,
        headers=headers,
        timeout=timeout,
    )


def _get(
    path: str,
    headers: dict = None,
    timeout: int = AUTH_TIMEOUT_SECONDS,
) -> requests.Response:
    return _request(
        "GET",
        path,
        headers=headers,
        timeout=timeout,
    )


def _require_token(token: str) -> str:
    token = str(token or "").strip()
    if not token:
        raise ApiError("Authentication token is missing.")
    return token


def _auth_headers(token: str) -> dict:
    return {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {_require_token(token)}",
    }


def _parse_json_object(response: requests.Response, fallback: str) -> dict:
    try:
        data = response.json()
    except (ValueError, requests.exceptions.JSONDecodeError) as exc:
        raise ApiError(fallback, response.status_code) from exc

    if not isinstance(data, dict):
        raise ApiError("Unexpected response format from the server.", response.status_code)

    return data


def register_user(username: str, email: str, password: str) -> dict:
    """POST /api/auth/register."""
    username = str(username or "").strip()
    email = str(email or "").strip()
    password = str(password or "")

    if not username:
        raise ApiError("Username is required.")
    if not email:
        raise ApiError("Email is required.")
    if not password:
        raise ApiError("Password is required.")

    response = _post(
        "/api/auth/register",
        {
            "username": username,
            "email": email,
            "password": password,
        },
    )

    if not response.ok:
        raise ApiError(
            _extract_error_message(response, "Registration failed."),
            response.status_code,
        )

    try:
        return response.json()
    except (ValueError, requests.exceptions.JSONDecodeError):
        return {}


def login_user(email: str, password: str) -> dict:
    """POST /api/auth/login and return a normalized token response."""
    email = str(email or "").strip()
    password = str(password or "")

    if not email or not password:
        raise ApiError("Email and password are required.")

    response = _post(
        "/api/auth/login",
        {"email": email, "password": password},
    )

    if response.status_code == 401:
        raise ApiError("Invalid email or password.", 401)

    if not response.ok:
        raise ApiError(
            _extract_error_message(response, "Login failed."),
            response.status_code,
        )

    data = _parse_json_object(
        response,
        "Unexpected response from the server.",
    )

    token = data.get("access_token") or data.get("token")
    if not isinstance(token, str) or not token.strip():
        raise ApiError(
            "Login successful, but no access token was returned."
        )

    return {
        "token": token.strip(),
        "raw": data,
    }


def search_transport_options(token: str, payload: dict) -> dict:
    """POST /api/trips/search-transport."""
    if not isinstance(payload, dict) or not payload:
        raise ApiError("Transport search request is empty.")

    response = _post(
        "/api/trips/search-transport",
        payload,
        headers=_auth_headers(token),
        timeout=PLAN_TIMEOUT_SECONDS,
    )

    if response.status_code == 401:
        raise ApiError("Session expired. Please login again.", 401)

    if not response.ok:
        raise ApiError(
            _extract_error_message(
                response,
                "Failed to search transport options.",
            ),
            response.status_code,
        )

    return _parse_json_object(
        response,
        "Unexpected response from the transport search API.",
    )


def preview_budget(token: str, payload: dict) -> dict:
    """POST /api/trips/preview-budget."""
    if not isinstance(payload, dict) or not payload:
        raise ApiError("Budget preview request is empty.")

    response = _post(
        "/api/trips/preview-budget",
        payload,
        headers=_auth_headers(token),
        timeout=AUTH_TIMEOUT_SECONDS,
    )

    if response.status_code == 401:
        raise ApiError("Session expired. Please login again.", 401)

    if not response.ok:
        raise ApiError(
            _extract_error_message(
                response,
                "Failed to calculate budget preview.",
            ),
            response.status_code,
        )

    return _parse_json_object(
        response,
        "Unexpected response from the budget preview API.",
    )


def plan_trip(token: str, payload: dict) -> dict:
    """POST /api/trips/plan."""
    if not isinstance(payload, dict) or not payload:
        raise ApiError("Trip planning request is empty.")

    response = _post(
        "/api/trips/plan",
        payload,
        headers=_auth_headers(token),
        timeout=PLAN_TIMEOUT_SECONDS,
    )

    if response.status_code == 401:
        raise ApiError("Session expired. Please login again.", 401)

    if not response.ok:
        raise ApiError(
            _extract_error_message(response, "Failed to plan trip."),
            response.status_code,
        )

    return _parse_json_object(
        response,
        "Unexpected response from the planning API.",
    )


def select_hotel(token: str, planning_id: str, hotel_id: str) -> dict:
    """POST /api/trips/plan/{planning_id}/select-hotel."""
    planning_id = str(planning_id or "").strip()
    hotel_id = str(hotel_id or "").strip()

    if not planning_id:
        raise ApiError("Planning ID is missing.")
    if not hotel_id:
        raise ApiError("Hotel ID is missing.")

    response = _post(
        f"/api/trips/plan/{planning_id}/select-hotel",
        {"hotel_id": hotel_id},
        headers=_auth_headers(token),
        timeout=PLAN_TIMEOUT_SECONDS,
    )

    if response.status_code == 401:
        raise ApiError("Session expired. Please login again.", 401)

    if not response.ok:
        raise ApiError(
            _extract_error_message(
                response,
                "Failed to select hotel.",
            ),
            response.status_code,
        )

    return _parse_json_object(
        response,
        "Unexpected response from the hotel selection API.",
    )


def get_current_user(token: str) -> dict:
    """GET /api/auth/me."""
    response = _get(
        "/api/auth/me",
        headers=_auth_headers(token),
        timeout=AUTH_TIMEOUT_SECONDS,
    )

    if response.status_code == 401:
        raise ApiError("Session expired. Please login again.", 401)

    if not response.ok:
        raise ApiError(
            _extract_error_message(
                response,
                "Failed to fetch user profile.",
            ),
            response.status_code,
        )

    return _parse_json_object(
        response,
        "Unexpected response from the user profile API.",
    )


def create_trip(token: str, payload: dict) -> dict:
    """POST /api/trips/ and return the created trip record."""
    if not isinstance(payload, dict) or not payload:
        raise ApiError("Trip creation request is empty.")

    response = _post(
        "/api/trips/",
        payload,
        headers=_auth_headers(token),
        timeout=AUTH_TIMEOUT_SECONDS,
    )

    if response.status_code == 401:
        raise ApiError("Session expired. Please login again.", 401)

    if not response.ok:
        raise ApiError(
            _extract_error_message(
                response,
                "Failed to create trip.",
            ),
            response.status_code,
        )

    return _parse_json_object(
        response,
        "Unexpected response from the trip creation API.",
    )

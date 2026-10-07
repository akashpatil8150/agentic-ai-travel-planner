"""
Frontend validation for the AI Travel Planner.

Validation runs before HTTP calls so obviously invalid requests never reach
the FastAPI backend. This module contains validation / formatting helpers only.
"""

from datetime import date
import math
from numbers import Real

TRANSPORT_LABELS = {
    "train": "Train",
    "flight": "Flight",
}


def _is_leap_year(year: int) -> bool:
    return year % 4 == 0 and (year % 100 != 0 or year % 400 == 0)


def add_months(base_date: date, months: int) -> date:
    """Add calendar months and clamp the day for short months."""
    if not isinstance(base_date, date):
        raise TypeError("base_date must be a date")
    if not isinstance(months, int):
        raise TypeError("months must be an integer")

    month_index = base_date.month - 1 + months
    year = base_date.year + month_index // 12
    month = month_index % 12 + 1

    days_in_month = [
        31, 29 if _is_leap_year(year) else 28, 31, 30, 31, 30,
        31, 31, 30, 31, 30, 31,
    ]
    day = min(base_date.day, days_in_month[month - 1])
    return date(year, month, day)


def get_max_date(transport_preference: str, today: date = None) -> date:
    """
    Latest selectable trip date for a transport mode:
      - train: up to 2 calendar months from today
      - flight: up to 1 calendar year from today
    """
    today = today or date.today()
    mode = str(transport_preference or "").strip().lower()

    if mode == "train":
        return add_months(today, 2)
    if mode == "flight":
        return add_months(today, 12)

    # Keep the helper safe for UI callers while validation reports the
    # unsupported transport mode explicitly.
    return add_months(today, 12)


def parse_preferences(raw_text: str) -> list:
    """Split comma-separated preferences into clean, unique values."""
    if raw_text is None:
        return []
    if not isinstance(raw_text, str):
        raw_text = str(raw_text)

    result = []
    seen = set()
    for item in raw_text.split(","):
        value = item.strip()
        if value and value.casefold() not in seen:
            result.append(value)
            seen.add(value.casefold())
    return result


def extract_display_value(value) -> str:
    """
    Safely convert plain strings or common nested backend objects into
    readable display text. Never exposes raw dict representations.
    """
    if value is None:
        return ""

    if isinstance(value, str):
        return value.strip()

    if isinstance(value, dict):
        for key in ("city", "name", "label", "location", "display_name"):
            candidate = value.get(key)
            if candidate is not None:
                text = extract_display_value(candidate)
                if text:
                    return text
        return ""

    return str(value)


def _is_finite_number(value) -> bool:
    if isinstance(value, bool):
        return False
    if isinstance(value, Real):
        return math.isfinite(float(value))
    try:
        return math.isfinite(float(value))
    except (TypeError, ValueError):
        return False


def validate_trip_dates(
    start_date: date,
    end_date: date,
    transport_preference: str,
    today: date = None,
) -> list:
    """Return all date validation errors. Empty list means valid."""
    today = today or date.today()
    errors = []

    mode = str(transport_preference or "").strip().lower()
    if mode not in TRANSPORT_LABELS:
        errors.append("Please select a valid transport mode: Train or Flight.")

    if not isinstance(start_date, date):
        errors.append("Start date is required.")
    if not isinstance(end_date, date):
        errors.append("End date is required.")

    if not isinstance(start_date, date) or not isinstance(end_date, date):
        return errors

    if start_date < today:
        errors.append("Start date cannot be before today.")
    if end_date < today:
        errors.append("End date cannot be before today.")
    if end_date < start_date:
        errors.append("End date cannot be before start date.")

    if mode in TRANSPORT_LABELS:
        max_date = get_max_date(mode, today)
        if start_date > max_date or end_date > max_date:
            if mode == "train":
                errors.append(
                    f"Train dates must be within 2 months from today "
                    f"(on or before {max_date.isoformat()})."
                )
            else:
                errors.append(
                    f"Flight dates must be within 1 year from today "
                    f"(on or before {max_date.isoformat()})."
                )

    return errors


def validate_trip_input(
    origin: str,
    destination: str,
    start_date: date,
    end_date: date,
    adults: int,
    children: int,
    budget: float | None,
    transport_preference: str,
) -> list:
    """Validate every planner field before an API request."""
    errors = []

    origin_text = str(origin or "").strip()
    destination_text = str(destination or "").strip()

    if not origin_text:
        errors.append("Origin is required.")
    if not destination_text:
        errors.append("Destination is required.")

    if (
        origin_text
        and destination_text
        and origin_text.casefold() == destination_text.casefold()
    ):
        errors.append("Origin and destination cannot be the same.")

    mode = str(transport_preference or "").strip().lower()
    if mode not in TRANSPORT_LABELS:
        errors.append("Please select a valid transport mode: Train or Flight.")

    if isinstance(adults, bool) or not isinstance(adults, int) or adults < 1:
        errors.append("At least 1 adult is required.")

    if isinstance(children, bool) or not isinstance(children, int) or children < 0:
        errors.append("Children cannot be negative.")

    if budget is not None:
        if not _is_finite_number(budget):
            errors.append("Budget must be a valid number.")
        elif float(budget) < 0:
            errors.append("Budget cannot be negative.")

    errors.extend(
        validate_trip_dates(
            start_date=start_date,
            end_date=end_date,
            transport_preference=mode,
        )
    )
    return errors

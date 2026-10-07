"""
ExactTransportCache Module
Dedicated in-memory exact transport-result cache for TrainService.

Identity Contract:
A cached result is uniquely identified by the exact 6-tuple:
(train_number, origin_station_code, destination_station_code, travel_date, class_code, quota_code)

Constraints:
- In-memory process-local cache (resets on application restart).
- Case, whitespace, and date canonical normalization.
- No fuzzy matching, no matching by train name only, no route-only matching.
- Exact travel date matching is mandatory regardless of TTL.
- Re-validation (route, date, station identity) is strictly required on retrieval.
"""

import copy
import logging
import re
import time
from datetime import date as date_type
from typing import Any, Dict, List, Optional, Tuple, Union

from app.services.train.train_schema import TrainResponse, Station, TrainFare

logger = logging.getLogger(__name__)


def normalize_station_code(code: Any) -> str:
    """Strip whitespace and uppercase station code."""
    if not code:
        return ""
    return str(code).strip().upper()


def normalize_train_number(train_num: Any) -> str:
    """Strip whitespace from train number."""
    if not train_num:
        return ""
    return str(train_num).strip()


def normalize_date(d: Any) -> str:
    """Normalize date to canonical YYYY-MM-DD representation."""
    if not d:
        return ""
    if isinstance(d, date_type):
        return d.isoformat()
    s = str(d).strip()
    try:
        # Validate format
        dt = date_type.fromisoformat(s)
        return dt.isoformat()
    except (ValueError, TypeError):
        return s


def normalize_class_code(c: Any) -> str:
    """Strip whitespace and uppercase class code."""
    if not c:
        return "ALL"
    return str(c).strip().upper()


def normalize_quota_code(q: Any) -> str:
    """Strip whitespace and uppercase quota code."""
    if not q:
        return "GN"
    return str(q).strip().upper()


def make_cache_key(
    train_number: Any,
    origin_station_code: Any,
    destination_station_code: Any,
    travel_date: Any,
    class_code: Any = "ALL",
    quota_code: Any = "GN",
) -> Tuple[str, str, str, str, str, str]:
    """
    Construct the canonical exact cache key 6-tuple:
    (train_number, origin_station_code, destination_station_code, travel_date, class_code, quota_code)
    """
    return (
        normalize_train_number(train_number),
        normalize_station_code(origin_station_code),
        normalize_station_code(destination_station_code),
        normalize_date(travel_date),
        normalize_class_code(class_code),
        normalize_quota_code(quota_code),
    )


class ExactTransportEntry:
    """Represents a validated cached transport result."""

    def __init__(
        self,
        train_number: str,
        origin_station_code: str,
        destination_station_code: str,
        travel_date: str,
        class_code: str,
        quota_code: str,
        train_data: Any,
        cached_at: Optional[float] = None,
        ttl_seconds: float = 86400.0,
    ):
        self.train_number = train_number
        self.origin_station_code = origin_station_code
        self.destination_station_code = destination_station_code
        self.travel_date = travel_date
        self.class_code = class_code
        self.quota_code = quota_code
        self.train_data = train_data
        self.cached_at = cached_at if cached_at is not None else time.time()
        self.ttl_seconds = ttl_seconds

    def is_expired(self) -> bool:
        """Check if cache entry has expired past its TTL."""
        return (time.time() - self.cached_at) > self.ttl_seconds


class ExactTransportCache:
    """
    Process-local in-memory exact transport cache.
    Stores and retrieves structured, validated train objects.
    """

    DEFAULT_TTL_SECONDS: float = 86400.0  # 24 hours

    def __init__(self, ttl_seconds: float = DEFAULT_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._cache: Dict[Tuple[str, str, str, str, str, str], ExactTransportEntry] = {}

    def clear(self) -> None:
        """Clear all cached entries."""
        self._cache.clear()

    def __len__(self) -> int:
        return len(self._cache)

    def store_train(
        self,
        train: Any,
        from_code: str,
        to_code: str,
        date: str,
        class_code: Optional[str] = None,
        quota_code: str = "GN",
    ) -> List[Tuple[str, str, str, str, str, str]]:
        """
        Store a validated train in the exact cache.
        Stores entries for specific classes as well as general "ALL" class.
        Only called AFTER route and date validation have passed.
        """
        if not train:
            return []

        t_num = getattr(train, "train_number", None) if hasattr(train, "train_number") else (train.get("train_number") if isinstance(train, dict) else None)
        if not t_num:
            return []

        norm_num = normalize_train_number(t_num)
        norm_from = normalize_station_code(from_code)
        norm_to = normalize_station_code(to_code)
        norm_date = normalize_date(date)
        norm_quota = normalize_quota_code(quota_code)

        if not norm_num or not norm_from or not norm_to or not norm_date:
            return []

        # Create a deep copy of train data to isolate cache from mutations
        stored_obj = copy.deepcopy(train)
        if hasattr(stored_obj, "train_number"):
            stored_obj.train_number = norm_num
        elif isinstance(stored_obj, dict):
            stored_obj["train_number"] = norm_num
        if hasattr(stored_obj, "from_code"):
            stored_obj.from_code = norm_from
        elif isinstance(stored_obj, dict):
            stored_obj["from_code"] = norm_from
        if hasattr(stored_obj, "to_code"):
            stored_obj.to_code = norm_to
        elif isinstance(stored_obj, dict):
            stored_obj["to_code"] = norm_to
        if hasattr(stored_obj, "boarding_station_code"):
            stored_obj.boarding_station_code = norm_from
        if hasattr(stored_obj, "alighting_station_code"):
            stored_obj.alighting_station_code = norm_to

        # Collect classes to index
        classes_to_index = set()
        if class_code and str(class_code).strip():
            classes_to_index.add(normalize_class_code(class_code))

        # Inspect classes/fares in train object
        train_classes = getattr(train, "classes", None) if hasattr(train, "classes") else (train.get("classes") if isinstance(train, dict) else None)
        if isinstance(train_classes, list):
            for c in train_classes:
                if c:
                    classes_to_index.add(normalize_class_code(c))

        train_fares = getattr(train, "fares", None) if hasattr(train, "fares") else (train.get("fares") if isinstance(train, dict) else None)
        if isinstance(train_fares, list):
            for f in train_fares:
                c = getattr(f, "class_code", None) if hasattr(f, "class_code") else (f.get("class_code") if isinstance(f, dict) else None)
                if c:
                    classes_to_index.add(normalize_class_code(c))

        # Always include "ALL" to allow general queries
        classes_to_index.add("ALL")

        stored_keys = []
        for c_code in classes_to_index:
            key = (norm_num, norm_from, norm_to, norm_date, c_code, norm_quota)
            entry = ExactTransportEntry(
                train_number=norm_num,
                origin_station_code=norm_from,
                destination_station_code=norm_to,
                travel_date=norm_date,
                class_code=c_code,
                quota_code=norm_quota,
                train_data=stored_obj,
                ttl_seconds=self.ttl_seconds,
            )
            self._cache[key] = entry
            stored_keys.append(key)
            print(f"[EXACT CACHE] STORED: train={norm_num} route={norm_from}->{norm_to} date={norm_date} class={c_code} quota={norm_quota}")
            logger.info("[EXACT CACHE] STORED: train=%s route=%s->%s date=%s class=%s quota=%s", norm_num, norm_from, norm_to, norm_date, c_code, norm_quota)

        return stored_keys

    def get_exact(
        self,
        train_number: str,
        from_code: str,
        to_code: str,
        date: str,
        class_code: str = "ALL",
        quota_code: str = "GN",
    ) -> Optional[Any]:
        """
        Retrieve a cached train by exact 6-tuple identity.
        Returns a fresh copy of the train object if matched and not expired, else None.
        """
        key = make_cache_key(train_number, from_code, to_code, date, class_code, quota_code)
        entry = self._cache.get(key)

        if entry is None:
            print(f"[EXACT CACHE] MISS: train={key[0]} route={key[1]}->{key[2]} date={key[3]} class={key[4]} quota={key[5]}")
            return None

        if entry.is_expired():
            print(f"[EXACT CACHE] REJECTED: train={key[0]} reason=expired")
            del self._cache[key]
            return None

        print(f"[EXACT CACHE] HIT: train={entry.train_number} route={entry.origin_station_code}->{entry.destination_station_code} date={entry.travel_date}")
        logger.info("[EXACT CACHE] HIT: train=%s route=%s->%s date=%s", entry.train_number, entry.origin_station_code, entry.destination_station_code, entry.travel_date)

        train_copy = copy.deepcopy(entry.train_data)
        if isinstance(train_copy, dict):
            train_copy["data_source"] = "cache"
            train_copy["provider"] = "cache"
        else:
            if hasattr(train_copy, "data_source"):
                train_copy.data_source = "cache"
            if hasattr(train_copy, "provider"):
                train_copy.provider = "cache"
        return train_copy

    def find_trains(
        self,
        from_code: str,
        to_code: str,
        date: str,
        quota_code: str = "GN",
        class_code: Optional[str] = None,
    ) -> List[Any]:
        """
        Find all cached trains matching exact route, travel date, and quota.
        Deduplicates by train number.
        Returns fresh copies of matching validated train objects.
        """
        norm_from = normalize_station_code(from_code)
        norm_to = normalize_station_code(to_code)
        norm_date = normalize_date(date)
        norm_quota = normalize_quota_code(quota_code)
        norm_class = normalize_class_code(class_code) if class_code else None

        if not norm_from or not norm_to or not norm_date:
            return []

        matched_trains = []
        seen_train_numbers = set()

        for key, entry in list(self._cache.items()):
            # Exact identity checks
            if entry.origin_station_code != norm_from:
                continue
            if entry.destination_station_code != norm_to:
                continue
            if entry.travel_date != norm_date:
                continue
            if entry.quota_code != norm_quota:
                continue
            if norm_class and norm_class != "ALL" and entry.class_code not in (norm_class, "ALL"):
                continue

            if entry.is_expired():
                del self._cache[key]
                continue

            t_num = entry.train_number
            if t_num in seen_train_numbers:
                continue

            seen_train_numbers.add(t_num)
            train_copy = copy.deepcopy(entry.train_data)
            if isinstance(train_copy, dict):
                train_copy["data_source"] = "cache"
                train_copy["provider"] = "cache"
            else:
                if hasattr(train_copy, "data_source"):
                    train_copy.data_source = "cache"
                if hasattr(train_copy, "provider"):
                    train_copy.provider = "cache"

            print(f"[EXACT CACHE] HIT: train={t_num} route={norm_from}->{norm_to} date={norm_date}")
            logger.info("[EXACT CACHE] HIT: train=%s route=%s->%s date=%s", t_num, norm_from, norm_to, norm_date)
            matched_trains.append(train_copy)

        if not matched_trains:
            print(f"[EXACT CACHE] MISS: route={norm_from}->{norm_to} date={norm_date}")
            logger.info("[EXACT CACHE] MISS: route=%s->%s date=%s", norm_from, norm_to, norm_date)

        return matched_trains


# Global singleton instance for process-local caching
exact_transport_cache = ExactTransportCache()

from app.services.train.train_schema import (
    TrainResponse,
    Station,
    TrainFare,
    TrainAvailability,
)


# ============================================================
# SAFE HELPERS
# ============================================================

def _safe_list(value):

    if isinstance(value, list):
        return value

    return []


def _safe_dict(value):

    if isinstance(value, dict):
        return value

    return {}


# ============================================================
# RAILRADAR TRAIN NORMALIZER
# ============================================================

def normalize_railradar_train(
    train: dict,
) -> TrainResponse:

    train = _safe_dict(train)

    train_info = _safe_dict(
        train.get("train")
    )

    from_info = _safe_dict(
        train.get("from")
    )

    to_info = _safe_dict(
        train.get("to")
    )

    src_code = str(from_info.get("code") or train.get("from_station_code") or train.get("from_code") or train.get("source_code") or "").strip().upper()
    src_name = str(from_info.get("name") or train.get("from_station_name") or train.get("from_name") or train.get("source_name") or src_code).strip()
    dst_code = str(to_info.get("code") or train.get("to_station_code") or train.get("to_code") or train.get("destination_code") or "").strip().upper()
    dst_name = str(to_info.get("name") or train.get("to_station_name") or train.get("to_name") or train.get("destination_name") or dst_code).strip()

    t_num = str(train_info.get("number") or train.get("train_number") or train.get("number") or "").strip()
    t_name = str(train_info.get("name") or train.get("train_name") or train.get("name") or "").strip()
    t_type = train_info.get("type") or train.get("train_type") or train.get("type")

    dep_time = from_info.get("departure") or train.get("departure_time") or train.get("departure")
    arr_time = to_info.get("arrival") or train.get("arrival_time") or train.get("arrival")
    dur_min = train.get("duration") or train.get("duration_minutes")
    dist_km = train.get("distance") or train.get("distance_km")
    halts = train.get("totalHaltsBetween") or train.get("total_halts") or train.get("halts")
    run_days = _safe_list(
        train_info.get("runDays") or train.get("running_days") or train.get("run_days") or train_info.get("running_days") or []
    )

    actual_train_orig_display = f"{src_name} ({src_code})" if src_code and src_name != src_code else src_name
    actual_train_dest_display = f"{dst_name} ({dst_code})" if dst_code and dst_name != dst_code else dst_name

    return TrainResponse(

        train_number=t_num,

        train_name=t_name,

        train_type=t_type,

        source=Station(
            code=src_code,
            name=src_name,
        ),

        destination=Station(
            code=dst_code,
            name=dst_name,
        ),

        departure_time=dep_time,

        arrival_time=arr_time,

        duration_minutes=dur_min,

        distance_km=dist_km,

        total_halts=halts,

        running_days=run_days,

        classes=[],

        fares=[],

        availability=[],

        provider="railradar",

        train_origin_station=src_code,
        train_destination_station=dst_code,
        boarding_station=src_code,
        alighting_station=dst_code,
        boarding_station_code=src_code,
        boarding_station_name=src_name,
        alighting_station_code=dst_code,
        alighting_station_name=dst_name,

        actual_origin_station=src_code,
        actual_destination_station=dst_code,
        actual_train_origin=actual_train_orig_display,
        actual_train_destination=actual_train_dest_display,
        from_station_code=src_code,
        to_station_code=dst_code,
        from_station_name=src_name,
        to_station_name=dst_name,
        from_code=src_code,
        to_code=dst_code,
        stations=train.get("stations") or train.get("stops") or train.get("route"),
        stops=train.get("stops"),
        route=train.get("route"),
    )


# ============================================================
# RAILCORE TRAIN NORMALIZER
# ============================================================

def normalize_railcore_train(
    train: dict,
    from_code: str,
    to_code: str,
) -> TrainResponse:

    train = _safe_dict(train)

    fares = []

    availability = []

    for item in _safe_list(
        train.get(
            "availability_summary",
            []
        )
    ):

        item = _safe_dict(item)

        class_code = item.get(
            "class_code",
            ""
        )

        if class_code:

            fares.append(
                TrainFare(
                    class_code=str(
                        class_code
                    ),
                    amount=item.get(
                        "fare"
                    ),
                    currency=item.get(
                        "currency",
                        "INR",
                    ),
                )
            )

            availability.append(
                TrainAvailability(
                    class_code=str(
                        class_code
                    ),
                    status=item.get(
                        "status"
                    ),
                    text=item.get(
                        "text"
                    ),
                    confidence=item.get(
                        "confidence"
                    ),
                )
            )

    src_code = str(train.get("from_station_code") or train.get("source_code") or train.get("from_code") or train.get("from") or from_code or "").strip().upper()
    src_name = str(train.get("from_station_name") or train.get("source_name") or train.get("from_name") or src_code).strip()
    dst_code = str(train.get("to_station_code") or train.get("destination_code") or train.get("to_code") or train.get("to") or to_code or "").strip().upper()
    dst_name = str(train.get("to_station_name") or train.get("destination_name") or train.get("to_name") or dst_code).strip()

    t_num = str(train.get("train_number", "")).strip()
    t_name = str(train.get("train_name", "")).strip()

    actual_train_orig_display = f"{src_name} ({src_code})" if src_code and src_name != src_code else src_name
    actual_train_dest_display = f"{dst_name} ({dst_code})" if dst_code and dst_name != dst_code else dst_name

    return TrainResponse(

        train_number=t_num,

        train_name=t_name,

        train_type=train.get(
            "train_type"
        ),

        source=Station(
            code=src_code,
            name=src_name,
        ),

        destination=Station(
            code=dst_code,
            name=dst_name,
        ),

        departure_time=train.get(
            "departure_time"
        ),

        arrival_time=train.get(
            "arrival_time"
        ),

        duration_minutes=train.get(
            "duration_minutes"
        ),

        distance_km=train.get(
            "distance_km"
        ),

        total_halts=None,

        running_days=_safe_list(
            train.get(
                "running_days",
                []
            )
        ),

        classes=_safe_list(
            train.get(
                "classes",
                []
            )
        ),

        fares=fares,

        availability=availability,

        provider="railcore",

        train_origin_station=src_code,
        train_destination_station=dst_code,
        boarding_station=src_code,
        alighting_station=dst_code,
        boarding_station_code=src_code,
        boarding_station_name=src_name,
        alighting_station_code=dst_code,
        alighting_station_name=dst_name,

        actual_origin_station=src_code,
        actual_destination_station=dst_code,
        actual_train_origin=actual_train_orig_display,
        actual_train_destination=actual_train_dest_display,
        from_station_code=src_code,
        to_station_code=dst_code,
        from_station_name=src_name,
        to_station_name=dst_name,
        from_code=src_code,
        to_code=dst_code,
        stations=train.get("stations") or train.get("stops") or train.get("route"),
        stops=train.get("stops"),
        route=train.get("route"),
    )


# ============================================================
# TRAIN DETAILS NORMALIZER
# ============================================================

def normalize_train_details(
    fare_data: dict | None,
    availability_data: dict | None,
    train_number: str,
    from_code: str,
    to_code: str,
    date: str,
    class_code: str,
    quota_code: str,
    provider: str,
):

    fare = None

    availability = []

    fare_data = _safe_dict(
        fare_data
    )

    availability_data = _safe_dict(
        availability_data
    )

    # ========================================================
    # RAILRADAR
    # ========================================================

    if provider == "railradar":

        # ----------------------------------------------------
        # FARE
        # ----------------------------------------------------

        breakdown = _safe_dict(
            fare_data.get(
                "breakdown"
            )
        )

        if breakdown:

            fare = {
                "amount": breakdown.get(
                    "totalFare"
                ),

                "currency": "INR",

                "base_fare": breakdown.get(
                    "baseFare"
                ),

                "reservation_charge": breakdown.get(
                    "reservationCharge"
                ),

                "superfast_charge": breakdown.get(
                    "superfastCharge"
                ),

                "gst": breakdown.get(
                    "goodsServiceTax"
                ),

                "catering_charge": breakdown.get(
                    "cateringCharge"
                ),

                "dynamic_fare": breakdown.get(
                    "dynamicFare"
                ),
            }

        # ----------------------------------------------------
        # AVAILABILITY
        # ----------------------------------------------------

        calendar = _safe_list(
            availability_data.get(
                "calendar",
                []
            )
        )

        for item in calendar:

            item = _safe_dict(item)

            item_date = item.get(
                "date"
            )

            raw_date = item.get(
                "rawDate"
            )

            if (
                item_date == date
                or raw_date == date
            ):

                availability.append(
                    {
                        "date": (
                            item_date
                            or raw_date
                        ),

                        "status": item.get(
                            "statusCode"
                        ),

                        "text": item.get(
                            "status"
                        ),

                        "available": item.get(
                            "isAvailable"
                        ),

                        "available_seats": item.get(
                            "availableSeats"
                        ),

                        "waitlist_number": item.get(
                            "waitlistNumber"
                        ),

                        "waitlist_type": item.get(
                            "waitlistType"
                        ),
                    }
                )

                break

    # ========================================================
    # RAILCORE
    # ========================================================

    elif provider == "railcore":

        # ----------------------------------------------------
        # FARE
        # ----------------------------------------------------

        fare_amount = fare_data.get(
            "fare"
        )

        if fare_amount is not None:

            fare = {
                "amount": fare_amount,

                "currency": fare_data.get(
                    "currency",
                    "INR"
                ),

                "base_fare": None,

                "reservation_charge": None,

                "superfast_charge": None,

                "gst": None,

                "catering_charge": fare_data.get(
                    "catering_charge"
                ),

                "dynamic_fare": None,
            }

        # ----------------------------------------------------
        # AVAILABILITY
        # ----------------------------------------------------

        classes = _safe_list(
            availability_data.get(
                "classes",
                []
            )
        )

        for item in classes:

            item = _safe_dict(item)

            if (
                str(
                    item.get(
                        "class_code",
                        ""
                    )
                ).upper()
                != class_code.upper()
            ):
                continue

            available_count = item.get(
                "available_count"
            )

            if not isinstance(
                available_count,
                int
            ):
                available_count = 0

            availability.append(
                {
                    "date": availability_data.get(
                        "journey_date",
                        date
                    ),

                    "status": item.get(
                        "status"
                    ),

                    "text": item.get(
                        "availability_text"
                    ),

                    "available": (
                        available_count > 0
                    ),

                    "available_seats": (
                        item.get(
                            "available_count"
                        )
                    ),

                    "waitlist_number": item.get(
                        "waitlist_count"
                    ),

                    "waitlist_type": item.get(
                        "wl_pool"
                    ),
                }
            )

            break

    # ========================================================
    # COMMON RESPONSE
    # ========================================================

    return {
        "train_number": train_number,

        "source": {
            "code": from_code,
            "name": None,
        },

        "destination": {
            "code": to_code,
            "name": None,
        },

        "journey_date": date,

        "class_code": class_code,

        "quota_code": quota_code,

        "fare": fare,

        "availability": availability,

        "provider": provider,
    }
import logging

logger = logging.getLogger(__name__)

from typing import Any

from app.services.hotel.hotel_schema import HotelOption


class HotelNormalizer:

    @staticmethod
    def _normalize_rating(value):
        """Normalize provider ratings to a strict 0-5 scale."""
        try:
            rating = float(value)
        except (TypeError, ValueError):
            return None
        if rating <= 0:
            return None
        if rating <= 5:
            return round(rating, 1)
        if rating <= 10:
            return round(rating / 2.0, 1)
        return None

    """
    Converts provider-specific hotel responses
    into the common HotelOption model.

    Responsibilities:
        - Safely read provider responses
        - Reject malformed hotel records
        - Normalize LiteAPI data
        - Normalize SerpAPI data

    Does NOT:
        - call APIs
        - perform request validation
        - decide provider fallback
    """

    # ========================================================
    # LITEAPI NORMALIZER
    # ========================================================

    @staticmethod
    def normalize_liteapi(
        result: dict,
        max_hotels: int = 5,
    ) -> list[HotelOption]:

        hotels: list[HotelOption] = []

        if not isinstance(result, dict):
            return hotels

        if max_hotels < 1:
            return hotels

        data = result.get("data", [])

        if not isinstance(data, list):
            logger.warning(
                "LiteAPI normalization skipped | reason=data_not_list | type=%s",
                type(data).__name__,
            )
            return hotels

        logger.info(
            "LiteAPI normalization started | raw_rate_records=%s | hotel_details=%s",
            len(data),
            len(result.get("hotels", []))
            if isinstance(result.get("hotels", []), list)
            else 0,
        )

        hotel_details = result.get("hotels", [])

        if not isinstance(hotel_details, list):
            hotel_details = []

        # ----------------------------------------------------
        # HOTEL LOOKUP
        # ----------------------------------------------------

        hotel_lookup: dict[str, dict] = {}

        for hotel in hotel_details:

            if not isinstance(hotel, dict):
                continue

            hotel_id = hotel.get("id")

            if hotel_id is not None:
                hotel_lookup[str(hotel_id)] = hotel

        # ----------------------------------------------------
        # PROCESS HOTELS
        # ----------------------------------------------------

        processed_count = 0
        rejected_count = 0

        for hotel in data:

            if len(hotels) >= max_hotels:
                break

            if not isinstance(hotel, dict):
                rejected_count += 1
                logger.warning(
                    "LiteAPI normalization skip | reason=record_not_dict | type=%s",
                    type(hotel).__name__,
                )
                continue

            processed_count += 1
            hotel_id = hotel.get("hotelId")

            if hotel_id is None:
                rejected_count += 1
                logger.warning(
                    "LiteAPI normalization skip | reason=missing_hotel_id | keys=%s",
                    list(hotel.keys())[:20],
                )
                continue

            hotel_info = hotel_lookup.get(
                str(hotel_id),
                {},
            )

            if not isinstance(hotel_info, dict):
                hotel_info = {}

            # ------------------------------------------------
            # BASIC INFORMATION
            # ------------------------------------------------

            hotel_name = (
                hotel_info.get("name")
                or hotel.get("name")
                or "Hotel"
            )

            if not isinstance(hotel_name, str):
                hotel_name = "Hotel"

            hotel_name = hotel_name.strip()

            if not hotel_name:
                hotel_name = "Hotel"

            rating = HotelNormalizer._normalize_rating(hotel_info.get("rating"))

            address = hotel_info.get("address")

            location_data = hotel_info.get("location") or hotel.get("location") or {}
            latitude = (
                hotel_info.get("latitude")
                or hotel_info.get("lat")
                or (location_data.get("latitude") if isinstance(location_data, dict) else None)
                or (location_data.get("lat") if isinstance(location_data, dict) else None)
            )
            longitude = (
                hotel_info.get("longitude")
                or hotel_info.get("lng")
                or hotel_info.get("lon")
                or (location_data.get("longitude") if isinstance(location_data, dict) else None)
                or (location_data.get("lng") if isinstance(location_data, dict) else None)
                or (location_data.get("lon") if isinstance(location_data, dict) else None)
            )

            photo = hotel_info.get("main_photo")

            # ------------------------------------------------
            # ROOM TYPES
            # ------------------------------------------------

            room_types = hotel.get(
                "roomTypes",
                [],
            )

            if not isinstance(room_types, list):
                rejected_count += 1
                logger.warning(
                    "LiteAPI normalization skip | hotel_id=%s | reason=room_types_not_list | type=%s",
                    hotel_id,
                    type(room_types).__name__,
                )
                continue

            if not room_types:
                rejected_count += 1
                logger.warning(
                    "LiteAPI normalization skip | hotel_id=%s | reason=empty_room_types",
                    hotel_id,
                )
                continue

            room = room_types[0]

            if not isinstance(room, dict):
                rejected_count += 1
                logger.warning(
                    "LiteAPI normalization skip | hotel_id=%s | reason=room_not_dict",
                    hotel_id,
                )
                continue

            offer_id = room.get("offerId")

            if not offer_id:
                rejected_count += 1
                logger.warning(
                    "LiteAPI normalization skip | hotel_id=%s | reason=missing_offer_id | room_keys=%s",
                    hotel_id,
                    list(room.keys())[:20],
                )
                continue

            # ------------------------------------------------
            # RATES
            # ------------------------------------------------

            rates = room.get(
                "rates",
                [],
            )

            if not isinstance(rates, list):
                rejected_count += 1
                logger.warning(
                    "LiteAPI normalization skip | hotel_id=%s | reason=rates_not_list | type=%s",
                    hotel_id,
                    type(rates).__name__,
                )
                continue

            if not rates:
                rejected_count += 1
                logger.warning(
                    "LiteAPI normalization skip | hotel_id=%s | reason=empty_rates",
                    hotel_id,
                )
                continue

            rate = rates[0]

            if not isinstance(rate, dict):
                rejected_count += 1
                logger.warning(
                    "LiteAPI normalization skip | hotel_id=%s | reason=rate_not_dict",
                    hotel_id,
                )
                continue

            room_name = rate.get("name")

            board_name = rate.get("boardName")

            # ------------------------------------------------
            # PRICE
            # ------------------------------------------------

            retail_rate = rate.get(
                "retailRate",
                {},
            )

            if not isinstance(retail_rate, dict):
                retail_rate = {}

            total = retail_rate.get(
                "total",
                [],
            )

            price = None
            currency = "INR"

            if isinstance(total, list) and total:

                total_info = total[0]

                if isinstance(
                    total_info,
                    dict,
                ):

                    price = total_info.get(
                        "amount"
                    )

                    currency = total_info.get(
                        "currency",
                        "INR",
                    )

            if not isinstance(currency, str):
                currency = "INR"

            currency = currency.upper()

            # ------------------------------------------------
            # TAXES
            # ------------------------------------------------

            taxes = retail_rate.get(
                "taxesAndFees",
                [],
            )

            taxes_text = None

            if isinstance(taxes, list) and taxes:

                valid_taxes = [
                    tax
                    for tax in taxes
                    if isinstance(tax, dict)
                ]

                if valid_taxes:

                    included = all(
                        tax.get(
                            "included",
                            False,
                        )
                        is True
                        for tax in valid_taxes
                    )

                    taxes_text = (
                        "Included"
                        if included
                        else "Additional"
                    )

            # ------------------------------------------------
            # CANCELLATION
            # ------------------------------------------------

            cancellation_policies = (
                rate.get(
                    "cancellationPolicies",
                    {},
                )
            )

            if not isinstance(
                cancellation_policies,
                dict,
            ):
                cancellation_policies = {}

            refundable_tag = (
                cancellation_policies.get(
                    "refundableTag"
                )
            )

            if refundable_tag == "RFN":

                cancellation = "Refundable"

            elif refundable_tag == "NRFN":

                cancellation = "Non-refundable"

            else:

                cancellation = "Not specified"

            # ------------------------------------------------
            # CANCELLATION DEADLINE
            # ------------------------------------------------

            cancel_infos = (
                cancellation_policies.get(
                    "cancelPolicyInfos",
                    [],
                )
            )

            cancellation_deadline = None

            if (
                isinstance(
                    cancel_infos,
                    list,
                )
                and cancel_infos
            ):

                first_policy = cancel_infos[0]

                if isinstance(
                    first_policy,
                    dict,
                ):

                    cancellation_deadline = (
                        first_policy.get(
                            "cancelTime"
                        )
                    )

            # ------------------------------------------------
            # CREATE COMMON OBJECT
            # ------------------------------------------------

            try:

                hotels.append(
                    HotelOption(
                        hotel_id=str(hotel_id),
                        hotel_name=hotel_name,
                        rating=rating,
                        address=address,
                        photo=photo,
                        room_name=room_name,
                        board_name=board_name,
                        price=price,
                        currency=currency,
                        taxes=taxes_text,
                        cancellation=cancellation,
                        cancellation_deadline=(
                            cancellation_deadline
                        ),
                        offer_id=str(offer_id),
                        provider="liteapi",
                        raw_data=hotel,
                    )
                )
                if hotels:
                    if latitude is not None:
                        hotels[-1].latitude = latitude
                    if longitude is not None:
                        hotels[-1].longitude = longitude

            except Exception as exc:
                rejected_count += 1
                logger.warning(
                    "LiteAPI normalization rejected hotel | "
                    "hotel_id=%s | hotel_name=%s | error=%s",
                    hotel_id,
                    hotel_name,
                    exc,
                )
                continue

        logger.info(
            "LiteAPI normalization completed | "
            "raw_rate_records=%s | processed=%s | "
            "usable_hotels=%s | rejected=%s",
            len(data),
            processed_count,
            len(hotels),
            rejected_count,
        )
        return hotels

    # ========================================================
    # SERPAPI NORMALIZER
    # ========================================================

    @staticmethod
    def normalize_serpapi(
        result: dict,
        max_hotels: int = 5,
    ) -> list[HotelOption]:

        hotels: list[HotelOption] = []

        if not isinstance(result, dict):
            return hotels

        if max_hotels < 1:
            return hotels

        properties = result.get(
            "properties",
            [],
        )

        if not isinstance(properties, list):
            logger.warning(
                "SerpAPI normalization skipped | reason=properties_not_list | type=%s",
                type(properties).__name__,
            )
            return hotels

        logger.info(
            "SerpAPI normalization started | raw_properties=%s",
            len(properties),
        )

        rejected_count = 0
        processed_count = 0

        for hotel in properties:

            if len(hotels) >= max_hotels:
                break

            if not isinstance(hotel, dict):
                rejected_count += 1
                logger.warning(
                    "SerpAPI normalization skip | reason=property_not_dict | type=%s",
                    type(hotel).__name__,
                )
                continue

            processed_count += 1

            # ------------------------------------------------
            # BASIC INFORMATION
            # ------------------------------------------------

            name = hotel.get(
                "name",
                "Hotel",
            )

            if not isinstance(name, str):
                name = "Hotel"

            name = name.strip()

            if not name:
                name = "Hotel"

            rating = HotelNormalizer._normalize_rating(hotel.get(
                "overall_rating"
            ))

            address = hotel.get(
                "address"
            )

            if not address:
                address = hotel.get(
                    "location"
                )

            # ------------------------------------------------
            # GPS FALLBACK
            # ------------------------------------------------

            if not address:

                gps = hotel.get(
                    "gps_coordinates",
                    {},
                )

                if isinstance(gps, dict):

                    latitude = gps.get(
                        "latitude"
                    )

                    longitude = gps.get(
                        "longitude"
                    )

                    if (
                        latitude is not None
                        and longitude is not None
                    ):

                        address = (
                            f"{latitude}, "
                            f"{longitude}"
                        )

            # ------------------------------------------------
            # PRICE
            # ------------------------------------------------

            rate_per_night = hotel.get(
                "rate_per_night",
                {},
            )

            if not isinstance(
                rate_per_night,
                dict,
            ):
                rate_per_night = {}

            price_per_night = (
                rate_per_night.get(
                    "extracted_lowest"
                )
            )

            total_rate = hotel.get(
                "total_rate",
                {},
            )

            if not isinstance(
                total_rate,
                dict,
            ):
                total_rate = {}

            total_price = (
                total_rate.get(
                    "extracted_lowest"
                )
            )

            # Prefer total price.
            price = (
                total_price
                if total_price is not None
                else price_per_night
            )

            # ------------------------------------------------
            # PROPERTY TYPE
            # ------------------------------------------------

            property_type = hotel.get(
                "type",
                "Hotel",
            )

            if not isinstance(
                property_type,
                str,
            ):
                property_type = "Hotel"

            # ------------------------------------------------
            # CANCELLATION
            # ------------------------------------------------

            free_cancellation = hotel.get(
                "free_cancellation",
                False,
            )

            cancellation = (
                "Available"
                if free_cancellation is True
                else "Not specified"
            )

            # ------------------------------------------------
            # CREATE COMMON OBJECT
            # ------------------------------------------------

            try:

                hotels.append(
                    HotelOption(
                        hotel_id=None,
                        hotel_name=name,
                        rating=rating,
                        address=address,
                        photo=None,
                        room_name=property_type,
                        board_name=None,
                        price=price,
                        currency="INR",
                        taxes=None,
                        cancellation=cancellation,
                        cancellation_deadline=None,
                        offer_id=None,
                        provider="serpapi",
                        raw_data=hotel,
                    )
                )

            except Exception as exc:
                rejected_count += 1
                logger.warning(
                    "SerpAPI normalization rejected hotel | "
                    "hotel_name=%s | error=%s",
                    name,
                    exc,
                )
                continue

        logger.info(
            "SerpAPI normalization completed | "
            "raw_properties=%s | processed=%s | "
            "usable_hotels=%s | rejected=%s",
            len(properties),
            processed_count,
            len(hotels),
            rejected_count,
        )
        return hotels

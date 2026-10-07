import logging

from fastapi import APIRouter, Depends, HTTPException

from app.auth.auth_dependencies import get_current_user
from app.services.hotel.hotel_schema import (
    HotelSearchRequest,
)
from app.services.hotel.hotel_service import (
    HotelService,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/hotels",
    tags=["Hotels"],
)


# =========================================================
# HOTEL SEARCH
# =========================================================

@router.post("/search")
def search_hotels(
    request: HotelSearchRequest,
    current_user=Depends(get_current_user),
):
    """
    Search hotels for the requested destination and dates.

    Validation is performed by HotelSearchRequest
    before this function executes.

    Therefore:
        Invalid request -> provider API is NOT called.
    """

    try:

        service = HotelService()

        result = service.search_hotels(
            request
        )

        return result

    # =====================================================
    # LOCAL / REQUEST VALIDATION ERROR
    # =====================================================

    except ValueError as exc:

        logger.warning(
            "Hotel search validation error | "
            "user=%s | error=%s",
            current_user,
            exc,
        )

        raise HTTPException(
            status_code=400,
            detail=str(exc),
        ) from exc

    # =====================================================
    # PROVIDER / SERVICE ERROR
    # =====================================================

    except RuntimeError as exc:

        logger.error(
            "Hotel provider/service error | "
            "user=%s | error=%s",
            current_user,
            exc,
        )

        raise HTTPException(
            status_code=503,
            detail=(
                "Sorry, hotel search is temporarily "
                "unavailable. Please try again later."
            ),
        ) from exc

    # =====================================================
    # UNEXPECTED ERROR
    # =====================================================

    except Exception as exc:

        logger.exception(
            "Unexpected hotel search error | "
            "user=%s | error=%s",
            current_user,
            exc,
        )

        raise HTTPException(
            status_code=500,
            detail=(
                "Sorry, something went wrong while "
                "searching for hotels."
            ),
        ) from exc
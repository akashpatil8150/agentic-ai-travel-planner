import logging

from fastapi import (
    APIRouter,
    Depends,
    HTTPException,
)

from app.auth.auth_dependencies import (
    get_current_user,
)

from app.state.trip_state import (
    TripState,
)

from app.services.places.places_service import (
    PlacesService,
    PlacesAPIError,
    PlacesServiceError,
)


logger = logging.getLogger(__name__)


router = APIRouter(
    prefix="/places",
    tags=["Places"],
)


# =========================================================
# PLACES SEARCH
# =========================================================

@router.post("/search")
def search_places(
    state: TripState,
    current_user=Depends(
        get_current_user
    ),
):

    try:

        # -------------------------------------------------
        # SEARCH PLACES
        # -------------------------------------------------

        service = PlacesService()

        updated_state = (
            service.search_for_trip(
                state=state,
                radius=30000,
                limit=5,
            )
        )

        places = (
            updated_state.place_options
        )

        # -------------------------------------------------
        # NO RESULTS
        # -------------------------------------------------

        if not places:

            return {
                "status": "unavailable",
                "provider": "geoapify",
                "places_found": 0,
                "places": [],
                "message": (
                    "Sorry, no places were found "
                    "for your selected preferences "
                    "and destination."
                ),
            }

        # -------------------------------------------------
        # SUCCESS
        # -------------------------------------------------

        return {

            "status": "available",

            "provider": "geoapify",

            "places_found": len(
                places
            ),

            "places": places,

            "message": (
                "Places found successfully."
            ),
        }

    # =====================================================
    # GEOAPIFY FAILURE
    # =====================================================

    except PlacesAPIError as exc:

        logger.error(
            "Places API error | "
            "user=%s | error=%s",
            current_user,
            exc,
        )

        raise HTTPException(

            status_code=503,

            detail=(
                "Sorry, places search is "
                "temporarily unavailable. "
                "Please try again later."
            ),

        ) from exc

    # =====================================================
    # SERVICE ERROR
    # =====================================================

    except PlacesServiceError as exc:

        logger.warning(
            "Places service error | "
            "user=%s | error=%s",
            current_user,
            exc,
        )

        raise HTTPException(

            status_code=400,

            detail=str(exc),

        ) from exc

    # =====================================================
    # VALIDATION ERROR
    # =====================================================

    except ValueError as exc:

        logger.warning(
            "Places validation error | "
            "user=%s | error=%s",
            current_user,
            exc,
        )

        raise HTTPException(

            status_code=422,

            detail=str(exc),

        ) from exc

    # =====================================================
    # UNEXPECTED ERROR
    # =====================================================

    except Exception as exc:

        logger.exception(
            "Unexpected Places error | "
            "user=%s | error=%s",
            current_user,
            exc,
        )

        raise HTTPException(

            status_code=500,

            detail=(
                "Sorry, something went wrong "
                "while searching for places."
            ),

        ) from exc
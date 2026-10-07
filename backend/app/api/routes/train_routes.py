from fastapi import APIRouter, HTTPException

from app.services.train.train_service import (
    TrainService,
    TrainNoAvailabilityError,
    TrainProviderUnavailableError,
)
from app.models.train_models import TrainDetailsResponse


router = APIRouter(
    prefix="/trains",
    tags=["Trains"],
)

train_service = TrainService()


# ============================================================
# TRAIN SEARCH
# ============================================================

@router.get("/search")
async def search_trains(
    from_code: str,
    to_code: str,
    date: str,
    quota_code: str = "GN",
):

    try:

        trains = train_service.search_trains(
            from_code=from_code,
            to_code=to_code,
            date=date,
            quota_code=quota_code,
        )

        return {
            "success": True,
            "status": "available",
            "message": "Trains found successfully.",
            "count": len(trains),
            "trains": trains,
        }

    except ValueError as e:

        # ========================================================
        # INVALID USER INPUT
        # ========================================================

        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "status": "invalid_request",
                "message": str(e),
            },
        )

    except TrainNoAvailabilityError:

        # ========================================================
        # NO TRAINS AVAILABLE
        # ========================================================

        raise HTTPException(
            status_code=200,
            detail={
                "success": True,
                "status": "no_trains_available",
                "message": (
                    "No trains are available for the "
                    "selected route and journey date."
                ),
                "count": 0,
                "trains": [],
            },
        )

    except TrainProviderUnavailableError:

        # ========================================================
        # PROVIDER / API FAILURE
        # ========================================================

        raise HTTPException(
            status_code=503,
            detail={
                "success": False,
                "status": "provider_unavailable",
                "message": (
                    "We're unable to fetch train information "
                    "right now. Please try again shortly."
                ),
            },
        )

    except RuntimeError:

        # ========================================================
        # BACKWARD-COMPATIBLE PROVIDER FAILURE
        # ========================================================

        raise HTTPException(
            status_code=503,
            detail={
                "success": False,
                "status": "provider_unavailable",
                "message": (
                    "We're unable to fetch train information "
                    "right now. Please try again shortly."
                ),
            },
        )

    except Exception:

        # ========================================================
        # UNEXPECTED ERROR
        # ========================================================

        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "status": "internal_error",
                "message": (
                    "Something went wrong while searching "
                    "for trains. Please try again later."
                ),
            },
        )


# ============================================================
# SELECTED TRAIN DETAILS
# ============================================================

@router.get(
    "/{train_number}/details",
    response_model=TrainDetailsResponse,
)
async def get_train_details(
    train_number: str,
    from_code: str,
    to_code: str,
    date: str,
    class_code: str,
    quota_code: str = "GN",
):

    try:

        details = train_service.get_train_details(
            train_number=train_number,
            from_code=from_code,
            to_code=to_code,
            date=date,
            class_code=class_code,
            quota_code=quota_code,
        )

        return {
            "success": True,
            "data": details,
        }

    except ValueError as e:

        # ========================================================
        # INVALID USER INPUT
        # ========================================================

        raise HTTPException(
            status_code=400,
            detail={
                "success": False,
                "status": "invalid_request",
                "message": str(e),
            },
        )

    except TrainNoAvailabilityError:

        # ========================================================
        # TRAIN / CLASS NOT AVAILABLE
        # ========================================================

        raise HTTPException(
            status_code=200,
            detail={
                "success": True,
                "status": "not_available",
                "message": (
                    "The selected train or class is "
                    "not available for this journey."
                ),
            },
        )

    except TrainProviderUnavailableError:

        # ========================================================
        # PROVIDER / API FAILURE
        # ========================================================

        raise HTTPException(
            status_code=503,
            detail={
                "success": False,
                "status": "provider_unavailable",
                "message": (
                    "We're unable to fetch train details "
                    "right now. Please try again shortly."
                ),
            },
        )

    except RuntimeError:

        # ========================================================
        # BACKWARD-COMPATIBLE PROVIDER FAILURE
        # ========================================================

        raise HTTPException(
            status_code=503,
            detail={
                "success": False,
                "status": "provider_unavailable",
                "message": (
                    "We're unable to fetch train details "
                    "right now. Please try again shortly."
                ),
            },
        )

    except Exception:

        # ========================================================
        # UNEXPECTED ERROR
        # ========================================================

        raise HTTPException(
            status_code=500,
            detail={
                "success": False,
                "status": "internal_error",
                "message": (
                    "Something went wrong while fetching "
                    "train details. Please try again later."
                ),
            },
        )
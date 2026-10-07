from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from app.observability.logger import logger
from app.core.config import settings
from app.core.database import Base, engine

from app.api.routes.auth_routes import (
    router as auth_router,
)

from app.models.user import User
from app.models.trip_models import Trip

from app.observability.request_logger import (
    RequestLoggerMiddleware,
)

from app.api.routes.trip_routes import (
    router as trip_router,
)

from app.api.routes.train_routes import (
    router as train_router,
)

from app.api.routes.flight_routes import (
    router as flight_router,
)

from app.api.routes.hotel_routes import (
    router as hotel_router,
)

from app.api.routes.places_routes import (
    router as places_router,
)


# =========================================================
# FASTAPI APPLICATION
# =========================================================

app = FastAPI(
    title=settings.app_name,
    version="1.0.0",
    debug=settings.debug,
)


# =========================================================
# TRAIN ROUTES
# =========================================================

app.include_router(
    train_router,
    prefix="/api",
)


# =========================================================
# FLIGHT ROUTES
# =========================================================

app.include_router(
    flight_router,
)


# =========================================================
# HOTEL ROUTES
# =========================================================

app.include_router(
    hotel_router,
)


# =========================================================
# PLACES ROUTES
# =========================================================

app.include_router(
    places_router,
)


# =========================================================
# DATABASE
# =========================================================

try:
    Base.metadata.create_all(
        bind=engine
    )
except Exception as db_err:
    logger.warning(
        "Database initialization skipped or unavailable: %s",
        db_err,
    )


# =========================================================
# REQUEST LOGGING MIDDLEWARE
# =========================================================

app.add_middleware(
    RequestLoggerMiddleware
)


# =========================================================
# AUTHENTICATION ROUTES
# =========================================================

app.include_router(
    auth_router,
    prefix="/api/auth",
    tags=["Authentication"],
)


# =========================================================
# TRIP ROUTES
# =========================================================

app.include_router(
    trip_router,
    prefix="/api/trips",
    tags=["Trips"],
)


# =========================================================
# GLOBAL EXCEPTION HANDLER
# =========================================================

@app.exception_handler(Exception)
async def global_exception_handler(
    request: Request,
    exc: Exception,
):

    logger.exception(
        f"Unhandled exception | "
        f"{request.method} "
        f"{request.url.path} | "
        f"{type(exc).__name__}: {exc}"
    )

    return JSONResponse(
        status_code=500,
        content={
            "detail": "Internal server error"
        },
    )


# =========================================================
# HEALTH CHECK
# =========================================================

@app.get("/health")
async def health_check():

    return {
        "status": "healthy",
        "environment": settings.app_env,
    }
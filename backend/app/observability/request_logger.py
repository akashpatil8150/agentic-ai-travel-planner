import time
import uuid

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware

from app.observability.logger import logger, request_id_context


class RequestLoggerMiddleware(BaseHTTPMiddleware):

    async def dispatch(self, request: Request, call_next):
        start_time = time.perf_counter()

        request_id = request.headers.get(
            "X-Request-ID"
        ) or str(uuid.uuid4())

        request.state.request_id = request_id
        context_token = request_id_context.set(request_id)

        try:
            response = await call_next(request)

            duration = (
                time.perf_counter() - start_time
            ) * 1000

            response.headers["X-Request-ID"] = request_id

            logger.info(
                "%s %s | status=%s | duration_ms=%.2f",
                request.method,
                request.url.path,
                response.status_code,
                duration,
            )

            return response

        except Exception as exc:
            duration = (
                time.perf_counter() - start_time
            ) * 1000

            logger.exception(
                "%s %s | status=500 | duration_ms=%.2f | "
                "error=%s: %s",
                request.method,
                request.url.path,
                duration,
                type(exc).__name__,
                exc,
            )

            raise

        finally:
            request_id_context.reset(context_token)

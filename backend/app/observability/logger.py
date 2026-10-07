import logging
from contextvars import ContextVar

logger = logging.getLogger("travel_planner")
logger.setLevel(logging.INFO)

# Request-level correlation ID.
request_id_context: ContextVar[str] = ContextVar(
    "request_id",
    default="-",
)

# Workflow-level correlation IDs.
planning_id_context: ContextVar[str | None] = ContextVar(
    "planning_id",
    default=None,
)

trip_id_context: ContextVar[int | str | None] = ContextVar(
    "trip_id",
    default=None,
)

console_handler = logging.StreamHandler()

formatter = logging.Formatter(
    "%(asctime)s | %(levelname)s | %(name)s | "
    "request_id=%(request_id)s | %(message)s"
)

console_handler.setFormatter(formatter)


class RequestIdFilter(logging.Filter):
    def filter(self, record: logging.LogRecord) -> bool:
        record.request_id = request_id_context.get()
        return True


if not logger.handlers:
    logger.addHandler(console_handler)

if not any(
    isinstance(f, RequestIdFilter)
    for f in console_handler.filters
):
    console_handler.addFilter(RequestIdFilter())

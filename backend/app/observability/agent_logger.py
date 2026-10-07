import logging
import time
from typing import Optional

from app.observability.metrics import observability_metrics


logger = logging.getLogger("travel_planner")


def get_state_context(state) -> tuple[Optional[str], Optional[str]]:
    """
    Extract planning_id and trip_id from TripState safely, falling back to contextvars.
    """
    _, planning_id, trip_id = observability_metrics.get_correlation_ids(state)
    return planning_id, trip_id


def agent_start(agent_name: str, state):
    """
    Start timing an agent execution and log START.
    """
    return observability_metrics.record_agent_start(agent_name, state=state)


def agent_success(
    agent_name: str,
    state,
    start_time: float,
    status: str = "success",
):
    """
    Log successful agent execution and record duration.
    """
    return observability_metrics.record_agent_complete(
        agent_name=agent_name,
        start_time=start_time,
        state=state,
        status=status,
    )


def agent_failure(
    agent_name: str,
    state,
    start_time: float,
    error: Exception,
):
    """
    Log failed agent execution and record error.
    """
    return observability_metrics.record_agent_failed(
        agent_name=agent_name,
        start_time=start_time,
        error=error,
        state=state,
    )
from app.observability.logger import logger


def audit_log(
    action: str,
    user_id: str | None = None,
    details: str | None = None,
    planning_id: str | None = None,
    trip_id: str | None = None,
):
    context_parts = []

    if planning_id:
        context_parts.append(
            f"planning_id={planning_id}"
        )

    if trip_id:
        context_parts.append(
            f"trip_id={trip_id}"
        )

    if details:
        context_parts.append(details)

    final_details = ", ".join(context_parts) or None

    logger.info(
        "AUDIT | action=%s | user_id=%s | details=%s",
        action,
        user_id,
        final_details,
    )

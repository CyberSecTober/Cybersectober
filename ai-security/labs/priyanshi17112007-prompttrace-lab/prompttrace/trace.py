
"""Structured, in-memory event tracing for PromptTrace Lab."""

from datetime import datetime, timezone


def create_event(
    stage: str,
    message: str,
    *,
    source: str = "system",
    status: str = "info",
    details: dict | None = None,
) -> dict:
    """Create a structured event for the current experiment."""
    return {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "stage": stage,
        "source": source,
        "status": status,
        "message": message,
        "details": details or {},
    }


def create_trace() -> list[dict]:
    """Start a fresh trace for one experiment."""
    return []


def record_event(
    trace: list[dict],
    stage: str,
    message: str,
    *,
    source: str = "system",
    status: str = "info",
    details: dict | None = None,
) -> None:
    """Append a structured event to the current experiment trace."""
    trace.append(
        create_event(
            stage,
            message,
            source=source,
            status=status,
            details=details,
        )
    )

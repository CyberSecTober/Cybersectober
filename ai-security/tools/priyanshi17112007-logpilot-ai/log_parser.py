"""Parse Linux SSH authentication logs into LogPilot AI events."""

import re
from datetime import datetime, timezone
from typing import Any


_FAILED_PATTERNS = [
    re.compile(
        r"Failed password for (?:invalid user )?(?P<username>\S+) "
        r"from (?P<ip>\S+)"
    ),
    re.compile(r"Invalid user (?P<username>\S+) from (?P<ip>\S+)"),
]

_SUCCESS_PATTERN = re.compile(
    r"Accepted \S+ for (?P<username>\S+) from (?P<ip>\S+)"
)


def parse_auth_line(
    line: str, *, year: int | None = None
) -> dict[str, Any] | None:
    """Parse a common Linux syslog SSH authentication record.

    Returns None for unrelated or unrecognized lines.
    """
    match = re.search(
        r"^(?P<month>[A-Z][a-z]{2})\s+"
        r"(?P<day>\d{1,2})\s+"
        r"(?P<clock>\d{2}:\d{2}:\d{2})\s+"
        r"(?P<host>\S+)\s+sshd(?:\[\d+\])?:\s+"
        r"(?P<message>.*)$",
        line.strip(),
    )
    if not match:
        return None

    current_year = year if year is not None else datetime.now(timezone.utc).year
    try:
        timestamp = datetime.strptime(
            f"{current_year} {match['month']} {match['day']} {match['clock']}",
            "%Y %b %d %H:%M:%S",
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None

    message = match["message"]

    for pattern in _FAILED_PATTERNS:
        event_match = pattern.search(message)
        if event_match:
            return {
                "timestamp": timestamp.isoformat(),
                "source_ip": event_match["ip"],
                "username": event_match["username"],
                "event_type": "login_failed",
            }

    event_match = _SUCCESS_PATTERN.search(message)
    if event_match:
        return {
            "timestamp": timestamp.isoformat(),
            "source_ip": event_match["ip"],
            "username": event_match["username"],
            "event_type": "login_success",
        }

    return None


def parse_auth_lines(
    lines: list[str], *, year: int | None = None
) -> list[dict[str, Any]]:
    """Convert recognized SSH authentication lines into normalized events."""
    events = []
    for line in lines:
        event = parse_auth_line(line, year=year)
        if event is not None:
            events.append(event)
    return events

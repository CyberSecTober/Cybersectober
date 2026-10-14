
"""Parse Linux SSH and Ubuntu authentication logs into LogPilot events."""

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

# Ubuntu records commonly use an ISO-8601 timestamp, hostname, and message.
_ISO_PREFIX = re.compile(
    r"^(?P<timestamp>\d{4}-\d{2}-\d{2}T\S+)\s+"
    r"(?P<host>\S+)\s+(?P<message>.*)$"
)

_LOCAL_SUDO_FAILURE = re.compile(
    r"\bsudo:\s+pam_unix\(sudo:auth\): authentication failure\b"
)

_LOCAL_USERNAME = re.compile(r"\buser=(?P<username>[^\s;]+)")


def _event_from_message(
    message: str, timestamp: datetime
) -> dict[str, Any] | None:
    """Parse recognized SSH authentication messages."""
    for pattern in _FAILED_PATTERNS:
        match = pattern.search(message)
        if match:
            return {
                "timestamp": timestamp.isoformat(),
                "source_ip": match["ip"],
                "username": match["username"],
                "event_type": "login_failed",
            }

    match = _SUCCESS_PATTERN.search(message)
    if match:
        return {
            "timestamp": timestamp.isoformat(),
            "source_ip": match["ip"],
            "username": match["username"],
            "event_type": "login_success",
        }

    return None


def parse_auth_line(
    line: str, *, year: int | None = None
) -> dict[str, Any] | None:
    """Parse a Linux SSH or supported Ubuntu authentication log record.

    Local sudo authentication failures are represented without a source IP.
    unix_chkpwd records are not emitted as separate events because they may
    describe the same failed authentication already recorded by PAM.
    """
    line = line.strip()
    if not line:
        return None

    # Format used by the observed Ubuntu /var/log/auth.log:
    # 2026-10-11T13:39:00.613997+00:00 HOST sudo: ...
    iso_match = _ISO_PREFIX.match(line)
    if iso_match:
        try:
            timestamp = datetime.fromisoformat(iso_match["timestamp"])
        except ValueError:
            return None

        if timestamp.tzinfo is None:
            timestamp = timestamp.replace(tzinfo=timezone.utc)
        timestamp = timestamp.astimezone(timezone.utc)

        message = iso_match["message"]

        # Count the PAM authentication-failure record as the primary event.
        # Do not also count unix_chkpwd as an independent failure.
        if _LOCAL_SUDO_FAILURE.search(message):
            username_match = _LOCAL_USERNAME.search(message)
            if not username_match:
                return None

            return {
                "timestamp": timestamp.isoformat(),
                "username": username_match["username"],
                "event_type": "local_auth_failed",
                "event_source": "local",
            }

        # SSH messages can also be logged with ISO timestamps.
        return _event_from_message(message, timestamp)

    # Traditional Linux syslog format, for example:
    # Oct 11 14:00:00 server sshd[1234]: Failed password ...
    legacy_match = re.match(
        r"^(?P<month>[A-Z][a-z]{2})\s+"
        r"(?P<day>\d{1,2})\s+"
        r"(?P<clock>\d{2}:\d{2}:\d{2})\s+"
        r"(?P<host>\S+)\s+sshd(?:\[\d+\])?:\s+"
        r"(?P<message>.*)$",
        line,
    )
    if not legacy_match:
        return None

    current_year = (
        year if year is not None else datetime.now(timezone.utc).year
    )

    try:
        timestamp = datetime.strptime(
            f"{current_year} {legacy_match['month']} "
            f"{legacy_match['day']} {legacy_match['clock']}",
            "%Y %b %d %H:%M:%S",
        ).replace(tzinfo=timezone.utc)
    except ValueError:
        return None

    return _event_from_message(legacy_match["message"], timestamp)


def parse_auth_lines(
    lines, *, year: int | None = None
) -> list[dict[str, Any]]:
    """Convert recognized log lines into normalized event dictionaries."""
    events = []

    for line in lines:
        event = parse_auth_line(line, year=year)
        if event is not None:
            events.append(event)

    return events

"""Deterministic detection rules for LOGPILOT AI.

This module uses only the Python standard library. It does not call an LLM,
connect to external services, or take action against any account or host.

Supported event fields:
    timestamp: ISO-8601 timestamp
    source_ip: source IP address
    username: attempted account name
    event_type: login_failed, failed_login, login_success, or login_failed_attempt

Alternatively, use action="login" and status="failed" or "success".
"""

from __future__ import annotations

import ipaddress
from datetime import datetime, timedelta, timezone
from typing import Any


FAILED_EVENT_TYPES = {
    "login_failed",
    "failed_login",
    "authentication_failure",
    "auth_failure",
    "failed_login_attempt",
    "login_failed_attempt",
}

SUCCESS_EVENT_TYPES = {
    "login_success",
    "successful_login",
    "authentication_success",
    "auth_success",
}


def _parse_timestamp(value: Any) -> datetime:
    """Parse an ISO-8601 timestamp and normalize it to UTC."""
    if not isinstance(value, str) or not value.strip():
        raise ValueError("timestamp must be a non-empty ISO-8601 string")

    raw = value.strip()
    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(raw)
    except ValueError as exc:
        raise ValueError(f"invalid ISO-8601 timestamp: {value!r}") from exc

    # Treat timestamps without an explicit timezone as UTC.
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)

    return parsed.astimezone(timezone.utc)


def _event_type(event: dict[str, Any]) -> str:
    """Normalize event type aliases into a comparable string."""
    value = event.get("event_type") or event.get("event") or ""
    return str(value).strip().lower().replace("-", "_").replace(" ", "_")


def _is_failed_login(event: dict[str, Any]) -> bool:
    """Return True only for events that explicitly indicate login failure."""
    event_type = _event_type(event)
    if event_type in FAILED_EVENT_TYPES:
        return True

    action = str(event.get("action") or "").strip().lower()
    status = str(
        event.get("status") or event.get("result") or ""
    ).strip().lower()

    return action in {"login", "authentication", "auth"} and status in {
        "failed",
        "failure",
        "denied",
        "unsuccessful",
    }


def _normalize_event(
    event: dict[str, Any], index: int
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate and normalize one input event."""
    if not isinstance(event, dict):
        return None, f"Event {index}: expected a JSON object/dictionary"

    try:
        timestamp = _parse_timestamp(event.get("timestamp"))

        raw_ip = event.get("source_ip") or event.get("src_ip") or event.get("ip")
        if not isinstance(raw_ip, str) or not raw_ip.strip():
            raise ValueError("source_ip is required")

        try:
            source_ip = str(ipaddress.ip_address(raw_ip.strip()))
        except ValueError as exc:
            raise ValueError(f"invalid source IP address: {raw_ip!r}") from exc

        raw_username = event.get("username") or event.get("user")
        if not isinstance(raw_username, str) or not raw_username.strip():
            raise ValueError("username is required")

        return {
            "timestamp": timestamp,
            "source_ip": source_ip,
            "username": raw_username.strip(),
            "failed_login": _is_failed_login(event),
        }, None

    except ValueError as exc:
        return None, f"Event {index}: {exc}"


def _find_windows(
    events: list[dict[str, Any]],
    window: timedelta,
    minimum_events: int,
) -> list[dict[str, Any]]:
    """Find qualifying sliding windows in timestamp-sorted events."""
    results = []
    left = 0

    for right, current in enumerate(events):
        while (
            left <= right
            and current["timestamp"] - events[left]["timestamp"] > window
        ):
            left += 1

        window_events = events[left : right + 1]
        if len(window_events) >= minimum_events:
            results.append(
                {
                    "events": window_events,
                    "start": window_events[0]["timestamp"],
                    "end": window_events[-1]["timestamp"],
                }
            )
            # One representative finding per source IP and rule is enough.
            break

    return results


def analyze_events(
    events: list[dict[str, Any]],
    *,
    failed_login_threshold: int = 5,
    username_threshold: int = 3,
    window_minutes: int = 10,
) -> dict[str, Any]:
    """Analyze authentication events and return a JSON-serializable report.

    Args:
        events: A list of dictionaries containing timestamp, source_ip,
            username and event_type (or action/status).
        failed_login_threshold: Failures from one IP required for an alert.
        username_threshold: Distinct usernames attempted by one IP required
            for an alert.
        window_minutes: Time window used by both detection rules.

    Returns:
        A dictionary containing findings, scan counts, and validation errors.
        Invalid records are reported and skipped rather than crashing analysis.
    """
    if not isinstance(events, list):
        raise TypeError("events must be a list of dictionaries")

    if failed_login_threshold < 1:
        raise ValueError("failed_login_threshold must be at least 1")
    if username_threshold < 1:
        raise ValueError("username_threshold must be at least 1")
    if window_minutes < 1:
        raise ValueError("window_minutes must be at least 1")

    normalized_events = []
    validation_errors = []

    for index, event in enumerate(events, start=1):
        normalized, error = _normalize_event(event, index)
        if error:
            validation_errors.append(error)
        else:
            normalized_events.append(normalized)

    failed_by_ip: dict[str, list[dict[str, Any]]] = {}
    for event in normalized_events:
        if event["failed_login"]:
            failed_by_ip.setdefault(event["source_ip"], []).append(event)

    window = timedelta(minutes=window_minutes)
    findings = []

    for source_ip, ip_events in sorted(failed_by_ip.items()):
        ip_events.sort(key=lambda item: item["timestamp"])

        # Rule 1: repeated failed authentication attempts.
        repeated_windows = _find_windows(
            ip_events, window, failed_login_threshold
        )
        if repeated_windows:
            matched = repeated_windows[0]["events"]
            findings.append(
                {
                    "rule_id": "AUTH-001",
                    "severity": "high",
                    "title": "Repeated failed login attempts",
                    "source_ip": source_ip,
                    "description": (
                        f"{len(matched)} failed login attempts were observed "
                        f"from this IP within {window_minutes} minutes."
                    ),
                    "evidence": {
                        "failed_attempts": len(matched),
                        "usernames": sorted(
                            {item["username"] for item in matched}
                        ),
                        "window_start": matched[0]["timestamp"].isoformat(),
                        "window_end": matched[-1]["timestamp"].isoformat(),
                    },
                    "recommendation": (
                        "Review authentication records and source-IP context. "
                        "Apply rate limiting or an appropriate access control "
                        "policy if the activity is confirmed suspicious."
                    ),
                }
            )

        # Rule 2: one source IP attempts multiple account names.
        # Only failed login attempts are considered.
        spray_windows = []
        left = 0
        for right, current in enumerate(ip_events):
            while (
                left <= right
                and current["timestamp"] - ip_events[left]["timestamp"] > window
            ):
                left += 1

            window_events = ip_events[left : right + 1]
            usernames = {item["username"] for item in window_events}

            if len(usernames) >= username_threshold:
                spray_windows.append(
                    {
                        "events": window_events,
                        "usernames": usernames,
                    }
                )
                break

        if spray_windows:
            matched = spray_windows[0]["events"]
            usernames = spray_windows[0]["usernames"]
            findings.append(
                {
                    "rule_id": "AUTH-002",
                    "severity": "high",
                    "title": "Multiple usernames targeted from one IP",
                    "source_ip": source_ip,
                    "description": (
                        f"Failed login attempts targeted {len(usernames)} "
                        f"distinct usernames within {window_minutes} minutes."
                    ),
                    "evidence": {
                        "distinct_usernames": len(usernames),
                        "usernames": sorted(usernames),
                        "failed_attempts": len(matched),
                        "window_start": matched[0]["timestamp"].isoformat(),
                        "window_end": matched[-1]["timestamp"].isoformat(),
                    },
                    "recommendation": (
                        "Investigate for possible username enumeration or "
                        "password spraying. Correlate with successful logins "
                        "and other available authentication telemetry."
                    ),
                }
            )

    return {
        "tool": "LOGPILOT AI",
        "events_scanned": len(events),
        "events_accepted": len(normalized_events),
        "failed_login_events": sum(
            1 for event in normalized_events if event["failed_login"]
        ),
        "validation_errors": validation_errors,
        "findings_count": len(findings),
        "findings": findings,
    }

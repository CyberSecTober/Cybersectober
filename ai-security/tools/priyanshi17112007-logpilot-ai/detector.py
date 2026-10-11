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

LOCAL_FAILURE_EVENT_TYPES = {"local_auth_failed"}


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
    """Return True only for event types that explicitly indicate failure."""
    event_type = _event_type(event)
    if event_type in FAILED_EVENT_TYPES:
        return True

    action = str(event.get("action") or "").strip().lower()
    status = str(event.get("status") or event.get("result") or "").strip().lower()

    return action in {"login", "authentication", "auth"} and status in {
        "failed",
        "failure",
        "denied",
        "unsuccessful",
    }


def _normalize_event(
    event: dict[str, Any], index: int
) -> tuple[dict[str, Any] | None, str | None]:
    """Validate and normalize one remote or local authentication event."""
    if not isinstance(event, dict):
        return None, f"Event {index}: expected a JSON object/dictionary"

    try:
        timestamp = _parse_timestamp(event.get("timestamp"))

        raw_username = event.get("username") or event.get("user")
        if not isinstance(raw_username, str) or not raw_username.strip():
            raise ValueError("username is required")
        username = raw_username.strip()

        event_type = _event_type(event)
        is_local_failure = event_type in LOCAL_FAILURE_EVENT_TYPES

        # Local PAM events have no remote source IP. Do not fabricate one.
        if is_local_failure:
            return {
                "timestamp": timestamp,
                "source_ip": None,
                "username": username,
                "failed_login": False,
                "local_auth_failure": True,
            }, None

        raw_ip = event.get("source_ip") or event.get("src_ip") or event.get("ip")
        if not isinstance(raw_ip, str) or not raw_ip.strip():
            raise ValueError("source_ip is required")

        try:
            source_ip = str(ipaddress.ip_address(raw_ip.strip()))
        except ValueError as exc:
            raise ValueError(f"invalid source IP address: {raw_ip!r}") from exc

        return {
            "timestamp": timestamp,
            "source_ip": source_ip,
            "username": username,
            "failed_login": _is_failed_login(event),
            "local_auth_failure": False,
        }, None

    except ValueError as exc:
        return None, f"Event {index}: {exc}"


def _find_windows(
    events: list[dict[str, Any]],
    window: timedelta,
    minimum_events: int,
) -> list[dict[str, Any]]:
    """Find the first qualifying sliding window in timestamp-sorted events."""
    left = 0

    for right, current in enumerate(events):
        while (
            left <= right
            and current["timestamp"] - events[left]["timestamp"] > window
        ):
            left += 1

        window_events = events[left : right + 1]
        if len(window_events) >= minimum_events:
            return [{
                "events": window_events,
                "start": window_events[0]["timestamp"],
                "end": window_events[-1]["timestamp"],
            }]

    return []


def analyze_events(
    events: list[dict[str, Any]],
    *,
    failed_login_threshold: int = 5,
    username_threshold: int = 3,
    window_minutes: int = 10,
    local_failure_threshold: int = 5,
) -> dict[str, Any]:
    """Analyze authentication events and return a JSON-serializable report.

    Args:
        events: A list of remote or supported local authentication event dicts.
        failed_login_threshold: Remote failed logins from one IP for AUTH-001.
        username_threshold: Distinct remote usernames from one IP for AUTH-002.
        window_minutes: Detection window shared by all rules.
        local_failure_threshold: Local failures for one account for AUTH-003.

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
    if local_failure_threshold < 1:
        raise ValueError("local_failure_threshold must be at least 1")

    normalized_events: list[dict[str, Any]] = []
    validation_errors: list[str] = []

    for index, event in enumerate(events, start=1):
        normalized, error = _normalize_event(event, index)
        if error:
            validation_errors.append(error)
        elif normalized is not None:
            normalized_events.append(normalized)

    window = timedelta(minutes=window_minutes)
    findings: list[dict[str, Any]] = []

    # AUTH-001 and AUTH-002: remote failed logins grouped by source IP.
    failed_by_ip: dict[str, list[dict[str, Any]]] = {}
    for event in normalized_events:
        if event["failed_login"] and event["source_ip"] is not None:
            failed_by_ip.setdefault(event["source_ip"], []).append(event)

    for source_ip, ip_events in sorted(failed_by_ip.items()):
        ip_events.sort(key=lambda item: item["timestamp"])

        repeated_windows = _find_windows(
            ip_events, window, failed_login_threshold
        )
        if repeated_windows:
            matched = repeated_windows[0]["events"]
            findings.append({
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
                    "usernames": sorted({item["username"] for item in matched}),
                    "window_start": matched[0]["timestamp"].isoformat(),
                    "window_end": matched[-1]["timestamp"].isoformat(),
                },
                "recommendation": (
                    "Review authentication records and source-IP context. "
                    "Apply rate limiting or an appropriate access control "
                    "policy if the activity is confirmed suspicious."
                ),
            })

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
                matched = window_events
                findings.append({
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
                })
                break

    # AUTH-003: repeated local PAM failures for one account. The parser emits
    # PAM authentication-failure records as primary events and intentionally
    # does not emit related unix_chkpwd records, reducing double counting.
    local_by_username: dict[str, list[dict[str, Any]]] = {}
    for event in normalized_events:
        if event["local_auth_failure"]:
            local_by_username.setdefault(event["username"], []).append(event)

    for username, user_events in sorted(local_by_username.items()):
        user_events.sort(key=lambda item: item["timestamp"])
        local_windows = _find_windows(user_events, window, local_failure_threshold)
        if not local_windows:
            continue

        matched = local_windows[0]["events"]
        findings.append({
            "rule_id": "AUTH-003",
            "severity": "medium",
            "title": "Repeated local authentication failures",
            "source_ip": None,
            "description": (
                f"{len(matched)} local authentication failure record(s) "
                f"were observed for account {username!r} within "
                f"{window_minutes} minutes. This may include ordinary "
                "mistyped passwords and is not proof of an attack."
            ),
            "evidence": {
                "username": username,
                "failure_count": len(matched),
                "window_start": matched[0]["timestamp"].isoformat(),
                "window_end": matched[-1]["timestamp"].isoformat(),
                "event_source": "local",
            },
            "recommendation": (
                "Check whether the failures correspond to expected user "
                "activity. Correlate timestamps and other authentication "
                "records before treating the pattern as suspicious."
            ),
        })

    return {
        "tool": "LOGPILOT AI",
        "events_scanned": len(events),
        "events_accepted": len(normalized_events),
        "failed_login_events": sum(
            1 for event in normalized_events if event["failed_login"]
        ),
        "local_auth_failure_events": sum(
            1 for event in normalized_events if event["local_auth_failure"]
        ),
        "validation_errors": validation_errors,
        "findings_count": len(findings),
        "findings": findings,
    }

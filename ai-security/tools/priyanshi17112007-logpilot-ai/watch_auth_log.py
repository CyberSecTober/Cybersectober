import argparse
import json
import sys
import time
from collections import OrderedDict
from datetime import datetime, timedelta
from pathlib import Path

from agent import run_investigation
from detector import analyze_events
from live_monitor import AuthLogTailer
from logpilot import render_report


def build_parser():
    """Build the command-line arguments for live monitoring."""
    parser = argparse.ArgumentParser(
        prog="logpilot-watch",
        description=(
            "Continuously monitor a Linux authentication log, "
            "detect suspicious patterns, and investigate findings."
        ),
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to an accessible authentication log file.",
    )
    parser.add_argument(
        "--poll-interval",
        type=float,
        default=1.0,
        help="Seconds between polls (default: 1).",
    )
    parser.add_argument(
        "--failed-threshold",
        type=int,
        default=5,
        help="Failed remote logins for AUTH-001 (default: 5).",
    )
    parser.add_argument(
        "--username-threshold",
        type=int,
        default=3,
        help="Distinct usernames for AUTH-002 (default: 3).",
    )
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=10,
        help="Detection window in minutes (default: 10).",
    )
    parser.add_argument(
        "--max-events",
        type=int,
        default=5000,
        help="Maximum events retained in memory (default: 5000).",
    )
    parser.add_argument(
        "--read-existing",
        action="store_true",
        help="Process existing entries instead of starting at the end.",
    )
    return parser


def event_time(event):
    """Convert an event timestamp to a datetime."""
    timestamp = event["timestamp"]
    if timestamp.endswith("Z"):
        timestamp = timestamp[:-1] + "+00:00"

    value = datetime.fromisoformat(timestamp)
    if value.tzinfo is None:
        from datetime import timezone
        value = value.replace(tzinfo=timezone.utc)

    return value


def finding_key(finding):
    """Create a stable key to avoid repeatedly printing the same finding."""
    return json.dumps(
        {
            "rule_id": finding.get("rule_id"),
            "source_ip": finding.get("source_ip"),
            "evidence": finding.get("evidence", {}),
        },
        sort_keys=True,
    )


def main(argv=None):
    """Run the continuous log-monitoring loop."""
    parser = build_parser()
    args = parser.parse_args(argv)

    if args.poll_interval <= 0:
        parser.error("--poll-interval must be greater than zero")
    if args.failed_threshold < 1 or args.username_threshold < 1:
        parser.error("detection thresholds must be at least 1")
    if args.window_minutes < 1 or args.max_events < 1:
        parser.error("--window-minutes and --max-events must be at least 1")

    if not args.input.is_file():
        print(
            f"LogPilot AI: log file not found: {args.input}",
            file=sys.stderr,
        )
        return 2

    monitor = AuthLogTailer(
        args.input,
        start_at_end=not args.read_existing,
    )

    
    if not args.read_existing:
        monitor.poll_once()

    history = []
    reported = OrderedDict()
    previous_error = None

    print(f"LogPilot AI live monitoring: {args.input}", flush=True)
    print(f"Polling every {args.poll_interval:g} second(s).", flush=True)
    print("Press Ctrl+C to stop.", flush=True)

    try:
        while True:
            new_events = monitor.poll_once()

            if monitor.last_error:
                if monitor.last_error != previous_error:
                    print(
                        "Warning: unable to read log file: "
                        f"{monitor.last_error}",
                        file=sys.stderr,
                        flush=True,
                    )
                previous_error = monitor.last_error
            else:
                previous_error = None

            if new_events:
                print(
                    f"\nReceived {len(new_events)} parsed event(s).",
                    flush=True,
                )

                history.extend(new_events)

                # Keep events within the configured event-time window.
                newest = max(event_time(event) for event in history)
                cutoff = newest - timedelta(minutes=args.window_minutes)
                history = [
                    event
                    for event in history
                    if event_time(event) >= cutoff
                ][-args.max_events:]

                report = analyze_events(
                    history,
                    failed_login_threshold=args.failed_threshold,
                    username_threshold=args.username_threshold,
                    window_minutes=args.window_minutes,
                )

                # Display only findings not previously reported.
                unseen = []
                for finding in report["findings"]:
                    key = finding_key(finding)
                    if key not in reported:
                        reported[key] = None
                        unseen.append(finding)

                # Bound memory used by the finding cache.
                while len(reported) > 10_000:
                    reported.popitem(last=False)

                if unseen:
                    report["findings"] = unseen
                    report["findings_count"] = len(unseen)

                    report = run_investigation(report)
                    render_report(report)

            time.sleep(args.poll_interval)

    except KeyboardInterrupt:
        print("\nLive monitoring stopped.", flush=True)
        return 0


if __name__ == "__main__":
    raise SystemExit(main())

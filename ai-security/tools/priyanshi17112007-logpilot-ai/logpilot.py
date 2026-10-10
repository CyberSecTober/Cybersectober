"""Command-line interface for LOGPILOT AI."""

import argparse
import json
import sys
from pathlib import Path

from detector import analyze_events


def build_parser():
    parser = argparse.ArgumentParser(
        prog="logpilot",
        description=(
            "Analyze authentication logs for suspicious failed-login "
            "patterns. Detection runs locally without an LLM."
        ),
    )
    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to a JSON file containing a list of authentication events.",
    )
    parser.add_argument(
        "--output",
        type=Path,
        help="Optional path for saving the complete JSON report.",
    )
    parser.add_argument(
        "--failed-threshold",
        type=int,
        default=5,
        help="Failed logins from one IP required for AUTH-001 (default: 5).",
    )
    parser.add_argument(
        "--username-threshold",
        type=int,
        default=3,
        help="Distinct usernames required for AUTH-002 (default: 3).",
    )
    parser.add_argument(
        "--window-minutes",
        type=int,
        default=10,
        help="Detection time window in minutes (default: 10).",
    )
    return parser


def render_report(report):
    """Print a concise human-readable report."""
    print("\nLOGPILOT AI — Authentication Log Analysis")
    print("=" * 44)
    print(f"Events scanned:       {report['events_scanned']}")
    print(f"Events accepted:      {report['events_accepted']}")
    print(f"Failed login events:  {report['failed_login_events']}")
    print(f"Findings:             {report['findings_count']}")
    print(f"Validation errors:    {len(report['validation_errors'])}")

    for finding in report["findings"]:
        print()
        print(
            f"[{finding['severity'].upper()}] "
            f"{finding['rule_id']}: {finding['title']}"
        )
        print(f"  Source IP: {finding['source_ip']}")
        print(f"  Details:   {finding['description']}")

        evidence = finding["evidence"]
        print(f"  Evidence:  {json.dumps(evidence, sort_keys=True)}")
        print(f"  Guidance:  {finding['recommendation']}")

    if report["validation_errors"]:
        print("\nInput validation warnings:")
        for error in report["validation_errors"]:
            print(f"  - {error}")

    if not report["findings"]:
        print("\nNo configured detection rules were triggered.")

    print("\nNote: Findings indicate suspicious patterns, not proof of an attack.")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if not args.input.is_file():
            print(f"LOGPILOT AI: input file does not exist or is not a file: {args.input}", file=sys.stderr)
            return 2

        with args.input.open("r", encoding="utf-8") as file:
            events = json.load(file)

        if not isinstance(events, list):
            print("LOGPILOT AI: input JSON must contain a list of event objects", file=sys.stderr)
            return 2

        report = analyze_events(
            events,
            failed_login_threshold=args.failed_threshold,
            username_threshold=args.username_threshold,
            window_minutes=args.window_minutes,
        )

        if args.output:
            # Do not create missing parent directories silently.
            with args.output.open("w", encoding="utf-8") as file:
                json.dump(report, file, indent=2, ensure_ascii=False)
                file.write("\n")

        render_report(report)

        # Invalid records are reported in the report, and do not hide
        # findings from valid records. Use a nonzero exit code to flag them.
        return 2 if report["validation_errors"] else 0

    except json.JSONDecodeError as exc:
        print(
            f"LOGPILOT AI: invalid JSON in {args.input}: "
            f"line {exc.lineno}, column {exc.colno}: {exc.msg}",
            file=sys.stderr,
        )
        return 2
    except OSError as exc:
        print(f"LOGPILOT AI: file error: {exc}", file=sys.stderr)
        return 2
    except (TypeError, ValueError) as exc:
        print(f"LOGPILOT AI: invalid input or configuration: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

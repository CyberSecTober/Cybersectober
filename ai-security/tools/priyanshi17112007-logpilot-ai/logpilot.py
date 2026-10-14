"""Command-line interface for LOGPILOT AI."""

import argparse
import json
import sys
from pathlib import Path

from agent import run_investigation
from detector import analyze_events
from log_parser import parse_auth_lines


def build_parser():
    parser = argparse.ArgumentParser(
        prog="logpilot",
        description=(
            "Analyze JSON authentication events or Linux SSH authentication "
            "logs. Detection runs locally without an LLM."
        ),
    )

    parser.add_argument(
        "--input",
        required=True,
        type=Path,
        help="Path to a JSON events file or Linux SSH authentication log.",
    )
    parser.add_argument(
        "--format",
        choices=("json", "authlog"),
        default="json",
        help="Input format: json or authlog (default: json).",
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

        source_ip = finding.get("source_ip")
        if source_ip:
           print(f"  Source IP: {source_ip}")
        else:
           print("  Source:    Local host (no remote IP)")

        print(f"  Details:   {finding['description']}")
        print(f"  Evidence:  {json.dumps(finding['evidence'], sort_keys=True)}")
        print(f"  Guidance:  {finding['recommendation']}")

    if report["validation_errors"]:
        print("\nInput validation warnings:")
        for error in report["validation_errors"]:
            print(f"  - {error}")

    investigation = report.get("investigation")
    if investigation:
        print("\nInvestigation Summary")
        print("---------------------")
        print(investigation.get("analyst_summary", "No summary available."))

        
        for item in investigation.get("source_investigations", []):
         print(f"\nSource IP: {item.get('source_ip', 'Unknown')}")
         print(f"  Assessment: {item.get('assessment', 'Not available')}")
         print(f"  Rules triggered: {', '.join(item.get('rule_ids', [])) or 'None'}")
         print(f"  Confidence note: {item.get('confidence_note', 'Not available')}")


        recommendations = investigation.get("recommendations", [])
        if recommendations:
            print("\nInvestigation Recommendations:")
            for recommendation in recommendations:
                print(f"  - {recommendation}")

        print(
            "\nInvestigation mode: "
            f"{investigation.get('mode', 'unspecified')}"
        )
        print(
            "LLM used: "
            f"{'Yes' if investigation.get('llm_used') else 'No'}"
        )
        print(
            "Automated response performed: "
            f"{'Yes' if investigation.get('automated_response_performed') else 'No'}"
        )

    if not report["findings"]:
        print("\nNo configured detection rules were triggered.")

    print("\nNote: Findings indicate suspicious patterns, not proof of an attack.")


def main(argv=None):
    parser = build_parser()
    args = parser.parse_args(argv)

    try:
        if not args.input.is_file():
            print(
                f"LOGPILOT AI: input file does not exist or is not a file: "
                f"{args.input}",
                file=sys.stderr,
            )
            return 2

        with args.input.open("r", encoding="utf-8") as file:
            if args.format == "json":
                events = json.load(file)

                if not isinstance(events, list):
                    print(
                        "LOGPILOT AI: input JSON must contain a list "
                        "of event objects",
                        file=sys.stderr,
                    )
                    return 2
            else:
                events = parse_auth_lines(file)

        report = analyze_events(
            events,
            failed_login_threshold=args.failed_threshold,
            username_threshold=args.username_threshold,
            window_minutes=args.window_minutes,
        )

        # Run the deterministic investigation workflow after detection.
        report = run_investigation(report)

        if args.output:
            with args.output.open("w", encoding="utf-8") as file:
                json.dump(report, file, indent=2, ensure_ascii=False)
                file.write("\n")

        render_report(report)

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
        print(
            f"LOGPILOT AI: invalid input or configuration: {exc}",
            file=sys.stderr,
        )
        return 2


if __name__ == "__main__":
    raise SystemExit(main())

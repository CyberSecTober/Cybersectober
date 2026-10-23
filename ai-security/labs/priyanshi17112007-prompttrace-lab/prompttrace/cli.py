"""User-driven terminal scanner for PromptTrace Lab."""

import argparse
import sys
from pathlib import Path

from prompttrace.detection import analyze_injection


def scan_text(text: str, source: str = "user_input") -> dict:
    """Analyze user-supplied text and display configured rule matches."""
    if not text.strip():
        raise ValueError("Input cannot be empty.")

    result = analyze_injection(text, source=source)

    print("\n" + "=" * 65)
    print("PROMPTTRACE - TERMINAL SECURITY SCAN")
    print("=" * 65)
    print(f"Source: {source}")
    print(f"Characters: {len(text)}")

    if result["injection_detected"]:
        print("Result: CONFIGURED PATTERN DETECTED")
    else:
        print("Result: NO CONFIGURED PATTERN MATCHED")

    print("Categories:", ", ".join(result["categories"]) or "None")
    print("Matched markers:", ", ".join(result["matched_markers"]) or "None")

    if result["matched_rules"]:
        print("\nMatched rules:")
        for rule in result["matched_rules"]:
            print(f"  {rule['id']} - {rule['category']}")
            print(f"    {rule['description']}")
    else:
        print("\nNo configured rules matched this input.")

    print("\nImportant:")
    print("- A match is not proof that an input is malicious.")
    print("- No match does not prove the input is safe.")
    print("- The scanner does not execute prompts or real tools.")

    return result


def interactive(source: str) -> int:
    """Accept arbitrary multiline text until the user scans or exits."""
    print("\nPROMPTTRACE - INTERACTIVE SCANNER")
    print("Paste any text, including multiple lines.")
    print("Commands: /scan, /clear, /quit")
    print(f"Source: {source}")

    while True:
        lines = []

        try:
            while True:
                prompt = "prompttrace> " if not lines else "           | "
                line = input(prompt)
                command = line.strip().lower()

                if command in {"/quit", "/exit"}:
                    print("Exiting PromptTrace.")
                    return 0

                if command == "/clear":
                    lines.clear()
                    print("Current input cleared.")
                    continue

                if command == "/scan":
                    if not "\n".join(lines).strip():
                        print("Paste some text before using /scan.")
                        continue
                    break

                lines.append(line)

        except (EOFError, KeyboardInterrupt):
            print("\nExiting PromptTrace.")
            return 0

        try:
            scan_text("\n".join(lines), source)
        except ValueError as exc:
            print(f"Input error: {exc}")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Scan arbitrary text with PromptTrace's configured rules."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    scan = commands.add_parser(
        "scan",
        help="scan custom text, a file, or standard input",
    )
    inputs = scan.add_mutually_exclusive_group(required=True)
    inputs.add_argument("--text", help="text to scan")
    inputs.add_argument("--file", help="UTF-8 text file to scan")
    inputs.add_argument(
        "--stdin",
        action="store_true",
        help="read text from standard input",
    )
    scan.add_argument(
        "--source",
        choices=("user_input", "retrieved_document", "tool_output"),
        default="user_input",
        help="label the origin of the untrusted content",
    )

    session = commands.add_parser(
        "interactive",
        help="paste custom multiline text in an interactive session",
    )
    session.add_argument(
        "--source",
        choices=("user_input", "retrieved_document", "tool_output"),
        default="user_input",
        help="label the origin of the untrusted content",
    )

    args = parser.parse_args(argv)

    if args.command == "interactive":
        return interactive(args.source)

    try:
        if args.text is not None:
            text = args.text
        elif args.file is not None:
            text = Path(args.file).read_text(encoding="utf-8")
        else:
            text = sys.stdin.read()

        scan_text(text, args.source)

    except (OSError, UnicodeError, ValueError) as exc:
        print(f"Input error: {exc}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    raise SystemExit(main())

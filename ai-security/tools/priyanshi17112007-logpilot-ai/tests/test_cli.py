import contextlib
import io
import json
import tempfile
import unittest
from pathlib import Path

from logpilot import main


class TestLogpilotCLI(unittest.TestCase):
    def test_cli_prints_findings_for_valid_input(self):
        events = [
            {
                "timestamp": f"2026-10-09T10:0{i}:00Z",
                "source_ip": "203.0.113.10",
                "username": f"user{i}",
                "event_type": "login_failed",
            }
            for i in range(5)
        ]

        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "events.json"
            input_path.write_text(json.dumps(events), encoding="utf-8")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["--input", str(input_path)])

        self.assertEqual(exit_code, 0)
        self.assertIn("AUTH-001", stdout.getvalue())
        self.assertIn("Findings:", stdout.getvalue())

    def test_cli_writes_json_report(self):
        events = [
            {
                "timestamp": f"2026-10-09T10:0{i}:00Z",
                "source_ip": "203.0.113.10",
                "username": f"user{i}",
                "event_type": "login_failed",
            }
            for i in range(5)
        ]

        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "events.json"
            output_path = Path(tmp) / "report.json"
            input_path.write_text(json.dumps(events), encoding="utf-8")

            with contextlib.redirect_stdout(io.StringIO()):
                exit_code = main([
                    "--input", str(input_path),
                    "--output", str(output_path),
                ])

            saved_report = json.loads(output_path.read_text(encoding="utf-8"))

        self.assertEqual(exit_code, 0)
        self.assertEqual(saved_report["findings_count"], 2)
        rule_ids = {finding["rule_id"] for finding in saved_report["findings"]}
        self.assertEqual(rule_ids, {"AUTH-001", "AUTH-002"})

    def test_cli_returns_error_for_invalid_json(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "broken.json"
            input_path.write_text("{invalid json", encoding="utf-8")

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main(["--input", str(input_path)])

        self.assertEqual(exit_code, 2)
        self.assertIn("invalid JSON", stderr.getvalue())

    def test_cli_returns_error_for_missing_file(self):
        with tempfile.TemporaryDirectory() as tmp:
            input_path = Path(tmp) / "missing.json"

            stderr = io.StringIO()
            with contextlib.redirect_stderr(stderr):
                exit_code = main(["--input", str(input_path)])

        self.assertEqual(exit_code, 2)
        self.assertIn("does not exist", stderr.getvalue())


if __name__ == "__main__":
    unittest.main()

"""Regression tests for local Ubuntu authentication events."""

import unittest

from detector import analyze_events
from log_parser import parse_auth_line


def pam_failure(minute, username="demo"):
    """Build a sanitized Ubuntu ISO-format PAM failure record."""
    return (
        f"2026-10-11T13:{minute:02d}:00+00:00 "
        f"DESKTOP sudo: pam_unix(sudo:auth): authentication failure; "
        f"logname={username} uid=1000 euid=0 user={username}"
    )


class TestLocalAuthentication(unittest.TestCase):
    def test_parses_ubuntu_pam_failure_without_source_ip(self):
        event = parse_auth_line(pam_failure(10))

        self.assertIsNotNone(event)
        self.assertEqual(event["event_type"], "local_auth_failed")
        self.assertEqual(event["username"], "demo")
        self.assertEqual(event["event_source"], "local")
        self.assertNotIn("source_ip", event)

    def test_unix_chkpwd_record_is_not_counted_as_separate_event(self):
        line = (
            "2026-10-11T13:10:00+00:00 DESKTOP "
            "unix_chkpwd[555]: password check failed for user (demo)"
        )

        self.assertIsNone(parse_auth_line(line))

    def test_repeated_local_failures_trigger_auth_003(self):
        events = [
            parse_auth_line(pam_failure(minute))
            for minute in range(10, 15)
        ]

        report = analyze_events(events)
        rules = {finding["rule_id"] for finding in report["findings"]}

        self.assertEqual(report["events_accepted"], 5)
        self.assertEqual(report["local_auth_failure_events"], 5)
        self.assertEqual(report["failed_login_events"], 0)
        self.assertIn("AUTH-003", rules)
        self.assertEqual(report["validation_errors"], [])

        finding = next(
            item for item in report["findings"]
            if item["rule_id"] == "AUTH-003"
        )
        self.assertIsNone(finding["source_ip"])
        self.assertEqual(finding["evidence"]["username"], "demo")

    def test_below_threshold_does_not_trigger_auth_003(self):
        events = [
            parse_auth_line(pam_failure(minute))
            for minute in range(10, 14)
        ]

        report = analyze_events(events)

        self.assertEqual(report["local_auth_failure_events"], 4)
        self.assertNotIn(
            "AUTH-003",
            {finding["rule_id"] for finding in report["findings"]},
        )

    def test_local_failures_are_grouped_by_username(self):
        events = [
            parse_auth_line(pam_failure(minute, username="alice"))
            for minute in range(10, 13)
        ]
        events.extend(
            parse_auth_line(pam_failure(minute, username="bob"))
            for minute in range(13, 15)
        )

        report = analyze_events(events)

        self.assertNotIn(
            "AUTH-003",
            {finding["rule_id"] for finding in report["findings"]},
        )


if __name__ == "__main__":
    unittest.main()

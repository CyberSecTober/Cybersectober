import unittest

from detector import analyze_events


def event(minute, ip="203.0.113.10", username="alice",
          event_type="login_failed"):
    return {
        "timestamp": f"2026-10-09T10:{minute:02d}:00Z",
        "source_ip": ip,
        "username": username,
        "event_type": event_type,
    }


class TestAnalyzeEvents(unittest.TestCase):
    def test_repeated_failures_trigger_auth_001(self):
        events = [event(i) for i in range(5)]

        report = analyze_events(events)

        findings = [
            finding for finding in report["findings"]
            if finding["rule_id"] == "AUTH-001"
        ]
        self.assertEqual(len(findings), 1)
        self.assertEqual(findings[0]["evidence"]["failed_attempts"], 5)
        self.assertEqual(report["validation_errors"], [])

    def test_multiple_usernames_trigger_auth_002(self):
        events = [
            event(0, username="alice"),
            event(1, username="bob"),
            event(2, username="charlie"),
        ]

        report = analyze_events(events, failed_login_threshold=10)

        findings = [
            finding for finding in report["findings"]
            if finding["rule_id"] == "AUTH-002"
        ]
        self.assertEqual(len(findings), 1)
        self.assertEqual(
            findings[0]["evidence"]["usernames"],
            ["alice", "bob", "charlie"],
        )

    def test_successful_logins_do_not_trigger_failure_alerts(self):
        events = [
            event(i, event_type="login_success")
            for i in range(6)
        ]

        report = analyze_events(events)

        self.assertEqual(report["failed_login_events"], 0)
        self.assertEqual(report["findings_count"], 0)

    def test_attempts_outside_window_do_not_combine(self):
        events = [
            event(0),
            event(1),
            event(2),
            event(20),
            event(21),
        ]

        report = analyze_events(
            events,
            failed_login_threshold=5,
            username_threshold=3,
            window_minutes=10,
        )

        self.assertEqual(report["findings_count"], 0)

    def test_custom_thresholds_are_respected(self):
        events = [event(0), event(1), event(2)]

        report = analyze_events(
            events,
            failed_login_threshold=3,
            username_threshold=10,
        )

        self.assertEqual(report["findings_count"], 1)
        self.assertEqual(report["findings"][0]["rule_id"], "AUTH-001")

    def test_malformed_record_is_reported_and_skipped(self):
        events = [
            event(0),
            {
                "timestamp": "not-a-timestamp",
                "source_ip": "203.0.113.10",
                "username": "alice",
                "event_type": "login_failed",
            },
        ]

        report = analyze_events(events)

        self.assertEqual(report["events_scanned"], 2)
        self.assertEqual(report["events_accepted"], 1)
        self.assertEqual(len(report["validation_errors"]), 1)

    def test_invalid_ip_is_reported_and_skipped(self):
        events = [event(0, ip="not-an-ip")]

        report = analyze_events(events)

        self.assertEqual(report["events_accepted"], 0)
        self.assertEqual(report["validation_errors"], [
            "Event 1: invalid source IP address: 'not-an-ip'"
        ])

    def test_alternate_action_status_format(self):
        events = [
            {
                "timestamp": f"2026-10-09T10:{i:02d}:00Z",
                "source_ip": "203.0.113.10",
                "username": "alice",
                "action": "login",
                "status": "failed",
            }
            for i in range(5)
        ]

        report = analyze_events(events)

        self.assertEqual(report["failed_login_events"], 5)
        self.assertIn(
            "AUTH-001",
            {finding["rule_id"] for finding in report["findings"]},
        )

    def test_invalid_configuration_is_rejected(self):
        with self.assertRaises(ValueError):
            analyze_events([], failed_login_threshold=0)

        with self.assertRaises(ValueError):
            analyze_events([], username_threshold=0)

        with self.assertRaises(ValueError):
            analyze_events([], window_minutes=0)

    def test_non_list_input_is_rejected(self):
        with self.assertRaises(TypeError):
            analyze_events({})


if __name__ == "__main__":
    unittest.main()

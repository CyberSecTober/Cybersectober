import unittest

from log_parser import parse_auth_line, parse_auth_lines


class TestAuthLogParser(unittest.TestCase):
    def test_failed_password(self):
        line = (
            "Oct 11 09:30:01 server sshd[123]: "
            "Failed password for alice from 203.0.113.10 port 2222 ssh2"
        )
        event = parse_auth_line(line, year=2026)

        self.assertIsNotNone(event)
        self.assertEqual(event["username"], "alice")
        self.assertEqual(event["source_ip"], "203.0.113.10")
        self.assertEqual(event["event_type"], "login_failed")

    def test_invalid_user(self):
        line = (
            "Oct 11 09:30:02 server sshd[123]: "
            "Invalid user guest from 203.0.113.11"
        )
        event = parse_auth_line(line, year=2026)

        self.assertIsNotNone(event)
        self.assertEqual(event["username"], "guest")
        self.assertEqual(event["event_type"], "login_failed")

    def test_successful_login(self):
        line = (
            "Oct 11 09:30:03 server sshd[123]: "
            "Accepted publickey for alice from 203.0.113.12 port 2222 ssh2"
        )
        event = parse_auth_line(line, year=2026)

        self.assertIsNotNone(event)
        self.assertEqual(event["event_type"], "login_success")

    def test_unrelated_line_is_ignored(self):
        self.assertIsNone(
            parse_auth_line("Oct 11 09:30:03 server systemd: Started service")
        )

    def test_invalid_timestamp_is_ignored(self):
        self.assertIsNone(
            parse_auth_line(
                "Foo 99 99:99:99 server sshd[123]: "
                "Failed password for alice from 203.0.113.10",
                year=2026,
            )
        )

    def test_multiple_lines(self):
        lines = [
            "Oct 11 09:30:01 server sshd[123]: Failed password for alice from 203.0.113.10",
            "Oct 11 09:30:02 server sshd[123]: Accepted publickey for alice from 203.0.113.12 port 22 ssh2",
            "unrelated line",
        ]
        self.assertEqual(len(parse_auth_lines(lines, year=2026)), 2)


if __name__ == "__main__":
    unittest.main()

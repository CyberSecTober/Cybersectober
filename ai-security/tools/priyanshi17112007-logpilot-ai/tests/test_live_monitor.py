
"""Tests for the LogPilot AI live log collector."""

import tempfile
import unittest
from pathlib import Path

from live_monitor import AuthLogTailer


def auth_line(username="alice", port=50001, second=0):
    return (
        f"Oct  9 10:00:{second:02d} server sshd[1001]: "
        f"Failed password for {username} from 203.0.113.10 "
        f"port {port} ssh2"
    )


class TestAuthLogTailer(unittest.TestCase):
    def setUp(self):
        temporary = tempfile.TemporaryDirectory()
        self.addCleanup(temporary.cleanup)
        self.path = Path(temporary.name) / "auth.log"

    def test_starts_at_end_by_default(self):
        self.path.write_text(auth_line() + "\n", encoding="utf-8")
        monitor = AuthLogTailer(self.path, year=2026)

        self.assertEqual(monitor.poll_once(), [])

        with self.path.open("a", encoding="utf-8") as file:
            file.write(auth_line("bob", 50002, 1) + "\n")

        events = monitor.poll_once()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["username"], "bob")

    def test_can_read_existing_entries(self):
        self.path.write_text(auth_line() + "\n", encoding="utf-8")
        monitor = AuthLogTailer(
            self.path, start_at_end=False, year=2026
        )

        events = monitor.poll_once()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["username"], "alice")

    def test_buffers_incomplete_line(self):
        self.path.write_text("", encoding="utf-8")
        monitor = AuthLogTailer(
            self.path, start_at_end=False, year=2026
        )
        monitor.poll_once()

        with self.path.open("a", encoding="utf-8") as file:
            file.write(auth_line())

        self.assertEqual(monitor.poll_once(), [])

        with self.path.open("a", encoding="utf-8") as file:
            file.write("\n")

        self.assertEqual(len(monitor.poll_once()), 1)

    def test_suppresses_duplicate_lines(self):
        self.path.write_text("", encoding="utf-8")
        monitor = AuthLogTailer(
            self.path, start_at_end=False, year=2026
        )
        monitor.poll_once()

        with self.path.open("a", encoding="utf-8") as file:
            file.write(auth_line() + "\n")
            file.write(auth_line() + "\n")

        self.assertEqual(len(monitor.poll_once()), 1)

    def test_detects_truncation(self):
        self.path.write_text(
            auth_line("alice", 50001) + "\n"
            + auth_line("bob", 50002, 1) + "\n",
            encoding="utf-8",
        )
        monitor = AuthLogTailer(
            self.path, start_at_end=False, year=2026
        )
        self.assertEqual(len(monitor.poll_once()), 2)

        self.path.write_text(
            auth_line("charlie", 50003, 2) + "\n",
            encoding="utf-8",
        )
        events = monitor.poll_once()

        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["username"], "charlie")

    def test_detects_file_rotation(self):
        self.path.write_text(auth_line() + "\n", encoding="utf-8")
        monitor = AuthLogTailer(
            self.path, start_at_end=False, year=2026
        )
        self.assertEqual(len(monitor.poll_once()), 1)

        rotated = self.path.with_suffix(".log.1")
        self.path.rename(rotated)
        self.path.write_text(
            auth_line("bob", 50002, 1) + "\n",
            encoding="utf-8",
        )

        events = monitor.poll_once()
        self.assertEqual(len(events), 1)
        self.assertEqual(events[0]["username"], "bob")

    def test_recovers_after_temporary_file_error(self):
        monitor = AuthLogTailer(self.path, year=2026)

        self.assertEqual(monitor.poll_once(), [])
        self.assertIsNotNone(monitor.last_error)

        self.path.write_text(auth_line() + "\n", encoding="utf-8")
        events = monitor.poll_once()

        self.assertEqual(len(events), 1)
        self.assertIsNone(monitor.last_error)


if __name__ == "__main__":
    unittest.main()

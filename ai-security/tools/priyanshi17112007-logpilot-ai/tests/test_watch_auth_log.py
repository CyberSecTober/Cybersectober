"""Integration tests for the LogPilot AI live-monitoring command."""

import os
import queue
import signal
import subprocess
import sys
import tempfile
import threading
import time
import unittest
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]
SCRIPT = PROJECT_ROOT / "watch_auth_log.py"


def auth_line(message):
    return (
        f"Oct 11 14:00:00 server sshd[4001]: {message}\n"
    )


class TestWatchAuthLog(unittest.TestCase):
    def test_missing_log_file_returns_error(self):
        with tempfile.TemporaryDirectory() as temporary:
            missing = Path(temporary) / "missing.log"
            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(missing),
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=5,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("log file not found", result.stderr)

    def test_invalid_poll_interval_is_rejected(self):
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "auth.log"
            log_path.touch()

            result = subprocess.run(
                [
                    sys.executable,
                    str(SCRIPT),
                    "--input",
                    str(log_path),
                    "--poll-interval",
                    "0",
                ],
                cwd=PROJECT_ROOT,
                capture_output=True,
                text=True,
                timeout=5,
            )

        self.assertEqual(result.returncode, 2)
        self.assertIn("--poll-interval must be greater than zero",
                      result.stderr)

    def test_live_command_processes_mixed_events(self):
        with tempfile.TemporaryDirectory() as temporary:
            log_path = Path(temporary) / "auth.log"
            log_path.touch()

            process = subprocess.Popen(
                [
                    sys.executable,
                    "-u",
                    str(SCRIPT),
                    "--input",
                    str(log_path),
                    "--poll-interval",
                    "0.05",
                ],
                cwd=PROJECT_ROOT,
                stdout=subprocess.PIPE,
                stderr=subprocess.STDOUT,
                text=True,
                bufsize=1,
            )

            lines = queue.Queue()
            collected = []

            def read_output():
                if process.stdout is None:
                    return
                for line in process.stdout:
                    lines.put(line)

            reader = threading.Thread(target=read_output, daemon=True)
            reader.start()

            def wait_for_count(text, count, timeout=5):
                deadline = time.monotonic() + timeout
                while time.monotonic() < deadline:
                    if sum(text in line for line in collected) >= count:
                        return

                    remaining = deadline - time.monotonic()
                    try:
                        collected.append(lines.get(timeout=remaining))
                    except queue.Empty:
                        break

                self.fail(
                    f"Timed out waiting for {text!r} occurrence {count}.\n"
                    f"Output so far:\n{''.join(collected)}"
                )

            received_count = 0

            def append_and_wait(message):
                nonlocal received_count
                with log_path.open("a", encoding="utf-8") as file:
                    file.write(auth_line(message))

                received_count += 1
                wait_for_count("Received 1 parsed event(s).", received_count)

            try:
                wait_for_count("LogPilot AI live monitoring:", 1)

                # Three distinct failed usernames should trigger AUTH-002.
                append_and_wait(
                    "Failed password for invalid user deploy "
                    "from 198.51.100.77 port 53001 ssh2"
                )
                append_and_wait(
                    "Invalid user oracle from 198.51.100.77 port 53002"
                )
                append_and_wait(
                    "Failed password for root "
                    "from 198.51.100.77 port 53003 ssh2"
                )
                wait_for_count(
                    "AUTH-002: Multiple usernames targeted from one IP", 1
                )

                # Successful login must be parsed, not counted as a failure.
                append_and_wait(
                    "Accepted publickey for analyst "
                    "from 192.0.2.45 port 53004 ssh2"
                )

                append_and_wait(
                    "Failed password for admin "
                    "from 198.51.100.77 port 53005 ssh2"
                )

                # An unrelated message must not produce a parsed event.
                with log_path.open("a", encoding="utf-8") as file:
                    file.write(
                        auth_line(
                            "Connection closed by authenticating user admin "
                            "198.51.100.77 port 53006 [preauth]"
                        )
                    )

                time.sleep(0.2)
                self.assertEqual(received_count, 5)

                append_and_wait(
                    "Failed password for deploy "
                    "from 198.51.100.77 port 53007 ssh2"
                )

                wait_for_count(
                    "AUTH-001: Repeated failed login attempts", 1
                )
                wait_for_count("Events scanned:       6", 1)
                wait_for_count("Failed login events:  5", 1)

                output = "".join(collected)
                self.assertIn(
                    "AUTH-002: Multiple usernames targeted from one IP",
                    output,
                )
                self.assertIn("Source IP: 198.51.100.77", output)
                self.assertIn("LLM used: No", output)

            finally:
                if process.poll() is None:
                    process.send_signal(signal.SIGINT)
                    try:
                        process.wait(timeout=3)
                    except subprocess.TimeoutExpired:
                        process.kill()
                        process.wait(timeout=3)

                if process.stdout is not None:
                    process.stdout.close()


if __name__ == "__main__":
    unittest.main()

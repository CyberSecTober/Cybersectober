"""Poll a Linux SSH authentication log for new entries."""

from __future__ import annotations

import hashlib
import os
from collections import OrderedDict
from pathlib import Path
from typing import Any

from log_parser import parse_auth_line


class AuthLogTailer:
    """Read newly appended SSH log entries without reprocessing duplicates."""

    def __init__(
        self,
        path: str | Path,
        *,
        start_at_end: bool = True,
        year: int | None = None,
        max_seen_lines: int = 10_000,
    ) -> None:
        if max_seen_lines < 1:
            raise ValueError("max_seen_lines must be at least 1")

        self.path = Path(path)
        self.start_at_end = start_at_end
        self.year = year
        self.max_seen_lines = max_seen_lines

        self._identity: tuple[int, int] | None = None
        self._offset = 0
        self._partial = b""
        self._seen: OrderedDict[str, None] = OrderedDict()
        self._recovery_required = False

        # Exposed so the caller can report temporary file-access problems.
        self.last_error: str | None = None

    def _already_seen(self, line: str) -> bool:
        """Remember recent exact log lines to suppress duplicate processing."""
        fingerprint = hashlib.sha256(line.encode("utf-8")).hexdigest()

        if fingerprint in self._seen:
            self._seen.move_to_end(fingerprint)
            return True

        self._seen[fingerprint] = None

        if len(self._seen) > self.max_seen_lines:
            self._seen.popitem(last=False)

        return False

    def poll_once(self) -> list[dict[str, Any]]:
        """Read currently available complete lines and return parsed events.

        The first poll normally starts at the end of an existing file.
        Set start_at_end=False to process its existing contents instead.
        """
        try:
            with self.path.open("rb") as stream:
                file_stat = os.fstat(stream.fileno())
                identity = (file_stat.st_dev, file_stat.st_ino)

                if self._identity is None and not self._recovery_required:
                    self._identity = identity

                    if self.start_at_end:
                        stream.seek(0, os.SEEK_END)
                        self._offset = stream.tell()
                        self.last_error = None
                        return []

                    self._offset = 0

                elif (
                    self._recovery_required
                    or identity != self._identity
                    or file_stat.st_size < self._offset
                ):
                    # A replacement, truncation, or recovery requires a rescan.
                    self._identity = identity
                    self._offset = 0
                    self._partial = b""
                    self._recovery_required = False

                stream.seek(self._offset)
                data = stream.read()
                self._offset = stream.tell()

        except OSError as exc:
            self.last_error = str(exc)
            self._recovery_required = True
            return []

        self.last_error = None

        chunks = (self._partial + data).split(b"\n")
        self._partial = chunks.pop()

        events: list[dict[str, Any]] = []

        for raw_line in chunks:
            line = raw_line.rstrip(b"\r").decode(
                "utf-8", errors="replace"
            ).strip()

            if not line or self._already_seen(line):
                continue

            event = parse_auth_line(line, year=self.year)
            if event is not None:
                events.append(event)

        return events

"""Structured event logging for mission coordination.

Events are appended to .ai/events.log in a simple, grep-friendly format:
  YYYY-MM-DDTHH:MM:SS  <category>  <actor>  <message>

This module also writes to the main aifw log at logs/aifw.log.
"""

from __future__ import annotations

import logging
import sys
from datetime import datetime, timezone
from pathlib import Path

logger = logging.getLogger("aifw")

# ---------------------------------------------------------------------------
# Event categories
# ---------------------------------------------------------------------------

MISSION = "mission"
WORKER = "worker"
CONTAINER = "container"
ASSIGNMENT = "assignment"
STATUS = "status"
ERROR = "error"


# ---------------------------------------------------------------------------
# Event logger
# ---------------------------------------------------------------------------


class EventLog:
    """Append-only structured event log for a mission."""

    def __init__(self, events_path: Path, aifw_log_path: Path | None = None) -> None:
        self._events_path = events_path
        self._events_path.parent.mkdir(parents=True, exist_ok=True)

        if aifw_log_path:
            aifw_log_path.parent.mkdir(parents=True, exist_ok=True)
            handler = logging.FileHandler(aifw_log_path)
            handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s"))
            logger.addHandler(handler)

    def log(self, category: str, actor: str, message: str) -> None:
        """Write one event line."""
        ts = datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")
        line = f"{ts}  {category:<12s}  {actor:<16s}  {message}\n"
        with open(self._events_path, "a") as f:
            f.write(line)
        logger.info("%s  %s  %s", category, actor, message)

    def read_recent(self, n: int = 20) -> list[str]:
        """Return the last n event lines."""
        if not self._events_path.exists():
            return []
        lines = self._events_path.read_text().splitlines()
        return lines[-n:]


def setup_stderr_logging(level: str = "INFO") -> None:
    """Configure the aifw logger to also write to stderr."""
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)s  %(message)s"))
    logger.addHandler(handler)
    logger.setLevel(getattr(logging, level.upper(), logging.INFO))

"""Tests for aifw.events."""

from __future__ import annotations

from pathlib import Path

from aifw.events import MISSION, WORKER, EventLog


def test_event_log_creates_file(tmp_path: Path) -> None:
    events_path = tmp_path / "events.log"
    log = EventLog(events_path)
    log.log(MISSION, "aifw", "test event")
    assert events_path.exists()
    content = events_path.read_text()
    assert "mission" in content
    assert "test event" in content


def test_event_log_append(tmp_path: Path) -> None:
    events_path = tmp_path / "events.log"
    log = EventLog(events_path)
    log.log(MISSION, "aifw", "first")
    log.log(WORKER, "alpha", "second")
    lines = events_path.read_text().strip().splitlines()
    assert len(lines) == 2


def test_read_recent(tmp_path: Path) -> None:
    events_path = tmp_path / "events.log"
    log = EventLog(events_path)
    for i in range(30):
        log.log(MISSION, "aifw", f"event-{i}")

    recent = log.read_recent(5)
    assert len(recent) == 5
    assert "event-29" in recent[-1]
    assert "event-25" in recent[0]


def test_read_recent_empty(tmp_path: Path) -> None:
    events_path = tmp_path / "events.log"
    log = EventLog(events_path)
    assert log.read_recent() == []


def test_event_format(tmp_path: Path) -> None:
    events_path = tmp_path / "events.log"
    log = EventLog(events_path)
    log.log("container", "aifw", "started")
    line = events_path.read_text().strip()
    # Format: YYYY-MM-DDTHH:MM:SSZ  category  actor  message
    parts = line.split("  ")
    assert len(parts) >= 4
    assert parts[0].endswith("Z")  # UTC timestamp
    assert "container" in parts[1]

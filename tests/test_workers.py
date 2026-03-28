"""Tests for aifw.workers."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from aifw.config import load_config
from aifw.mission import Mission
from aifw.workers import assign_worker, list_workers, render_brief


def _make_config(tmp_path: Path):
    config = load_config(tmp_path / "nonexistent.toml")
    object.__setattr__(config, "mission_root", tmp_path / "missions")
    return config


def _make_mission(tmp_path: Path, mission_id: str = "test-w01") -> tuple:
    config = _make_config(tmp_path)
    mission = Mission(mission_id, config)
    mission.init_directory(["/tmp/repo-a"])
    return config, mission


def test_render_brief(tmp_path: Path) -> None:
    _, mission = _make_mission(tmp_path)
    brief = render_brief("alpha", mission, "/tmp/repo-a", "Implement the login API")
    assert "alpha" in brief
    assert "repo-a" in brief
    assert "Implement the login API" in brief
    assert "status" in brief.lower()
    assert "handoff" in brief.lower()


def test_list_workers_empty(tmp_path: Path) -> None:
    _, mission = _make_mission(tmp_path)
    assert list_workers(mission) == []


@mock.patch("aifw.workers.launch_worker_session")
def test_assign_worker_creates_brief(mock_launch, tmp_path: Path) -> None:
    config, mission = _make_mission(tmp_path)

    assign_worker(config, mission, "alpha", "Build the auth module", "/tmp/repo-a")

    # Brief file should exist
    brief_path = mission.ai_dir / "workers" / "alpha.md"
    assert brief_path.exists()
    assert "Build the auth module" in brief_path.read_text()

    # Status file should exist
    status_path = mission.ai_dir / "status" / "alpha.json"
    assert status_path.exists()
    data = json.loads(status_path.read_text())
    assert data["worker"] == "alpha"
    assert data["status"] == "ready"
    assert data["repo"] == "/tmp/repo-a"

    # Event should be logged
    events = (mission.ai_dir / "events.log").read_text()
    assert "alpha" in events
    assert "assignment" in events.lower()

    # Claude session should have been launched
    mock_launch.assert_called_once()


@mock.patch("aifw.workers.launch_worker_session")
def test_assign_worker_from_file(mock_launch, tmp_path: Path) -> None:
    config, mission = _make_mission(tmp_path)

    # Write a task file
    task_file = tmp_path / "my-task.md"
    task_file.write_text("# Task\nDo something complex with the API.")

    assign_worker(config, mission, "beta", str(task_file), "/tmp/repo-a")

    brief = (mission.ai_dir / "workers" / "beta.md").read_text()
    assert "Do something complex with the API" in brief


@mock.patch("aifw.workers.launch_worker_session")
def test_assign_worker_uses_first_repo_if_none(mock_launch, tmp_path: Path) -> None:
    config, mission = _make_mission(tmp_path)

    assign_worker(config, mission, "gamma", "A task")

    status = json.loads((mission.ai_dir / "status" / "gamma.json").read_text())
    assert status["repo"] == "/tmp/repo-a"


@mock.patch("aifw.workers.send_prompt_to_worker")
@mock.patch("aifw.workers.launch_worker_session")
def test_reassign_sends_prompt(mock_launch, mock_send, tmp_path: Path) -> None:
    config, mission = _make_mission(tmp_path)

    # First assignment creates the window
    assign_worker(config, mission, "delta", "First task", "/tmp/repo-a")
    mock_launch.assert_called_once()

    # Simulate the window existing
    with mock.patch("aifw.tmux.window_exists", return_value=True):
        assign_worker(config, mission, "delta", "New task", "/tmp/repo-a")

    # Should have sent prompt, not launched a new session
    mock_send.assert_called_once()


@mock.patch("aifw.workers.launch_worker_session")
def test_list_workers_after_assign(mock_launch, tmp_path: Path) -> None:
    config, mission = _make_mission(tmp_path)

    assign_worker(config, mission, "w1", "Task 1", "/tmp/repo-a")
    assign_worker(config, mission, "w2", "Task 2", "/tmp/repo-a")

    workers = list_workers(mission)
    assert len(workers) == 2
    names = {w["worker"] for w in workers}
    assert names == {"w1", "w2"}

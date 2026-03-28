"""Tests for aifw.mission."""

from __future__ import annotations

from pathlib import Path
from unittest import mock

import pytest

from aifw.config import load_config
from aifw.mission import Mission, generate_mission_id, find_current_mission, list_missions


def _make_config(tmp_path: Path):
    """Create a config pointing to a tmp mission root."""
    config = load_config(tmp_path / "nonexistent.toml")
    # Override mission_root to use tmp
    object.__setattr__(config, "mission_root", tmp_path / "missions")
    return config


def test_generate_mission_id() -> None:
    mid = generate_mission_id()
    # Format: YYYYMMDD-xxxx
    assert len(mid) == 13
    parts = mid.split("-")
    assert len(parts) == 2
    assert len(parts[0]) == 8  # date
    assert len(parts[1]) == 4  # random


def test_mission_directory_structure(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    mission = Mission("test-001", config)
    mission.init_directory(["/tmp/repo-a", "/tmp/repo-b"])

    # Check directory tree
    assert mission.root.exists()
    assert mission.control_dir.exists()
    assert mission.repos_dir.exists()
    assert mission.logs_dir.exists()
    assert mission.worker_logs_dir.exists()
    assert mission.runtime_dir.exists()
    assert mission.ai_dir.exists()
    assert (mission.ai_dir / "workers").exists()
    assert (mission.ai_dir / "status").exists()
    assert (mission.ai_dir / "handoffs").exists()
    assert (mission.ai_dir / "contracts").exists()

    # Check initial files
    assert mission.mission_toml_path.exists()
    assert (mission.ai_dir / "spec.md").exists()
    assert (mission.ai_dir / "architecture.md").exists()
    assert (mission.ai_dir / "task-board.yaml").exists()
    assert (mission.ai_dir / "events.log").exists()

    # Check runtime markers
    assert (mission.runtime_dir / "tmux-session").read_text() == mission.tmux_session
    assert (mission.runtime_dir / "container-name").read_text() == mission.container_name


def test_mission_naming(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    mission = Mission("20260327-abcd", config)
    assert mission.container_name == "aifw-20260327-abcd"
    assert mission.tmux_session == "aifw-20260327-abcd"


def test_mission_exists(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    mission = Mission("test-002", config)
    assert not mission.exists()
    mission.init_directory([])
    assert mission.exists()


def test_repo_paths_roundtrip(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    mission = Mission("test-003", config)
    repos = ["/tmp/repo-x", "/tmp/repo-y"]
    mission.init_directory(repos)
    loaded = mission.repo_paths()
    assert loaded == repos


def test_worker_names_empty(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    mission = Mission("test-004", config)
    mission.init_directory([])
    assert mission.worker_names() == []


def test_worker_names_with_workers(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    mission = Mission("test-005", config)
    mission.init_directory([])
    (mission.ai_dir / "workers" / "alpha.md").write_text("brief")
    (mission.ai_dir / "workers" / "beta.md").write_text("brief")
    assert mission.worker_names() == ["alpha", "beta"]


def test_read_worker_status(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    mission = Mission("test-006", config)
    mission.init_directory([])

    # No status file
    assert mission.read_worker_status("ghost") is None

    # Write a status
    import json
    status = {"worker": "alpha", "status": "in_progress", "summary": "working"}
    (mission.ai_dir / "status" / "alpha.json").write_text(json.dumps(status))
    loaded = mission.read_worker_status("alpha")
    assert loaded is not None
    assert loaded["status"] == "in_progress"


def test_find_current_mission(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    # No missions
    assert find_current_mission(config) is None

    # Create one
    m = Mission("test-007", config)
    m.init_directory([])
    found = find_current_mission(config)
    assert found is not None
    assert found.mission_id == "test-007"


def test_list_missions(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    assert list_missions(config) == []

    Mission("aaa-001", config).init_directory([])
    Mission("bbb-002", config).init_directory([])

    missions = list_missions(config)
    assert len(missions) == 2


def test_build_mounts(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    mission = Mission("test-008", config)
    mission.init_directory([])

    repo = tmp_path / "my-repo"
    repo.mkdir()

    mounts = mission.build_mounts([str(repo)])

    names = [m.name for m in mounts]
    assert "mission" in names
    assert "repo-my-repo" in names
    assert "claude-config" in names

    # Mission mount uses the same path in container
    mission_mount = next(m for m in mounts if m.name == "mission")
    assert mission_mount.source == str(mission.root)
    assert mission_mount.path == str(mission.root)

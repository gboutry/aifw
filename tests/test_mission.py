"""Tests for aifw.mission."""

from __future__ import annotations

import subprocess
from pathlib import Path
from unittest import mock

import pytest

from aifw.config import load_config
from aifw.mission import Mission, generate_mission_id, find_current_mission, list_missions


def _make_config(tmp_path: Path):
    """Create a config pointing to a tmp mission root."""
    config = load_config(tmp_path / "nonexistent.toml")
    object.__setattr__(config, "mission_root", tmp_path / "missions")
    return config


def _init_git_repo(path: Path) -> Path:
    """Create a git repo with one commit."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "t@t.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "T"], check=True, capture_output=True)
    (path / "README.md").write_text("# test\n")
    subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], check=True, capture_output=True)
    return path


def test_generate_mission_id() -> None:
    mid = generate_mission_id()
    assert len(mid) == 13
    parts = mid.split("-")
    assert len(parts) == 2
    assert len(parts[0]) == 8
    assert len(parts[1]) == 4


def test_mission_directory_structure(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    repo_a = _init_git_repo(tmp_path / "repo-a")
    repo_b = _init_git_repo(tmp_path / "repo-b")

    mission = Mission("test-001", config)
    mission.init_directory([str(repo_a), str(repo_b)])

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
    assert mission.mission_toml_path.exists()
    assert (mission.ai_dir / "spec.md").exists()
    assert (mission.ai_dir / "architecture.md").exists()
    assert (mission.ai_dir / "task-board.yaml").exists()
    assert (mission.ai_dir / "events.log").exists()
    assert (mission.runtime_dir / "tmux-session").read_text() == mission.tmux_session
    assert (mission.runtime_dir / "container-name").read_text() == mission.container_name


def test_repos_are_cloned(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    repo_a = _init_git_repo(tmp_path / "repo-a")

    mission = Mission("test-clone", config)
    mission.init_directory([str(repo_a)])

    clone_path = mission.repos_dir / "repo-a"
    assert clone_path.exists()
    assert (clone_path / ".git").exists()
    assert (clone_path / "README.md").exists()

    result = subprocess.run(
        ["git", "-C", str(clone_path), "remote", "get-url", "origin"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == str(repo_a)


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
    repo_a = _init_git_repo(tmp_path / "repo-x")
    repo_b = _init_git_repo(tmp_path / "repo-y")

    mission = Mission("test-003", config)
    original_paths = [str(repo_a), str(repo_b)]
    mission.init_directory(original_paths)
    loaded = mission.repo_paths()
    assert loaded == original_paths


def test_clone_paths(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    repo_a = _init_git_repo(tmp_path / "my-api")

    mission = Mission("test-cp", config)
    mission.init_directory([str(repo_a)])

    clone_paths = mission.clone_paths()
    assert len(clone_paths) == 1
    assert clone_paths["my-api"] == str(mission.repos_dir / "my-api")


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
    assert mission.read_worker_status("ghost") is None
    import json
    status = {"worker": "alpha", "status": "in_progress", "summary": "working"}
    (mission.ai_dir / "status" / "alpha.json").write_text(json.dumps(status))
    loaded = mission.read_worker_status("alpha")
    assert loaded is not None
    assert loaded["status"] == "in_progress"


def test_find_current_mission(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    assert find_current_mission(config) is None
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


def test_build_mounts_no_per_repo_mounts(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    mission = Mission("test-008", config)
    mission.init_directory([])

    mounts = mission.build_mounts()
    names = [m.name for m in mounts]
    assert "mission" in names
    assert "claude-config" in names
    assert not any(n.startswith("repo-") for n in names)


def test_check_unpushed_clean(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    repo_a = _init_git_repo(tmp_path / "repo-a")
    mission = Mission("test-up1", config)
    mission.init_directory([str(repo_a)])

    result = mission.check_unpushed()
    status = result["repo-a"]
    assert status.dirty is False
    # The mission branch has no remote tracking branch (local-only clone),
    # so it is reported as unpushed. No uncommitted changes though.
    assert status.unpushed == ["mission/test-up1"]


def test_check_unpushed_dirty(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    repo_a = _init_git_repo(tmp_path / "repo-a2")
    mission = Mission("test-up2", config)
    mission.init_directory([str(repo_a)])

    clone = mission.repos_dir / "repo-a2"
    (clone / "new.txt").write_text("dirty")

    result = mission.check_unpushed()
    assert result["repo-a2"].dirty is True


def test_clones_on_mission_branch(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    repo_a = _init_git_repo(tmp_path / "repo-a3")

    mission = Mission("20260329-xyz1", config)
    mission.init_directory([str(repo_a)])

    clone = mission.repos_dir / "repo-a3"
    result = subprocess.run(
        ["git", "-C", str(clone), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "mission/20260329-xyz1"


def test_init_directory_with_spec_content(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    mission = Mission("test-spec", config)
    mission.init_directory([], spec_content="# My Objective\n\nBuild the auth system.")

    spec = (mission.ai_dir / "spec.md").read_text()
    assert "My Objective" in spec
    assert "Build the auth system" in spec


def test_init_directory_without_spec_content_uses_template(tmp_path: Path) -> None:
    config = _make_config(tmp_path)

    mission = Mission("test-nospec", config)
    mission.init_directory([])

    spec = (mission.ai_dir / "spec.md").read_text()
    assert "Define the mission objective here" in spec

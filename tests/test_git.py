"""Tests for aifw.git."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aifw.git import clone_local, GitError, has_uncommitted, has_unpushed, repo_status, RepoStatus


def _init_repo(path: Path, *, commit: bool = True) -> Path:
    """Create a git repo with one commit."""
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", str(path)], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.email", "test@test.com"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(path), "config", "user.name", "Test"], check=True, capture_output=True)
    if commit:
        (path / "README.md").write_text("# test\n")
        subprocess.run(["git", "-C", str(path), "add", "."], check=True, capture_output=True)
        subprocess.run(["git", "-C", str(path), "commit", "-m", "init"], check=True, capture_output=True)
    return path


def test_clone_local(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin")
    dest = tmp_path / "clone"

    clone_local(str(origin), str(dest))

    assert dest.exists()
    assert (dest / ".git").exists()
    assert (dest / "README.md").exists()

    result = subprocess.run(
        ["git", "-C", str(dest), "remote", "get-url", "origin"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == str(origin)


def test_clone_local_nonexistent_source(tmp_path: Path) -> None:
    with pytest.raises(GitError):
        clone_local(str(tmp_path / "nope"), str(tmp_path / "dest"))


def test_has_uncommitted_clean(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "clean")
    assert has_uncommitted(str(repo)) is False


def test_has_uncommitted_dirty(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "dirty")
    (repo / "new_file.txt").write_text("change")
    assert has_uncommitted(str(repo)) is True


def test_has_unpushed_no_remote(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "no-remote")
    assert has_unpushed(str(repo)) == []


def test_has_unpushed_clean_clone(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin2")
    dest = tmp_path / "clone2"
    clone_local(str(origin), str(dest))
    assert has_unpushed(str(dest)) == []


def test_has_unpushed_with_local_commit(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin3")
    dest = tmp_path / "clone3"
    clone_local(str(origin), str(dest))

    (dest / "extra.txt").write_text("extra")
    subprocess.run(["git", "-C", str(dest), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "commit", "-m", "local change"], check=True, capture_output=True)

    unpushed = has_unpushed(str(dest))
    assert len(unpushed) > 0


def test_repo_status_clean_clone(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin4")
    dest = tmp_path / "clone4"
    clone_local(str(origin), str(dest))

    status = repo_status(str(dest))
    assert isinstance(status, RepoStatus)
    assert status.branch == "main" or status.branch == "master"
    assert status.dirty is False
    assert status.unpushed == []


def test_repo_status_dirty_with_unpushed(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin5")
    dest = tmp_path / "clone5"
    clone_local(str(origin), str(dest))

    (dest / "new.txt").write_text("new")
    (dest / "committed.txt").write_text("committed")
    subprocess.run(["git", "-C", str(dest), "add", "committed.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "commit", "-m", "local"], check=True, capture_output=True)

    status = repo_status(str(dest))
    assert status.dirty is True
    assert len(status.unpushed) > 0

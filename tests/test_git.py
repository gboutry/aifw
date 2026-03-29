"""Tests for aifw.git."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aifw.git import clone_local, current_branch, GitError, has_uncommitted, has_unpushed, repo_status, RepoStatus, push_branch, PushResult


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


def test_clone_local_with_branch(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin6")
    dest = tmp_path / "clone6"

    clone_local(str(origin), str(dest), branch="mission/test-001")

    assert dest.exists()
    result = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "mission/test-001"


def test_clone_local_without_branch_stays_on_default(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin7")
    dest = tmp_path / "clone7"

    clone_local(str(origin), str(dest))

    result = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() in ("main", "master")


def test_clone_local_existing_branch(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin8")
    # Create a branch in the origin
    subprocess.run(
        ["git", "-C", str(origin), "checkout", "-b", "feat/my-feature"],
        check=True, capture_output=True,
    )
    (origin / "feature.txt").write_text("feature work")
    subprocess.run(["git", "-C", str(origin), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(origin), "commit", "-m", "feature"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(origin), "checkout", "main"], check=True, capture_output=True)

    dest = tmp_path / "clone8"
    clone_local(str(origin), str(dest), branch="feat/my-feature", existing_branch=True)

    result = subprocess.run(
        ["git", "-C", str(dest), "rev-parse", "--abbrev-ref", "HEAD"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == "feat/my-feature"
    assert (dest / "feature.txt").exists()


def test_push_branch_up_to_date(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin-push1")
    dest = tmp_path / "clone-push1"
    clone_local(str(origin), str(dest))

    result = push_branch(str(dest), "main")
    assert isinstance(result, PushResult)
    assert result.up_to_date is True
    assert result.pushed == 0
    assert result.error is None


def test_push_branch_with_commits(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin-push2")
    subprocess.run(
        ["git", "-C", str(origin), "config", "receive.denyCurrentBranch", "ignore"],
        check=True, capture_output=True,
    )
    dest = tmp_path / "clone-push2"
    clone_local(str(origin), str(dest))

    (dest / "new.txt").write_text("new")
    subprocess.run(["git", "-C", str(dest), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "commit", "-m", "local"], check=True, capture_output=True)

    branch = current_branch(str(dest))
    result = push_branch(str(dest), branch)
    assert result.up_to_date is False
    assert result.pushed >= 1
    assert result.error is None


def test_push_branch_dry_run(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin-push3")
    dest = tmp_path / "clone-push3"
    clone_local(str(origin), str(dest))

    (dest / "dry.txt").write_text("dry")
    subprocess.run(["git", "-C", str(dest), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "commit", "-m", "dry"], check=True, capture_output=True)

    branch = current_branch(str(dest))
    result = push_branch(str(dest), branch, dry_run=True)
    assert result.error is None

    origin_log = subprocess.run(
        ["git", "-C", str(origin), "log", "--oneline"],
        capture_output=True, text=True, check=True,
    )
    assert len(origin_log.stdout.strip().splitlines()) == 1


def test_push_branch_new_branch(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin-push4")
    dest = tmp_path / "clone-push4"
    clone_local(str(origin), str(dest), branch="mission/test-push")

    (dest / "feat.txt").write_text("feat")
    subprocess.run(["git", "-C", str(dest), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "commit", "-m", "feat"], check=True, capture_output=True)

    result = push_branch(str(dest), "mission/test-push")
    assert result.error is None
    assert result.pushed >= 1

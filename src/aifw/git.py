"""Git CLI wrapper for repo cloning and status checking.

All operations use subprocess to call git directly.
Same pattern as lxd.py — thin, inspectable, no library dependency.
"""

from __future__ import annotations

import logging
import subprocess
from dataclasses import dataclass, field

logger = logging.getLogger("aifw")


class GitError(Exception):
    """Raised when a git operation fails."""


@dataclass
class RepoStatus:
    """Snapshot of a repo's git state."""

    branch: str
    dirty: bool
    unpushed: list[str] = field(default_factory=list)


def _run_git(
    args: list[str],
    *,
    cwd: str | None = None,
    check: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a git command."""
    cmd = ["git", *args]
    logger.debug("git %s", " ".join(args))
    try:
        return subprocess.run(
            cmd,
            check=check,
            capture_output=True,
            text=True,
            cwd=cwd,
            timeout=120,
        )
    except subprocess.CalledProcessError as exc:
        raise GitError(
            f"git {' '.join(args)} failed (rc={exc.returncode}): {exc.stderr}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise GitError(f"git {' '.join(args)} timed out") from exc


def clone_local(source: str, dest: str, *, branch: str | None = None) -> None:
    """Clone a repo using --local for hardlinked objects.

    If branch is provided, create and checkout that branch after cloning.
    """
    _run_git(["clone", "--local", source, dest])
    if branch:
        _run_git(["checkout", "-b", branch], cwd=dest)


def has_uncommitted(repo_path: str) -> bool:
    """Return True if the working tree has uncommitted changes."""
    result = _run_git(["status", "--porcelain"], cwd=repo_path)
    return bool(result.stdout.strip())


def has_unpushed(repo_path: str) -> list[str]:
    """Return list of local branches with commits not pushed to origin.

    Returns an empty list if there is no remote or all branches are up to date.
    """
    # Check if origin remote exists
    result = _run_git(["remote"], cwd=repo_path)
    if "origin" not in result.stdout.splitlines():
        return []

    # Fetch to make sure we have up-to-date remote refs
    _run_git(["fetch", "origin", "--quiet"], cwd=repo_path, check=False)

    # List local branches
    result = _run_git(
        ["for-each-ref", "--format=%(refname:short)", "refs/heads/"],
        cwd=repo_path,
    )
    branches = [b.strip() for b in result.stdout.splitlines() if b.strip()]

    unpushed = []
    for branch in branches:
        # Check if remote tracking branch exists
        remote_ref = f"origin/{branch}"
        check = _run_git(
            ["rev-parse", "--verify", remote_ref],
            cwd=repo_path,
            check=False,
        )
        if check.returncode != 0:
            # No remote tracking branch — all commits are "unpushed"
            unpushed.append(branch)
            continue

        # Count commits ahead of remote
        result = _run_git(
            ["log", "--oneline", f"{remote_ref}..{branch}"],
            cwd=repo_path,
        )
        if result.stdout.strip():
            unpushed.append(branch)

    return unpushed


def current_branch(repo_path: str) -> str:
    """Return the current branch name."""
    result = _run_git(["rev-parse", "--abbrev-ref", "HEAD"], cwd=repo_path)
    return result.stdout.strip()


def repo_status(repo_path: str) -> RepoStatus:
    """Return a snapshot of the repo's git state."""
    return RepoStatus(
        branch=current_branch(repo_path),
        dirty=has_uncommitted(repo_path),
        unpushed=has_unpushed(repo_path),
    )

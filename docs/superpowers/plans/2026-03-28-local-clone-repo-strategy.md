# Local Clone Repo Strategy Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace direct repo mounts with local git clones so each mission gets isolated copies, and add destroy safety checks for unpushed work.

**Architecture:** New `git.py` module wraps git CLI for clone/status operations. `mission.py` calls `git.py` to clone repos during init and check unpushed work during destroy. `build_mounts()` drops per-repo mounts since clones live under the mission directory. `cli.py` adds `--force` to destroy and gates on unpushed check.

**Tech Stack:** Python 3.12+, subprocess (git CLI), pytest

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Create | `src/aifw/git.py` | Git CLI wrapper: clone_local, has_unpushed, has_uncommitted, repo_status |
| Create | `tests/test_git.py` | Tests for git.py (uses real git repos in tmp_path) |
| Modify | `src/aifw/mission.py:111-153` | Replace symlinks with clones, simplify build_mounts, add check_unpushed, update mission.toml format |
| Modify | `src/aifw/cli.py:57-58,176-207` | Add --force to destroy parser, gate destroy on unpushed check |
| Modify | `src/aifw/status.py:64-70` | Show git status (branch, dirty, unpushed) per repo |
| Modify | `src/aifw/tmux.py:247-260` | Point git/integration windows to clone paths |
| Modify | `tests/test_mission.py:32-35,77-83,145-163` | Update tests for clone-based repos, fix build_mounts test |

---

### Task 1: Create `git.py` — `clone_local`

**Files:**
- Create: `src/aifw/git.py`
- Create: `tests/test_git.py`

- [ ] **Step 1: Write the failing test for clone_local**

```python
# tests/test_git.py
"""Tests for aifw.git."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from aifw.git import clone_local, GitError


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

    # origin remote should point to the source
    result = subprocess.run(
        ["git", "-C", str(dest), "remote", "get-url", "origin"],
        capture_output=True, text=True, check=True,
    )
    assert result.stdout.strip() == str(origin)


def test_clone_local_nonexistent_source(tmp_path: Path) -> None:
    with pytest.raises(GitError):
        clone_local(str(tmp_path / "nope"), str(tmp_path / "dest"))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `uv run pytest tests/test_git.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'aifw.git'`

- [ ] **Step 3: Write minimal implementation**

```python
# src/aifw/git.py
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


def clone_local(source: str, dest: str) -> None:
    """Clone a repo using --local for hardlinked objects."""
    _run_git(["clone", "--local", source, dest])
```

- [ ] **Step 4: Run test to verify it passes**

Run: `uv run pytest tests/test_git.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aifw/git.py tests/test_git.py
git commit -m "feat(git): add git.py module with clone_local"
```

---

### Task 2: Add `has_uncommitted` and `has_unpushed` to `git.py`

**Files:**
- Modify: `src/aifw/git.py`
- Modify: `tests/test_git.py`

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_git.py`:

```python
from aifw.git import has_uncommitted, has_unpushed


def test_has_uncommitted_clean(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "clean")
    assert has_uncommitted(str(repo)) is False


def test_has_uncommitted_dirty(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "dirty")
    (repo / "new_file.txt").write_text("change")
    assert has_uncommitted(str(repo)) is True


def test_has_unpushed_no_remote(tmp_path: Path) -> None:
    repo = _init_repo(tmp_path / "no-remote")
    # No remote — nothing to compare against, should return empty
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

    # Make a local commit
    (dest / "extra.txt").write_text("extra")
    subprocess.run(["git", "-C", str(dest), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "commit", "-m", "local change"], check=True, capture_output=True)

    unpushed = has_unpushed(str(dest))
    assert len(unpushed) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_git.py -v`
Expected: FAIL — `ImportError: cannot import name 'has_uncommitted'`

- [ ] **Step 3: Implement has_uncommitted and has_unpushed**

Append to `src/aifw/git.py`:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_git.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aifw/git.py tests/test_git.py
git commit -m "feat(git): add has_uncommitted and has_unpushed"
```

---

### Task 3: Add `repo_status` dataclass to `git.py`

**Files:**
- Modify: `src/aifw/git.py`
- Modify: `tests/test_git.py`

- [ ] **Step 1: Write the failing test**

Append to `tests/test_git.py`:

```python
from aifw.git import repo_status, RepoStatus


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

    # Dirty working tree
    (dest / "new.txt").write_text("new")
    # Unpushed commit
    (dest / "committed.txt").write_text("committed")
    subprocess.run(["git", "-C", str(dest), "add", "committed.txt"], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "commit", "-m", "local"], check=True, capture_output=True)

    status = repo_status(str(dest))
    assert status.dirty is True
    assert len(status.unpushed) > 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_git.py::test_repo_status_clean_clone -v`
Expected: FAIL — `ImportError: cannot import name 'repo_status'`

- [ ] **Step 3: Implement RepoStatus and repo_status**

Add to `src/aifw/git.py` (the `RepoStatus` dataclass near the top after imports, `repo_status` function at the bottom):

Add after `logger = logging.getLogger("aifw")`:

```python
@dataclass
class RepoStatus:
    """Snapshot of a repo's git state."""

    branch: str
    dirty: bool
    unpushed: list[str] = field(default_factory=list)
```

Add at the bottom of the file:

```python
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
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_git.py -v`
Expected: PASS (all 9 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aifw/git.py tests/test_git.py
git commit -m "feat(git): add RepoStatus dataclass and repo_status function"
```

---

### Task 4: Replace symlinks with clones in `mission.py`

**Files:**
- Modify: `src/aifw/mission.py:111-153,155-172,276-310,336-343`
- Modify: `tests/test_mission.py`

- [ ] **Step 1: Write failing tests for clone-based init**

Replace the existing `test_mission_directory_structure`, `test_repo_paths_roundtrip`, and `test_build_mounts` tests, and add a new clone test. Replace the full content of `tests/test_mission.py` with:

```python
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

    # Check origin points to the original
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
    # No repo-* mounts
    assert not any(n.startswith("repo-") for n in names)


def test_check_unpushed_clean(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    repo_a = _init_git_repo(tmp_path / "repo-a")
    mission = Mission("test-up1", config)
    mission.init_directory([str(repo_a)])

    result = mission.check_unpushed()
    status = result["repo-a"]
    assert status.dirty is False
    assert status.unpushed == []


def test_check_unpushed_dirty(tmp_path: Path) -> None:
    config = _make_config(tmp_path)
    repo_a = _init_git_repo(tmp_path / "repo-a2")
    mission = Mission("test-up2", config)
    mission.init_directory([str(repo_a)])

    # Dirty the clone
    clone = mission.repos_dir / "repo-a2"
    (clone / "new.txt").write_text("dirty")

    result = mission.check_unpushed()
    assert result["repo-a2"].dirty is True
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mission.py -v`
Expected: FAIL — `test_repos_are_cloned` fails (still creates symlinks), `test_build_mounts_no_per_repo_mounts` fails (signature changed), `test_clone_paths` fails (method doesn't exist), `test_check_unpushed_*` fail (method doesn't exist)

- [ ] **Step 3: Update mission.py**

In `src/aifw/mission.py`, make these changes:

1. Add import at top:

```python
from aifw.git import clone_local, repo_status, RepoStatus
```

2. Replace the symlink block in `init_directory()` (lines 142-147):

Replace:
```python
        # Create repo symlinks
        for rp in repo_paths:
            p = Path(rp).resolve()
            link = self.repos_dir / p.name
            if not link.exists():
                link.symlink_to(p)
```

With:
```python
        # Clone repos locally
        self._clone_repos(repo_paths)
```

3. Add `_clone_repos` method after `_place_claude_md_files`:

```python
    def _clone_repos(self, repo_paths: list[str]) -> None:
        """Clone each repo into the mission's repos/ directory."""
        for rp in repo_paths:
            p = Path(rp).resolve()
            dest = self.repos_dir / p.name
            if dest.exists():
                continue
            clone_local(str(p), str(dest))
```

4. Update `_write_mission_toml` to record both original and clone paths:

Replace the entire `_write_mission_toml` method with:

```python
    def _write_mission_toml(self, repo_paths: list[str]) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        repos_toml = "\n".join(f'  "{rp}",' for rp in repo_paths)
        repos_table = "\n".join(
            f'{Path(rp).name} = "{rp}"' for rp in repo_paths
        )
        content = f"""\
# aifw mission metadata
# Generated: {ts}

mission_id = "{self.mission_id}"
created = "{ts}"
state = "active"
container = "{self.container_name}"
tmux_session = "{self.tmux_session}"

# Original repo paths (for reference / re-cloning)
repos = [
{repos_toml}
]

# Mapping: clone name -> original path
[repo_origins]
{repos_table}
"""
        self.mission_toml_path.write_text(content)
```

5. Replace `build_mounts` — remove the `repo_paths` parameter and per-repo mounts:

```python
    def build_mounts(self) -> list[DiskMount]:
        """Build the list of disk mounts for the container.

        Only the mission directory and Claude state are mounted.
        Repos are cloned under the mission dir, so they're included automatically.
        """
        mounts: list[DiskMount] = []

        # Mount the mission directory (contains cloned repos)
        mounts.append(DiskMount(
            name="mission",
            source=str(self.root),
            path=str(self.root),
        ))

        # Claude state mounts — mapped to /home/ubuntu/ in the container
        # so Claude Code (running as ubuntu) finds ~/.claude correctly.
        mounts.append(DiskMount(
            name="claude-config",
            source=str(self.config.claude_config_host_path),
            path=self.config.claude_config_container_path,
        ))
        if self.config.claude_auth_host_path.exists():
            mounts.append(DiskMount(
                name="claude-auth",
                source=str(self.config.claude_auth_host_path),
                path=self.config.claude_auth_container_path,
            ))

        return mounts
```

6. Update `provision_container` to not pass repo_paths:

```python
    def provision_container(self) -> None:
        """Create and start the mission container."""
        mounts = self.build_mounts()
        create_container(self.container_name, self.config, mounts)
        self.ensure_events().log(CONTAINER, "aifw", f"Container {self.container_name} provisioned")
```

7. Add `clone_paths` and `check_unpushed` methods after `repo_paths`:

```python
    def clone_paths(self) -> dict[str, str]:
        """Return {repo_name: clone_path} for all cloned repos."""
        if not self.repos_dir.exists():
            return {}
        return {
            p.name: str(p)
            for p in sorted(self.repos_dir.iterdir())
            if p.is_dir() and (p / ".git").exists()
        }

    def check_unpushed(self) -> dict[str, RepoStatus]:
        """Check all cloned repos for unpushed work."""
        result = {}
        for name, path in self.clone_paths().items():
            result[name] = repo_status(path)
        return result
```

8. Update the module docstring — change `repos/  # symlinks to actual repo paths` to `repos/  # local clones of source repos`.

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mission.py -v`
Expected: PASS (all tests)

- [ ] **Step 5: Commit**

```bash
git add src/aifw/mission.py tests/test_mission.py
git commit -m "feat(mission): replace repo symlinks with local git clones"
```

---

### Task 5: Update `cli.py` — destroy safety check and `--force`

**Files:**
- Modify: `src/aifw/cli.py:57-58,96-104,176-207`

- [ ] **Step 1: Add `--force` to the destroy subparser**

In `_build_parser()`, add to the destroy parser:

```python
    p_destroy.add_argument("-f", "--force", action="store_true", help="Destroy even with unpushed work")
```

- [ ] **Step 2: Update `cmd_destroy` with unpushed check**

Replace `cmd_destroy` with:

```python
def cmd_destroy(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    setup_stderr_logging(config.log_level)
    from aifw.mission import Mission, find_current_mission
    from aifw.tmux import kill_session

    if args.mission:
        mission = Mission(args.mission, config)
    else:
        mission = find_current_mission(config)

    if mission is None or not mission.exists():
        print("No active mission found.", file=sys.stderr)
        sys.exit(1)

    # Check for unpushed work unless --force
    if not args.force and not args.keep_files:
        statuses = mission.check_unpushed()
        has_issues = any(s.dirty or s.unpushed for s in statuses.values())
        if has_issues:
            print(f"Cannot destroy mission {mission.mission_id}: unpushed work found\n")
            for name, s in statuses.items():
                if s.dirty or s.unpushed:
                    print(f"  {name}:")
                    if s.unpushed:
                        print(f"    {len(s.unpushed)} unpushed branch(es): {', '.join(s.unpushed)}")
                    if s.dirty:
                        print(f"    Uncommitted changes")
                else:
                    print(f"  {name}: clean")
            print(f"\nUse --force to destroy anyway.")
            sys.exit(1)

    print(f"Destroying mission {mission.mission_id} ...")

    kill_session(config, mission.tmux_session)
    mission.destroy()

    if not args.keep_files:
        import shutil
        shutil.rmtree(mission.root, ignore_errors=True)
        print(f"Removed {mission.root}")
    else:
        print(f"Kept mission files at {mission.root}")

    print("Mission destroyed.")
```

- [ ] **Step 3: Update `cmd_start` — remove repo_paths from provision_container call**

In `cmd_start`, change:

```python
    mission.provision_container(repo_paths)
```

to:

```python
    mission.provision_container()
```

Also update `setup_control_plane` call — pass clone paths instead of original repo paths:

```python
    clone_paths = list(mission.clone_paths().values())
    setup_control_plane(
        config,
        mission.tmux_session,
        mission.container_name,
        str(mission.root),
        clone_paths,
    )
```

- [ ] **Step 4: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aifw/cli.py
git commit -m "feat(cli): add destroy safety check for unpushed work"
```

---

### Task 6: Update `status.py` — show per-repo git info

**Files:**
- Modify: `src/aifw/status.py:64-70`

- [ ] **Step 1: Update the Repos section in `show_status`**

Replace the repos display block (lines 64-70) with:

```python
    # Repos
    clones = mission.clone_paths()
    origins = mission.repo_paths()
    out.write(f"\n  Repositories ({len(origins)}):\n")
    if clones:
        from aifw.git import repo_status
        for name, clone_path in clones.items():
            try:
                rs = repo_status(clone_path)
                dirty_mark = " [dirty]" if rs.dirty else ""
                unpushed_mark = f" [{len(rs.unpushed)} unpushed]" if rs.unpushed else ""
                out.write(f"    {rs.branch:<12s} {name:<20s}{dirty_mark}{unpushed_mark}\n")
            except Exception:
                out.write(f"    ?            {name:<20s} (git error)\n")
    else:
        for rp in origins:
            name = Path(rp).name
            out.write(f"    -            {name:<20s} (not cloned)\n")
```

- [ ] **Step 2: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/aifw/status.py
git commit -m "feat(status): show per-repo git branch and dirty/unpushed info"
```

---

### Task 7: Update `tmux.py` — point git/integration windows to clone paths

**Files:**
- Modify: `src/aifw/tmux.py:247-260`

- [ ] **Step 1: Update git window to use first clone path**

In `setup_control_plane`, the git window currently uses `repo_paths[0]`. Since `repo_paths` now contains clone paths (passed from `cmd_start`), this already works correctly. Verify by reading the code — no change needed if `cmd_start` passes clone paths.

However, the integration window should also default to the repos dir. Change the integration window `cwd` from `mission_dir` to `mission_dir + "/repos"`:

Replace:
```python
    integration_shell = _lxc_exec_string(
        container_name, config.lxd_container_user,
        cwd=mission_dir,
        command="bash -l",
    )
```

With:
```python
    integration_shell = _lxc_exec_string(
        container_name, config.lxd_container_user,
        cwd=f"{mission_dir}/repos",
        command="bash -l",
    )
```

- [ ] **Step 2: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/aifw/tmux.py
git commit -m "feat(tmux): point integration window to repos directory"
```

---

### Task 8: Update `workers.py` — default repo_path to clone path

**Files:**
- Modify: `src/aifw/workers.py:153-156`

- [ ] **Step 1: Update the default repo_path in assign_worker**

In `assign_worker`, replace:

```python
    # Determine repo path
    if repo_path is None:
        repos = mission.repo_paths()
        repo_path = repos[0] if repos else str(mission.root)
```

With:

```python
    # Determine repo path — use clone path, not original
    if repo_path is None:
        clones = mission.clone_paths()
        if clones:
            repo_path = next(iter(clones.values()))
        else:
            repo_path = str(mission.root)
```

- [ ] **Step 2: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/aifw/workers.py
git commit -m "feat(workers): default repo_path to clone path"
```

---

### Task 9: Final integration test — full run

- [ ] **Step 1: Run the full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Verify CLI still works**

Run: `PYTHONPATH=src python -m aifw doctor`
Expected: Doctor output with no crashes

- [ ] **Step 3: Commit any remaining changes**

```bash
git add -A
git status
# Only commit if there are meaningful changes
```

# Spec B: Operations Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add `aifw sync`, `aifw kill/restart`, and `aifw log` commands for day-to-day mission operations.

**Architecture:** `push_branch` in git.py handles the push logic. All new CLI commands are thin wrappers over existing tmux/git/mission modules. `log` uses the existing `capture_pane`. `kill`/`restart` use existing tmux window management and status JSON.

**Tech Stack:** Python 3.12+, subprocess (git CLI), pytest, argparse

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/aifw/git.py` | Add `PushResult` dataclass and `push_branch` function |
| Modify | `src/aifw/cli.py` | Add `sync`, `kill`, `restart`, `log` subparsers and handlers |
| Modify | `tests/test_git.py` | Tests for `push_branch` |

---

### Task 1: Add `PushResult` and `push_branch` to git.py

**Files:**
- Modify: `src/aifw/git.py`
- Modify: `tests/test_git.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_git.py`:

```python
from aifw.git import push_branch, PushResult


def test_push_branch_up_to_date(tmp_path: Path) -> None:
    """Clone without local changes — push should be up to date."""
    origin = _init_repo(tmp_path / "origin-push1")
    dest = tmp_path / "clone-push1"
    clone_local(str(origin), str(dest))

    result = push_branch(str(dest), "main")
    assert isinstance(result, PushResult)
    assert result.up_to_date is True
    assert result.pushed == 0
    assert result.error is None


def test_push_branch_with_commits(tmp_path: Path) -> None:
    """Clone, commit locally, push — should report pushed commits."""
    origin = _init_repo(tmp_path / "origin-push2")
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
    """Dry run should not actually push."""
    origin = _init_repo(tmp_path / "origin-push3")
    dest = tmp_path / "clone-push3"
    clone_local(str(origin), str(dest))

    (dest / "dry.txt").write_text("dry")
    subprocess.run(["git", "-C", str(dest), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "commit", "-m", "dry"], check=True, capture_output=True)

    branch = current_branch(str(dest))
    result = push_branch(str(dest), branch, dry_run=True)
    assert result.error is None

    # Verify nothing was actually pushed — origin should still have 1 commit
    origin_log = subprocess.run(
        ["git", "-C", str(origin), "log", "--oneline"],
        capture_output=True, text=True, check=True,
    )
    assert len(origin_log.stdout.strip().splitlines()) == 1


def test_push_branch_new_branch(tmp_path: Path) -> None:
    """Push a branch that doesn't exist on origin yet."""
    origin = _init_repo(tmp_path / "origin-push4")
    dest = tmp_path / "clone-push4"
    clone_local(str(origin), str(dest), branch="mission/test-push")

    (dest / "feat.txt").write_text("feat")
    subprocess.run(["git", "-C", str(dest), "add", "."], check=True, capture_output=True)
    subprocess.run(["git", "-C", str(dest), "commit", "-m", "feat"], check=True, capture_output=True)

    result = push_branch(str(dest), "mission/test-push")
    assert result.error is None
    assert result.pushed >= 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_git.py::test_push_branch_up_to_date -v`
Expected: FAIL — `ImportError: cannot import name 'push_branch'`

- [ ] **Step 3: Implement PushResult and push_branch**

Add to `src/aifw/git.py` after the `RepoStatus` dataclass:

```python
@dataclass
class PushResult:
    """Result of a git push operation."""

    pushed: int
    up_to_date: bool
    error: str | None = None
```

Add at the bottom of the file:

```python
def push_branch(repo_path: str, branch: str, *, dry_run: bool = False) -> PushResult:
    """Push a branch to origin.

    Returns a PushResult with the outcome.
    """
    args = ["push", "origin", branch]
    if dry_run:
        args.insert(1, "--dry-run")

    # Count commits to push before pushing
    remote_ref = f"origin/{branch}"
    check_remote = _run_git(["rev-parse", "--verify", remote_ref], cwd=repo_path, check=False)

    if check_remote.returncode == 0:
        # Remote branch exists — count ahead commits
        count_result = _run_git(
            ["rev-list", "--count", f"{remote_ref}..{branch}"],
            cwd=repo_path,
        )
        ahead = int(count_result.stdout.strip())
        if ahead == 0:
            return PushResult(pushed=0, up_to_date=True)
    else:
        # New branch — count all commits on it
        count_result = _run_git(["rev-list", "--count", branch], cwd=repo_path)
        ahead = int(count_result.stdout.strip())

    try:
        _run_git(args, cwd=repo_path)
        return PushResult(pushed=ahead, up_to_date=False)
    except GitError as exc:
        return PushResult(pushed=0, up_to_date=False, error=str(exc))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_git.py -v`
Expected: PASS (all 15 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aifw/git.py tests/test_git.py
git commit -m "feat(git): add PushResult and push_branch for aifw sync"
```

---

### Task 2: Add `sync`, `kill`, `restart`, `log` subcommands to CLI

**Files:**
- Modify: `src/aifw/cli.py`

- [ ] **Step 1: Add subparsers**

In `_build_parser`, after the `list` parser and before `return parser`, add:

```python
    # sync
    p_sync = sub.add_parser("sync", help="Push mission branches to origin repos")
    p_sync.add_argument("--dry-run", action="store_true", help="Show what would be pushed without pushing")

    # kill
    p_kill = sub.add_parser("kill", help="Kill a worker's tmux window")
    p_kill.add_argument("worker", help="Worker name")

    # restart
    p_restart = sub.add_parser("restart", help="Kill and re-launch a worker from its existing brief")
    p_restart.add_argument("worker", help="Worker name")

    # log
    p_log = sub.add_parser("log", help="Show a worker's Claude Code conversation")
    p_log.add_argument("worker", help="Worker name (or 'orchestrator')")
    p_log.add_argument("--lines", "-n", type=int, default=50, help="Number of lines to show (default: 50)")
    p_log.add_argument("-f", "--follow", action="store_true", help="Follow mode (like tail -f)")
```

- [ ] **Step 2: Add cmd_sync**

Add after `cmd_list`:

```python
def cmd_sync(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    setup_stderr_logging(config.log_level)
    from aifw.mission import Mission, find_current_mission
    from aifw.git import push_branch, current_branch

    if args.mission:
        mission = Mission(args.mission, config)
    else:
        mission = find_current_mission(config)

    if mission is None or not mission.exists():
        print("No active mission found.", file=sys.stderr)
        sys.exit(1)

    clones = mission.clone_paths()
    if not clones:
        print("No cloned repos to sync.")
        return

    action = "Dry-run sync" if args.dry_run else "Syncing"
    print(f"{action} mission {mission.mission_id} ...\n")

    synced = 0
    failed = 0
    for name, clone_path in clones.items():
        branch = current_branch(clone_path)
        result = push_branch(clone_path, branch, dry_run=args.dry_run)
        if result.error:
            print(f"  {name}:  FAILED — {result.error}")
            failed += 1
        elif result.up_to_date:
            print(f"  {name}:  already up to date")
            synced += 1
        else:
            print(f"  {name}:  pushed {result.pushed} commit(s) to {branch}")
            synced += 1

    print(f"\n{synced} synced, {failed} failed.")
```

- [ ] **Step 3: Add cmd_kill**

```python
def cmd_kill(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    setup_stderr_logging(config.log_level)
    from aifw.mission import Mission, find_current_mission
    from aifw.tmux import kill_window

    if args.mission:
        mission = Mission(args.mission, config)
    else:
        mission = find_current_mission(config)

    if mission is None or not mission.exists():
        print("No active mission found.", file=sys.stderr)
        sys.exit(1)

    worker_name = args.worker
    window_name = f"w-{worker_name}"

    # Kill the tmux window
    kill_window(config, mission.tmux_session, window_name)

    # Update status
    import json
    from datetime import datetime, timezone
    status_path = mission.ai_dir / "status" / f"{worker_name}.json"
    if status_path.exists():
        data = json.loads(status_path.read_text())
        data["status"] = "error"
        data["summary"] = "Killed by operator"
        data["updated"] = datetime.now(timezone.utc).isoformat()
        status_path.write_text(json.dumps(data, indent=2) + "\n")

    # Log event
    mission.ensure_events().log("worker", "aifw", f"Killed worker: {worker_name}")
    print(f"Killed worker '{worker_name}'")
```

- [ ] **Step 4: Add cmd_restart**

```python
def cmd_restart(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    setup_stderr_logging(config.log_level)
    from aifw.mission import Mission, find_current_mission
    from aifw.tmux import kill_window
    from aifw.claude import launch_worker_session, build_worker_prompt

    if args.mission:
        mission = Mission(args.mission, config)
    else:
        mission = find_current_mission(config)

    if mission is None or not mission.exists():
        print("No active mission found.", file=sys.stderr)
        sys.exit(1)

    worker_name = args.worker
    window_name = f"w-{worker_name}"
    brief_path = mission.ai_dir / "workers" / f"{worker_name}.md"
    status_path = mission.ai_dir / "status" / f"{worker_name}.json"

    if not brief_path.exists():
        print(f"Error: no brief found for worker '{worker_name}'", file=sys.stderr)
        sys.exit(1)

    # Read model and repo from status
    import json
    from datetime import datetime, timezone
    model = ""
    repo = str(mission.root)
    if status_path.exists():
        data = json.loads(status_path.read_text())
        model = data.get("model", "")
        repo = data.get("repo", str(mission.root))

    # Kill existing window
    kill_window(config, mission.tmux_session, window_name)

    # Update status
    status_data = {
        "worker": worker_name,
        "status": "ready",
        "updated": datetime.now(timezone.utc).isoformat(),
        "summary": "Restarted by operator",
        "blockers": [],
        "repo": repo,
        "model": model,
    }
    status_path.write_text(json.dumps(status_data, indent=2) + "\n")

    # Re-launch
    prompt = build_worker_prompt(str(brief_path))
    launch_worker_session(
        config,
        mission.tmux_session,
        mission.container_name,
        worker_name,
        working_dir=repo,
        initial_prompt=prompt,
        model=model,
    )

    mission.ensure_events().log("worker", "aifw", f"Restarted worker: {worker_name}")
    print(f"Restarted worker '{worker_name}' (model={model or 'default'})")
```

- [ ] **Step 5: Add cmd_log**

```python
def cmd_log(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    from aifw.mission import Mission, find_current_mission
    from aifw.tmux import capture_pane

    if args.mission:
        mission = Mission(args.mission, config)
    else:
        mission = find_current_mission(config)

    if mission is None or not mission.exists():
        print("No active mission found.", file=sys.stderr)
        sys.exit(1)

    worker_name = args.worker
    # Special case: "orchestrator" targets the orchestrator window directly
    window_name = "orchestrator" if worker_name == "orchestrator" else f"w-{worker_name}"

    if not args.follow:
        # Snapshot mode
        output = capture_pane(config, mission.tmux_session, window_name, lines=args.lines)
        if output:
            print(output, end="")
        else:
            print(f"No output from '{worker_name}' (window may not exist)")
        return

    # Follow mode
    import time
    previous = ""
    try:
        while True:
            current = capture_pane(config, mission.tmux_session, window_name, lines=args.lines)
            if current != previous:
                # Find new lines by comparing
                prev_lines = previous.splitlines()
                curr_lines = current.splitlines()
                if previous and curr_lines:
                    # Find where new content starts
                    # Simple approach: print lines not in previous
                    new_count = len(curr_lines) - len(prev_lines)
                    if new_count > 0:
                        for line in curr_lines[-new_count:]:
                            print(line)
                    elif current != previous:
                        # Content changed but same line count — reprint all
                        print(current, end="")
                else:
                    print(current, end="")
                previous = current
            time.sleep(1)
    except KeyboardInterrupt:
        pass
```

- [ ] **Step 6: Register new commands**

Update the `_COMMANDS` dict:

```python
_COMMANDS = {
    "start": cmd_start,
    "status": cmd_status,
    "attach": cmd_attach,
    "stop": cmd_stop,
    "destroy": cmd_destroy,
    "assign": cmd_assign,
    "tail": cmd_tail,
    "doctor": cmd_doctor,
    "list": cmd_list,
    "sync": cmd_sync,
    "kill": cmd_kill,
    "restart": cmd_restart,
    "log": cmd_log,
}
```

- [ ] **Step 7: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 8: Verify CLI help**

Run: `PYTHONPATH=src python -m aifw sync --help`
Expected: Shows `--dry-run`

Run: `PYTHONPATH=src python -m aifw kill --help`
Expected: Shows `worker` argument

Run: `PYTHONPATH=src python -m aifw restart --help`
Expected: Shows `worker` argument

Run: `PYTHONPATH=src python -m aifw log --help`
Expected: Shows `--lines`, `-f/--follow`

- [ ] **Step 9: Commit**

```bash
git add src/aifw/cli.py
git commit -m "feat(cli): add sync, kill, restart, log commands"
```

---

### Task 3: Final integration verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Verify CLI**

Run: `PYTHONPATH=src python -m aifw --help`
Expected: Shows all commands including sync, kill, restart, log

Run: `PYTHONPATH=src python -m aifw doctor`
Expected: All checks pass

- [ ] **Step 3: Commit any remaining changes**

```bash
git status
# Only commit if there are meaningful changes
```

# Spec A: Core Workflow Improvements Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add model selection per worker/orchestrator, initial mission objective, auto-branch on clone, and mission resume.

**Architecture:** Model flows through status JSON → dispatch watcher → `claude --model` arg. Auto-branch adds a `checkout -b` after clone. Initial objective writes to spec.md and sends a prompt to the orchestrator. Resume makes repos optional and handles existing tmux sessions.

**Tech Stack:** Python 3.12+, subprocess (git CLI), pytest, argparse

---

## File Structure

| Action | File | Responsibility |
|--------|------|---------------|
| Modify | `src/aifw/config.py` | Add `default_model` setting |
| Modify | `src/aifw/git.py` | Add `branch` param to `clone_local` |
| Modify | `src/aifw/mission.py` | Pass branch to clone, accept `spec_content` in `init_directory` |
| Modify | `src/aifw/tmux.py` | Pass model to worker/orchestrator, handle resume in `setup_control_plane`, send initial prompt |
| Modify | `src/aifw/dispatch.py` | Read model from status JSON, pass to `create_worker_window` |
| Modify | `src/aifw/workers.py` | Accept and store `model` param in `assign_worker` |
| Modify | `src/aifw/claude.py` | Pass model through `launch_worker_session` |
| Modify | `src/aifw/cli.py` | Add `--model`, `--orchestrator-model`, `--spec`, `--objective` flags, make repos optional with `--id` |
| Modify | `src/aifw/status.py` | Show model in worker status display |
| Modify | `templates/orchestrator-CLAUDE.md` | Document model field in status JSON |
| Modify | `tests/test_config.py` | Test default_model |
| Modify | `tests/test_git.py` | Test clone_local with branch param |
| Modify | `tests/test_mission.py` | Test auto-branch, spec_content |
| Modify | `tests/test_workers.py` | Test model param in assign_worker |

---

### Task 1: Add `default_model` to config

**Files:**
- Modify: `src/aifw/config.py`
- Modify: `tests/test_config.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_config.py`:

```python
def test_default_model_empty_by_default(tmp_path: Path) -> None:
    config = load_config(tmp_path / "nonexistent.toml")
    assert config.default_model == ""


def test_default_model_from_file(tmp_path: Path) -> None:
    config_file = tmp_path / "config.toml"
    config_file.write_text('default_model = "sonnet"')
    config = load_config(config_file)
    assert config.default_model == "sonnet"
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_config.py::test_default_model_empty_by_default -v`
Expected: FAIL — `AttributeError: 'Config' object has no attribute 'default_model'`

- [ ] **Step 3: Implement**

In `src/aifw/config.py`:

1. Add to `_DEFAULTS` dict after the `claude_auth_container_path` line:
```python
    "default_model": "",
```

2. Add to `Config` dataclass after `claude_auth_container_path`:
```python
    default_model: str
```

3. Add to the `return Config(...)` call in `load_config` after `claude_auth_container_path`:
```python
        default_model=str(resolved["default_model"]),
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_config.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aifw/config.py tests/test_config.py
git commit -m "feat(config): add default_model setting"
```

---

### Task 2: Add `branch` param to `clone_local` in git.py

**Files:**
- Modify: `src/aifw/git.py`
- Modify: `tests/test_git.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_git.py`:

```python
def test_clone_local_with_branch(tmp_path: Path) -> None:
    origin = _init_repo(tmp_path / "origin6")
    dest = tmp_path / "clone6"

    clone_local(str(origin), str(dest), branch="mission/test-001")

    assert dest.exists()
    # Should be on the mission branch
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
    # Should be on main or master (default)
    assert result.stdout.strip() in ("main", "master")
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_git.py::test_clone_local_with_branch -v`
Expected: FAIL — `TypeError: clone_local() got an unexpected keyword argument 'branch'`

- [ ] **Step 3: Implement**

In `src/aifw/git.py`, replace `clone_local`:

```python
def clone_local(source: str, dest: str, *, branch: str | None = None) -> None:
    """Clone a repo using --local for hardlinked objects.

    If branch is provided, create and checkout that branch after cloning.
    """
    _run_git(["clone", "--local", source, dest])
    if branch:
        _run_git(["checkout", "-b", branch], cwd=dest)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_git.py -v`
Expected: PASS (all 11 tests)

- [ ] **Step 5: Commit**

```bash
git add src/aifw/git.py tests/test_git.py
git commit -m "feat(git): add branch param to clone_local for auto-branch"
```

---

### Task 3: Auto-branch in mission.py + spec_content param

**Files:**
- Modify: `src/aifw/mission.py`
- Modify: `tests/test_mission.py`

- [ ] **Step 1: Write failing tests**

Append to `tests/test_mission.py`:

```python
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
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_mission.py::test_clones_on_mission_branch -v`
Expected: FAIL — clone is on main/master, not mission branch

- [ ] **Step 3: Implement**

In `src/aifw/mission.py`:

1. Update `init_directory` signature and pass `spec_content` through:

```python
    def init_directory(self, repo_paths: list[str], *, spec_content: str | None = None) -> None:
```

2. Update the `_init_ai_files` call to pass spec_content:

Replace:
```python
        self._init_ai_files(repo_paths)
```
With:
```python
        self._init_ai_files(repo_paths, spec_content=spec_content)
```

3. Update `_init_ai_files` to accept and use spec_content:

```python
    def _init_ai_files(self, repo_paths: list[str], *, spec_content: str | None = None) -> None:
        repo_names = [Path(rp).name for rp in repo_paths]

        # spec.md
        if spec_content:
            (self.ai_dir / "spec.md").write_text(spec_content)
        else:
            (self.ai_dir / "spec.md").write_text(f"""\
# Mission Specification

**Mission ID**: {self.mission_id}
**Created**: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
**Repositories**: {', '.join(repo_names)}

## Objective

_Define the mission objective here._

## Scope

_Define what is in and out of scope._

## Success Criteria

_Define how to know when the mission is complete._
""")
```

(Keep the rest of `_init_ai_files` unchanged — architecture.md and task-board.yaml.)

4. Update `_clone_repos` to pass mission branch:

```python
    def _clone_repos(self, repo_paths: list[str]) -> None:
        """Clone each repo into the mission's repos/ directory."""
        branch = f"mission/{self.mission_id}"
        for rp in repo_paths:
            p = Path(rp).resolve()
            dest = self.repos_dir / p.name
            if dest.exists():
                continue
            clone_local(str(p), str(dest), branch=branch)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `uv run pytest tests/test_mission.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aifw/mission.py tests/test_mission.py
git commit -m "feat(mission): auto-branch on clone, accept spec_content"
```

---

### Task 4: Model selection in tmux.py, claude.py, workers.py, dispatch.py

**Files:**
- Modify: `src/aifw/tmux.py`
- Modify: `src/aifw/claude.py`
- Modify: `src/aifw/workers.py`
- Modify: `src/aifw/dispatch.py`
- Modify: `tests/test_workers.py`

- [ ] **Step 1: Write failing test**

Append to `tests/test_workers.py`:

```python
@mock.patch("aifw.workers.launch_worker_session")
def test_assign_worker_with_model(mock_launch, tmp_path: Path) -> None:
    config, mission = _make_mission(tmp_path)
    repo_a = str(tmp_path / "repo-a")

    assign_worker(config, mission, "epsilon", "A task", repo_a, model="sonnet")

    status = json.loads((mission.ai_dir / "status" / "epsilon.json").read_text())
    assert status["model"] == "sonnet"

    # Model should be passed to launch_worker_session
    mock_launch.assert_called_once()
    call_kwargs = mock_launch.call_args
    assert call_kwargs.kwargs.get("model") == "sonnet" or call_kwargs[1].get("model") == "sonnet"


@mock.patch("aifw.workers.launch_worker_session")
def test_assign_worker_without_model(mock_launch, tmp_path: Path) -> None:
    config, mission = _make_mission(tmp_path)
    repo_a = str(tmp_path / "repo-a")

    assign_worker(config, mission, "zeta", "A task", repo_a)

    status = json.loads((mission.ai_dir / "status" / "zeta.json").read_text())
    assert status.get("model") is None or status.get("model") == ""
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `uv run pytest tests/test_workers.py::test_assign_worker_with_model -v`
Expected: FAIL — `assign_worker() got an unexpected keyword argument 'model'`

- [ ] **Step 3: Implement model threading through the stack**

**3a. Update `workers.py` — accept model param:**

Change `assign_worker` signature:

```python
def assign_worker(
    config: Config,
    mission: Mission,
    worker_name: str,
    task: str,
    repo_path: str | None = None,
    *,
    model: str = "",
) -> None:
```

Add `"model": model` to the `status_data` dict:

```python
    status_data = {
        "worker": worker_name,
        "status": "ready",
        "updated": datetime.now(timezone.utc).isoformat(),
        "summary": "Assignment received, ready to start",
        "blockers": [],
        "repo": repo_path,
        "model": model,
    }
```

Pass model to `launch_worker_session`:

```python
        launch_worker_session(
            config,
            mission.tmux_session,
            mission.container_name,
            worker_name,
            working_dir=repo_path,
            initial_prompt=prompt,
            model=model,
        )
```

**3b. Update `claude.py` — pass model through:**

Change `launch_worker_session` signature:

```python
def launch_worker_session(
    config: Config,
    session_name: str,
    container_name: str,
    worker_name: str,
    working_dir: str,
    initial_prompt: str | None = None,
    *,
    model: str = "",
) -> None:
```

Build claude_args from model:

```python
    claude_args = ""
    if model:
        claude_args = f"--model {model}"
    elif config.default_model:
        claude_args = f"--model {config.default_model}"
    create_worker_window(
        config, session_name, container_name, worker_name,
        cwd=working_dir,
        claude_args=claude_args,
    )
```

**3c. Update `dispatch.py` — read model from status JSON:**

Add a helper function after `_read_worker_repo`:

```python
def _read_worker_model(ai_dir: Path, worker_name: str) -> str:
    """Try to extract the model from the worker's status file."""
    status_file = ai_dir / "status" / f"{worker_name}.json"
    if status_file.exists():
        try:
            data = json.loads(status_file.read_text())
            return data.get("model", "")
        except (json.JSONDecodeError, KeyError):
            pass
    return ""
```

In `run_dispatch_loop`, where workers are spawned (both new and re-spawned), read the model and pass it as `claude_args`:

For the "New brief" spawn block (around line 110), replace:

```python
                        create_worker_window(
                            config, tmux_session, container_name, worker_name,
                            cwd=cwd,
                        )
```

With:

```python
                        model = _read_worker_model(ai_dir, worker_name)
                        claude_args = f"--model {model}" if model else ""
                        if not claude_args and config.default_model:
                            claude_args = f"--model {config.default_model}"
                        create_worker_window(
                            config, tmux_session, container_name, worker_name,
                            cwd=cwd,
                            claude_args=claude_args,
                        )
```

For the "re-spawn" block (around line 144), make the same change:

```python
                        model = _read_worker_model(ai_dir, worker_name)
                        claude_args = f"--model {model}" if model else ""
                        if not claude_args and config.default_model:
                            claude_args = f"--model {config.default_model}"
                        create_worker_window(
                            config, tmux_session, container_name, worker_name,
                            cwd=cwd,
                            claude_args=claude_args,
                        )
```

**3d. Update `tmux.py` — `setup_control_plane` accepts orchestrator_model:**

Change signature:

```python
def setup_control_plane(
    config: Config,
    session_name: str,
    container_name: str,
    mission_dir: str,
    repo_paths: list[str],
    *,
    orchestrator_model: str = "",
    initial_prompt: str | None = None,
) -> None:
```

Update orchestrator claude command to include model:

```python
    # Orchestrator window: Claude Code in the container at mission .ai dir
    create_window(config, session_name, "orchestrator", start_dir=mission_dir)
    orch_claude_cmd = config.claude_bin
    orch_model = orchestrator_model or config.default_model
    if orch_model:
        orch_claude_cmd = f"{orch_claude_cmd} --model {orch_model}"
    orchestrator_cmd = _lxc_exec_string(
        container_name, config.lxd_container_user,
        cwd=f"{mission_dir}/.ai",
        command=orch_claude_cmd,
    )
    send_command(config, session_name, "orchestrator", orchestrator_cmd)

    # Send initial prompt to orchestrator if provided
    if initial_prompt:
        import time
        time.sleep(3)
        send_keys(config, session_name, "orchestrator", initial_prompt, enter=True)
```

- [ ] **Step 4: Run all tests to verify they pass**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add src/aifw/workers.py src/aifw/claude.py src/aifw/dispatch.py src/aifw/tmux.py tests/test_workers.py
git commit -m "feat: thread model selection through worker/orchestrator stack"
```

---

### Task 5: Update CLI — all new flags

**Files:**
- Modify: `src/aifw/cli.py`

- [ ] **Step 1: Update start subparser**

Replace the start parser section in `_build_parser`:

```python
    # start
    p_start = sub.add_parser("start", help="Create a mission and launch the control plane")
    p_start.add_argument("repos", nargs="*", default=[], help="Paths to repositories")
    p_start.add_argument("--id", dest="mission_id", default=None, help="Custom mission ID (or resume existing)")
    p_start.add_argument("--no-attach", action="store_true", help="Don't attach to tmux after start")
    p_start.add_argument("--orchestrator-model", default="", help="Model for the orchestrator session")
    p_start.add_argument("--spec", dest="spec_file", default=None, help="Path to mission spec file")
    p_start.add_argument("--objective", default=None, help="Inline mission objective text")
```

- [ ] **Step 2: Update assign subparser**

Add `--model` to the assign parser:

```python
    p_assign.add_argument("--model", default="", help="Claude model for this worker (e.g. sonnet, opus)")
```

- [ ] **Step 3: Rewrite `cmd_start` for resume and objective support**

Replace `cmd_start` entirely:

```python
def cmd_start(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    setup_stderr_logging(config.log_level)

    from aifw.mission import Mission, generate_mission_id
    from aifw.tmux import session_exists

    # Validate --spec and --objective are mutually exclusive
    if args.spec_file and args.objective:
        print("Error: --spec and --objective are mutually exclusive.", file=sys.stderr)
        sys.exit(1)

    # Resolve spec content
    spec_content: str | None = None
    if args.spec_file:
        spec_path = Path(args.spec_file)
        if not spec_path.is_file():
            print(f"Error: spec file does not exist: {spec_path}", file=sys.stderr)
            sys.exit(1)
        spec_content = spec_path.read_text()
    elif args.objective:
        spec_content = f"# Mission Objective\n\n{args.objective}\n"

    mission_id = args.mission_id or generate_mission_id()
    mission = Mission(mission_id, config)

    if mission.exists():
        # Resume mode
        if args.repos:
            print(f"Warning: repos ignored when resuming mission {mission_id}", file=sys.stderr)
        print(f"Resuming mission {mission_id} ...")
    else:
        # New mission — repos required
        if not args.repos:
            print("Error: repos are required for a new mission (or use --id to resume).", file=sys.stderr)
            sys.exit(1)
        repo_paths = [str(Path(r).resolve()) for r in args.repos]
        for rp in repo_paths:
            if not Path(rp).is_dir():
                print(f"Error: repository path does not exist: {rp}", file=sys.stderr)
                sys.exit(1)
        print(f"Creating mission {mission_id} ...")
        mission.init_directory(repo_paths, spec_content=spec_content)

    # Provision container (idempotent)
    print(f"Provisioning container {mission.container_name} ...")
    mission.provision_container()

    # Set up tmux control plane (skip if session exists — just attach)
    from aifw.tmux import setup_control_plane, attach_session
    if session_exists(config, mission.tmux_session):
        print(f"tmux session {mission.tmux_session} exists, attaching ...")
        if not args.no_attach:
            attach_session(config, mission.tmux_session)
        return

    print(f"Setting up tmux session {mission.tmux_session} ...")
    clone_paths = list(mission.clone_paths().values())

    initial_prompt: str | None = None
    if spec_content:
        initial_prompt = "Read the mission spec at .ai/spec.md and begin planning."

    setup_control_plane(
        config,
        mission.tmux_session,
        mission.container_name,
        str(mission.root),
        clone_paths,
        orchestrator_model=args.orchestrator_model,
        initial_prompt=initial_prompt,
    )

    print(f"\nMission {mission_id} is ready.")
    print(f"  Directory:  {mission.root}")
    print(f"  Container:  {mission.container_name}")
    print(f"  tmux:       {mission.tmux_session}")

    if not args.no_attach:
        print(f"\nAttaching to tmux session ...")
        attach_session(config, mission.tmux_session)
```

- [ ] **Step 4: Update `cmd_assign` to pass model**

Replace the `assign_worker` call:

```python
    assign_worker(config, mission, args.worker, args.task, args.repo, model=args.model)
```

- [ ] **Step 5: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 6: Verify CLI help**

Run: `PYTHONPATH=src python -m aifw start --help`
Expected: Shows `--spec`, `--objective`, `--orchestrator-model`, repos as optional

Run: `PYTHONPATH=src python -m aifw assign --help`
Expected: Shows `--model`

- [ ] **Step 7: Commit**

```bash
git add src/aifw/cli.py
git commit -m "feat(cli): add --model, --orchestrator-model, --spec, --objective, resume support"
```

---

### Task 6: Show model in status display

**Files:**
- Modify: `src/aifw/status.py`

- [ ] **Step 1: Update worker display in `show_status`**

In the workers display loop, add model info. Replace:

```python
            out.write(f"    {icon} {name:<16s} [{status:<12s}] {repo:<20s} {summary}\n")
```

With:

```python
            model = w.get("model", "")
            model_str = f"({model}) " if model else ""
            out.write(f"    {icon} {name:<16s} [{status:<12s}] {model_str}{repo:<20s} {summary}\n")
```

- [ ] **Step 2: Run all tests**

Run: `uv run pytest tests/ -v`
Expected: PASS

- [ ] **Step 3: Commit**

```bash
git add src/aifw/status.py
git commit -m "feat(status): show model in worker status display"
```

---

### Task 7: Update orchestrator CLAUDE.md template

**Files:**
- Modify: `templates/orchestrator-CLAUDE.md`

- [ ] **Step 1: Add model field documentation**

In the orchestrator template, find the "Step 2: Write the initial status" section. Update the example JSON to include the `model` field:

Replace:
```json
{
  "worker": "<worker-name>",
  "status": "ready",
  "updated": "<ISO timestamp>",
  "summary": "Assignment received, ready to start",
  "blockers": [],
  "repo": "<absolute repo path>"
}
```

With:
```json
{
  "worker": "<worker-name>",
  "status": "ready",
  "updated": "<ISO timestamp>",
  "summary": "Assignment received, ready to start",
  "blockers": [],
  "repo": "<absolute repo path>",
  "model": "sonnet"
}
```

Also add a note after "That's it. The dispatch watcher handles the rest.":

```markdown

### Model selection

The `model` field in the status JSON controls which Claude model the worker uses. Valid values: `sonnet`, `opus`, `haiku`, or empty string for the default. The dispatch watcher reads this field when spawning the worker session and passes it as `--model` to Claude Code.

Use cheaper models (sonnet, haiku) for mechanical tasks. Use opus for complex architecture or debugging work.
```

- [ ] **Step 2: Commit**

```bash
git add templates/orchestrator-CLAUDE.md
git commit -m "docs: document model field in orchestrator CLAUDE.md"
```

---

### Task 8: Final integration verification

- [ ] **Step 1: Run full test suite**

Run: `uv run pytest tests/ -v`
Expected: ALL PASS

- [ ] **Step 2: Verify CLI works end-to-end**

Run: `PYTHONPATH=src python -m aifw doctor`
Expected: Doctor output, no crashes

Run: `PYTHONPATH=src python -m aifw start --help`
Expected: Shows all new flags

Run: `PYTHONPATH=src python -m aifw assign --help`
Expected: Shows `--model` flag

- [ ] **Step 3: Commit any remaining changes**

```bash
git status
# Only commit if there are meaningful changes
```

# Spec A: Core Workflow Improvements

## 1. Model per worker

Workers and the orchestrator use different Claude models based on task complexity.

### Three paths for model selection

**Path 1 — Human assigns via CLI:**
`aifw assign --model sonnet worker-1 "task"` writes `"model": "sonnet"` into the worker's status JSON. `launch_worker_session` passes `--model sonnet` to the `claude` command.

**Path 2 — Orchestrator dispatches via brief:**
Orchestrator writes `.ai/status/worker-1.json` with `"model": "sonnet"`. The dispatch watcher reads the `model` field when spawning the worker window and passes `--model sonnet` to `claude`.

**Path 3 — Orchestrator session itself:**
`aifw start --orchestrator-model haiku ...` passes `--model haiku` to the orchestrator's `claude` command in `setup_control_plane`.

### Defaults

No `--model` flag means Claude Code uses its own default. A `default_model` key in `config.toml` can override this globally for all sessions.

### Model values

Passed through verbatim to `claude --model <value>`. No validation on our side — Claude Code handles unknown models.

### Module changes

| Module | Change |
|--------|--------|
| `config.py` | Add `default_model` setting (default: empty string = no override) |
| `cli.py` | Add `--model` to `assign`, `--orchestrator-model` to `start` |
| `tmux.py` | `create_worker_window` passes `--model` to claude command. `setup_control_plane` accepts `orchestrator_model` param. |
| `dispatch.py` | Read `model` from status JSON, pass to `create_worker_window` |
| `workers.py` | `assign_worker` accepts `model` param, writes to status JSON |
| `status.py` | Show model in worker status display |
| Templates | Update orchestrator CLAUDE.md to document the `model` field in status JSON |

## 2. Initial mission objective

Provide the orchestrator with a mission objective at start time.

### CLI

- `aifw start --spec ./objective.md repo1 repo2` — reads file content
- `aifw start --objective "Build auth system" repo1 repo2` — inline string
- Mutually exclusive. If both given, error and exit.
- If neither given, behaviour is unchanged (blank session, placeholder spec.md).

### What happens

1. The content replaces the placeholder template in `.ai/spec.md`.
2. After the orchestrator Claude Code session starts, it receives the prompt: `Read the mission spec at .ai/spec.md and begin planning.`
3. The prompt is sent via the existing `send_keys` mechanism — short delay after launch, then send.

### Module changes

| Module | Change |
|--------|--------|
| `cli.py` | Add `--spec` and `--objective` to `start`, mutually exclusive |
| `mission.py` | `init_directory` accepts optional `spec_content` param, writes to `.ai/spec.md` |
| `tmux.py` | `setup_control_plane` accepts optional `initial_prompt` param, sends to orchestrator window after launch |

## 3. Auto-branch on clone

Each clone creates and checks out a mission-specific branch instead of working on the default branch.

### Branch name

`mission/<mission-id>` (e.g., `mission/20260329-a1b2`)

### Behaviour

After `git clone --local`, immediately:
```
git -C <clone> checkout -b mission/<mission-id>
```

The original repo's default branch is untouched. All worker commits land on the mission branch. Merging back is the user's responsibility.

### Module changes

| Module | Change |
|--------|--------|
| `git.py` | `clone_local` gains optional `branch: str \| None` param. After clone, runs `git checkout -b <branch>` if provided. |
| `mission.py` | `_clone_repos` passes `branch=f"mission/{self.mission_id}"` to `clone_local` |

## 4. Resume

`aifw start --id <existing-id>` with an existing mission rebuilds tmux and restarts the container without re-cloning.

### Behaviour

1. **Repos**: Skip `init_directory()` — clones already exist.
2. **Container**: Call `provision_container()` — idempotent (starts if stopped, no-ops if running).
3. **tmux**: If session exists, attach directly. If session is gone, rebuild the full layout (overview, dispatch, orchestrator, git, integration). Workers are NOT auto-restarted — the user re-dispatches from the orchestrator or re-assigns.
4. **repos arg**: Optional when `--id` is provided. If given with `--id`, warn and ignore.

### Module changes

| Module | Change |
|--------|--------|
| `cli.py` | `repos` becomes `nargs="*"` (optional) when `--id` is set. Validate: error if no `--id` and no repos. Warn if both. |
| `tmux.py` | `setup_control_plane` checks `session_exists()` first. If true, skip creation and return (caller handles attach). |

## What does not change

- LXD container lifecycle
- Worker brief format and coordination model (except adding `model` field)
- Event logging structure
- Dispatch watcher polling mechanism
- File-based coordination in `.ai/`

# aifw — Terminal-first AI Orchestration Workflow

`aifw` is a thin operator layer around tmux, LXD, and Claude Code for coordinating multi-repository AI-assisted engineering work.

## Quick Start

```bash
# Install
cd aifw && pip install -e .

# Check your environment
aifw doctor

# Start a mission spanning multiple repos
aifw start ~/repos/api-server ~/repos/frontend ~/repos/shared-lib

# Assign work to workers
aifw assign api-worker "Implement the new authentication endpoint"
aifw assign ui-worker "Build the login page component" --repo ~/repos/frontend

# Monitor progress
aifw status
aifw tail api-worker

# Attach to the tmux control plane
aifw attach

# Stop (preserves state)
aifw stop

# Destroy (cleans up everything)
aifw destroy
```

## How It Works

```
┌─────────────────────────────────────────────────────────┐
│  HOST                                                   │
│                                                         │
│  ┌──────────── tmux session ──────────────────────┐     │
│  │  [overview] [orchestrator] [git] [integration] │     │
│  │  [w-api]    [w-frontend]   [w-lib]             │     │
│  └────────────────────────────────────────────────┘     │
│         │              │           │                    │
│         └──── lxc exec ────────────┘                    │
│                    │                                    │
│  ┌─────── LXD Container (one per mission) ──────────┐  │
│  │                                                   │  │
│  │  Claude Code ×N   (workers + orchestrator)        │  │
│  │                                                   │  │
│  │  Mounts:                                          │  │
│  │    ~/.claude      → /home/ubuntu/.claude          │  │
│  │    ~/.claude.json → /home/ubuntu/.claude.json     │  │
│  │    ~/repos/*      → same absolute paths           │  │
│  │    ~/.local/share/aifw/missions/<id>/ → same path │  │
│  └───────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────┘
```

- **One tmux session** on the host provides the control plane
- **One LXD container** per mission provides isolation
- **Multiple Claude Code instances** run inside the container
- **File-based coordination** in `.ai/` — no hidden state, no IPC

## Commands

| Command | Description |
|---------|-------------|
| `aifw start <repo...>` | Create a mission and launch the control plane |
| `aifw status` | Show mission overview (container, workers, repos, events) |
| `aifw attach` | Attach to the mission's tmux session |
| `aifw stop` | Stop the container (preserves mission state) |
| `aifw destroy` | Stop container, kill tmux, remove mission files |
| `aifw assign <worker> <task>` | Assign a task to a named worker |
| `aifw tail <worker>` | Show worker status, brief, handoff, and events |
| `aifw doctor` | Run environment health checks |
| `aifw list` | List all missions |

### Global flags

- `--config <path>` — Path to config.toml (default: `~/.config/aifw/config.toml`)
- `--mission <id>` / `-m <id>` — Target a specific mission (default: most recent)

## Mission Directory Layout

```
~/.local/share/aifw/missions/20260327-a1b2/
├── control/
│   └── mission.toml              # mission metadata, repos, timestamps
├── repos/
│   ├── api-server → ~/repos/api-server
│   └── frontend → ~/repos/frontend
├── logs/
│   ├── aifw.log                  # main aifw log
│   └── workers/
├── runtime/
│   ├── tmux-session              # "aifw-20260327-a1b2"
│   └── container-name            # "aifw-20260327-a1b2"
└── .ai/
    ├── spec.md                   # mission specification (orchestrator writes)
    ├── architecture.md           # architecture notes
    ├── task-board.yaml           # task tracking
    ├── workers/
    │   ├── api-worker.md         # worker brief (assignment)
    │   └── ui-worker.md
    ├── status/
    │   ├── api-worker.json       # machine-readable worker status
    │   └── ui-worker.json
    ├── handoffs/
    │   ├── api-worker.md         # human-readable handoff notes
    │   └── ui-worker.md
    ├── contracts/                # cross-repo interface agreements
    └── events.log                # structured event log
```

## tmux Layout

| Window | Purpose |
|--------|---------|
| `overview` | `watch aifw status` — auto-refreshing dashboard |
| `orchestrator` | Claude Code session for planning and dispatch |
| `git` | Shell in the container for git operations |
| `integration` | Shell in the container for testing/validation |
| `w-<name>` | One per worker — Claude Code session with brief |

Navigate with standard tmux: `Ctrl-b <n>` for window number, `Ctrl-b w` for window list.

## Configuration

Create `~/.config/aifw/config.toml`:

```toml
# LXD base image (built by your base-container.sh)
lxd_base_image_alias = "worktainer-base"

# Path to your base image build script
lxd_base_container_script = "/path/to/base-container.sh"

# Claude Code binary name inside the container
claude_bin = "claude"

# Mission storage location
# mission_root = "~/.local/share/aifw/missions"

# tmux overview refresh interval
# overview_interval = 5
```

All settings can also be set via environment variables with `AIFW_` prefix:
```bash
export AIFW_LXD_BASE_IMAGE_ALIAS=my-custom-image
export AIFW_CLAUDE_BIN=/usr/local/bin/claude
```

See `sample/config.toml` for all options with defaults.

## Worker Assignment Flow

```bash
# Assign from a text description
aifw assign api-worker "Implement JWT-based auth for the /login endpoint"

# Assign from a file
aifw assign api-worker ./tasks/auth-implementation.md

# Assign to a specific repo
aifw assign ui-worker "Build login form" --repo ~/repos/frontend
```

What happens:
1. A worker brief is rendered from the template at `templates/worker_brief.md`
2. The brief is written to `.ai/workers/<name>.md`
3. An initial status file is created at `.ai/status/<name>.json`
4. A tmux window `w-<name>` is created running Claude Code in the container
5. Claude Code receives a prompt pointing it to the brief file
6. The assignment is logged to `.ai/events.log`

Re-assigning the same worker updates the brief and sends a new prompt.

## Worker Coordination Model

Workers coordinate through files, not messages:

- **Task board** (`.ai/task-board.yaml`): Orchestrator maintains the global task list
- **Status files** (`.ai/status/<worker>.json`): Workers update machine-readable status
- **Handoff notes** (`.ai/handoffs/<worker>.md`): Workers write human-readable summaries
- **Contracts** (`.ai/contracts/`): Cross-repo interface agreements
- **Events log** (`.ai/events.log`): Append-only audit trail

## Prerequisites

- Python 3.12+
- tmux
- LXD with a pre-built base image (see [LXD Integration](docs/lxd-integration.md))
- Claude Code installed in the base image

## Language Choice

Python was chosen because:
- The user's existing tooling is shell scripts; Python is a natural step up
- Strong subprocess handling (`subprocess`, `shlex`)
- Built-in TOML support (Python 3.12+)
- Type hints for maintainability
- Fast iteration — no compile step
- Good testability with `pytest` and `unittest.mock`

## Architecture

See [docs/architecture.md](docs/architecture.md) for detailed design notes.

See [docs/lxd-integration.md](docs/lxd-integration.md) for how to plug in your existing LXD scripts.

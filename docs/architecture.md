# Architecture

## Design Philosophy

`aifw` is a **thin operator layer**, not a framework. It wraps four existing tools:

1. **tmux** — user interface (windows, panes, session management)
2. **LXD** — container isolation (one container per mission)
3. **Claude Code** — AI worker runtime (multiple instances per container)
4. **Git** — version control (one checkout per repo)

The glue between them is **files on disk**. No database, no message broker, no daemon.

## Module Structure

```
src/aifw/
├── cli.py       # argparse-based CLI entry point
├── config.py    # Configuration loading, defaults, env overrides
├── events.py    # Structured event logging
├── lxd.py       # LXD adapter (container lifecycle via lxc CLI)
├── tmux.py      # tmux session/window management
├── mission.py   # Mission lifecycle, directory structure, state
├── claude.py    # Claude Code session launch and prompt injection
├── workers.py   # Worker assignment, briefs, status
└── status.py    # Status display, doctor, tail
```

### Dependency Flow

```
cli.py
  ├── config.py        (standalone)
  ├── events.py        (standalone)
  ├── lxd.py           ← config
  ├── tmux.py          ← config
  ├── mission.py       ← config, events, lxd
  ├── claude.py        ← config, tmux
  ├── workers.py       ← config, mission, claude, events, tmux
  └── status.py        ← config, mission, workers, lxd, tmux
```

No circular dependencies. Each module has a clear responsibility.

## Key Design Decisions

### 1. One container per mission

All workers share a single LXD container. This avoids:
- Container proliferation
- Cross-container networking
- Duplicate mounts

The container is created once during `aifw start` and shared by all workers via `lxc exec`.

### 2. Same paths in host and container

Repository paths and the mission directory are mounted at the **same path** in the container as on the host. This means:
- No path translation needed
- Claude Code's path references work everywhere
- File-based coordination "just works"

### 3. File-based coordination

Workers communicate through structured files in `.ai/`:
- **Status files** (JSON) — machine-readable, polled by `aifw status`
- **Handoff notes** (Markdown) — human-readable, written when work is complete
- **Contracts** (Markdown) — cross-repo interface agreements requiring escalation
- **Events log** (text) — append-only audit trail

This is deliberate. Files are:
- Inspectable (`cat`, `jq`, `grep`)
- Versioned (if the mission dir is in a git repo)
- Debuggable (no hidden state)
- Simple (no serialisation framework)

### 4. tmux as the UI

tmux provides:
- Multiple windows for different concerns
- Persistent sessions (survive terminal disconnects)
- Standard keybindings terminal users already know
- Scriptable window/pane management

The overview window runs `watch aifw status` for an auto-refreshing dashboard.

### 5. Prompt injection via tmux send-keys

When assigning work, `aifw` sends a prompt to Claude Code through tmux:
- Short prompts: `tmux send-keys`
- Long prompts: `tmux load-buffer` + `paste-buffer`

This is transparent and inspectable. The prompt points Claude to the brief file rather than inlining the full task.

### 6. No custom LXD logic — adapter pattern

`aifw` does not replace the user's existing LXD scripts. The `lxd.py` module mirrors the logic of `work-it.sh` but adds:
- Support for multiple disk mounts
- Non-interactive operation
- Configurable fallback to external scripts

If the built-in adapter doesn't fit, set `lxd_bootstrap_script` in config.

### 7. Configuration hierarchy

Priority order:
1. `AIFW_*` environment variables (highest)
2. Config file (`~/.config/aifw/config.toml`)
3. Built-in defaults (lowest)

All Claude-related paths are centralised in `config.py` — no scattered path assumptions.

## State Model

A mission transitions through these states:

```
(none) → created → running → stopped → destroyed
                     ↑          │
                     └──────────┘  (aifw start --id <existing>)
```

- **created**: directory exists, no container
- **running**: container up, tmux session active
- **stopped**: container stopped, mission files preserved
- **destroyed**: container deleted, files removed (unless `--keep-files`)

## Error Handling

- LXD operations raise `LXDError` with the full `lxc` stderr
- tmux operations raise `TmuxError`
- `aifw doctor` validates the environment before things break
- Operations are idempotent — re-running is safe
- The CLI catches exceptions and prints clear messages

## Testing Strategy

- **Unit tests**: config, events, mission, workers — all testable without LXD/tmux
- **Mocking**: LXD and tmux operations are mocked at the module boundary
- **No integration tests requiring LXD**: these would need a running LXD daemon
- Tests run with `pytest` and use `tmp_path` for isolation

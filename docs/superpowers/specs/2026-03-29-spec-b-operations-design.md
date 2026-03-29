# Spec B: Operations

## 1. `aifw sync`

Push all mission clone branches back to their origin repos.

### CLI

```
aifw sync [--mission ID] [--dry-run]
```

### Behaviour

For each clone in `missions/<id>/repos/`:
1. Get current branch name (should be `mission/<id>`)
2. Run `git push origin <branch>` (or `git push --dry-run origin <branch>`)
3. Report per-repo result

### Output

```
Syncing mission 20260329-a1b2 ...

  api-server:    pushed 3 commits to mission/20260329-a1b2
  frontend:      already up to date
  shared-lib:    FAILED — remote rejected (permission denied)

2 synced, 1 failed.
```

### New types

`PushResult` dataclass in `git.py`:
- `pushed: int` — number of commits pushed
- `up_to_date: bool` — True if nothing to push
- `error: str | None` — error message if push failed

### Module changes

| Module | Change |
|--------|--------|
| `git.py` | Add `push_branch(repo_path: str, branch: str, *, dry_run: bool = False) -> PushResult` and `PushResult` dataclass |
| `cli.py` | Add `sync` subparser with `--dry-run`, add `cmd_sync` |

## 2. Worker lifecycle

Individual worker management without affecting the whole mission.

### CLI

```
aifw kill <worker>       — kill the worker's tmux window
aifw restart <worker>    — kill + re-launch from existing brief
```

### `kill` behaviour

1. Kill tmux window `w-<worker>` (existing `tmux.kill_window`)
2. Update status JSON: `"status": "error"`, `"summary": "Killed by operator"`
3. Log event

### `restart` behaviour

1. Kill tmux window if it exists
2. Read existing status JSON to get `repo` and `model`
3. Read existing brief from `.ai/workers/<worker>.md`
4. Update status JSON: `"status": "ready"`, `"summary": "Restarted by operator"`
5. Spawn new worker window with model from status, send brief prompt
6. Log event

If no brief or status file exists, error and exit.

### Module changes

| Module | Change |
|--------|--------|
| `cli.py` | Add `kill` and `restart` subparsers, add `cmd_kill` and `cmd_restart` |

No new modules. Uses existing `tmux.kill_window`, `tmux.create_worker_window`, `claude.launch_worker_session`, `claude.build_worker_prompt`. Reads/writes status JSON directly.

## 3. `aifw log <worker>`

Stream the Claude Code conversation from a worker's tmux pane.

### CLI

```
aifw log <worker> [--lines N] [-f/--follow]
```

### Default mode (snapshot)

Calls `tmux.capture_pane` with the specified line count (default 50), prints the buffer.

### Follow mode

Loops every 1 second:
1. Capture pane content
2. Compare with previous capture
3. Print only new lines
4. Ctrl-C to stop

### Special target

`aifw log orchestrator` targets the `orchestrator` window instead of `w-<name>`. The window name logic: if the worker name is `orchestrator`, use `orchestrator` as the window name; otherwise use `w-<name>`.

### Module changes

| Module | Change |
|--------|--------|
| `cli.py` | Add `log` subparser with `--lines` and `-f/--follow`, add `cmd_log` |

No new modules. Uses existing `tmux.capture_pane`.

## What does not change

- Mission lifecycle
- Container management
- Dispatch watcher
- Worker brief format
- Coordination model

# Spec B: Operations

Depends on: Spec A (auto-branch, model selection)

## Features

### 1. `aifw sync`

Push all mission clone branches back to their origin repos.

```
aifw sync [--mission ID]
```

For each clone in `missions/<id>/repos/`:
1. Run `git push origin mission/<id>`
2. Report per-repo result: pushed N commits, already up to date, or failed (with error)

Options:
- `--dry-run` — show what would be pushed without pushing

**Touchpoints:** New `cmd_sync` in cli.py. New `push_to_origin()` in git.py. Status output after push.

### 2. Worker lifecycle

Individual worker management without affecting the whole mission.

```
aifw kill <worker>      — kill the worker's tmux window
aifw restart <worker>   — kill + re-launch from existing brief
```

`kill`: Kills the tmux window `w-<worker>`. Sets status to `error` with summary "Killed by operator". Logs the event.

`restart`: Kills the window if it exists, then re-launches Claude Code with the existing brief. Reads model from the status file. Sets status back to `ready`.

**Touchpoints:** New `cmd_kill` and `cmd_restart` in cli.py. Uses existing `tmux.kill_window` and `create_worker_window`. Updates status file and events.

### 3. `aifw log <worker>`

Stream the Claude Code conversation from a worker's tmux pane.

```
aifw log <worker> [--lines N]
```

Uses `tmux capture-pane` (already implemented as `capture_pane` in tmux.py) to grab the visible buffer. With `--follow`/`-f`, loops with a short interval (like `tail -f`).

**Touchpoints:** New `cmd_log` in cli.py. Uses existing `tmux.capture_pane`. Add `--follow` mode with poll loop.

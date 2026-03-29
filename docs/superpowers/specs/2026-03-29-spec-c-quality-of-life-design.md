# Spec C: Quality of Life

Depends on: Spec A, Spec B

## Features

### 1. Cost tracking

Claude Code exposes token usage per session. After a mission completes (or on demand), show a cost breakdown.

```
aifw cost [--mission ID]
```

Approach: Claude Code writes usage data to its session files. Parse these to extract token counts per worker. Display as a table: worker, model, input tokens, output tokens, estimated cost.

This depends on Claude Code's internal file format, which may change. Isolate behind a parser module and fail gracefully if the format is unreadable.

**Touchpoints:** New `cost.py` module with session file parser. New `cmd_cost` in cli.py.

### 2. Mission templates

Pre-defined mission configurations for recurring task shapes.

```
aifw start --template ubuntu-merge repo1 repo2
```

A template defines:
- Default worker names and their model assignments
- Pre-filled spec.md content
- Pre-filled architecture.md content
- Orchestrator initial prompt

Templates are TOML files in `~/.config/aifw/templates/` or `<project>/templates/`.

**Touchpoints:** New `templates.py` module. Template loading in `cmd_start`. Template TOML format spec. Sample template.

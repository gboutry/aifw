"""Worker lifecycle management.

A worker is a named agent (Claude Code session) with:
  - A brief file (.ai/workers/<name>.md) defining its assignment
  - A status file (.ai/status/<name>.json) for machine-readable state
  - A handoff file (.ai/handoffs/<name>.md) for human-readable notes
  - A tmux window (w-<name>) running Claude Code
  - An optional log file (logs/workers/<name>.log)

Workers are assigned via `aifw assign <worker> <task>`.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from string import Template

from aifw.claude import build_worker_prompt, launch_worker_session, send_prompt_to_worker
from aifw.config import Config
from aifw.events import ASSIGNMENT, WORKER, EventLog
from aifw.mission import Mission

logger = logging.getLogger("aifw")

# ---------------------------------------------------------------------------
# Brief template
# ---------------------------------------------------------------------------

BRIEF_TEMPLATE_PATH = Path(__file__).parent.parent.parent / "templates" / "worker_brief.md"


def _load_brief_template() -> str:
    """Load the worker brief template."""
    if BRIEF_TEMPLATE_PATH.exists():
        return BRIEF_TEMPLATE_PATH.read_text()
    # Fallback inline template
    return """\
# Worker Brief: $worker_name

**Mission**: $mission_id
**Assigned**: $timestamp
**Repo**: $repo_path

## Objective

$task_description

## Scope

- Repository: `$repo_name`
- Working directory: `$repo_path`

## Constraints

- Only modify files within your assigned repository
- Do not modify shared contracts without escalating

## Dependencies

_None specified. Check task-board.yaml for updates._

## Required Outputs

1. Implementation as described in the objective
2. Update your status file: `$status_path`
3. Write a handoff note when done: `$handoff_path`

## Status Reporting

Write your status to `$status_path` as JSON:
```json
{
  "worker": "$worker_name",
  "status": "in_progress",
  "updated": "<ISO timestamp>",
  "summary": "<one-line summary of current state>",
  "blockers": []
}
```

Status values: `ready`, `in_progress`, `done`, `blocked`, `error`

## Handoff Notes

When your work is complete, write `$handoff_path` with:
- What you changed and why
- Any cross-repo impacts
- Testing status
- Anything the next worker or integrator should know

## Escalation Rules

If you need to change a cross-repo contract (shared API, data format, config):
1. Document the proposed change in `$contracts_dir/<contract-name>.md`
2. Set your status to `blocked`
3. Add a blocker note referencing the contract
4. Wait for orchestrator guidance
"""


def render_brief(
    worker_name: str,
    mission: Mission,
    repo_path: str,
    task_description: str,
) -> str:
    """Render a worker brief from the template."""
    repo_name = Path(repo_path).name
    template = Template(_load_brief_template())
    return template.safe_substitute(
        worker_name=worker_name,
        mission_id=mission.mission_id,
        timestamp=datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        repo_path=repo_path,
        repo_name=repo_name,
        task_description=task_description,
        status_path=str(mission.ai_dir / "status" / f"{worker_name}.json"),
        handoff_path=str(mission.ai_dir / "handoffs" / f"{worker_name}.md"),
        contracts_dir=str(mission.ai_dir / "contracts"),
    )


# ---------------------------------------------------------------------------
# Worker operations
# ---------------------------------------------------------------------------


def assign_worker(
    config: Config,
    mission: Mission,
    worker_name: str,
    task: str,
    repo_path: str | None = None,
    *,
    model: str = "",
) -> None:
    """Assign a task to a worker.

    If the task looks like a file path and exists, its contents are used.
    Otherwise, the task string is used directly as the task description.
    """
    events = mission.ensure_events()

    # Resolve task content
    task_path = Path(task)
    if task_path.exists() and task_path.is_file():
        task_description = task_path.read_text()
        events.log(ASSIGNMENT, "aifw", f"Loaded task from file: {task}")
    else:
        task_description = task

    # Determine repo path — use clone path, not original
    if repo_path is None:
        clones = mission.clone_paths()
        if clones:
            repo_path = next(iter(clones.values()))
        else:
            repo_path = str(mission.root)

    # Render and write brief
    brief_content = render_brief(worker_name, mission, repo_path, task_description)
    brief_path = mission.ai_dir / "workers" / f"{worker_name}.md"
    brief_path.write_text(brief_content)

    # Write initial status
    status_data = {
        "worker": worker_name,
        "status": "ready",
        "updated": datetime.now(timezone.utc).isoformat(),
        "summary": "Assignment received, ready to start",
        "blockers": [],
        "repo": repo_path,
        "model": model,
    }
    status_path = mission.ai_dir / "status" / f"{worker_name}.json"
    status_path.write_text(json.dumps(status_data, indent=2) + "\n")

    events.log(ASSIGNMENT, "aifw", f"Assigned worker '{worker_name}' to: {task_description[:80]}")

    # Launch or refresh Claude Code session
    prompt = build_worker_prompt(str(brief_path))

    from aifw.tmux import window_exists
    window_name = f"w-{worker_name}"

    if window_exists(config, mission.tmux_session, window_name):
        # Worker window exists — send re-assignment prompt
        events.log(WORKER, worker_name, "Re-assigned, sending new brief")
        send_prompt_to_worker(config, mission.tmux_session, worker_name, prompt)
    else:
        # Create new worker window
        events.log(WORKER, worker_name, "Creating new worker session")
        launch_worker_session(
            config,
            mission.tmux_session,
            mission.container_name,
            worker_name,
            working_dir=repo_path,
            initial_prompt=prompt,
            model=model,
        )


def list_workers(mission: Mission) -> list[dict]:
    """List workers with their current status."""
    result = []
    for name in mission.worker_names():
        status = mission.read_worker_status(name) or {
            "worker": name,
            "status": "unknown",
            "summary": "No status file",
        }
        result.append(status)
    return result

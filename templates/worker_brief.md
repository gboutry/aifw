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

- Only modify files within your assigned repository unless coordinating a cross-repo change
- Follow existing code style and conventions in the repository
- Do not modify shared contracts without escalating (see Escalation Rules)

## Dependencies

_Check the task board for current dependencies: `$mission_id/.ai/task-board.yaml`_

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

Update your status file whenever your state changes meaningfully.

## Handoff Notes

When your work is complete, write `$handoff_path` with:

- What you changed and why
- Files modified (key changes, not exhaustive)
- Any cross-repo impacts
- Testing status (what you tested, what still needs testing)
- Anything the next worker or integrator should know

## Escalation Rules

If you need to change a cross-repo contract (shared API, data format, configuration schema):

1. Document the proposed change in `$contracts_dir/<contract-name>.md`
2. Set your status to `blocked` with a clear blocker description
3. Wait for orchestrator guidance before proceeding
4. Do not assume the change is approved until your status is updated to `in_progress`

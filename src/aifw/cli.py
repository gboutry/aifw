"""CLI entry point for aifw.

Subcommands:
  start <repo...>              Create a mission and launch the control plane
  status                       Show mission overview
  attach                       Attach to the mission tmux session
  stop                         Stop the mission container (preserves state)
  destroy                      Stop container and remove mission data
  assign <worker> <task>       Assign a task to a named worker
  tail <worker>                Stream worker status and events
  doctor                       Run environment health checks
  list                         List all missions
  sync                         Push mission branches to origin repos
  kill <worker>                Kill a worker's tmux window
  restart <worker>             Kill and re-launch a worker from its existing brief
  log <worker>                 Show a worker's Claude Code conversation
"""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

from aifw.config import load_config
from aifw.events import setup_stderr_logging


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="aifw",
        description="Terminal-first AI orchestration for multi-repository work",
    )
    parser.add_argument(
        "--config", type=Path, default=None,
        help="Path to config.toml (default: ~/.config/aifw/config.toml)",
    )
    parser.add_argument(
        "--mission", "-m", type=str, default=None,
        help="Mission ID (default: most recent)",
    )

    sub = parser.add_subparsers(dest="command")

    # start
    p_start = sub.add_parser("start", help="Create a mission and launch the control plane")
    p_start.add_argument("repos", nargs="*", default=[], help="Paths to repositories")
    p_start.add_argument("--id", dest="mission_id", default=None, help="Custom mission ID (or resume existing)")
    p_start.add_argument("--no-attach", action="store_true", help="Don't attach to tmux after start")
    p_start.add_argument("--orchestrator-model", default="", help="Model for the orchestrator session")
    p_start.add_argument("--spec", dest="spec_file", default=None, help="Path to mission spec file")
    p_start.add_argument("--objective", default=None, help="Inline mission objective text")

    # status
    sub.add_parser("status", help="Show mission overview")

    # attach
    sub.add_parser("attach", help="Attach to mission tmux session")

    # stop
    sub.add_parser("stop", help="Stop the mission container")

    # destroy
    p_destroy = sub.add_parser("destroy", help="Stop container and clean up mission")
    p_destroy.add_argument("--keep-files", action="store_true", help="Keep mission directory")
    p_destroy.add_argument("-f", "--force", action="store_true", help="Destroy even with unpushed work")

    # assign
    p_assign = sub.add_parser("assign", help="Assign a task to a worker")
    p_assign.add_argument("worker", help="Worker name")
    p_assign.add_argument("task", help="Task description or path to a task file")
    p_assign.add_argument("--repo", default=None, help="Repository path for this worker")
    p_assign.add_argument("--model", default="", help="Claude model for this worker (e.g. sonnet, opus)")

    # tail
    p_tail = sub.add_parser("tail", help="Stream worker status and events")
    p_tail.add_argument("worker", help="Worker name")

    # doctor
    sub.add_parser("doctor", help="Run environment health checks")

    # list
    sub.add_parser("list", help="List all missions")

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

    return parser


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


def cmd_status(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    from aifw.status import show_status
    show_status(config, args.mission)


def cmd_attach(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    from aifw.mission import Mission, find_current_mission

    if args.mission:
        mission = Mission(args.mission, config)
    else:
        mission = find_current_mission(config)

    if mission is None or not mission.exists():
        print("No active mission found.", file=sys.stderr)
        sys.exit(1)

    from aifw.tmux import attach_session
    attach_session(config, mission.tmux_session)


def cmd_stop(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    setup_stderr_logging(config.log_level)
    from aifw.mission import Mission, find_current_mission

    if args.mission:
        mission = Mission(args.mission, config)
    else:
        mission = find_current_mission(config)

    if mission is None or not mission.exists():
        print("No active mission found.", file=sys.stderr)
        sys.exit(1)

    print(f"Stopping mission {mission.mission_id} ...")
    mission.stop()
    print("Container stopped. Mission state preserved.")
    print(f"  Restart with: aifw start --id {mission.mission_id} {' '.join(mission.repo_paths())}")


def cmd_destroy(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    setup_stderr_logging(config.log_level)
    from aifw.mission import Mission, find_current_mission
    from aifw.tmux import kill_session

    if args.mission:
        mission = Mission(args.mission, config)
    else:
        mission = find_current_mission(config)

    if mission is None or not mission.exists():
        print("No active mission found.", file=sys.stderr)
        sys.exit(1)

    # Check for unpushed work unless --force
    if not args.force and not args.keep_files:
        statuses = mission.check_unpushed()
        has_issues = any(s.dirty or s.unpushed for s in statuses.values())
        if has_issues:
            print(f"Cannot destroy mission {mission.mission_id}: unpushed work found\n")
            for name, s in statuses.items():
                if s.dirty or s.unpushed:
                    print(f"  {name}:")
                    if s.unpushed:
                        print(f"    {len(s.unpushed)} unpushed branch(es): {', '.join(s.unpushed)}")
                    if s.dirty:
                        print(f"    Uncommitted changes")
                else:
                    print(f"  {name}: clean")
            print(f"\nUse --force to destroy anyway.")
            sys.exit(1)

    print(f"Destroying mission {mission.mission_id} ...")

    kill_session(config, mission.tmux_session)
    mission.destroy()

    if not args.keep_files:
        import shutil
        shutil.rmtree(mission.root, ignore_errors=True)
        print(f"Removed {mission.root}")
    else:
        print(f"Kept mission files at {mission.root}")

    print("Mission destroyed.")


def cmd_assign(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    setup_stderr_logging(config.log_level)
    from aifw.mission import Mission, find_current_mission
    from aifw.workers import assign_worker

    if args.mission:
        mission = Mission(args.mission, config)
    else:
        mission = find_current_mission(config)

    if mission is None or not mission.exists():
        print("No active mission found.", file=sys.stderr)
        sys.exit(1)

    assign_worker(config, mission, args.worker, args.task, args.repo, model=args.model)
    print(f"Assigned '{args.worker}' — brief at {mission.ai_dir / 'workers' / f'{args.worker}.md'}")


def cmd_tail(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    from aifw.status import tail_worker
    tail_worker(config, args.worker, args.mission)


def cmd_doctor(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    from aifw.status import run_doctor
    run_doctor(config)


def cmd_list(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    from aifw.mission import list_missions

    missions = list_missions(config)
    if not missions:
        print("No missions found.")
        return

    print(f"\n{'─' * 60}")
    print(f"  {'ID':<24s} {'State':<12s} {'Repos'}")
    print(f"{'─' * 60}")
    for m in missions:
        from aifw.lxd import container_status
        state = container_status(m.container_name) or "NO CONTAINER"
        repos = [Path(r).name for r in m.repo_paths()]
        print(f"  {m.mission_id:<24s} {state:<12s} {', '.join(repos)}")
    print(f"{'─' * 60}\n")


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

    kill_window(config, mission.tmux_session, window_name)

    import json
    from datetime import datetime, timezone
    status_path = mission.ai_dir / "status" / f"{worker_name}.json"
    if status_path.exists():
        data = json.loads(status_path.read_text())
        data["status"] = "error"
        data["summary"] = "Killed by operator"
        data["updated"] = datetime.now(timezone.utc).isoformat()
        status_path.write_text(json.dumps(data, indent=2) + "\n")

    mission.ensure_events().log("worker", "aifw", f"Killed worker: {worker_name}")
    print(f"Killed worker '{worker_name}'")


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

    import json
    from datetime import datetime, timezone
    model = ""
    repo = str(mission.root)
    if status_path.exists():
        data = json.loads(status_path.read_text())
        model = data.get("model", "")
        repo = data.get("repo", str(mission.root))

    kill_window(config, mission.tmux_session, window_name)

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
    window_name = "orchestrator" if worker_name == "orchestrator" else f"w-{worker_name}"

    if not args.follow:
        output = capture_pane(config, mission.tmux_session, window_name, lines=args.lines)
        if output:
            print(output, end="")
        else:
            print(f"No output from '{worker_name}' (window may not exist)")
        return

    import time
    previous = ""
    try:
        while True:
            current = capture_pane(config, mission.tmux_session, window_name, lines=args.lines)
            if current != previous:
                prev_lines = previous.splitlines()
                curr_lines = current.splitlines()
                if previous and curr_lines:
                    new_count = len(curr_lines) - len(prev_lines)
                    if new_count > 0:
                        for line in curr_lines[-new_count:]:
                            print(line)
                    elif current != previous:
                        print(current, end="")
                else:
                    print(current, end="")
                previous = current
            time.sleep(1)
    except KeyboardInterrupt:
        pass


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


def main() -> None:
    parser = _build_parser()
    args = parser.parse_args()

    if args.command is None:
        parser.print_help()
        sys.exit(0)

    handler = _COMMANDS.get(args.command)
    if handler is None:
        parser.print_help()
        sys.exit(1)

    try:
        handler(args)
    except KeyboardInterrupt:
        sys.exit(130)
    except Exception as exc:
        print(f"\nError: {exc}", file=sys.stderr)
        sys.exit(1)

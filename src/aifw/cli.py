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
    p_start.add_argument("repos", nargs="+", help="Paths to repositories")
    p_start.add_argument("--id", dest="mission_id", default=None, help="Custom mission ID")
    p_start.add_argument("--no-attach", action="store_true", help="Don't attach to tmux after start")

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

    # tail
    p_tail = sub.add_parser("tail", help="Stream worker status and events")
    p_tail.add_argument("worker", help="Worker name")

    # doctor
    sub.add_parser("doctor", help="Run environment health checks")

    # list
    sub.add_parser("list", help="List all missions")

    return parser


def cmd_start(args: argparse.Namespace) -> None:
    config = load_config(args.config)
    setup_stderr_logging(config.log_level)

    from aifw.mission import Mission, generate_mission_id

    # Resolve repo paths
    repo_paths = [str(Path(r).resolve()) for r in args.repos]
    for rp in repo_paths:
        if not Path(rp).is_dir():
            print(f"Error: repository path does not exist: {rp}", file=sys.stderr)
            sys.exit(1)

    # Create mission
    mission_id = args.mission_id or generate_mission_id()
    mission = Mission(mission_id, config)

    if mission.exists():
        print(f"Mission {mission_id} already exists. Reusing.", file=sys.stderr)
    else:
        print(f"Creating mission {mission_id} ...")
        mission.init_directory(repo_paths)

    # Provision container
    print(f"Provisioning container {mission.container_name} ...")
    mission.provision_container()

    # Set up tmux control plane
    print(f"Setting up tmux session {mission.tmux_session} ...")
    from aifw.tmux import setup_control_plane
    clone_paths = list(mission.clone_paths().values())
    setup_control_plane(
        config,
        mission.tmux_session,
        mission.container_name,
        str(mission.root),
        clone_paths,
    )

    print(f"\nMission {mission_id} is ready.")
    print(f"  Directory:  {mission.root}")
    print(f"  Container:  {mission.container_name}")
    print(f"  tmux:       {mission.tmux_session}")
    print(f"\nNext steps:")
    print(f"  aifw assign <worker> <task>   — assign work to a worker")
    print(f"  aifw status                   — check mission status")
    print(f"  aifw attach                   — attach to tmux session")

    # Attach unless --no-attach
    if not args.no_attach:
        print(f"\nAttaching to tmux session ...")
        from aifw.tmux import attach_session
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

    assign_worker(config, mission, args.worker, args.task, args.repo)
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

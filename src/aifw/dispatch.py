"""Dispatch watcher — bridges orchestrator (container) to worker sessions (host).

Runs on the host in a tmux pane. Watches .ai/workers/ for new or updated
brief files. When a brief appears for a worker that doesn't have a tmux
window yet, the watcher spawns one.

This is what allows the orchestrator Claude (inside the container) to
dispatch workers by simply writing brief files — no host-side CLI needed.

Usage:
    python -m aifw.dispatch <mission-dir> <tmux-session> <container-name>

Or via aifw internals — launched automatically in the dispatch tmux pane.
"""

from __future__ import annotations

import json
import logging
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

from aifw.config import Config, load_config
from aifw.events import WORKER, EventLog
from aifw.tmux import create_worker_window, send_keys, window_exists

logger = logging.getLogger("aifw.dispatch")


def _worker_window_name(worker_name: str) -> str:
    return f"w-{worker_name}"


def _scan_briefs(ai_dir: Path) -> dict[str, float]:
    """Return {worker_name: mtime} for all briefs in .ai/workers/."""
    workers_dir = ai_dir / "workers"
    if not workers_dir.exists():
        return {}
    result = {}
    for p in workers_dir.glob("*.md"):
        result[p.stem] = p.stat().st_mtime
    return result


def _read_worker_repo(ai_dir: Path, worker_name: str) -> str | None:
    """Try to extract the repo path from the worker's status file."""
    status_file = ai_dir / "status" / f"{worker_name}.json"
    if status_file.exists():
        try:
            data = json.loads(status_file.read_text())
            return data.get("repo")
        except (json.JSONDecodeError, KeyError):
            pass
    return None


def _read_worker_model(ai_dir: Path, worker_name: str) -> str:
    """Try to extract the model from the worker's status file."""
    status_file = ai_dir / "status" / f"{worker_name}.json"
    if status_file.exists():
        try:
            data = json.loads(status_file.read_text())
            return data.get("model", "")
        except (json.JSONDecodeError, KeyError):
            pass
    return ""


def _build_initial_prompt(brief_path: Path) -> str:
    return (
        f"Read your worker brief at {brief_path} and follow the instructions. "
        f"Begin by confirming you understand the assignment, then start working."
    )


def run_dispatch_loop(
    config: Config,
    mission_dir: Path,
    tmux_session: str,
    container_name: str,
    *,
    poll_interval: float = 2.0,
) -> None:
    """Watch for new briefs and spawn worker sessions.

    Runs forever until interrupted.
    """
    ai_dir = mission_dir / ".ai"
    events = EventLog(
        events_path=ai_dir / "events.log",
        aifw_log_path=mission_dir / "logs" / "aifw.log",
    )

    # Track which briefs we've already processed and their mtimes
    known: dict[str, float] = {}

    print(f"[dispatch] Watching {ai_dir / 'workers'} for briefs ...")
    print(f"[dispatch] tmux={tmux_session}  container={container_name}")
    print(f"[dispatch] Poll interval: {poll_interval}s")
    print()

    while True:
        try:
            current = _scan_briefs(ai_dir)

            for worker_name, mtime in current.items():
                window_name = _worker_window_name(worker_name)
                brief_path = ai_dir / "workers" / f"{worker_name}.md"
                has_window = window_exists(config, tmux_session, window_name)

                if worker_name not in known:
                    # New brief — spawn worker if no window exists
                    if not has_window:
                        repo = _read_worker_repo(ai_dir, worker_name)
                        if not repo:
                            # Status file may not be written yet — skip this cycle
                            ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
                            print(f"[dispatch {ts}] Brief found for {worker_name} but no status file yet, waiting...")
                            continue
                        cwd = repo

                        ts = datetime.now(timezone.utc).strftime("%H:%M:%S")
                        print(f"[dispatch {ts}] New worker: {worker_name} → spawning session (cwd={cwd})")

                        model = _read_worker_model(ai_dir, worker_name)
                        claude_args = f"--model {model}" if model else ""
                        if not claude_args and config.default_model:
                            claude_args = f"--model {config.default_model}"
                        create_worker_window(
                            config, tmux_session, container_name, worker_name,
                            cwd=cwd,
                            claude_args=claude_args,
                        )
                        # Give Claude Code a moment to start
                        time.sleep(3)
                        prompt = _build_initial_prompt(brief_path)
                        send_keys(config, tmux_session, window_name, prompt, enter=True)

                        events.log(WORKER, "dispatch", f"Spawned worker session: {worker_name}")
                    else:
                        print(f"[dispatch] Worker {worker_name} already has window, tracking")

                    known[worker_name] = mtime

                elif mtime > known[worker_name]:
                    # Brief was updated — notify existing worker
                    known[worker_name] = mtime
                    ts = datetime.now(timezone.utc).strftime("%H:%M:%S")

                    if has_window:
                        print(f"[dispatch {ts}] Brief updated: {worker_name} → sending re-read prompt")
                        prompt = (
                            f"Your brief has been updated at {brief_path}. "
                            f"Re-read it and adjust your work accordingly."
                        )
                        send_keys(config, tmux_session, window_name, prompt, enter=True)
                        events.log(WORKER, "dispatch", f"Re-read prompt sent to: {worker_name}")
                    else:
                        # Window gone but brief updated — re-spawn
                        repo = _read_worker_repo(ai_dir, worker_name)
                        if not repo:
                            print(f"[dispatch {ts}] Brief updated for {worker_name} but no status file, skipping")
                            continue
                        print(f"[dispatch {ts}] Brief updated, window gone: {worker_name} → re-spawning")
                        cwd = repo

                        model = _read_worker_model(ai_dir, worker_name)
                        claude_args = f"--model {model}" if model else ""
                        if not claude_args and config.default_model:
                            claude_args = f"--model {config.default_model}"
                        create_worker_window(
                            config, tmux_session, container_name, worker_name,
                            cwd=cwd,
                            claude_args=claude_args,
                        )
                        time.sleep(3)
                        prompt = _build_initial_prompt(brief_path)
                        send_keys(config, tmux_session, window_name, prompt, enter=True)
                        events.log(WORKER, "dispatch", f"Re-spawned worker session: {worker_name}")

            time.sleep(poll_interval)

        except KeyboardInterrupt:
            print("\n[dispatch] Stopped.")
            break
        except Exception as exc:
            logger.exception("Dispatch loop error: %s", exc)
            print(f"[dispatch] Error: {exc}", file=sys.stderr)
            time.sleep(poll_interval)


def main() -> None:
    """Entry point for running dispatch standalone."""
    if len(sys.argv) != 4:
        print(f"Usage: python -m aifw.dispatch <mission-dir> <tmux-session> <container-name>")
        sys.exit(1)

    mission_dir = Path(sys.argv[1])
    tmux_session = sys.argv[2]
    container_name = sys.argv[3]

    config = load_config()

    logging.basicConfig(level=logging.INFO, format="%(asctime)s  %(levelname)s  %(message)s")
    run_dispatch_loop(config, mission_dir, tmux_session, container_name)


if __name__ == "__main__":
    main()

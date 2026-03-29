"""tmux session and window management for the mission control plane.

Layout design:
  Window 0: overview     — watch-based status dashboard
  Window 1: dispatch     — host-side watcher, auto-spawns workers from briefs
  Window 2: orchestrator — Claude Code session for planning/dispatch
  Window 3: git          — shell in container for git/review work
  Window 4: integration  — shell in container for validation/testing
  Window 5+: w-<name>    — one per active worker, Claude Code sessions

All worker and shell windows run commands via `lxc exec` into the
mission container. tmux itself runs on the host.
"""

from __future__ import annotations

import logging
import shutil
import subprocess
import sys

from aifw.config import Config

logger = logging.getLogger("aifw")


class TmuxError(Exception):
    """Raised when a tmux operation fails."""


def _run_tmux(
    config: Config,
    args: list[str],
    *,
    check: bool = True,
    capture: bool = True,
) -> subprocess.CompletedProcess[str]:
    """Run a tmux command."""
    cmd = [config.tmux_bin, *args]
    logger.debug("tmux %s", " ".join(args))
    try:
        return subprocess.run(cmd, check=check, capture_output=capture, text=True, timeout=30)
    except subprocess.CalledProcessError as exc:
        raise TmuxError(f"tmux {' '.join(args)} failed: {exc.stderr}") from exc
    except FileNotFoundError as exc:
        raise TmuxError(f"tmux binary not found at {config.tmux_bin}") from exc


# ---------------------------------------------------------------------------
# Session lifecycle
# ---------------------------------------------------------------------------


def session_exists(config: Config, session_name: str) -> bool:
    result = _run_tmux(config, ["has-session", "-t", session_name], check=False)
    return result.returncode == 0


def create_session(
    config: Config,
    session_name: str,
    *,
    window_name: str = "overview",
    start_dir: str | None = None,
) -> None:
    """Create a new detached tmux session."""
    if session_exists(config, session_name):
        logger.info("tmux session %s already exists", session_name)
        return

    args = ["new-session", "-d", "-s", session_name, "-n", window_name]
    if start_dir:
        args.extend(["-c", start_dir])
    _run_tmux(config, args)
    logger.info("Created tmux session %s", session_name)


def kill_session(config: Config, session_name: str) -> None:
    """Kill a tmux session."""
    if not session_exists(config, session_name):
        return
    _run_tmux(config, ["kill-session", "-t", session_name])
    logger.info("Killed tmux session %s", session_name)


def attach_session(config: Config, session_name: str) -> None:
    """Attach to a tmux session (replaces current process)."""
    if not session_exists(config, session_name):
        raise TmuxError(f"Session {session_name} does not exist")

    import os
    tmux_path = shutil.which(config.tmux_bin) or config.tmux_bin
    os.execvp(tmux_path, [config.tmux_bin, "attach-session", "-t", session_name])


# ---------------------------------------------------------------------------
# Window management
# ---------------------------------------------------------------------------


def create_window(
    config: Config,
    session_name: str,
    window_name: str,
    *,
    start_dir: str | None = None,
) -> None:
    """Create a new window in the session."""
    args = ["new-window", "-t", session_name, "-n", window_name]
    if start_dir:
        args.extend(["-c", start_dir])
    _run_tmux(config, args)


def window_exists(config: Config, session_name: str, window_name: str) -> bool:
    result = _run_tmux(
        config,
        ["list-windows", "-t", session_name, "-F", "#{window_name}"],
        check=False,
    )
    if result.returncode != 0:
        return False
    return window_name in result.stdout.splitlines()


def kill_window(config: Config, session_name: str, window_name: str) -> None:
    if window_exists(config, session_name, window_name):
        _run_tmux(config, ["kill-window", "-t", f"{session_name}:{window_name}"])


def select_window(config: Config, session_name: str, window_name: str) -> None:
    _run_tmux(config, ["select-window", "-t", f"{session_name}:{window_name}"])


def list_windows(config: Config, session_name: str) -> list[str]:
    """Return list of window names in the session."""
    result = _run_tmux(
        config,
        ["list-windows", "-t", session_name, "-F", "#{window_name}"],
        check=False,
    )
    if result.returncode != 0:
        return []
    return [w.strip() for w in result.stdout.splitlines() if w.strip()]


# ---------------------------------------------------------------------------
# Sending commands to panes
# ---------------------------------------------------------------------------


def send_keys(
    config: Config,
    session_name: str,
    window_name: str,
    keys: str,
    *,
    enter: bool = True,
) -> None:
    """Send keystrokes to a tmux pane."""
    target = f"{session_name}:{window_name}"
    _run_tmux(config, ["send-keys", "-t", target, keys, *(["Enter"] if enter else [])])


def send_command(
    config: Config,
    session_name: str,
    window_name: str,
    command: str,
) -> None:
    """Send a shell command to a tmux window."""
    send_keys(config, session_name, window_name, command, enter=True)


# ---------------------------------------------------------------------------
# Pane capture (for status)
# ---------------------------------------------------------------------------


def capture_pane(
    config: Config,
    session_name: str,
    window_name: str,
    *,
    lines: int = 50,
) -> str:
    """Capture the visible content of a pane."""
    target = f"{session_name}:{window_name}"
    result = _run_tmux(
        config,
        ["capture-pane", "-t", target, "-p", "-S", str(-lines)],
        check=False,
    )
    return result.stdout if result.returncode == 0 else ""


# ---------------------------------------------------------------------------
# Control plane setup
# ---------------------------------------------------------------------------


def setup_control_plane(
    config: Config,
    session_name: str,
    container_name: str,
    mission_dir: str,
    repo_paths: list[str],
) -> None:
    """Create the full tmux layout for a mission.

    Windows:
      0: overview     — status dashboard (watch aifw status)
      1: dispatch     — host-side watcher that auto-spawns workers from briefs
      2: orchestrator — Claude Code for planning (in container)
      3: git          — shell in container
      4: integration  — shell in container
    """
    aifw_bin = shutil.which("aifw") or "python -m aifw"
    python_bin = sys.executable

    # Session is created with the overview window
    create_session(config, session_name, window_name="overview", start_dir=mission_dir)

    # Overview: run a watch loop on aifw status
    send_command(
        config, session_name, "overview",
        f"watch -n {config.overview_interval} -c '{aifw_bin} status 2>/dev/null || echo No active mission'",
    )

    # Dispatch window: host-side watcher that spawns workers from briefs
    create_window(config, session_name, "dispatch", start_dir=mission_dir)
    dispatch_cmd = (
        f"{python_bin} -m aifw.dispatch"
        f" {mission_dir} {session_name} {container_name}"
    )
    send_command(config, session_name, "dispatch", dispatch_cmd)

    # Orchestrator window: Claude Code in the container at mission .ai dir
    create_window(config, session_name, "orchestrator", start_dir=mission_dir)
    orchestrator_cmd = _lxc_exec_string(
        container_name, config.lxd_container_user,
        cwd=f"{mission_dir}/.ai",
        command=f"{config.claude_bin}",
    )
    send_command(config, session_name, "orchestrator", orchestrator_cmd)

    # Git window: shell in container
    create_window(config, session_name, "git", start_dir=mission_dir)
    git_shell = _lxc_exec_string(
        container_name, config.lxd_container_user,
        cwd=repo_paths[0] if repo_paths else mission_dir,
        command="bash -l",
    )
    send_command(config, session_name, "git", git_shell)

    # Integration window: shell in container
    create_window(config, session_name, "integration", start_dir=mission_dir)
    integration_shell = _lxc_exec_string(
        container_name, config.lxd_container_user,
        cwd=f"{mission_dir}/repos",
        command="bash -l",
    )
    send_command(config, session_name, "integration", integration_shell)

    # Focus on orchestrator
    select_window(config, session_name, "orchestrator")


def create_worker_window(
    config: Config,
    session_name: str,
    container_name: str,
    worker_name: str,
    *,
    cwd: str,
    claude_args: str = "",
) -> None:
    """Create a tmux window for a worker running Claude Code."""
    window_name = f"w-{worker_name}"
    if window_exists(config, session_name, window_name):
        logger.info("Worker window %s already exists", window_name)
        return

    create_window(config, session_name, window_name)

    claude_cmd = config.claude_bin
    if claude_args:
        claude_cmd = f"{claude_cmd} {claude_args}"

    cmd = _lxc_exec_string(
        container_name, config.lxd_container_user,
        cwd=cwd,
        command=claude_cmd,
    )
    send_command(config, session_name, window_name, cmd)


def _lxc_exec_string(
    container_name: str,
    user: str,
    *,
    cwd: str | None = None,
    command: str = "bash -l",
) -> str:
    """Build an lxc exec command string for tmux send-keys."""
    shell_cmd = command
    if cwd:
        shell_cmd = f"cd {cwd} && exec {command}"
    # Use single quotes for the inner shell command to avoid escaping issues
    return (
        f"lxc exec {container_name}"
        f" -- sudo --login --user {user}"
        f" -- bash -c '{shell_cmd}'"
    )

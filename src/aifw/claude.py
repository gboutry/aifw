"""Claude Code session management.

Handles launching Claude Code instances inside the mission container
via tmux windows. Each worker gets its own Claude Code session.

Claude state sharing:
  ~/.claude and ~/.claude.json are mounted from the host into the
  container at the paths defined in config. This gives all Claude
  instances access to global settings, memories, skills, and auth.

Multiple concurrent sessions are supported because Claude Code uses
per-session state files, and the global config is read-only.
"""

from __future__ import annotations

import logging
from pathlib import Path

from aifw.config import Config
from aifw.tmux import (
    create_worker_window,
    send_command,
    send_keys,
    window_exists,
)

logger = logging.getLogger("aifw")


def launch_orchestrator(
    config: Config,
    session_name: str,
    container_name: str,
    mission_ai_dir: str,
) -> None:
    """The orchestrator Claude Code session is created during
    tmux setup_control_plane. This function exists for re-launching."""
    from aifw.tmux import _lxc_exec_string

    if not window_exists(config, session_name, "orchestrator"):
        from aifw.tmux import create_window
        create_window(config, session_name, "orchestrator")

    cmd = _lxc_exec_string(
        container_name, config.lxd_container_user,
        cwd=mission_ai_dir,
        command=config.claude_bin,
    )
    send_command(config, session_name, "orchestrator", cmd)


def launch_worker_session(
    config: Config,
    session_name: str,
    container_name: str,
    worker_name: str,
    working_dir: str,
    initial_prompt: str | None = None,
) -> None:
    """Launch a Claude Code session for a worker in a tmux window.

    Args:
        config: Global config.
        session_name: tmux session name.
        container_name: LXD container name.
        worker_name: Name of the worker.
        working_dir: Directory to start Claude Code in.
        initial_prompt: Optional initial prompt to send to Claude Code.
    """
    window_name = f"w-{worker_name}"

    # Build claude args — use --print for non-interactive or just bare claude
    claude_args = ""
    create_worker_window(
        config, session_name, container_name, worker_name,
        cwd=working_dir,
        claude_args=claude_args,
    )

    # Give Claude Code a moment to start, then send the initial prompt
    if initial_prompt:
        # Send the prompt text to the Claude Code session
        # We escape any single quotes in the prompt
        _send_prompt_to_worker(config, session_name, worker_name, initial_prompt)


def send_prompt_to_worker(
    config: Config,
    session_name: str,
    worker_name: str,
    prompt: str,
) -> None:
    """Send a prompt to an existing worker's Claude Code session."""
    _send_prompt_to_worker(config, session_name, worker_name, prompt)


def _send_prompt_to_worker(
    config: Config,
    session_name: str,
    worker_name: str,
    prompt: str,
) -> None:
    """Send text to a worker's tmux pane.

    This types the prompt text into the Claude Code session.
    For long prompts, we use tmux's load-buffer/paste-buffer
    to avoid issues with special characters and length limits.
    """
    window_name = f"w-{worker_name}"

    if not window_exists(config, session_name, window_name):
        logger.warning("Worker window %s does not exist", window_name)
        return

    # For short prompts, send-keys works fine
    if len(prompt) < 200 and "\n" not in prompt:
        send_keys(config, session_name, window_name, prompt, enter=True)
        return

    # For longer prompts, write to a temp file and use tmux load-buffer
    import tempfile
    with tempfile.NamedTemporaryFile(mode="w", suffix=".txt", delete=False) as f:
        f.write(prompt)
        tmp_path = f.name

    try:
        from aifw.tmux import _run_tmux
        _run_tmux(config, ["load-buffer", tmp_path])
        _run_tmux(config, ["paste-buffer", "-t", f"{session_name}:{window_name}"])
        # Send Enter to submit
        send_keys(config, session_name, window_name, "", enter=True)
    finally:
        Path(tmp_path).unlink(missing_ok=True)


def build_worker_prompt(brief_path: str) -> str:
    """Build the initial prompt for a worker from its brief file."""
    return (
        f"Read your worker brief at {brief_path} and follow the instructions. "
        f"Begin by confirming you understand the assignment, then start working."
    )

"""Configuration loading and defaults.

All path assumptions, tool locations, and tunables are centralised here.
Configuration is loaded from (in priority order):
  1. Environment variables (AIFW_*)
  2. Config file (~/.config/aifw/config.toml)
  3. Built-in defaults
"""

from __future__ import annotations

import os
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def _home() -> Path:
    return Path.home()


# ---------------------------------------------------------------------------
# Default values
# ---------------------------------------------------------------------------

_DEFAULTS: dict[str, Any] = {
    # Mission storage
    "mission_root": str(_home() / ".local" / "share" / "aifw" / "missions"),
    # tmux
    "tmux_bin": "tmux",
    "tmux_session_prefix": "aifw",
    # LXD
    "lxd_base_image_alias": "worktainer-base",
    "lxd_base_container_script": "",  # path to base-container.sh; empty = use built-in adapter
    "lxd_bootstrap_script": "",  # path to work-it.sh; empty = use built-in adapter
    "lxd_container_prefix": "aifw",
    "lxd_container_user": "ubuntu",
    "lxd_container_uid": 1000,
    "lxd_apt_proxy": "",
    # Claude Code
    "claude_bin": "claude",
    "claude_config_host_path": str(_home() / ".claude"),
    "claude_auth_host_path": str(_home() / ".claude.json"),
    "claude_config_container_path": "/home/ubuntu/.claude",
    "claude_auth_container_path": "/home/ubuntu/.claude.json",
    "default_model": "",
    # Repos
    "repo_strategy": "checkout",  # "checkout" or "worktree"
    # Logging
    "log_level": "INFO",
    # Overview refresh interval (seconds)
    "overview_interval": 5,
}


# ---------------------------------------------------------------------------
# Config dataclass
# ---------------------------------------------------------------------------


@dataclass
class Config:
    """Fully resolved configuration for aifw."""

    mission_root: Path
    tmux_bin: str
    tmux_session_prefix: str
    lxd_base_image_alias: str
    lxd_base_container_script: str
    lxd_bootstrap_script: str
    lxd_container_prefix: str
    lxd_container_user: str
    lxd_container_uid: int
    lxd_apt_proxy: str
    claude_bin: str
    claude_config_host_path: Path
    claude_auth_host_path: Path
    claude_config_container_path: str
    claude_auth_container_path: str
    default_model: str
    repo_strategy: str
    log_level: str
    overview_interval: int

    # Derived paths
    config_file: Path = field(default_factory=lambda: _home() / ".config" / "aifw" / "config.toml")

    @property
    def container_home(self) -> str:
        return f"/home/{self.lxd_container_user}"


def _env_override(key: str) -> str | None:
    """Check for AIFW_<KEY> environment variable."""
    return os.environ.get(f"AIFW_{key.upper()}")


def load_config(config_path: Path | None = None) -> Config:
    """Load configuration from file and environment, with defaults."""
    file_values: dict[str, Any] = {}

    path = config_path or Path(_home() / ".config" / "aifw" / "config.toml")
    if path.exists():
        with open(path, "rb") as f:
            file_values = tomllib.load(f)

    resolved: dict[str, Any] = {}
    for key, default in _DEFAULTS.items():
        # Environment takes priority
        env_val = _env_override(key)
        if env_val is not None:
            resolved[key] = env_val
        elif key in file_values:
            resolved[key] = file_values[key]
        else:
            resolved[key] = default

    return Config(
        mission_root=Path(resolved["mission_root"]),
        tmux_bin=str(resolved["tmux_bin"]),
        tmux_session_prefix=str(resolved["tmux_session_prefix"]),
        lxd_base_image_alias=str(resolved["lxd_base_image_alias"]),
        lxd_base_container_script=str(resolved["lxd_base_container_script"]),
        lxd_bootstrap_script=str(resolved["lxd_bootstrap_script"]),
        lxd_container_prefix=str(resolved["lxd_container_prefix"]),
        lxd_container_user=str(resolved["lxd_container_user"]),
        lxd_container_uid=int(resolved["lxd_container_uid"]),
        lxd_apt_proxy=str(resolved["lxd_apt_proxy"]),
        claude_bin=str(resolved["claude_bin"]),
        claude_config_host_path=Path(resolved["claude_config_host_path"]),
        claude_auth_host_path=Path(resolved["claude_auth_host_path"]),
        claude_config_container_path=str(resolved["claude_config_container_path"]),
        claude_auth_container_path=str(resolved["claude_auth_container_path"]),
        default_model=str(resolved["default_model"]),
        repo_strategy=str(resolved["repo_strategy"]),
        log_level=str(resolved["log_level"]),
        overview_interval=int(resolved["overview_interval"]),
        config_file=path,
    )

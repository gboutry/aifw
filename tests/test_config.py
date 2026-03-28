"""Tests for aifw.config."""

from __future__ import annotations

import os
from pathlib import Path
from unittest import mock

import pytest

from aifw.config import Config, load_config


def test_load_config_defaults(tmp_path: Path) -> None:
    """Loading config with no file should produce sensible defaults."""
    config = load_config(tmp_path / "nonexistent.toml")
    assert isinstance(config, Config)
    assert config.tmux_bin == "tmux"
    assert config.lxd_base_image_alias == "worktainer-base"
    assert config.claude_bin == "claude"
    assert config.repo_strategy == "checkout"
    assert config.log_level == "INFO"
    assert config.lxd_container_prefix == "aifw"
    assert config.lxd_container_user == "ubuntu"
    assert config.overview_interval == 5


def test_load_config_from_file(tmp_path: Path) -> None:
    """Config file values should override defaults."""
    config_file = tmp_path / "config.toml"
    config_file.write_text("""\
tmux_bin = "/usr/local/bin/tmux"
lxd_base_image_alias = "my-custom-image"
log_level = "DEBUG"
overview_interval = 10
""")
    config = load_config(config_file)
    assert config.tmux_bin == "/usr/local/bin/tmux"
    assert config.lxd_base_image_alias == "my-custom-image"
    assert config.log_level == "DEBUG"
    assert config.overview_interval == 10
    # Defaults still apply for unset values
    assert config.claude_bin == "claude"


def test_env_override(tmp_path: Path) -> None:
    """Environment variables should take priority over file and defaults."""
    config_file = tmp_path / "config.toml"
    config_file.write_text('claude_bin = "file-claude"')

    with mock.patch.dict(os.environ, {"AIFW_CLAUDE_BIN": "env-claude"}):
        config = load_config(config_file)

    assert config.claude_bin == "env-claude"


def test_mission_root_is_path(tmp_path: Path) -> None:
    """mission_root should be a Path object."""
    config = load_config(tmp_path / "nonexistent.toml")
    assert isinstance(config.mission_root, Path)


def test_container_home(tmp_path: Path) -> None:
    config = load_config(tmp_path / "nonexistent.toml")
    assert config.container_home == "/home/ubuntu"

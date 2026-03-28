"""Tests for aifw.status."""

from __future__ import annotations

import json
from io import StringIO
from pathlib import Path
from unittest import mock

import pytest

from aifw.config import load_config
from aifw.mission import Mission
from aifw.status import show_status, run_doctor


def _make_config(tmp_path: Path):
    config = load_config(tmp_path / "nonexistent.toml")
    object.__setattr__(config, "mission_root", tmp_path / "missions")
    return config


@mock.patch("aifw.lxd.get_container_info", return_value=None)
@mock.patch("aifw.tmux.session_exists", return_value=False)
def test_show_status_no_mission(mock_session, mock_container, tmp_path: Path, capsys) -> None:
    config = _make_config(tmp_path)
    show_status(config)
    captured = capsys.readouterr()
    assert "No active mission" in captured.out


@mock.patch("aifw.lxd.get_container_info", return_value=None)
@mock.patch("aifw.tmux.session_exists", return_value=False)
@mock.patch("aifw.tmux.list_windows", return_value=[])
def test_show_status_with_mission(mock_windows, mock_session, mock_container, tmp_path: Path, capsys) -> None:
    config = _make_config(tmp_path)
    mission = Mission("test-s01", config)
    mission.init_directory(["/tmp/repo-a"])

    show_status(config, "test-s01")
    captured = capsys.readouterr()
    assert "test-s01" in captured.out
    assert "repo-a" in captured.out


def test_run_doctor(tmp_path: Path, capsys) -> None:
    config = _make_config(tmp_path)
    # doctor should run without crashing even with missing tools
    run_doctor(config)
    captured = capsys.readouterr()
    assert "doctor" in captured.out
    assert "tmux" in captured.out

"""Mission lifecycle management.

A mission is the top-level unit of work in aifw. It owns:
  - A unique ID and directory under mission_root
  - A set of repository bindings
  - A single LXD container
  - A tmux session
  - A file-based coordination space (.ai/)

Mission directory layout:
  ~/.local/share/aifw/missions/<mission-id>/
  ├── control/
  │   └── mission.toml          # mission metadata
  ├── repos/                    # symlinks to actual repo paths
  ├── logs/
  │   ├── aifw.log
  │   └── workers/
  ├── runtime/
  │   ├── tmux-session          # tmux session name
  │   └── container-name        # LXD container name
  └── .ai/
      ├── spec.md
      ├── architecture.md
      ├── task-board.yaml
      ├── workers/
      ├── status/
      ├── handoffs/
      ├── contracts/
      └── events.log
"""

from __future__ import annotations

import json
import secrets
import string
from datetime import datetime, timezone
from pathlib import Path

from aifw.config import Config
from aifw.events import CONTAINER, MISSION, EventLog
from aifw.lxd import DiskMount, create_container, destroy_container, stop_container


# ---------------------------------------------------------------------------
# Mission ID generation
# ---------------------------------------------------------------------------


def generate_mission_id() -> str:
    """Generate a human-friendly mission ID: YYYYMMDD-<4 random chars>."""
    date_part = datetime.now(timezone.utc).strftime("%Y%m%d")
    rand_part = "".join(secrets.choice(string.ascii_lowercase + string.digits) for _ in range(4))
    return f"{date_part}-{rand_part}"


# ---------------------------------------------------------------------------
# Mission data
# ---------------------------------------------------------------------------


class Mission:
    """Represents a single mission and its on-disk state."""

    def __init__(self, mission_id: str, config: Config) -> None:
        self.mission_id = mission_id
        self.config = config
        self.root = config.mission_root / mission_id
        self.events: EventLog | None = None

    # --- Derived paths ---

    @property
    def control_dir(self) -> Path:
        return self.root / "control"

    @property
    def repos_dir(self) -> Path:
        return self.root / "repos"

    @property
    def logs_dir(self) -> Path:
        return self.root / "logs"

    @property
    def worker_logs_dir(self) -> Path:
        return self.root / "logs" / "workers"

    @property
    def runtime_dir(self) -> Path:
        return self.root / "runtime"

    @property
    def ai_dir(self) -> Path:
        return self.root / ".ai"

    @property
    def container_name(self) -> str:
        return f"{self.config.lxd_container_prefix}-{self.mission_id}"

    @property
    def tmux_session(self) -> str:
        return f"{self.config.tmux_session_prefix}-{self.mission_id}"

    @property
    def mission_toml_path(self) -> Path:
        return self.control_dir / "mission.toml"

    # --- Directory creation ---

    def init_directory(self, repo_paths: list[str]) -> None:
        """Create the full mission directory tree."""
        for d in [
            self.control_dir,
            self.repos_dir,
            self.logs_dir,
            self.worker_logs_dir,
            self.runtime_dir,
            self.ai_dir,
            self.ai_dir / "workers",
            self.ai_dir / "status",
            self.ai_dir / "handoffs",
            self.ai_dir / "contracts",
        ]:
            d.mkdir(parents=True, exist_ok=True)

        # Init event log
        self.events = EventLog(
            events_path=self.ai_dir / "events.log",
            aifw_log_path=self.logs_dir / "aifw.log",
        )

        # Write mission metadata
        self._write_mission_toml(repo_paths)

        # Create initial .ai files
        self._init_ai_files(repo_paths)

        # Place CLAUDE.md files for orchestrator and workers
        self._place_claude_md_files(repo_paths)

        # Create repo symlinks
        for rp in repo_paths:
            p = Path(rp).resolve()
            link = self.repos_dir / p.name
            if not link.exists():
                link.symlink_to(p)

        # Write runtime markers
        (self.runtime_dir / "tmux-session").write_text(self.tmux_session)
        (self.runtime_dir / "container-name").write_text(self.container_name)

        self.events.log(MISSION, "aifw", f"Mission {self.mission_id} initialised with repos: {', '.join(repo_paths)}")

    def _write_mission_toml(self, repo_paths: list[str]) -> None:
        ts = datetime.now(timezone.utc).isoformat()
        repos_toml = "\n".join(f'  "{rp}",' for rp in repo_paths)
        content = f"""\
# aifw mission metadata
# Generated: {ts}

mission_id = "{self.mission_id}"
created = "{ts}"
state = "active"
container = "{self.container_name}"
tmux_session = "{self.tmux_session}"

repos = [
{repos_toml}
]
"""
        self.mission_toml_path.write_text(content)

    def _init_ai_files(self, repo_paths: list[str]) -> None:
        repo_names = [Path(rp).name for rp in repo_paths]

        # spec.md
        (self.ai_dir / "spec.md").write_text(f"""\
# Mission Specification

**Mission ID**: {self.mission_id}
**Created**: {datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")}
**Repositories**: {', '.join(repo_names)}

## Objective

_Define the mission objective here._

## Scope

_Define what is in and out of scope._

## Success Criteria

_Define how to know when the mission is complete._
""")

        # architecture.md
        (self.ai_dir / "architecture.md").write_text(f"""\
# Architecture Notes

**Mission**: {self.mission_id}

## Repository Map

{chr(10).join(f'- **{name}**: _describe role_' for name in repo_names)}

## Key Interfaces

_Document cross-repo interfaces and contracts here._

## Dependencies

_Document dependency ordering here._
""")

        # task-board.yaml
        (self.ai_dir / "task-board.yaml").write_text(f"""\
# Task Board — Mission {self.mission_id}
# Status values: pending, in_progress, done, blocked
# Updated by orchestrator; workers update their own status files

tasks: []

# Example:
# tasks:
#   - id: task-001
#     title: "Implement API endpoint"
#     worker: worker-1
#     repo: my-api
#     status: pending
#     depends_on: []
#     notes: ""
""")

    def _place_claude_md_files(self, repo_paths: list[str]) -> None:
        """Place CLAUDE.md files so orchestrator and workers get their skills."""
        templates_dir = Path(__file__).parent.parent.parent / "templates"
        repo_names = [Path(rp).name for rp in repo_paths]
        repo_list = "\n".join(f"- **{Path(rp).name}**: `{rp}`" for rp in repo_paths)

        # Orchestrator CLAUDE.md goes in .ai/ (where orchestrator Claude starts)
        orch_template = templates_dir / "orchestrator-CLAUDE.md"
        if orch_template.exists():
            content = orch_template.read_text()
            content = content.replace("${mission_id}", self.mission_id)
            content = content.replace("${repo_list}", repo_list)
            (self.ai_dir / "CLAUDE.md").write_text(content)

        # Worker CLAUDE.md goes in each repo dir
        worker_template = templates_dir / "worker-CLAUDE.md"
        if worker_template.exists():
            worker_content = worker_template.read_text()
            worker_content = worker_content.replace("${mission_id}", self.mission_id)
            for rp in repo_paths:
                repo_dir = Path(rp)
                if not repo_dir.is_dir():
                    continue
                claude_md = repo_dir / "CLAUDE.md"
                # Don't overwrite existing CLAUDE.md files in repos
                if not claude_md.exists():
                    claude_md.write_text(worker_content)

    # --- Event log access ---

    def ensure_events(self) -> EventLog:
        if self.events is None:
            self.events = EventLog(
                events_path=self.ai_dir / "events.log",
                aifw_log_path=self.logs_dir / "aifw.log",
            )
        return self.events

    # --- Container lifecycle ---

    def build_mounts(self, repo_paths: list[str]) -> list[DiskMount]:
        """Build the list of disk mounts for the container."""
        mounts: list[DiskMount] = []

        # Mount the mission directory
        mounts.append(DiskMount(
            name="mission",
            source=str(self.root),
            path=str(self.root),
        ))

        # Mount each repo
        for rp in repo_paths:
            p = Path(rp).resolve()
            mounts.append(DiskMount(
                name=f"repo-{p.name}",
                source=str(p),
                path=str(p),  # same path in container (per user's requirement)
            ))

        # Claude state mounts — mapped to /home/ubuntu/ in the container
        # so Claude Code (running as ubuntu) finds ~/.claude correctly.
        mounts.append(DiskMount(
            name="claude-config",
            source=str(self.config.claude_config_host_path),
            path=self.config.claude_config_container_path,
        ))
        if self.config.claude_auth_host_path.exists():
            mounts.append(DiskMount(
                name="claude-auth",
                source=str(self.config.claude_auth_host_path),
                path=self.config.claude_auth_container_path,
            ))

        return mounts

    def provision_container(self, repo_paths: list[str]) -> None:
        """Create and start the mission container."""
        mounts = self.build_mounts(repo_paths)
        create_container(self.container_name, self.config, mounts)
        self.ensure_events().log(CONTAINER, "aifw", f"Container {self.container_name} provisioned")

    def stop(self) -> None:
        stop_container(self.container_name)
        self.ensure_events().log(CONTAINER, "aifw", f"Container {self.container_name} stopped")

    def destroy(self) -> None:
        destroy_container(self.container_name)
        self.ensure_events().log(CONTAINER, "aifw", f"Container {self.container_name} destroyed")

    # --- Persistence helpers ---

    def exists(self) -> bool:
        return self.root.exists()

    def is_active(self) -> bool:
        """Check if the mission is still active (has a running container)."""
        from aifw.lxd import container_status
        return container_status(self.container_name) == "RUNNING"

    def repo_paths(self) -> list[str]:
        """Read repo paths from mission.toml."""
        if not self.mission_toml_path.exists():
            return []
        import tomllib
        with open(self.mission_toml_path, "rb") as f:
            data = tomllib.load(f)
        return data.get("repos", [])

    def worker_names(self) -> list[str]:
        """List existing worker names from .ai/workers/."""
        workers_dir = self.ai_dir / "workers"
        if not workers_dir.exists():
            return []
        return sorted(p.stem for p in workers_dir.glob("*.md"))

    def read_worker_status(self, worker_name: str) -> dict | None:
        """Read a worker's status JSON."""
        status_file = self.ai_dir / "status" / f"{worker_name}.json"
        if not status_file.exists():
            return None
        try:
            return json.loads(status_file.read_text())
        except json.JSONDecodeError:
            return None


# ---------------------------------------------------------------------------
# Mission discovery
# ---------------------------------------------------------------------------


def find_current_mission(config: Config) -> Mission | None:
    """Find the most recently created active mission."""
    if not config.mission_root.exists():
        return None
    missions = sorted(config.mission_root.iterdir(), reverse=True)
    for d in missions:
        if d.is_dir() and (d / "control" / "mission.toml").exists():
            m = Mission(d.name, config)
            return m
    return None


def list_missions(config: Config) -> list[Mission]:
    """List all missions."""
    if not config.mission_root.exists():
        return []
    result = []
    for d in sorted(config.mission_root.iterdir(), reverse=True):
        if d.is_dir() and (d / "control" / "mission.toml").exists():
            result.append(Mission(d.name, config))
    return result

"""Status display and health checking.

Provides:
  - `aifw status` — full mission overview
  - `aifw doctor` — environment health checks
  - `aifw tail <worker>` — stream worker status/events
"""

from __future__ import annotations

import json
import shutil
import subprocess
import sys
from pathlib import Path

from aifw.config import Config
from aifw.lxd import base_image_exists, get_container_info
from aifw.mission import Mission, find_current_mission
from aifw.workers import list_workers


# ---------------------------------------------------------------------------
# Status display
# ---------------------------------------------------------------------------


def show_status(config: Config, mission_id: str | None = None) -> None:
    """Print a formatted status overview."""
    if mission_id:
        mission = Mission(mission_id, config)
    else:
        mission = find_current_mission(config)

    if mission is None or not mission.exists():
        print("No active mission found.")
        return

    out = sys.stdout

    # Header
    out.write(f"\n{'─' * 60}\n")
    out.write(f"  MISSION: {mission.mission_id}\n")
    out.write(f"{'─' * 60}\n\n")

    # Container
    info = get_container_info(mission.container_name)
    if info:
        status_icon = "●" if info.status == "RUNNING" else "○"
        ip_str = f" ({info.ipv4})" if info.ipv4 else ""
        out.write(f"  Container:  {status_icon} {info.name} [{info.status}]{ip_str}\n")
    else:
        out.write(f"  Container:  ✗ {mission.container_name} [NOT FOUND]\n")

    # tmux
    from aifw.tmux import session_exists, list_windows
    tmux_ok = session_exists(config, mission.tmux_session)
    out.write(f"  tmux:       {'●' if tmux_ok else '○'} {mission.tmux_session}")
    if tmux_ok:
        windows = list_windows(config, mission.tmux_session)
        out.write(f"  [{len(windows)} windows]")
    out.write("\n")

    # Repos
    clones = mission.clone_paths()
    origins = mission.repo_paths()
    out.write(f"\n  Repositories ({len(origins)}):\n")
    if clones:
        from aifw.git import repo_status
        for name, clone_path in clones.items():
            try:
                rs = repo_status(clone_path)
                dirty_mark = " [dirty]" if rs.dirty else ""
                unpushed_mark = f" [{len(rs.unpushed)} unpushed]" if rs.unpushed else ""
                out.write(f"    {rs.branch:<12s} {name:<20s}{dirty_mark}{unpushed_mark}\n")
            except Exception:
                out.write(f"    ?            {name:<20s} (git error)\n")
    else:
        for rp in origins:
            name = Path(rp).name
            out.write(f"    -            {name:<20s} (not cloned)\n")

    # Workers
    workers = list_workers(mission)
    out.write(f"\n  Workers ({len(workers)}):\n")
    if not workers:
        out.write("    (none assigned)\n")
    else:
        for w in workers:
            status = w.get("status", "unknown")
            icon = {
                "ready": "◯",
                "in_progress": "●",
                "done": "✓",
                "blocked": "⊘",
                "error": "✗",
            }.get(status, "?")
            name = w.get("worker", "?")
            summary = w.get("summary", "")
            repo = Path(w.get("repo", "")).name if w.get("repo") else ""
            model = w.get("model", "")
            model_str = f"({model}) " if model else ""
            out.write(f"    {icon} {name:<16s} [{status:<12s}] {model_str}{repo:<20s} {summary}\n")

    # Recent events
    events = mission.ensure_events()
    recent = events.read_recent(8)
    if recent:
        out.write(f"\n  Recent Events:\n")
        for line in recent:
            out.write(f"    {line}\n")

    out.write(f"\n{'─' * 60}\n")


# ---------------------------------------------------------------------------
# Tail worker
# ---------------------------------------------------------------------------


def tail_worker(config: Config, worker_name: str, mission_id: str | None = None) -> None:
    """Stream a worker's status and recent events."""
    if mission_id:
        mission = Mission(mission_id, config)
    else:
        mission = find_current_mission(config)

    if mission is None or not mission.exists():
        print("No active mission found.", file=sys.stderr)
        sys.exit(1)

    status_path = mission.ai_dir / "status" / f"{worker_name}.json"
    events_path = mission.ai_dir / "events.log"
    brief_path = mission.ai_dir / "workers" / f"{worker_name}.md"
    handoff_path = mission.ai_dir / "handoffs" / f"{worker_name}.md"

    print(f"=== Worker: {worker_name} ===\n")

    # Show current status
    if status_path.exists():
        try:
            data = json.loads(status_path.read_text())
            print(f"Status:  {data.get('status', 'unknown')}")
            print(f"Summary: {data.get('summary', 'N/A')}")
            print(f"Updated: {data.get('updated', 'N/A')}")
            blockers = data.get("blockers", [])
            if blockers:
                print(f"Blockers: {', '.join(blockers)}")
        except json.JSONDecodeError:
            print(f"Status file corrupt: {status_path}")
    else:
        print("No status file yet.")

    # Show brief
    if brief_path.exists():
        print(f"\n--- Brief ({brief_path}) ---")
        print(brief_path.read_text()[:500])
        if len(brief_path.read_text()) > 500:
            print("... (truncated)")

    # Show handoff if present
    if handoff_path.exists():
        print(f"\n--- Handoff ({handoff_path}) ---")
        print(handoff_path.read_text())

    # Show recent events for this worker
    print(f"\n--- Recent Events ---")
    if events_path.exists():
        lines = events_path.read_text().splitlines()
        worker_events = [l for l in lines if worker_name in l]
        for line in worker_events[-10:]:
            print(f"  {line}")
        if not worker_events:
            print("  (no events for this worker)")
    else:
        print("  (no events log)")


# ---------------------------------------------------------------------------
# Doctor
# ---------------------------------------------------------------------------


def run_doctor(config: Config) -> None:
    """Run environment health checks."""
    checks: list[tuple[str, bool, str]] = []

    # tmux
    tmux_path = shutil.which(config.tmux_bin)
    checks.append(("tmux", tmux_path is not None, tmux_path or "not found"))

    # lxc
    lxc_path = shutil.which("lxc")
    checks.append(("lxc client", lxc_path is not None, lxc_path or "not found"))

    # LXD connectivity
    if lxc_path:
        try:
            result = subprocess.run(
                ["lxc", "version"], capture_output=True, text=True, timeout=10,
            )
            checks.append(("LXD server", result.returncode == 0, result.stdout.strip() or "error"))
        except Exception as e:
            checks.append(("LXD server", False, str(e)))
    else:
        checks.append(("LXD server", False, "lxc not found"))

    # Base image
    if lxc_path:
        img_ok = base_image_exists(config.lxd_base_image_alias)
        checks.append(("base image", img_ok, config.lxd_base_image_alias))

    # Claude state
    checks.append((
        "Claude config",
        config.claude_config_host_path.exists(),
        str(config.claude_config_host_path),
    ))
    checks.append((
        "Claude auth",
        config.claude_auth_host_path.exists(),
        str(config.claude_auth_host_path),
    ))

    # Claude binary in PATH (on host, for reference)
    claude_path = shutil.which(config.claude_bin)
    checks.append(("Claude Code (host)", claude_path is not None, claude_path or "not in host PATH (OK if only in container)"))

    # Mission root
    checks.append((
        "mission root",
        config.mission_root.parent.exists(),
        str(config.mission_root),
    ))

    # Config file
    checks.append((
        "config file",
        config.config_file.exists(),
        str(config.config_file) + (" (exists)" if config.config_file.exists() else " (using defaults)"),
    ))

    # Bootstrap script
    if config.lxd_base_container_script:
        checks.append((
            "base container script",
            Path(config.lxd_base_container_script).exists(),
            config.lxd_base_container_script,
        ))

    # Print results
    print(f"\n{'─' * 50}")
    print("  aifw doctor")
    print(f"{'─' * 50}\n")

    all_ok = True
    for name, ok, detail in checks:
        icon = "✓" if ok else "✗"
        print(f"  {icon} {name:<22s} {detail}")
        if not ok:
            all_ok = False

    print(f"\n{'─' * 50}")
    if all_ok:
        print("  All checks passed.")
    else:
        print("  Some checks failed. Review above.")
    print(f"{'─' * 50}\n")

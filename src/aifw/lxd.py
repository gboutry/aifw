"""LXD adapter for container lifecycle management.

This module wraps `lxc` CLI commands to manage a single mission container.
It mirrors the logic of the user's existing work-it.sh but supports:
  - Multiple disk device mounts (repos + mission dir + Claude state)
  - Non-interactive operation
  - Configurable base image and bootstrap script fallback

If `lxd_bootstrap_script` is set in config, that script is called instead
of the built-in adapter logic. This is the escape hatch for custom setups.
"""

from __future__ import annotations

import json
import logging
import subprocess
from dataclasses import dataclass
from pathlib import Path

from aifw.config import Config

logger = logging.getLogger("aifw")


class LXDError(Exception):
    """Raised when an LXD operation fails."""


@dataclass
class DiskMount:
    """A disk device to mount into the container."""

    name: str
    source: str  # host path
    path: str  # container path


@dataclass
class ContainerInfo:
    """Snapshot of container state."""

    name: str
    status: str  # RUNNING, STOPPED, etc.
    ipv4: str | None = None


# ---------------------------------------------------------------------------
# Low-level lxc wrappers
# ---------------------------------------------------------------------------


def _run(
    args: list[str],
    *,
    check: bool = True,
    capture: bool = True,
    timeout: int = 300,
) -> subprocess.CompletedProcess[str]:
    """Run an lxc command."""
    logger.debug("lxc %s", " ".join(args))
    try:
        return subprocess.run(
            ["lxc", *args],
            check=check,
            capture_output=capture,
            text=True,
            timeout=timeout,
        )
    except subprocess.CalledProcessError as exc:
        raise LXDError(
            f"lxc {' '.join(args)} failed (rc={exc.returncode}): {exc.stderr}"
        ) from exc
    except subprocess.TimeoutExpired as exc:
        raise LXDError(f"lxc {' '.join(args)} timed out after {timeout}s") from exc


def container_exists(name: str) -> bool:
    result = _run(["info", name], check=False)
    return result.returncode == 0


def container_status(name: str) -> str | None:
    """Return container status string or None if it doesn't exist."""
    if not container_exists(name):
        return None
    result = _run(["info", name])
    for line in result.stdout.splitlines():
        if line.startswith("Status:"):
            return line.split(":", 1)[1].strip().upper()
    return None


def container_ipv4(name: str) -> str | None:
    """Get the container's IPv4 address on eth0."""
    try:
        result = _run(["list", "--format", "json", name])
        data = json.loads(result.stdout)
        if not data:
            return None
        network = data[0].get("state", {}).get("network", {})
        eth0 = network.get("eth0", {})
        for addr in eth0.get("addresses", []):
            if addr.get("family") == "inet":
                return addr.get("address")
    except (LXDError, json.JSONDecodeError, KeyError, IndexError):
        pass
    return None


def get_container_info(name: str) -> ContainerInfo | None:
    """Get a snapshot of container state."""
    status = container_status(name)
    if status is None:
        return None
    return ContainerInfo(
        name=name,
        status=status,
        ipv4=container_ipv4(name) if status == "RUNNING" else None,
    )


# ---------------------------------------------------------------------------
# Image management
# ---------------------------------------------------------------------------


def base_image_exists(alias: str) -> bool:
    result = _run(["image", "alias", "list", "--format", "csv"], check=False)
    if result.returncode != 0:
        return False
    for line in result.stdout.splitlines():
        fields = line.split(",")
        if fields and fields[0].strip() == alias:
            return True
    return False


_BUNDLED_BASE_SCRIPT = Path(__file__).parent.parent.parent / "scripts" / "base-container.sh"


def build_base_image(config: Config) -> None:
    """Build the base image using the configured or bundled script."""
    script = config.lxd_base_container_script
    if not script:
        if _BUNDLED_BASE_SCRIPT.exists():
            script = str(_BUNDLED_BASE_SCRIPT)
        else:
            raise LXDError(
                "No base image found and lxd_base_container_script is not configured. "
                "Either build the base image manually or set the config."
            )
    logger.info("Building base image using %s ...", script)
    try:
        subprocess.run(
            ["bash", script],
            check=True,
            env={
                **dict(__import__("os").environ),
                "PUBLISHED_NAME": config.lxd_base_image_alias,
                **({"APT_PROXY": config.lxd_apt_proxy} if config.lxd_apt_proxy else {}),
            },
            timeout=600,
        )
    except subprocess.CalledProcessError as exc:
        raise LXDError(f"Base image build failed: {exc}") from exc


# ---------------------------------------------------------------------------
# Container lifecycle
# ---------------------------------------------------------------------------


def create_container(
    name: str,
    config: Config,
    mounts: list[DiskMount],
) -> None:
    """Create and start a container with the given mounts.

    This mirrors work-it.sh logic:
      1. Init from base image
      2. Set UID mapping
      3. Add disk devices
      4. Start
      5. Wait for cloud-init
    """
    if container_exists(name):
        status = container_status(name)
        if status == "RUNNING":
            logger.info("Container %s already running", name)
            return
        if status == "STOPPED":
            logger.info("Starting stopped container %s", name)
            _run(["start", name])
            _wait_cloud_init(name)
            return
        raise LXDError(f"Container {name} in unexpected state: {status}")

    # Ensure base image exists
    if not base_image_exists(config.lxd_base_image_alias):
        build_base_image(config)

    logger.info("Creating container %s from %s", name, config.lxd_base_image_alias)

    # Init
    _run(["init", config.lxd_base_image_alias, name])

    # UID mapping
    host_uid = __import__("os").getuid()
    _run(["config", "set", name, "raw.idmap", f"both {host_uid} {config.lxd_container_uid}"])

    # Add disk mounts
    for mount in mounts:
        _run([
            "config", "device", "add", name, mount.name, "disk",
            f"source={mount.source}",
            f"path={mount.path}",
        ])

    # Start
    _run(["start", name])
    _wait_cloud_init(name)

    logger.info("Container %s is running", name)


def _wait_cloud_init(name: str, timeout: int = 300) -> None:
    """Wait for cloud-init to finish inside the container."""
    logger.info("Waiting for cloud-init in %s ...", name)
    result = _run(
        ["exec", name, "--", "cloud-init", "status", "--wait"],
        check=False,
        timeout=timeout,
    )
    if result.returncode != 0:
        logger.warning("cloud-init may not have completed cleanly: %s", result.stderr)


def stop_container(name: str) -> None:
    """Stop a running container."""
    status = container_status(name)
    if status is None:
        logger.info("Container %s does not exist", name)
        return
    if status == "STOPPED":
        logger.info("Container %s already stopped", name)
        return
    logger.info("Stopping container %s", name)
    _run(["stop", name])


def destroy_container(name: str) -> None:
    """Stop and delete a container."""
    if not container_exists(name):
        logger.info("Container %s does not exist, nothing to destroy", name)
        return
    status = container_status(name)
    if status == "RUNNING":
        _run(["stop", name, "--force"])
    logger.info("Deleting container %s", name)
    _run(["delete", name])


# ---------------------------------------------------------------------------
# Exec into container
# ---------------------------------------------------------------------------


def exec_command(
    container_name: str,
    command: list[str],
    *,
    user: str = "ubuntu",
    cwd: str | None = None,
    capture: bool = True,
    timeout: int = 120,
) -> subprocess.CompletedProcess[str]:
    """Run a command inside the container as the given user."""
    shell_cmd = " ".join(command)
    if cwd:
        shell_cmd = f"cd {cwd} && {shell_cmd}"

    return _run(
        [
            "exec", container_name,
            "--", "sudo", "--login", "--user", user,
            "--", "bash", "-c", shell_cmd,
        ],
        capture=capture,
        timeout=timeout,
    )


def exec_command_string(
    container_name: str,
    user: str = "ubuntu",
    cwd: str | None = None,
    command: str = "bash -l",
) -> list[str]:
    """Return the full lxc exec command as a list (for tmux send-keys)."""
    shell_cmd = command
    if cwd:
        shell_cmd = f"cd {cwd} && {command}"

    return [
        "lxc", "exec", container_name,
        "--", "sudo", "--login", "--user", user,
        "--", "bash", "-c", shell_cmd,
    ]

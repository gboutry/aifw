# LXD Integration Guide

## How aifw uses LXD

`aifw` creates one LXD container per mission. The container:
- Is initialised from a pre-built base image (`worktainer-base` by default)
- Has UID mapping (`raw.idmap`) so host user files are accessible
- Has disk devices for repos, mission directory, and Claude state
- Runs multiple Claude Code sessions via `lxc exec`

## Plugging In Your Existing Scripts

### Base image (base-container.sh)

Your `base-container.sh` builds a base image with:
- Ubuntu 24.04
- cloud-init configuration
- Claude Code (via npm)
- uv package manager

To use it with aifw:

```toml
# ~/.config/aifw/config.toml
lxd_base_container_script = "/path/to/base-container.sh"
lxd_base_image_alias = "worktainer-base"
```

When `aifw start` runs and the base image doesn't exist, it will call your script with `PUBLISHED_NAME=worktainer-base` in the environment.

### What aifw does instead of work-it.sh

Your `work-it.sh` creates a container, mounts one workdir, mounts Claude state, and shells in. `aifw` does the same thing but differently:

| work-it.sh | aifw |
|---|---|
| Single workdir mount | Multiple repo mounts + mission dir mount |
| Interactive (`exec bash`) | Non-interactive (tmux manages sessions) |
| Container named after directory | Container named `aifw-<mission-id>` |
| Mounts `~/.claude` and `~/.claude.json` | Same, but paths are configurable |
| `raw.idmap both <uid> 1000` | Same |
| Waits for cloud-init | Same |

### Using work-it.sh directly (advanced)

If you prefer to use `work-it.sh` to create the container:

1. Create the container manually:
   ```bash
   ./work-it.sh /path/to/mission/dir
   ```

2. Add additional mounts for repos:
   ```bash
   lxc config device add <container> repo-api disk \
     source=/home/user/repos/api path=/home/user/repos/api
   ```

3. Then use `aifw` with `--no-attach` and reference the existing container.

Note: this is an escape hatch, not the recommended flow.

## Mount Configuration

### Default mounts created by aifw

| Device name | Source (host) | Path (container) |
|---|---|---|
| `mission` | `~/.local/share/aifw/missions/<id>/` | Same path |
| `repo-<name>` | Each repo path | Same path |
| `claude-config` | `~/.claude` | `/home/ubuntu/.claude` |
| `claude-auth` | `~/.claude.json` | `/home/ubuntu/.claude.json` |

### Path identity

Repo and mission mounts use the **same absolute path** in host and container. This is required because Claude Code resolves project-scoped state (`.claude/` directories, project memories) using the absolute path of the working directory.

Claude global state (`~/.claude`, `~/.claude.json`) is mounted at `/home/ubuntu/` in the container because Claude Code runs as the `ubuntu` user and resolves `~` to `/home/ubuntu`.

### Customising mount paths

```toml
# ~/.config/aifw/config.toml
claude_config_host_path = "/home/myuser/.claude"
claude_auth_host_path = "/home/myuser/.claude.json"
claude_config_container_path = "/home/ubuntu/.claude"
claude_auth_container_path = "/home/ubuntu/.claude.json"
```

## Container Lifecycle

```
aifw start   → lxc init + config + device add + start + cloud-init wait
aifw stop    → lxc stop
aifw destroy → lxc stop --force + lxc delete
```

### Observing container state

```bash
# From host
lxc info aifw-20260327-a1b2
lxc list aifw-

# From inside the container (integration window)
whoami  # ubuntu
mount   # see all mounted filesystems
ls ~/.claude  # verify Claude state is accessible
```

### Debugging container issues

```bash
# Check cloud-init logs
lxc exec aifw-<id> -- cat /var/log/cloud-init-output.log

# Check if Claude Code is installed
lxc exec aifw-<id> -- which claude

# Check UID mapping
lxc exec aifw-<id> -- ls -la /home/ubuntu/

# Check disk mounts
lxc config device list aifw-<id>
lxc config device show aifw-<id>
```

## Multiple Claude Code Sessions

Multiple `lxc exec ... -- claude` commands create independent Claude Code processes inside the same container. This works because:

1. Each Claude Code instance uses a separate tty (allocated by `lxc exec`)
2. Claude's global config (`~/.claude`) is read-only for most operations
3. Per-session state is isolated by default

If you encounter resource issues with many concurrent sessions, consider adjusting the container's resource limits:

```bash
lxc config set aifw-<id> limits.cpu 4
lxc config set aifw-<id> limits.memory 8GB
```

## Base Image Requirements

The base image must have:
- A user named `ubuntu` with UID 1000
- `sudo` configured for passwordless access
- Claude Code installed (`npm install -g @anthropic-ai/claude-code`)
- `cloud-init` support (for initial boot wait)
- `bash`

Optional but recommended:
- `git`
- `curl`
- `jq`
- Your language toolchains (Python/uv, Go, Node, etc.)

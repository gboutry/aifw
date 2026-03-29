# Design: Local Clone Repo Strategy

## Problem

Today, `aifw start` mounts original repo paths directly into the container. This means:
- Two missions referencing the same repo fight over the same working tree
- Parallel missions are not safe
- There is no isolation between mission work and the user's own repo state

## Solution

Replace direct repo mounts with local git clones. Each mission gets its own independent copy of every repo, cloned into `missions/<id>/repos/<name>/`. The clone's `origin` remote points to the original repo via file path, enabling push/pull to sync changes.

## Design

### Cloning during `aifw start`

When `aifw start ~/repos/api ~/repos/frontend` is called:

1. Create the mission directory as today.
2. For each repo path, run `git clone --local <original-path> missions/<id>/repos/<name>`.
   - `--local` uses hardlinks for objects on the same filesystem — fast and space-efficient.
   - `origin` is automatically set to the original file path.
3. `missions/<id>/repos/` contains real cloned repos, not symlinks.
4. `mission.toml` records both original paths (for reference) and clone paths (working copies).

### Mount simplification

`build_mounts()` drops all per-repo disk devices. Only these mounts remain:

| Device | Source (host) | Path (container) |
|--------|---------------|-------------------|
| `mission` | `missions/<id>/` | Same absolute path |
| `claude-config` | `~/.claude` | `/home/ubuntu/.claude` |
| `claude-auth` | `~/.claude.json` | `/home/ubuntu/.claude.json` |

Repos are accessible inside the container via the mission mount since the clones live under the mission directory.

### Destroy safety

When `aifw destroy` is called:

1. For each repo clone in `missions/<id>/repos/`:
   - Check for uncommitted changes: `git status --porcelain`
   - Check for unpushed commits: for each local branch, `git log origin/<branch>..<branch> --oneline`
2. If any clone has uncommitted changes or unpushed commits, print a summary and refuse to destroy.
3. `--force` / `-f` overrides the check.
4. `--keep-files` still works (skips directory removal, still kills container/tmux).

Example refusal output:
```
Cannot destroy mission 20260328-a1b2: unpushed work found

  api-server:
    2 unpushed commits on main
    Uncommitted changes (3 files)

  frontend:
    clean

Use --force to destroy anyway.
```

### Module changes

**New module: `git.py`**

Thin wrapper around git CLI operations:

- `clone_local(source: str, dest: str) -> None` — runs `git clone --local`
- `has_unpushed(repo_path: str) -> list[str]` — returns branches with unpushed commits
- `has_uncommitted(repo_path: str) -> bool` — returns True if working tree is dirty
- `repo_status(repo_path: str) -> RepoStatus` — returns a dataclass with branch name, dirty flag, and list of unpushed branches

All operations use `subprocess.run(["git", ...])`. Same pattern as `lxd.py`.

**`mission.py`**

- `init_directory()` calls `_clone_repos()` instead of creating symlinks.
- `_clone_repos()` runs `clone_local()` for each repo.
- `build_mounts()` drops per-repo mounts.
- New method `check_unpushed() -> dict[str, RepoStatus]` returns status for all cloned repos.
- `mission.toml` gains a `[repos]` table mapping clone name to original path.

**`cli.py`**

- `cmd_destroy()` calls `mission.check_unpushed()` before destroying. Prints summary and exits unless `--force` is passed.

**`tmux.py`**

- `setup_control_plane()` points git/integration windows to clone paths under the mission dir.

**`workers.py` / `dispatch.py`**

- Worker `cwd` becomes `missions/<id>/repos/<name>/`.
- Brief template `$repo_path` points to the clone.

**`status.py`**

- `show_status()` includes per-repo git info: current branch, clean/dirty, unpushed commit count.

### What does not change

- LXD container lifecycle (one per mission)
- tmux layout (windows, dispatch watcher)
- Claude state mounting
- Worker brief format and coordination model
- Event logging

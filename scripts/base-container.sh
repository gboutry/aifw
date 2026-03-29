#!/usr/bin/env bash
set -euo pipefail

# Build a base LXD container image with Claude Code and uv pre-installed.
#
# Usage:
#   ./base-container.sh [container-name]
#
# Environment variables:
#   BASE_IMAGE       — source image (default: ubuntu:24.04)
#   APT_PROXY        — apt proxy URL (default: empty, no proxy)
#   PUBLISHED_NAME   — image alias to publish as (default: worktainer-base)

CONTAINER_NAME="${1:-worktainer-build}"
BASE_IMAGE="${BASE_IMAGE:-ubuntu:24.04}"
APT_PROXY="${APT_PROXY:-}"
PUBLISHED_NAME="${PUBLISHED_NAME:-worktainer-base}"

if lxc info "${CONTAINER_NAME}" >/dev/null 2>&1; then
  echo "Container '${CONTAINER_NAME}' already exists." >&2
  exit 1
fi

# Build cloud-init config — apt proxy only if set
apt_proxy_block=""
if [ -n "${APT_PROXY}" ]; then
  apt_proxy_block="$(cat <<EOF
apt:
  http_proxy: ${APT_PROXY}
  https_proxy: ${APT_PROXY}
EOF
)"
fi

cloud_init="$(cat <<EOC
#cloud-config
${apt_proxy_block}
package_update: true
package_upgrade: true
packages:
  - openssh-server
  - curl
  - git
  - jq
locale: C.UTF-8
users:
  - name: ubuntu
    lock_passwd: true
    shell: /bin/bash
    groups: [sudo, lxd]
    sudo: ALL=(ALL) NOPASSWD:ALL
EOC
)"

lxc init "${BASE_IMAGE}" "${CONTAINER_NAME}"
lxc config set "${CONTAINER_NAME}" cloud-init.user-data "${cloud_init}"
lxc start "${CONTAINER_NAME}"

# Wait for cloud-init. Exit code 2 = recoverable warnings (OK on cloud-init 25.3+).
lxc exec "${CONTAINER_NAME}" -- cloud-init status --wait || {
  rc=$?
  if [ "${rc}" -ne 2 ]; then
    echo "cloud-init failed (exit ${rc})." >&2
    exit 1
  fi
  echo "cloud-init finished with recoverable warnings (exit 2), continuing."
}

echo "Installing uv and Claude Code..."
cat > /tmp/aifw-setup.sh <<'SETUP'
#!/bin/bash
set -euo pipefail

# Install uv (system-wide)
curl -LsSf https://astral.sh/uv/install.sh -o /tmp/uv-install.sh
UV_UNMANAGED_INSTALL=/usr/local/bin sh /tmp/uv-install.sh
rm /tmp/uv-install.sh

# Install Claude Code native binary for the ubuntu user
# The installer puts it at ~/.local/bin/claude with the actual binary
# under ~/.local/share/claude/versions/<version>
su - ubuntu -c 'curl -fsSL https://claude.ai/install.sh | bash'

# Ensure ~/.local/bin is in PATH for the ubuntu user
echo 'export PATH="$HOME/.local/bin:$PATH"' >> /home/ubuntu/.bashrc
SETUP

lxc file push /tmp/aifw-setup.sh "${CONTAINER_NAME}/tmp/aifw-setup.sh"
lxc exec "${CONTAINER_NAME}" -- bash -c 'bash /tmp/aifw-setup.sh > /tmp/setup.log 2>&1'
lxc exec "${CONTAINER_NAME}" -- cat /tmp/setup.log
rm /tmp/aifw-setup.sh

# Verify Claude is installed
echo "Verifying Claude Code installation..."
lxc exec "${CONTAINER_NAME}" -- sudo --login --user ubuntu -- claude --version

lxc stop "${CONTAINER_NAME}"

if lxc image alias list --format csv | awk -F, '{print $1}' | grep -Fxq "${PUBLISHED_NAME}"; then
  lxc image alias delete "${PUBLISHED_NAME}"
fi

lxc publish "${CONTAINER_NAME}" --alias "${PUBLISHED_NAME}"
echo "Published '${CONTAINER_NAME}' as image alias '${PUBLISHED_NAME}'."
lxc delete "${CONTAINER_NAME}"

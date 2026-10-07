#!/bin/bash

# Oneshot boot hook for the teuthology CLI VM (teuthology-bootstrap.service).
# Runs after teuthology-udn-client; TimeoutStartSec=1h on the unit.
#
# - No-op when teuthology.install=false, or when teuthology-lock already
#   exists under /opt/teuthology/.venv.
# - Rewrite fedora*.repo to dl.fedoraproject.org baseurls (disable metalink)
#   and disable fedora-cisco-openh264; dnf install build deps
#   (max_parallel_downloads=1).
# - Shallow-clone teuthology.gitUrl@gitBranch into /opt/teuthology, run
#   ./bootstrap install (SETUPTOOLS_SCM_PRETEND_VERSION_FOR_TEUTHOLOGY),
#   then uv pip install kubernetes for the OpenShift provisioner.

set -euo pipefail

{{- if not (.Values.teuthology.install | default true) }}
echo "teuthology.install=false; skip clone/bootstrap"
exit 0
{{- end }}
GIT_URL="{{ .Values.teuthology.gitUrl | default "https://github.com/ceph/teuthology.git" }}"
GIT_BRANCH="{{ .Values.teuthology.gitBranch | default "main" }}"
DEST=/opt/teuthology
if [[ -x ${DEST}/.venv/bin/teuthology-lock ]]; then
  echo "teuthology already installed in $DEST"
  exit 0
fi
# Metalink mirrors often hang in-cluster; use dl.fedoraproject.org.
for f in /etc/yum.repos.d/fedora.repo /etc/yum.repos.d/fedora-updates.repo; do
  [[ -f "$f" ]] || continue
  sed -i \
    -e 's|^metalink=|#metalink=|' \
    -e 's|^#baseurl=http://download.example/pub/fedora/linux/|baseurl=https://dl.fedoraproject.org/pub/fedora/linux/|' \
    "$f"
done
if [[ -f /etc/yum.repos.d/fedora-cisco-openh264.repo ]]; then
  sed -i 's/^enabled=1/enabled=0/' /etc/yum.repos.d/fedora-cisco-openh264.repo || true
fi
dnf -y --setopt=max_parallel_downloads=1 install git python3 python3-pip python3-devel gcc libffi-devel openssl-devel libyaml-devel libev-devel libvirt-devel pipx jq curl
mkdir -p "$(dirname "$DEST")"
if [[ ! -d $DEST/.git ]]; then
  git clone --depth 1 --branch "$GIT_BRANCH" "$GIT_URL" "$DEST"
else
  git -C "$DEST" fetch origin "$GIT_BRANCH" && git -C "$DEST" checkout "$GIT_BRANCH"
fi
cd "$DEST"
chmod +x ./bootstrap
export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_TEUTHOLOGY="${SETUPTOOLS_SCM_PRETEND_VERSION_FOR_TEUTHOLOGY:-0.0.0}"
./bootstrap install
# OpenShift provisioner (kubernetes Python client)
uv pip install kubernetes || true

#!/bin/bash

# Oneshot boot hook for the teuthology node (teuthology-bootstrap.service).
# Runs after teuthology-udn-client. TimeoutStartSec=2h.
#
# Single node: clone/bootstrap teuthology, then enable dispatcher + archive.
# - Rewrite fedora repos; dnf install build deps.
# - Shallow-clone teuthology.git.url@git.branch into ~/teuthology.
# - Inject lab SSH keys into ocp user-data; ./bootstrap install.
# - Enable teuthology-dispatcher + teuthology-archive.

set -euo pipefail

{{- if not (.Values.teuthology.install | default true) }}
echo "teuthology.install=false; skip clone/bootstrap"
exit 0
{{- end }}
GIT_URL="{{ .Values.teuthology.git.url | default "https://github.com/ceph/teuthology.git" }}"
GIT_BRANCH="{{ .Values.teuthology.git.branch | default "main" }}"
USER_NAME="{{ include "teuthology.loginName" (.Values.teuthology.users | default list) }}"
DEST="/home/${USER_NAME}/teuthology"
KEYS_FILE=/etc/teuthology/lab_ssh_authorized_keys

inject_lab_ssh_keys() {
  local udir="${DEST}/teuthology/ocp/user_data"
  [[ -f "$KEYS_FILE" && -d "$udir" ]] || return 0
  python3 - "$KEYS_FILE" "$udir" <<'PY'
import pathlib, re, sys
keys_path, udir = pathlib.Path(sys.argv[1]), pathlib.Path(sys.argv[2])
keys = [ln.strip() for ln in keys_path.read_text().splitlines()
        if ln.strip() and not ln.strip().startswith("#")]
if not keys:
    raise SystemExit(0)
block = "    ssh_authorized_keys:\n" + "".join(f"      - {k}\n" for k in keys)
pat = re.compile(r"(?m)^    ssh_authorized_keys:\n(?:      - .*\n)*")
for path in sorted(udir.glob("ocp-*-user-data.txt")):
    text = path.read_text()
    new, n = pat.subn(block, text, count=1)
    if n:
        path.write_text(new)
        print(f"injected lab SSH keys into {path}")
    else:
        print(f"no ssh_authorized_keys block in {path}; skipped")
PY
  chown -R "${USER_NAME}:${USER_NAME}" "$udir" || true
}

install_dispatcher_wrapper() {
  # systemd cannot ExecStart paths under a 0700 home directory.
  cat > /usr/local/bin/teuthology-dispatcher <<EOF
#!/bin/bash
set -euo pipefail
export HOME="${HOME_DIR:-/home/${USER_NAME}}"
export VIRTUAL_ENV="${DEST}/.venv"
export PATH="\${VIRTUAL_ENV}/bin:/usr/local/bin:/usr/bin:/bin"
cd "${DEST}"
exec "\${VIRTUAL_ENV}/bin/python" "\${VIRTUAL_ENV}/bin/teuthology-dispatcher" "\$@"
EOF
  chmod 0755 /usr/local/bin/teuthology-dispatcher
}

enable_node_services() {
  systemctl enable --now teuthology-archive.service || true
  if [[ -x ${DEST}/.venv/bin/teuthology-dispatcher ]]; then
    sudo -u "$USER_NAME" env HOME="/home/${USER_NAME}" bash -lc \
      "cd '$DEST' && .venv/bin/python -c 'import kubernetes' 2>/dev/null || \
       (command -v uv >/dev/null && uv pip install kubernetes || .venv/bin/pip install kubernetes)" || true
    install_dispatcher_wrapper
    systemctl enable --now teuthology-dispatcher.service || true
  else
    echo "teuthology-dispatcher binary missing; skip enabling dispatcher" >&2
  fi
}

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

if [[ ! -d $DEST/.git ]]; then
  dnf -y --setopt=max_parallel_downloads=1 install git python3 python3-pip python3-devel gcc libffi-devel openssl-devel libyaml-devel libev-devel libvirt-devel pipx jq curl
  install -d -m 0755 -o "$USER_NAME" -g "$USER_NAME" "$DEST"
  sudo -u "$USER_NAME" git clone --depth 1 --branch "$GIT_BRANCH" "$GIT_URL" "$DEST"
elif [[ ! -x ${DEST}/.venv/bin/teuthology-lock ]]; then
  dnf -y --setopt=max_parallel_downloads=1 install git python3 python3-pip python3-devel gcc libffi-devel openssl-devel libyaml-devel libev-devel libvirt-devel pipx jq curl
  sudo -u "$USER_NAME" git -C "$DEST" fetch origin "$GIT_BRANCH"
  sudo -u "$USER_NAME" git -C "$DEST" checkout "$GIT_BRANCH"
fi

command -v python3 >/dev/null 2>&1 || dnf -y --setopt=max_parallel_downloads=1 install python3
inject_lab_ssh_keys

if [[ -x ${DEST}/.venv/bin/teuthology-lock ]]; then
  echo "teuthology already installed in $DEST"
  enable_node_services
  exit 0
fi

cd "$DEST"
chmod +x ./bootstrap
export SETUPTOOLS_SCM_PRETEND_VERSION_FOR_TEUTHOLOGY="${SETUPTOOLS_SCM_PRETEND_VERSION_FOR_TEUTHOLOGY:-0.0.0}"
chown -R "${USER_NAME}:${USER_NAME}" "$DEST"
# ansible-galaxy often hangs; bound the wait.
if ! timeout 90m sudo -u "$USER_NAME" env HOME="/home/${USER_NAME}" ./bootstrap install; then
  if [[ -x ${DEST}/.venv/bin/teuthology-lock ]]; then
    echo "./bootstrap install timed out/failed but teuthology-lock is present; continuing"
  else
    echo "./bootstrap install failed and teuthology-lock is missing" >&2
    exit 1
  fi
fi
sudo -u "$USER_NAME" env HOME="/home/${USER_NAME}" bash -lc "cd '$DEST' && (command -v uv >/dev/null && uv pip install kubernetes || .venv/bin/pip install kubernetes)" || true
ln -sfn "$DEST" /opt/teuthology

enable_node_services
echo "teuthology node bootstrap complete"

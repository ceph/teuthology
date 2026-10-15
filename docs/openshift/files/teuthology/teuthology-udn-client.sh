#!/bin/bash

# Oneshot boot hook for the teuthology node VM (teuthology-udn-client.service).
#
# Single node: CLI + dispatcher + archive live here.
# - Resolve the UDN NIC by teuthology.mac; keep masquerade as default route.
# - Split-DNS via dhcp-gateway for labDomain (target-*.labDomain).
# - Mount teuthology.dataVolumes (PVC disks) at their configured paths.
# - Ensure src/archive/teuthology/log dirs (from archive.path / dispatcher.path).
# - Lab SSH keypair; login shells cd + source venv. Config lives only at
#   /etc/teuthology.yaml (world-readable; teuthology.config falls back to it
#   when ~/.teuthology.yaml is absent) -- no per-user copy is made.

set -euo pipefail

# NetworkManager-wait-online.service reliably fails/times out on dual-NIC UDN
# guests (masquerade + secondary UDN iface); we resolve/configure the UDN NIC
# ourselves below instead of waiting on it. Mask it so it stops showing up as
# a failed unit.
systemctl mask NetworkManager-wait-online.service >/dev/null 2>&1 || true

UDN_MAC="{{ .Values.teuthology.mac }}"
UDN_MAC="$(printf '%s' "$UDN_MAC" | tr '[:upper:]' '[:lower:]')"
GW="{{ .Values.udn.gateway }}"
DOMAIN="{{ .Values.dispatcher.labDomain }}"
CON_NAME="teuthology-udn"
{{- $loginName := include "teuthology.loginName" (.Values.teuthology.users | default list) }}
USER_NAME="{{ $loginName }}"
HOME_DIR="/home/${USER_NAME}"
{{- $dispPath := .Values.dispatcher.path | default dict }}
SRC_DIR="{{ $dispPath.src | default (printf "/home/%s/src" $loginName) }}"
ARCHIVE_DIR="{{ .Values.archive.path | default $dispPath.archive | default (printf "/home/%s/archive" $loginName) }}"
TEUTH_DIR="${HOME_DIR}/teuthology"
LOG_DIR="${HOME_DIR}/log"

mount_data_volumes() {
{{- range .Values.teuthology.dataVolumes | default list }}
{{- $volName := .name | trim }}
{{- $serial := $volName | replace "-" "" | trunc 20 }}
{{- $path := required (printf "teuthology.dataVolumes entry %q needs path" $volName) .path }}
  # PVC {{ $volName }} → {{ $path }} (virtio serial {{ $serial }})
  _dev="/dev/disk/by-id/virtio-{{ $serial }}"
  _path={{ $path | quote }}
  if [[ -b "$_dev" ]]; then
    if ! blkid "$_dev" >/dev/null 2>&1; then
      mkfs.xfs -f "$_dev"
    fi
    install -d -m 0755 "$_path"
    if ! findmnt -n "$_path" >/dev/null 2>&1; then
      mount "$_dev" "$_path"
    fi
    if ! grep -q " ${_path} " /etc/fstab 2>/dev/null; then
      echo "$_dev $_path xfs defaults,nofail 0 2" >> /etc/fstab
    fi
    chown "${USER_NAME}:${USER_NAME}" "$_path" || true
  else
    echo "data volume device $_dev not found for {{ $volName }}; skipping mount of $_path" >&2
    ls -l /dev/disk/by-id/ 2>&1 || true
  fi
{{- end }}
  return 0
}

UDN_IFACE=""
for d in /sys/class/net/*; do
  n="$(basename "$d")"
  [[ "$n" = lo ]] && continue
  a="$(cat "$d/address" 2>/dev/null || true)"
  if [[ "$(printf '%s' "$a" | tr '[:upper:]' '[:lower:]')" = "$UDN_MAC" ]]; then
    UDN_IFACE="$n"
    break
  fi
done
if [[ -z "$UDN_IFACE" ]]; then
  echo "no NIC with MAC $UDN_MAC" >&2
  ip link >&2
  exit 1
fi

MASQ_IFACE="$(ip -4 route show default 2>/dev/null | awk '{for (i=1;i<=NF;i++) if ($i=="dev") {print $(i+1); exit}}')"
echo "UDN iface=$UDN_IFACE masq=${MASQ_IFACE:-none} gw=$GW domain=$DOMAIN"

if command -v nmcli >/dev/null 2>&1; then
  if nmcli -g NAME con show | grep -qx "$CON_NAME"; then
    nmcli con modify "$CON_NAME" \
      connection.interface-name "$UDN_IFACE" \
      ipv4.method auto \
      ipv4.never-default yes \
      ipv4.route-metric 200 \
      connection.autoconnect yes
  else
    nmcli con add type ethernet ifname "$UDN_IFACE" con-name "$CON_NAME" \
      ipv4.method auto ipv4.never-default yes ipv4.route-metric 200 \
      connection.autoconnect yes
  fi
  nmcli con up "$CON_NAME" || true
else
  ip link set "$UDN_IFACE" up
  command -v dhclient >/dev/null 2>&1 && dhclient -1 "$UDN_IFACE" || true
fi

if command -v resolvectl >/dev/null 2>&1; then
  resolvectl dns "$UDN_IFACE" "$GW" || true
  resolvectl domain "$UDN_IFACE" "~${DOMAIN}" "${DOMAIN}" || true
fi
mkdir -p /etc/systemd/resolved.conf.d
cat > /etc/systemd/resolved.conf.d/teuthology-udn.conf <<EOF
[Resolve]
DNS=${GW}
Domains=~${DOMAIN} ${DOMAIN}
EOF
systemctl try-reload-or-restart systemd-resolved >/dev/null 2>&1 || true

mount_data_volumes

install -d -m 0755 -o "$USER_NAME" -g "$USER_NAME" \
  "$SRC_DIR" "$ARCHIVE_DIR" "$TEUTH_DIR" "$LOG_DIR" || true
install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" "${HOME_DIR}/.ssh"
if [[ -f /etc/teuthology/ssh/id_ed25519 ]]; then
  install -m 0600 -o "$USER_NAME" -g "$USER_NAME" \
    /etc/teuthology/ssh/id_ed25519 "${HOME_DIR}/.ssh/id_ed25519"
  if [[ -f /etc/teuthology/ssh/id_ed25519.pub ]]; then
    install -m 0644 -o "$USER_NAME" -g "$USER_NAME" \
      /etc/teuthology/ssh/id_ed25519.pub "${HOME_DIR}/.ssh/id_ed25519.pub"
  fi
elif [[ ! -f ${HOME_DIR}/.ssh/id_ed25519 ]]; then
  sudo -u "$USER_NAME" ssh-keygen -t ed25519 -N '' -f "${HOME_DIR}/.ssh/id_ed25519"
fi
BASHRC="${HOME_DIR}/.bashrc"
sed -i '\|/teuthology/.venv/bin|d' "$BASHRC" 2>/dev/null || true
if ! grep -q 'TEUTHOLOGY_DIR=.*teuthology' "$BASHRC" 2>/dev/null; then
  cat >>"$BASHRC" <<EOF

# Teuthology node (chart): repo + virtualenv on login
TEUTHOLOGY_DIR="\$HOME/teuthology"
if [[ -f "\${TEUTHOLOGY_DIR}/.venv/bin/activate" ]]; then
  # shellcheck disable=SC1091
  . "\${TEUTHOLOGY_DIR}/.venv/bin/activate"
fi
if [[ -d "\${TEUTHOLOGY_DIR}" && "\${PWD}" != "\${TEUTHOLOGY_DIR}" && -z "\${TEUTHOLOGY_SKIP_CD:-}" ]]; then
  cd "\${TEUTHOLOGY_DIR}" || true
fi
EOF
fi
chown "${USER_NAME}:${USER_NAME}" "$BASHRC"

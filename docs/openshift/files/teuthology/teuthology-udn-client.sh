#!/bin/bash

# Oneshot boot hook for the teuthology CLI VM (teuthology-udn-client.service).
#
# - Resolve the UDN NIC by teuthology.mac; keep the pod/masquerade NIC as
#   the default route (UDN uses DHCP with never-default + route-metric 200).
# - Point systemd-resolved at udn.gateway for labDomain (split DNS:
#   Domains=~labDomain) so target-*.labDomain resolves via dhcp-gateway.
# - Ensure ~/archive, ed25519 SSH key, copy /etc/teuthology.yaml to
#   ~/.teuthology.yaml, and prepend /opt/teuthology/.venv/bin to PATH in
#   .bashrc for the chart SSH user.

set -euo pipefail

UDN_MAC="{{ .Values.teuthology.mac }}"
UDN_MAC="$(printf '%s' "$UDN_MAC" | tr '[:upper:]' '[:lower:]')"
GW="{{ .Values.udn.gateway }}"
DOMAIN="{{ .Values.dispatcher.labDomain }}"
CON_NAME="teuthology-udn"
USER_NAME="{{ .Values.teuthology.sshUser | default "teuthology" }}"

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

install -d -m 0755 -o "$USER_NAME" -g "$USER_NAME" "/home/${USER_NAME}/archive"
install -d -m 0700 -o "$USER_NAME" -g "$USER_NAME" "/home/${USER_NAME}/.ssh"
if [[ ! -f /home/${USER_NAME}/.ssh/id_ed25519 ]]; then
  sudo -u "$USER_NAME" ssh-keygen -t ed25519 -N '' -f "/home/${USER_NAME}/.ssh/id_ed25519"
fi
cp -a /etc/teuthology.yaml "/home/${USER_NAME}/.teuthology.yaml"
chown "${USER_NAME}:${USER_NAME}" "/home/${USER_NAME}/.teuthology.yaml"
grep -q '/opt/teuthology/.venv/bin' "/home/${USER_NAME}/.bashrc" 2>/dev/null || \
  echo 'export PATH="$PATH:/opt/teuthology/.venv/bin"' >> "/home/${USER_NAME}/.bashrc"
chown "${USER_NAME}:${USER_NAME}" "/home/${USER_NAME}/.bashrc"

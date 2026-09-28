#!/bin/bash

# Oneshot boot hook for the dhcp-gateway VM (teuthology-udn-gateway.service).
#
# - Resolve the UDN NIC by dhcpGateway.mac; take the default-route iface as
#   the masquerade egress (pod/masquerade network).
# - Assign udn.gateway/prefix on the UDN NIC (nmcli never-default, or ip addr).
# - sysctl: ip_forward=1, rp_filter=loose; nftables SNAT for udn.subnet out
#   the masquerade iface (table teuthology_udn_nat).
# - Install dnsmasq (prefer Fedora direct RPM over metalink dnf) and nftables.
# - Write /etc/dnsmasq.d/teuthology-net.conf: DHCP on the UDN only
#   (dhcpRangeStart–End, 12h leases), authoritative, router/DNS = gateway,
#   domain=labDomain, upstream resolvers from the masq NIC (else 8.8.8.8),
#   static leases from /etc/dnsmasq.d/dhcp-hosts.conf.

set -euo pipefail

UDN_MAC="{{ .Values.dhcpGateway.mac }}"
UDN_MAC="$(printf '%s' "$UDN_MAC" | tr '[:upper:]' '[:lower:]')"
CIDR="{{ .Values.udn.gateway }}/{{ .Values.udn.prefix }}"
ADDR="{{ .Values.udn.gateway }}"
SUBNET="{{ .Values.udn.subnet }}"
DOMAIN="{{ .Values.dispatcher.labDomain }}"
DHCP_START="{{ .Values.udn.dhcpRangeStart }}"
DHCP_END="{{ .Values.udn.dhcpRangeEnd }}"
NETMASK="{{ .Values.udn.netmask }}"
CON_NAME="teuthology-udn"

# Prefer direct RPM from dl.fedoraproject.org — dnf metalink mirrors often hang in-cluster.
if ! command -v dnsmasq >/dev/null 2>&1; then
  ver="$(rpm -E %fedora 2>/dev/null || true)"
  if [[ -n "$ver" ]]; then
    base="https://dl.fedoraproject.org/pub/fedora/linux/releases/${ver}/Everything/x86_64/os/Packages/d"
    rpm_name="$(curl -fsSL --max-time 60 "${base}/" | grep -oE 'dnsmasq-[0-9][^\"<> ]+\.x86_64\.rpm' | head -1 || true)"
    if [[ -n "$rpm_name" ]]; then
      curl -fsSL --max-time 180 -o /tmp/dnsmasq.rpm "${base}/${rpm_name}"
      rpm -Uvh /tmp/dnsmasq.rpm
    fi
  fi
fi
if ! command -v dnsmasq >/dev/null 2>&1; then
  dnf -y install dnsmasq || true
fi
command -v nft >/dev/null 2>&1 || dnf -y install nftables || true

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
if [[ -z "${MASQ_IFACE:-}" || "$MASQ_IFACE" = "$UDN_IFACE" ]]; then
  echo "could not detect masquerade NIC" >&2
  ip -4 route >&2
  exit 1
fi
echo "UDN iface=$UDN_IFACE masq=$MASQ_IFACE gw=$CIDR"

if command -v nmcli >/dev/null 2>&1; then
  if nmcli -g NAME con show | grep -qx "$CON_NAME"; then
    nmcli con modify "$CON_NAME" \
      connection.interface-name "$UDN_IFACE" \
      ipv4.method manual \
      ipv4.addresses "$CIDR" \
      ipv4.never-default yes \
      connection.autoconnect yes
  else
    nmcli con add type ethernet ifname "$UDN_IFACE" con-name "$CON_NAME" \
      ipv4.method manual ipv4.addresses "$CIDR" ipv4.never-default yes \
      connection.autoconnect yes
  fi
  nmcli con up "$CON_NAME" || true
else
  ip link set "$UDN_IFACE" up
  ip addr replace "$CIDR" dev "$UDN_IFACE"
fi

sysctl -p /etc/sysctl.d/99-teuthology-udn-forward.conf >/dev/null || true

install -d -m 0755 /etc/nftables
cat > /etc/nftables/teuthology-udn-nat.nft <<EOF
destroy table ip teuthology_udn_nat
table ip teuthology_udn_nat {
  chain postrouting {
    type nat hook postrouting priority srcnat; policy accept;
    oifname "${MASQ_IFACE}" ip saddr ${SUBNET} masquerade
  }
}
EOF
if [[ -f /etc/sysconfig/nftables.conf ]] && ! grep -q 'teuthology-udn-nat.nft' /etc/sysconfig/nftables.conf; then
  printf '\ninclude "/etc/nftables/teuthology-udn-nat.nft"\n' >> /etc/sysconfig/nftables.conf
fi
systemctl enable --now nftables >/dev/null 2>&1 || true
nft -f /etc/nftables/teuthology-udn-nat.nft

DNS_LINES=""
add_ns() {
  local ip="$1"
  [[ -z "$ip" ]] && return 0
  [[ "$ip" == 127.* ]] && return 0
  [[ "$ip" == "$ADDR" ]] && return 0
  case "$DNS_LINES" in
    *"server=${ip}"*) return 0 ;;
  esac
  DNS_LINES="${DNS_LINES}server=${ip}"$'\n'
}
if command -v nmcli >/dev/null 2>&1; then
  while IFS= read -r ns; do
    [[ -z "$ns" ]] && continue
    add_ns "$ns"
  done < <(nmcli -g IP4.DNS device show "$MASQ_IFACE" 2>/dev/null | tr '|' '\n')
fi
while read -r _ ip; do
  add_ns "$ip"
done < <(awk '/^nameserver[ \t]/ {print $1, $2}' /etc/resolv.conf 2>/dev/null || true)
if [[ -z "$DNS_LINES" ]]; then
  DNS_LINES="server=8.8.8.8"$'\n'"server=8.8.4.4"$'\n'
fi

cat > /etc/dnsmasq.d/teuthology-net.conf <<EOF
interface=${UDN_IFACE}
bind-dynamic
except-interface=lo
except-interface=${MASQ_IFACE}
no-resolv
${DNS_LINES}domain=${DOMAIN}
local=/${DOMAIN}/
expand-hosts
dhcp-authoritative
dhcp-range=${DHCP_START},${DHCP_END},${NETMASK},12h
dhcp-option=option:router,${ADDR}
dhcp-option=option:dns-server,${ADDR}
dhcp-option=option:netmask,${NETMASK}
conf-file=/etc/dnsmasq.d/dhcp-hosts.conf
log-dhcp
log-queries
EOF
touch /etc/dnsmasq.d/dhcp-hosts.conf
systemctl enable --now dnsmasq >/dev/null 2>&1 || true
systemctl restart dnsmasq
systemctl is-active dnsmasq

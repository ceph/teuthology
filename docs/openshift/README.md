# OpenShift teuthology

The Helm chart in `docs/openshift/` deploys paddles, pulpito, beanstalkd, PostgreSQL, a namespace-scoped UserDefinedNetwork, a dhcp-gateway VirtualMachine, and a single **teuthology node** VirtualMachine that runs the CLI, `teuthology-dispatcher`, and archive HTTP. Edit `values.yaml` for your cluster before you install.

This chart does not create test machines. After deploy, `teuthology-lock` and reimage create and delete those VirtualMachines through the OpenShift provisioner, which clones a guest DataSource onto each root disk.

## Prerequisites

The cluster needs OpenShift Virtualization (KubeVirt), the Containerized Data Importer (CDI), OVN-Kubernetes UserDefinedNetworks with Multus NetworkAttachmentDefinitions, and a StorageClass that supports ReadWriteMany for guest disks. Importer pods must be able to reach every `dataSources[].url` over HTTP(S).

## Components

| Component | Kind | Role |
|-----------|------|------|
| paddles, pulpito, beanstalk, postgres | Deployment and Service | Lab control plane on the pod network. App images default to `quay.io/ceph-infra`. |
| paddles, pulpito, archive | Route | HTTP by default; archive Route targets the teuthology node VM. |
| `teuthology-lab-ssh` | Secret | Lab keypair from `teuthology.users[].sshKey`, embedded into teuthology VM cloud-init. |
| `udn.name` | UserDefinedNetwork | Namespace-scoped Layer2 overlay with IPAM disabled. |
| dhcp-gateway | VirtualMachinePool (replicas=1) | Dual-NIC guest that runs DHCP, DNS, and NAT for the UDN. |
| teuthology | VirtualMachinePool (replicas=1) | Dual-NIC node: CLI, dispatcher, and archive HTTP on one root disk. |
| `dataSources` | DataVolume and DataSource | Cloud images for lock/reimage guests and for infra VM roots. |
| allow-openshift-ingress, allow-same-namespace | NetworkPolicy | Allows the OpenShift router (and, for portability, same-namespace pod-to-pod traffic) to reach application pods and the teuthology VM. |

Set these variables so later commands match `values.yaml`:

```bash
export NAMESPACE=teuthology
export LAB_DOMAIN=ocpvirt.local          # dispatcher.labDomain
export MACHINE_TYPE=ocpvirt              # dispatcher.tube
export UDN_NAME=teuthology-net           # udn.name
export SA=teuthology-provisioner
```

## Architecture

The pod network carries HTTP, PostgreSQL, and the beanstalk queue. The UserDefinedNetwork is a private Layer2 overlay for guest addressing. The dhcp-gateway VirtualMachine is the only DHCP, DNS, and NAT server on that overlay. The teuthology node sits on both networks (masquerade + UDN `l2bridge`): it talks to paddles and beanstalk on the pod network, and it reaches `target-*.<lab_domain>` on the UDN.

`teuthology.dataVolumes` creates PVCs attached as virtio disks and mounted in-guest at each entry's `path` (default: 100Gi at `/home/teuthology`). Job `~/src`, `~/archive`, and `~/teuthology` then live on that volume. `teuthology-archive.service` serves `~/archive` on port `archive.port` (default 8080). Service/Route `archive` select the teuthology VM.

```mermaid
flowchart TB
  subgraph Clients["Clients"]
    Browser["Browser"]
    SshCli["SSH to teuthology node"]
  end

  Router["OpenShift Router<br/>paddles · pulpito · archive"]

  subgraph NS["Namespace"]
    subgraph Apps["Pod network"]
      Pulpito["pulpito"]
      Paddles["paddles"]
      PG["postgres"]
      Beanstalk["beanstalkd"]
    end

    subgraph UDN["UserDefinedNetwork · Layer2 · IPAM disabled"]
      GW["dhcp-gateway VM"]
      TeuthVM["teuthology node<br/>CLI · dispatcher · archive"]
      TestVMs["test VMs target-*"]
    end
  end

  Browser --> Router
  Router --> Pulpito
  Router --> Paddles
  Router --> TeuthVM
  SshCli --> TeuthVM
  Pulpito --> Paddles
  Paddles --> PG
  TeuthVM --> Beanstalk
  TeuthVM --> Paddles
  TeuthVM -->|"ubuntu@target-*.lab_domain"| TestVMs
  GW -->|"DHCP DNS NAT"| TeuthVM
  GW -->|"DHCP DNS NAT"| TestVMs

  classDef clients fill:#E3F2FD,stroke:#1565C0,color:#0D47A1
  classDef apps fill:#E8F5E9,stroke:#2E7D32,color:#1B5E20
  classDef udn fill:#FFF8E1,stroke:#F9A825,color:#F57F17
  classDef gw fill:#F3E5F5,stroke:#7B1FA2,color:#4A148C
  classDef router fill:#ECEFF1,stroke:#546E7A,color:#37474F

  class Browser,SshCli clients
  class Pulpito,Paddles,PG,Beanstalk apps
  class TeuthVM,TestVMs udn
  class GW gw
  class Router router
```

## UserDefinedNetwork

The chart creates a namespace-scoped UserDefinedNetwork named `udn.name`. IPAM is disabled, so OVN only provides Layer2 connectivity and addresses come from the dhcp-gateway VirtualMachine rather than from OVN. OVN also creates a Multus NetworkAttachmentDefinition with the same name. The dhcp-gateway and teuthology node attach with a secondary NIC using the `l2bridge` binding; lock guests attach the same way when `openshift.udn_name` is set.

Keep the UDN namespace-scoped so DHCP stays inside this project. The UDN spec is immutable. To change IPAM or the subnet, detach every consumer, delete the UDN, and create it again.

| Key | Description |
|-----|-------------|
| `udn.name` | UDN and NAD name. `openshift.udn_name` in teuthology.yaml must match. |
| `udn.subnet` | Layer2 subnet, for example `192.168.0.0/20`. |
| `udn.gateway` | Static address on the dhcp-gateway UDN NIC. Do not assign this to the teuthology node or targets. |
| `udn.prefix` / `udn.netmask` | Must match `udn.subnet`. |
| `udn.dhcpRangeStart` / `udn.dhcpRangeEnd` | Dynamic pool for lock guests. |

```bash
oc get userdefinednetwork,network-attachment-definitions -n "$NAMESPACE"
```

The UDN should report `NetworkCreated=True`. If `openshift.udn_name` is empty, guests stay on the masquerade network and do not register in UDN DNS.

## DHCP and gateway

The dhcp-gateway is a VirtualMachinePool with `replicas: 1` and `runStrategy: Always`. It has two NICs: masquerade for the default route and egress, and the UDN NIC identified by `dhcpGateway.mac`. dnsmasq and nftables SNAT run inside the guest, so the pod does not need a privileged SCC. If the VM or VMI is deleted, the pool recreates it.

Service `dhcp-gateway` exposes SSH on port 22 through a LoadBalancer. Guest DNS is not on that Service. dnsmasq listens on the UDN NIC and uses `domain=<dispatcher.labDomain>`. Run only one DHCP and DNS server per namespace on this UDN.

| Item | Rule |
|------|------|
| Teuthology node lease | Generated automatically from `teuthology.mac` / `teuthology.ip` / `teuthology.name`. You do not need to (and should not) duplicate it in `dhcpGateway.dhcpHosts`. |
| `dhcpGateway.dhcpHosts` | Optional, additional infra leases only (beyond the teuthology node). |
| `target-*` | Do not add these names to `dhcpHosts`. They take addresses from the dynamic pool and send the paddles shortname as the DHCP hostname. |
| `teuthology.ip` | Static lease just below the DHCP range. Do not use `udn.gateway`. |
| Lock guests | Any free address in `dhcpRangeStart`–`dhcpRangeEnd`. DNS follows the current lease. |
| Stale DNS | An old name can linger until the lease expires (12 hours) unless the guest releases DHCP on teardown. |

Cloud-init copies ConfigMap `dhcp-hosts` into the guest on first boot. After you change `teuthology.mac`/`teuthology.ip` or `dhcpGateway.dhcpHosts` on a running gateway, edit `/etc/dnsmasq.d/dhcp-hosts.conf` and restart dnsmasq, or upgrade Helm and replace the VM disk so cloud-init runs again.

```yaml
# Only needed for extra infra leases; the teuthology node's own lease is
# generated from teuthology.mac/teuthology.ip/teuthology.name.
dhcpGateway:
  dhcpHosts: |
    dhcp-host=<mac>,<ip>,<hostname>
```

```bash
oc get vmpool,vm,vmi,svc -n "$NAMESPACE" -l app=dhcp-gateway
ssh teuthology@$(oc get svc dhcp-gateway -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].ip}') \
  'systemctl is-active teuthology-udn-gateway dnsmasq'
```

The default SSH user and password are `teuthology` / `passwd`. Run lock and SSH to `target-*.<lab_domain>` from the teuthology node, which uses dhcp-gateway DNS for the lab domain.

## Configuration files

| File | Purpose |
|------|---------|
| `docs/openshift/values.yaml` | Helm defaults for images, UDN, infra VMs, SSH material, and guest disk imports. |
| `docs/openshift/files/` | Chart assets under `dhcp-gateway/` and `teuthology/` (node scripts + systemd units embedded via `tpl` / `.Files.Get`; plus sample `teuthology/override.yaml` for suite scheduling — not embedded). |
| teuthology.yaml (`openshift:`) | Provisioner settings written to `/etc/teuthology.yaml` on the node: API auth, namespace, UDN, storage, and user-data path. |
| `teuthology/ocp/user_data/` | Cloud-init templates for **lock** guests. These come from the teuthology git checkout on the node (`git.url` / `git.branch`) and must exist before lock. |
| `files/teuthology/override.yaml` | Sample job overrides for `teuthology-suite` (public EPEL). Copy to `~/Config/override.yaml` on the teuthology node; not embedded into the VM by the chart. |

Edit `docs/openshift/values.yaml` before you deploy. Do not put paddles `target-*` inventory in that file or in `dhcpGateway.dhcpHosts`. Change guest bootstrap under `files/teuthology/` or `files/dhcp-gateway/`, then upgrade the release. Infra VM cloud-init still runs only on first boot of a new disk. Override any image with `--set *.image=...`.

| Key | Required | Description |
|-----|----------|-------------|
| `postgres.password` | Yes (fails fast if unset) | Paddles database password. |
| `*.image` (postgres, paddles, pulpito, beanstalk) | Optional | Each has a `quay.io/ceph-infra/...:latest` default baked into the templates; override to pin a tag or use a different registry. |
| `postgres.storage` | Optional | Defaults to `10Gi` if unset. |
| `paddles.workerCount` | Optional | Defaults to `"4"` so gunicorn does not spawn too many workers. |
| `paddles.jobLogHrefTempl` | Optional after deploy | Default `http://archive/{run_name}/{job_id}/teuthology.log` works in-cluster via the archive Service → teuthology VM. Set it to the archive Route URL when pulpito or browsers need externally reachable log links. |
| `dispatcher.tube` | Yes | Must match paddles `machine_type`. |
| `dispatcher.labDomain` | Yes | Appended to short hostnames for DNS and SSH. |
| `dispatcher.enabled` | No | Must stay `false` (or omitted). Dispatcher runs on the teuthology node. |
| `archive.port` | Optional | Archive HTTP listen port on the teuthology node (default `8080`). |
| `archive.path` | Optional | Directory served by `teuthology-archive.service` and used as `archive_base` (default `/home/teuthology/archive`). |
| `dispatcher.path.src` | Optional | `src_base_path` in `/etc/teuthology.yaml` (default `/home/teuthology/src`). |
| `dispatcher.path.archive` | Optional | Dispatcher `--archive-dir` (defaults to `archive.path`). |
| `teuthology.git.url` / `teuthology.git.branch` | Optional | Repo and branch cloned into `~/teuthology` during bootstrap. |
| `teuthology.dataVolumes` | Optional | Extra PVCs attached as virtio disks. Each entry needs `name`, `size`, and guest mount `path` (default mounts `/home/teuthology`). |
| `teuthology.mac` / `teuthology.ip` | Yes | Automatically reserved as the DHCP static lease (see [DHCP and gateway](#dhcp-and-gateway)); do not also hand-add this pair to `dhcpGateway.dhcpHosts`. |
| `teuthology.users` | Yes | OS users for the teuthology node. Each entry: `sshUser`/`name`, `password`, optional `sshKey` (`publicKey`+`privateKey` lab keypair), `authorizedKeys` (literal operator pubkeys). **Never commit a real `sshKey.privateKey`** — leave it unset to let `teuthology-udn-client.service` generate one on first boot, or supply your own out-of-band (e.g. via `--set-file` or a separate untracked values file). |
| `dhcpGateway.users` | Yes for SSH to gateway | Same shape as `teuthology.users` (usually login + `authorizedKeys` only). |
| `teuthology.dataSource` / `dhcpGateway.dataSource` | Yes | Usually `fedora` from `dataSources` for root disks. Set `*.dataSource.namespace` if the DataSource is not in the chart namespace. |
| `dataSources` | Optional | List of cloud images to import as DataVolume plus DataSource pairs. |
| `teuthology.rootDisk` / `dhcpGateway.rootDisk` | Yes | Root DataVolume: `size`, `accessMode`, optional `name` (defaults to `<vm name>-root`) and `storageClassName`. |
| `*.rootDisk.storageClassName` / `*.storageClassName` | If the cluster has no default RWX class | dhcp-gateway / teuthology node disks. |
| `dhcpGateway.mac` | Yes | dhcp-gateway's own UDN NIC address comes from `udn.gateway`, not a separate `dhcpGateway.ip` field. |
| `openshift.root_storage_class` | At lock | Guest operating-system disk StorageClass. |
| `openshift.data_storage_class` | At lock | Extra disks from user-data `volumes:`. |
| `openshift.root_storage_size` / `vcpus` / `ram` | At lock | Default guest size (chart template defaults apply when omitted). |

Helm writes `/etc/teuthology.yaml` on the teuthology node (world-readable, `root:root`); that is the only copy on the node -- `teuthology.config` falls back to it automatically when `~/.teuthology.yaml` is absent, so no per-user copy is made or needed there. Commented `openshift:` stubs in `values.yaml` can be filled with `--set` after you create the provisioner ServiceAccount. Cloud-init does not run again on a Helm upgrade unless you recreate the VM disk. A workstation copy (on your own laptop, for running `teuthology-lock` etc. out-of-cluster) belongs in `~/.teuthology.yaml`. Do not commit tokens.

```yaml
openshift:
  namespace: <namespace>
  machine_types: ['<machine_type>']
  user_data: teuthology/ocp/user_data/ocp-{os_type}-{os_version}-user-data.txt
  server: https://api.example.com:6443
  token: <service-account-token>
  certificate_authority_data: <base64-ca>   # if TLS verify needs a private CA
  udn_name: <udn.name>                      # empty string disables the UDN NIC
  udn_binding: l2bridge
  datasource_namespace: <datasource-namespace>
  vcpus: 4
  ram: 8Gi
  root_storage_size: 40Gi
  root_storage_class: <rwx-storage-class>
  data_storage_class: <rwx-storage-class>
```

| Key | Required | Description |
|-----|----------|-------------|
| `server` | Yes | OpenShift API URL. |
| `token` | Yes | ServiceAccount bearer token. |
| `certificate_authority_data` | If TLS needs it | Base64 CA from the cluster kubeconfig. |
| `namespace` | Yes | Namespace for VMs and DataVolumes. |
| `machine_types` | Yes | Must match `dispatcher.tube`. |
| `user_data` | Yes | Path template for cloud-init files relative to the teuthology checkout. |
| `udn_name` | For UDN guests | Multus network name. Empty disables the UDN NIC. |
| `datasource_namespace` | If DataSources are not in `$NAMESPACE` | Namespace of cluster OS DataSources when you are not using chart-local imports. |
| `root_storage_class` | Yes | Guest operating-system disk. |
| `data_storage_class` | Yes | Extra disks listed under `volumes:` in user-data. |

Also set `lab_domain`, `lock_server`, `results_server`, and `queue_host` / `queue_port`. Use the beanstalk LoadBalancer EXTERNAL-IP from a workstation, or the in-cluster Service DNS from the teuthology node.

## Names

`teuthology-lock` looks up `canonicalize_hostname()`, which appends `lab_domain`. The KubeVirt object name and the DHCP hostname stay short. When `udn_name` is set, paddles `mac_address` is required so the provisioner can stamp that MAC on the UDN NIC. That MAC is not a Helm DHCP reservation.

| Layer | Form |
|-------|------|
| paddles `nodes.name` | FQDN: `target-00.<lab_domain>` |
| paddles `mac_address` | Unique per node when UDN is enabled |
| KubeVirt VM and DHCP hostname | shortname: `target-00` |
| SSH and DNS | `target-00.<lab_domain>` maps to the current dhcp-gateway lease |

## Steps

### 1. Deploy

Install the chart, wait until the UDN, Deployments, and VirtualMachines (dhcp-gateway, teuthology) are Ready. The default `paddles.jobLogHrefTempl` already works for in-cluster paddles→archive links; optionally point it at the archive Route afterward so pulpito and browsers get externally reachable log URLs.

```bash
helm upgrade --install teuthology docs/openshift \
  --namespace "$NAMESPACE" --create-namespace --history-max 3 \
  -f docs/openshift/values.yaml

oc get userdefinednetwork -n "$NAMESPACE"
for d in paddles pulpito beanstalk paddles-postgres; do
  oc rollout status deploy/$d -n "$NAMESPACE"
done
oc wait -n "$NAMESPACE" --for=condition=Ready vm -l app=dhcp-gateway --timeout=20m
oc wait -n "$NAMESPACE" --for=condition=Ready vm -l app=teuthology --timeout=20m
```

SSH as the primary `teuthology.users[].sshUser` (default password `passwd`), or with a key listed under that user's `authorizedKeys`:

```bash
ssh teuthology@$(oc get svc dhcp-gateway -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
ssh teuthology@$(oc get svc teuthology -n "$NAMESPACE" -o jsonpath='{.status.loadBalancer.ingress[0].ip}')
```

On the teuthology node, after bootstrap finishes:

```bash
systemctl is-active teuthology-dispatcher teuthology-archive
```

```bash
ARCHIVE_HOST=$(oc get route archive -n "$NAMESPACE" -o jsonpath='{.spec.host}')
helm upgrade teuthology docs/openshift \
  --namespace "$NAMESPACE" --history-max 3 \
  --set paddles.jobLogHrefTempl="http://${ARCHIVE_HOST}/{run_name}/{job_id}/teuthology.log" \
  -f docs/openshift/values.yaml
```

```bash
echo "http://$(oc get route pulpito -n "$NAMESPACE" -o jsonpath='{.spec.host}')"
echo "http://$(oc get route paddles -n "$NAMESPACE" -o jsonpath='{.spec.host}')"
```

Use `https://` only when the Routes terminate TLS. A Route that returns **503** while pods are Ready usually means the router cannot reach the pods; the chart NetworkPolicy `allow-openshift-ingress` is meant to fix that. `allow-same-namespace` keeps pod-to-pod traffic (paddles → postgres, pulpito/teuthology → paddles, teuthology → beanstalk) working regardless of whether the project has its own baseline same-namespace policy.

### 2. ServiceAccount token

Create a ServiceAccount in the namespace with permission to manage VirtualMachines, DataVolumes, and Secrets. Bind the built-in `admin` role in that namespace. Kubernetes 1.24 and later do not mint a long-lived token unless you create a token Secret.

```bash
oc create serviceaccount "$SA" -n "$NAMESPACE"
oc adm policy add-role-to-user admin -z "$SA" -n "$NAMESPACE"

oc apply -n "$NAMESPACE" -f - <<EOF
apiVersion: v1
kind: Secret
metadata:
  name: ${SA}-token
  annotations:
    kubernetes.io/service-account.name: ${SA}
type: kubernetes.io/service-account-token
EOF

SERVER=$(oc whoami --show-server)
TOKEN=$(oc get secret "${SA}-token" -n "$NAMESPACE" -o jsonpath='{.data.token}' | base64 -d)
CA_DATA=$(oc config view --raw --minify -o jsonpath='{.clusters[0].cluster.certificate-authority-data}')
```

Put `server` and `token` under `openshift:` in teuthology.yaml on the lock host (`/etc/teuthology.yaml` on the teuthology node). You can also pass them at upgrade time without editing files by hand:

```bash
helm upgrade teuthology docs/openshift \
  --namespace "$NAMESPACE" --history-max 3 \
  -f docs/openshift/values.yaml \
  --set openshift.server="$SERVER" \
  --set openshift.token="$TOKEN" \
  --set openshift.certificate_authority_data="$CA_DATA"
```

Add `certificate_authority_data` only when the lock host does not trust the API server CA. Recreating the teuthology VM disk (or editing `/etc/teuthology.yaml` in place) is required if cloud-init already ran with empty auth fields.

```bash
oc login --token="$TOKEN" --server="$SERVER"
oc whoami
# system:serviceaccount:<namespace>:<sa>
```

Do not commit tokens. To rotate, delete and recreate Secret `${SA}-token` and replace `openshift.token`.

### 3. SSH keys and extra disks

Define OS users under `teuthology.users` / `dhcpGateway.users`. Put the lab keypair on a teuthology user as `sshKey` (used to reach targets). Put operator login pubkeys on each user as literal `authorizedKeys` strings.

`values.yaml` ships with `sshKey` commented out. If you leave it unset, `teuthology-udn-client.service` generates a fresh ed25519 keypair on the node's first boot — this is the recommended default. Only set `sshKey.privateKey` if you need a specific, pre-provisioned keypair, and never commit that key to version control (pass it with `--set-file` or a separate, gitignored values file instead).

```yaml
teuthology:
  users:
    - name: teuthology
      sshUser: teuthology
      password: passwd
      sshKey:
        publicKey: ssh-ed25519 AAAA... teuthology@lab
        privateKey: |
          -----BEGIN OPENSSH PRIVATE KEY-----
          ...
          -----END OPENSSH PRIVATE KEY-----
      authorizedKeys:
        - ssh-ed25519 AAAA... teuthology-user
dhcpGateway:
  users:
    - name: teuthology
      sshUser: teuthology
      password: passwd
      authorizedKeys:
        - ssh-ed25519 AAAA... teuthology-user
```

| Piece | Where it goes |
|-------|----------------|
| `users[].sshKey.privateKey` | Teuthology node `~/.ssh/id_ed25519` (via cloud-init) |
| `users[].sshKey.publicKey` | Injected into `teuthology/ocp/user_data/ocp-*-user-data.txt` at bootstrap |
| `users[].authorizedKeys` | Infra VM cloud-init `ssh_authorized_keys` |

Password login still works with the chart defaults (`teuthology` / `passwd`). Replace the sample password in `values.yaml` before production use, and never commit a real private key.

Extra disks on lock guests use a teuthology-only `volumes:` list in user-data that the provisioner strips before cloud-init runs.

### 4. Paddles nodes

Register FQDNs and a unique MAC per node. `machine_type` must match `dispatcher.tube` and `openshift.machine_types`. Set `PGPASSWORD` to `postgres.password`.

```bash
oc exec -i -n "$NAMESPACE" deploy/paddles-postgres -- \
  env PGPASSWORD=secret psql -U paddles -d paddles <<SQL
insert into nodes (name, machine_type, is_vm, locked, up, mac_address) values
('target-00.${LAB_DOMAIN}', '${MACHINE_TYPE}', false, false, true, '52:54:00:d4:ca:00'),
('target-01.${LAB_DOMAIN}', '${MACHINE_TYPE}', false, false, true, '52:54:00:d4:ca:01');
SQL
```

```bash
PADDLES=$(oc get route paddles -n "$NAMESPACE" -o jsonpath='{.spec.host}')
curl -X POST "http://${PADDLES}/nodes/" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"target-00.${LAB_DOMAIN}\",\"machine_type\":\"${MACHINE_TYPE}\",\"is_vm\":false,\"up\":true,\"locked\":false,\"mac_address\":\"52:54:00:d4:ca:00\"}"
```

### 5. Guest OS DataSources

`dataSources` in `values.yaml` imports cloud images (defaults: fedora, centos-9.stream, rocky-10, ubuntu-22.04, ubuntu-24.04) as DataVolume plus DataSource pairs in `$NAMESPACE`. The fedora entry also backs the dhcp-gateway and teuthology node root disks when `*.dataSource.name` is `fedora`. Use the same RWX storage class as guest root disks, and wait until each DataSource is Ready before locking.

```bash
oc get datavolume,datasource -n "$NAMESPACE" -l app=teuthology-guest-datasource
```

### 6. Lock and reimage

On the teuthology node, ensure `/home/teuthology/teuthology/.venv/bin` or `/opt/teuthology/.venv/bin` is on `PATH` after bootstrap. The provisioner creates a VirtualMachine named with the paddles shortname, attaches the UDN with the paddles MAC, clones the guest OS DataSource onto the root disk (`root_storage_class`), and adds extra DataVolumes from user-data (`data_storage_class`). Unlock and reimage delete that VM.

```bash
teuthology-lock --lock target-00 --machine-type "$MACHINE_TYPE" --os-type ubuntu --os-version 24.04
getent hosts "target-00.${LAB_DOMAIN}"
ssh ubuntu@"target-00.${LAB_DOMAIN}"
```

The guest obtains an address with DHCP on the UDN. DNS for that name is dhcp-gateway dnsmasq, not CoreDNS.

### 7. Suite overrides (`override.yaml`)

`ceph-cm-ansible` defaults pin EPEL (and often Rocky/CentOS base repos) at Sepia lab mirrors such as `epel-mirror.front.sepia.ceph.com`. Those names typically resolve to Sepia-private addresses that are not reachable from this cluster's UDN egress, so `dnf` hangs or fails during `ansible.cephlab` even when public Fedora/Rocky mirrors work.

A sample override lives at `docs/openshift/files/teuthology/override.yaml`. On the teuthology node, copy it into place and pass it to every `teuthology-suite` (or schedule) invocation. The file is merged into each job and overrides suite fragments:

```bash
mkdir -p ~/Config
# From a teuthology git checkout that includes this chart:
cp docs/openshift/files/teuthology/override.yaml ~/Config/override.yaml
# Or, if the chart sources are only on the workstation:
#   oc cp … / scp the same file to teuthology@<node>:~/Config/override.yaml
```

Also set `verify_host_keys: false` in `/etc/teuthology.yaml` (or ensure the chart/bootstrap writes it) so paramiko does not reject reimaged guests whose host keys change. For OpenSSH/ansible CLI, ignore host keys for lab FQDNs:

```bash
# ~/.ssh/config on the teuthology node
Host *.ocpvirt.local
    StrictHostKeyChecking no
    UserKnownHostsFile /dev/null
    GlobalKnownHostsFile /dev/null
    User ubuntu
    IdentityFile ~/.ssh/id_ed25519
```

Example smoke schedule (Rocky, tentacle, machine type matching `dispatcher.tube`):

```bash
teuthology-suite -v -c tentacle --suite smoke --seed 50 \
  -m "$MACHINE_TYPE" --distro rocky \
  --ceph-repo https://github.com/ceph/ceph.git \
  --suite-repo https://github.com/ceph/ceph.git \
  ~/Config/override.yaml
```

Allow public package mirrors (and any required Ceph hosts such as `shaman.ceph.com`) in the namespace TenantEgress / EgressFirewall. Wildcards are not supported for `dnsName`; refresh the allowlist when metalink returns new third-party hosts. Prefer pointing ansible at official CDNs via overrides (as above) instead of allowlisting every Sepia mirror that resolves to a private address.

## Uninstall

Detach remaining VMs from the UDN, then uninstall the release. Helm leaves PVCs in place unless you delete them, including guest DataVolume PVCs created from `dataSources`.

```bash
helm uninstall teuthology -n "$NAMESPACE"
oc delete userdefinednetwork "$UDN_NAME" -n "$NAMESPACE" --ignore-not-found
oc delete pvc -l app=dhcp-gateway -n "$NAMESPACE" --ignore-not-found
oc delete datavolume,pvc -l app=teuthology-guest-datasource -n "$NAMESPACE" --ignore-not-found
oc delete pvc paddles-postgres-data -n "$NAMESPACE" --ignore-not-found
```

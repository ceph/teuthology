# OpenShift teuthology

The Helm chart in `docs/openshift/` deploys paddles, pulpito, beanstalkd, PostgreSQL, and a single **teuthology node** VirtualMachine that runs the CLI, `teuthology-dispatcher`, and archive HTTP. Edit `values.yaml` for your cluster before you install.

This chart does not create test machines. After deploy, `teuthology-lock` and reimage create and delete those VirtualMachines through the OpenShift provisioner, which clones a guest DataSource onto each root disk. Unlock / reimage delete the guest VM with Foreground cascading deletion (owned DataVolumes go away with the VM).

**Networking (ocp-virt):** lock guests get a **single Multus NIC** on `openshift.udn_name` — no pod/masquerade interface (dual NICs break lab routing; ceph tracker #80437). Lab DHCP/DNS map paddles `mac_address` → hostname → IP. Unlock/reimage can delete guest VMs freely; addressing is not owned by in-namespace DHCP.

## Prerequisites

The cluster needs OpenShift Virtualization (KubeVirt), the Containerized Data Importer (CDI), a Multus NetworkAttachmentDefinition (and/or UserDefinedNetwork) for the lab front network named by `udn.name`, and a StorageClass that supports ReadWriteMany for guest disks. Importer pods must be able to reach every `dataSources[].url` over HTTP(S). Lab DHCP/DNS must serve that Multus network.

## Components

| Component | Kind | Role |
|-----------|------|------|
| paddles, pulpito, beanstalk, postgres | Deployment and Service | Lab control plane on the pod network. App images default to `quay.io/ceph-infra`. |
| paddles, pulpito, archive | Route | HTTP by default; archive Route targets the teuthology node VM. |
| `teuthology-lab-ssh` | Secret | Lab keypair from `teuthology.users[].sshKey`, embedded into teuthology VM cloud-init. |
| teuthology | VirtualMachinePool (replicas=1) | Dual-NIC infra node: masquerade (paddles/beanstalk) + Multus `l2bridge` (lab front). CLI, dispatcher, archive HTTP. |
| `dataSources` | DataVolume and DataSource | Cloud images for lock/reimage guests and for infra VM roots. |
| allow-openshift-ingress, allow-same-namespace | NetworkPolicy | Allows the OpenShift router (and, for portability, same-namespace pod-to-pod traffic) to reach application pods and the teuthology VM. |

Set these variables so later commands match `values.yaml`:

```bash
export NAMESPACE=teuthology
export LAB_DOMAIN=ocpvirt.local          # dispatcher.labDomain
export MACHINE_TYPE=ocpvirt              # dispatcher.tube
export UDN_NAME=<lab-front-network>      # udn.name / openshift.udn_name (existing Multus NAD)
export SA=teuthology-provisioner
```

## Architecture

The pod network carries HTTP, PostgreSQL, and the beanstalk queue. Lock guests and the teuthology node's Multus NIC sit on the lab front network named by `udn.name`. Lab DHCP/DNS owns addressing on that network. The teuthology node keeps a masquerade NIC for in-cluster services and a Multus NIC to reach `ocpvirt*`. Lock guests attach **only** the Multus NIC.

`teuthology.dataVolumes` creates PVCs attached as virtio disks and mounted in-guest at each entry's `path` (default: 100Gi at `/home/teuthology`). Job `~/src`, `~/archive`, and `~/teuthology` then live on that volume. `teuthology-archive.service` serves `~/archive` on port `archive.port` (default 8080). Service/Route `archive` select the teuthology VM.

```mermaid
flowchart TB
  Browser[Browser]
  SshCli[SSH to teuthology node]
  Router[OpenShift Router]
  LabDHCP[Lab DHCP and DNS]

  subgraph NS[Namespace]
    Pulpito[pulpito]
    Paddles[paddles]
    PG[postgres]
    Beanstalk[beanstalkd]
    TeuthVM[teuthology node]
    TestVMs[ocpvirt guests]
  end

  Front[Multus lab front]

  Browser --> Router
  Router --> Pulpito
  Router --> Paddles
  Router --> TeuthVM
  SshCli --> TeuthVM
  Pulpito --> Paddles
  Paddles --> PG
  TeuthVM --> Beanstalk
  TeuthVM --> Paddles
  TeuthVM --> Front
  TestVMs --> Front
  LabDHCP --> Front
  TeuthVM -->|SSH to ocpvirt guests| TestVMs
```

## Multus network and lab DHCP/DNS

`udn.name` is the existing Multus NetworkAttachmentDefinition (or UDN) name written to `openshift.udn_name` (for example `<lab-front-network>`). Lock guests require it: the provisioner builds a single Multus interface with the paddles MAC. Masquerade-only guests are unsupported.

Lab DHCP/DNS must already serve that network. Register each paddles node with a unique `mac_address` that matches a lab DHCP host entry (MAC → short hostname → IP). Set `udn.dnsServers` so the teuthology node resolves `*.${LAB_DOMAIN}` over its Multus NIC (split DNS). The node still uses masquerade as its default route.

| Key | Description |
|-----|-------------|
| `udn.name` | Multus NAD / UDN name. Must match `openshift.udn_name`. |
| `udn.dnsServers` | Lab resolvers for `dispatcher.labDomain` on the teuthology Multus NIC. |

```bash
oc get network-attachment-definitions,userdefinednetwork -A | grep -E "$UDN_NAME|NAME"
```

## Configuration files

| File | Purpose |
|------|---------|
| `docs/openshift/values.yaml` | Helm defaults for images, Multus name, infra VM, SSH material, and guest disk imports. |
| `docs/openshift/files/teuthology/` | Node scripts + systemd units embedded via `tpl` / `.Files.Get`; plus sample `override.yaml` for suite scheduling (not embedded). |
| teuthology.yaml (`openshift:`) | Provisioner settings written to `/etc/teuthology.yaml` on the node: API auth, namespace, Multus name, storage, DataSource map, extra disks, and guest SSH keys. |
| `teuthology/ocp/user_data/` | Cloud-init-only templates for **lock** guests (plus optional `network:` for NoCloud). Extra disks and DataSource names come from `openshift.volumes` / `openshift.datasources`, not these files. They come from the teuthology git checkout on the node (`git.url` / `git.branch`) and must exist before lock. |
| `files/teuthology/override.yaml` | Sample job overrides for `teuthology-suite` (public EPEL). Copy to `~/Config/override.yaml` on the teuthology node; not embedded into the VM by the chart. |

Edit `docs/openshift/values.yaml` before you deploy. Point `udn.name` at the lab Multus network and set `udn.dnsServers`. Do not put paddles `ocpvirt*` inventory in values (lab DHCP owns those leases). Change guest bootstrap under `files/teuthology/`, then upgrade the release. Infra VM cloud-init still runs only on first boot of a new disk. Override any image with `--set *.image=...`.

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
| `teuthology.mac` | Yes | Multus NIC MAC; must match the lab DHCP reservation for the teuthology node. |
| `udn.name` / `udn.dnsServers` | Yes | Lab Multus network name and split-DNS resolvers (see [Multus network and lab DHCP/DNS](#multus-network-and-lab-dhcpdns)). |
| `teuthology.users` | Yes | OS users for the teuthology node. Each entry: `sshUser`/`name`, `password`, optional `sshKey` (`publicKey`+`privateKey` lab keypair), `authorizedKeys` (literal operator pubkeys). **Never commit a real `sshKey.privateKey`** — leave it unset to let `teuthology-udn-client.service` generate one on first boot, or supply your own out-of-band (e.g. via `--set-file` or a separate untracked values file). |
| `teuthology.dataSource` | Yes | Usually `fedora` from `dataSources` for the node root disk. |
| `dataSources` | Optional | List of cloud images to import as DataVolume plus DataSource pairs (names must match `openshift.datasources` when locking against chart-local imports). |
| `teuthology.rootDisk` | Yes | Root DataVolume: `size`, `accessMode`, optional `name` (defaults to `<vm name>-root`) and `storageClassName`. |
| `*.rootDisk.storageClassName` / `*.storageClassName` | If the cluster has no default RWX class | teuthology node disks. |
| `openshift.root_storage_class` | At lock | Guest operating-system disk StorageClass. |
| `openshift.data_storage_class` | At lock | Extra blank disks from `openshift.volumes`. |
| `openshift.root_storage_size` / `vcpus` / `ram` | At lock | Default guest size (chart template defaults apply when omitted). |
| `openshift.datasources` / `volumes` / `ssh_authorized_keys` | At lock | Required by the OpenShift provisioner (see below). |

Helm writes `/etc/teuthology.yaml` on the teuthology node (world-readable, `root:root`); that is the only copy on the node -- `teuthology.config` falls back to it automatically when `~/.teuthology.yaml` is absent, so no per-user copy is made or needed there. The chart emits `verify_host_keys: false`, `openshift.udn_name`, chart-local `datasources`, `volumes: []`, and storage defaults from `values.yaml`. Fill `openshift.server` / `token` / storage classes with `--set` after you create the provisioner ServiceAccount. Cloud-init does not run again on a Helm upgrade unless you recreate the VM disk. A workstation copy (on your own laptop, for running `teuthology-lock` etc. out-of-cluster) belongs in `~/.teuthology.yaml`. Do not commit tokens.

```yaml
openshift:
  namespace: <namespace>
  machine_types: ['<machine_type>']
  user_data: teuthology/ocp/user_data/ocp-{os_type}-{os_version}-user-data.txt
  # Public keys injected into guest cloud-init (do not hardcode in user_data)
  ssh_authorized_keys:
    - ssh-ed25519 AAAA... teuthology@lab
  server: https://api.example.com:6443
  token: <service-account-token>
  # Optional cluster CA (base64). When unset, the system CA store is used.
  # certificate_authority_data: <base64-ca>
  # Explicit opt-out only; defaults to verifying TLS (never silent).
  # insecure_skip_tls_verify: true
  udn_name: <udn.name>                      # Multus NAD; single NIC; no masquerade
  udn_binding: l2bridge
  # Chart-local imports use $NAMESPACE; cluster images often use
  # openshift-virtualization-os-images (DataSource names may differ).
  datasource_namespace: <datasource-namespace>
  datasources:
    ubuntu/22.04: ubuntu-22.04
    ubuntu/24.04: ubuntu-24.04
    rocky/10: rocky-10
    centos/9.stream: centos-9.stream
  # Extra blank disks on every guest ([] = root disk only; key must exist)
  volumes:
    - count: 3
      size: 15
    - count: 2
      size: 20
  timeout: 900                              # status/IP/delete/SSH wait (seconds)
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
| `certificate_authority_data` | Optional | Base64 CA from the cluster kubeconfig. When unset, TLS uses the system CA store. |
| `insecure_skip_tls_verify` | No | Explicit opt-out only (`true`); defaults to verifying TLS. |
| `namespace` | Yes | Namespace for VMs and DataVolumes. |
| `machine_types` | Yes | Must match `dispatcher.tube`. |
| `user_data` | Yes | Path template for cloud-init files relative to the teuthology checkout. Templates must not define `volumes` or `datasource`. |
| `ssh_authorized_keys` | Yes | Guest SSH public keys injected into cloud-init by the provisioner. |
| `udn_name` | Yes | Multus NAD / UDN name for the guest's single NIC. Required; masquerade-only is unsupported. |
| `udn_binding` | No | KubeVirt Multus NIC binding (default `l2bridge`). |
| `datasource_namespace` | Yes | Namespace of OS DataSources (`$NAMESPACE` for chart imports, or e.g. `openshift-virtualization-os-images`). |
| `datasources` | Yes | Map of `os_type/os_version` → DataSource name (for example `ubuntu/24.04: ubuntu-24.04`). |
| `volumes` | Yes | Extra blank-disk groups (`count` + `size` in Gi, or `[]` for root only). Driven from teuthology.yaml, not user-data. |
| `timeout` | No | Wait timeout in seconds for Ready/IP/delete/SSH (default `900`). |
| `root_storage_class` | Yes | Guest operating-system disk. |
| `data_storage_class` | Yes | Extra disks from `openshift.volumes`. |

Also set `lab_domain`, `lock_server`, `results_server`, and `queue_host` / `queue_port`. Use the beanstalk LoadBalancer EXTERNAL-IP from a workstation, or the in-cluster Service DNS from the teuthology node.

## Names

`teuthology-lock` looks up `canonicalize_hostname()`, which appends `lab_domain`. The KubeVirt object name stays short. Paddles `mac_address` is required so the provisioner can stamp that MAC on the single Multus NIC. Lab DHCP/DNS map that MAC to the short hostname and IP (Sepia-style front names such as `ocpvirt001` are fine as long as paddles FQDNs and DNS agree).

| Layer | Form |
|-------|------|
| paddles `nodes.name` | FQDN: `ocpvirt010.<lab_domain>` |
| paddles `mac_address` | Unique per node (stamped on the Multus NIC; must match lab DHCP) |
| KubeVirt VM name | shortname: `ocpvirt010` |
| SSH and DNS | `ocpvirt010.<lab_domain>` from lab DNS (not CoreDNS) |

## Steps

### 1. Deploy

Install the chart, wait until Deployments and the teuthology VirtualMachine are Ready. The default `paddles.jobLogHrefTempl` already works for in-cluster paddles→archive links; optionally point it at the archive Route afterward so pulpito and browsers get externally reachable log URLs.

```bash
helm upgrade --install teuthology docs/openshift \
  --namespace "$NAMESPACE" --create-namespace --history-max 3 \
  -f docs/openshift/values.yaml

oc get network-attachment-definitions -A | grep "$UDN_NAME" || true
for d in paddles pulpito beanstalk paddles-postgres; do
  oc rollout status deploy/$d -n "$NAMESPACE"
done
oc wait -n "$NAMESPACE" --for=condition=Ready vm -l app=teuthology --timeout=20m
```

SSH as the primary `teuthology.users[].sshUser` (default password `passwd`), or with a key listed under that user's `authorizedKeys`:

```bash
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

TLS verification is on by default (system CAs). Add `certificate_authority_data` when the lock host needs the cluster CA; use `insecure_skip_tls_verify: true` only as an explicit opt-out. Recreating the teuthology VM disk (or editing `/etc/teuthology.yaml` in place) is required if cloud-init already ran with empty auth fields.

```bash
oc login --token="$TOKEN" --server="$SERVER"
oc whoami
# system:serviceaccount:<namespace>:<sa>
```

Do not commit tokens. To rotate, delete and recreate Secret `${SA}-token` and replace `openshift.token`.

### 3. SSH keys and extra disks

Define OS users under `teuthology.users`. Put the lab keypair on a teuthology user as `sshKey` (private key on the node to reach targets). Put the matching public key(s) in `openshift.ssh_authorized_keys` so the provisioner injects them into guest cloud-init. Put operator login pubkeys on each user as literal `authorizedKeys` strings. Do not hardcode guest keys in `teuthology/ocp/user_data/` templates.

`values.yaml` ships with `sshKey` commented out. If you leave it unset, `teuthology-udn-client.service` generates a fresh ed25519 keypair on the node's first boot and appends the public key to `openshift.ssh_authorized_keys` in `/etc/teuthology.yaml` — this is the recommended default. You can also set `openshift.ssh_authorized_keys` (or `users[].sshKey.publicKey`) explicitly in values; the chart prefers `openshift.ssh_authorized_keys`, then falls back to lab `publicKey` values. Only set `sshKey.privateKey` if you need a specific, pre-provisioned keypair, and never commit that key to version control (pass it with `--set-file` or a separate, gitignored values file instead).

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
openshift:
  ssh_authorized_keys:
    - ssh-ed25519 AAAA... teuthology@lab
  volumes: []   # or [{count: 3, size: 15}, ...]
```

| Piece | Where it goes |
|-------|----------------|
| `users[].sshKey.privateKey` | Teuthology node `~/.ssh/id_ed25519` (via cloud-init) |
| `openshift.ssh_authorized_keys` | Injected into lock-guest cloud-init by the OpenShift provisioner |
| `users[].authorizedKeys` | Infra VM cloud-init `ssh_authorized_keys` |

Password login still works with the chart defaults (`teuthology` / `passwd`). Replace the sample password in `values.yaml` before production use, and never commit a real private key.

Extra disks on lock guests come from `openshift.volumes` (`count` + `size` groups, or `[]` for root disk only). The provisioner rejects `volumes` / `datasource` keys inside user-data templates.

### 4. Paddles nodes

Register FQDNs and a unique MAC per node. Each `mac_address` must match lab DHCP (MAC → short hostname → IP) on `udn.name`. `machine_type` must match `dispatcher.tube` and `openshift.machine_types`. Set `PGPASSWORD` to `postgres.password`.

```bash
oc exec -i -n "$NAMESPACE" deploy/paddles-postgres -- \
  env PGPASSWORD=secret psql -U paddles -d paddles <<SQL
insert into nodes (name, machine_type, is_vm, locked, up, mac_address) values
('ocpvirt010.${LAB_DOMAIN}', '${MACHINE_TYPE}', false, false, true, '52:54:00:14:c2:0a'),
('ocpvirt013.${LAB_DOMAIN}', '${MACHINE_TYPE}', false, false, true, '52:54:00:14:c2:0d');
SQL
```

```bash
PADDLES=$(oc get route paddles -n "$NAMESPACE" -o jsonpath='{.spec.host}')
curl -X POST "http://${PADDLES}/nodes/" \
  -H 'Content-Type: application/json' \
  -d "{\"name\":\"ocpvirt010.${LAB_DOMAIN}\",\"machine_type\":\"${MACHINE_TYPE}\",\"is_vm\":false,\"up\":true,\"locked\":false,\"mac_address\":\"52:54:00:14:c2:0a\"}"
```

### 5. Guest OS DataSources

`dataSources` in `values.yaml` imports cloud images (defaults: fedora, centos-9.stream, rocky-10, ubuntu-22.04, ubuntu-24.04) as DataVolume plus DataSource pairs in `$NAMESPACE`. The fedora entry also backs the teuthology node root disk when `*.dataSource.name` is `fedora`. Use the same RWX storage class as guest root disks, and wait until each DataSource is Ready before locking.

Point `openshift.datasource_namespace` at `$NAMESPACE` (chart imports) or at a cluster image namespace such as `openshift-virtualization-os-images`. `openshift.datasources` must map each `os_type/os_version` you lock to the DataSource object name in that namespace (chart-local names match the `dataSources[].name` entries; cluster image names may differ, for example `centos-stream9`).

```bash
oc get datavolume,datasource -n "$NAMESPACE" -l app=teuthology-guest-datasource
```

### 6. Lock and reimage

On the teuthology node, ensure `/home/teuthology/teuthology/.venv/bin` or `/opt/teuthology/.venv/bin` is on `PATH` after bootstrap. The provisioner creates a VirtualMachine named with the paddles shortname, attaches a **single** Multus NIC (`openshift.udn_name`) with the paddles MAC, clones the guest OS DataSource from `openshift.datasources` onto the root disk (`root_storage_class`), injects `openshift.ssh_authorized_keys` into cloud-init, and adds extra blank DataVolumes from `openshift.volumes` (`data_storage_class`). Unlock and reimage **delete** that VM (Foreground cascade, including owned DataVolumes) — safe because addressing comes from lab DHCP/DNS.

```bash
teuthology-lock --lock ocpvirt010 --machine-type "$MACHINE_TYPE" --os-type ubuntu --os-version 24.04
getent hosts "ocpvirt010.${LAB_DOMAIN}"
ssh ubuntu@"ocpvirt010.${LAB_DOMAIN}"
```

The guest obtains an address from lab DHCP on the Multus network. DNS for that name is lab DNS (configured via `udn.dnsServers` on the teuthology node), not CoreDNS.

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

The chart writes `verify_host_keys: false` into `/etc/teuthology.yaml` so paramiko does not reject reimaged guests whose host keys change. For OpenSSH/ansible CLI, ignore host keys for lab FQDNs:

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

Delete remaining lock VMs, then uninstall the release. Helm leaves PVCs in place unless you delete them, including guest DataVolume PVCs created from `dataSources`. Do not delete the shared lab front Multus NAD / UDN.

```bash
helm uninstall teuthology -n "$NAMESPACE"
oc delete datavolume,pvc -l app=teuthology-guest-datasource -n "$NAMESPACE" --ignore-not-found
oc delete pvc paddles-postgres-data -n "$NAMESPACE" --ignore-not-found
```

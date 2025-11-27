# OpenShift VM Provisioning for Teuthology - Complete Guide

**Version:** 1.0  
**Last Updated:** November 2025

## Table of Contents

1. [Overview](#overview)
2. [Quick Start (5 Minutes)](#quick-start)
3. [Prerequisites](#prerequisites)
4. [Installation](#installation)
5. [Configuration](#configuration)
6. [Usage](#usage)
7. [How It Works](#how-it-works)
8. [Reference](#reference)

---

## Overview

This implementation adds **OpenShift Virtualization (KubeVirt)** support to Teuthology, allowing you to provision VMs for Ceph testing on OpenShift clusters.


### Architecture
```
teuthology-lock --lock --machine-type openshift-vms --num 3
         ↓
  Python code creates VMs via Kubernetes API
         ↓
  VMs running in OpenShift (2-5 minutes)
         ↓
  Ready for Ceph testing!
```

---

## Quick Start

### 1. Install Dependencies
```bash
pip install -e '.[openshift]'
```

### 2. Configure `~/.teuthology.yaml`
```yaml
libcloud:
  providers:
    openshift-vms:
      driver: openshift
      namespace: teuthology
      kubeconfig: ~/.kube/config
      ssh_service_type: NodePort

openshift:
  machine:
    memory: 16Gi
    cpus: 4
    disk: 40Gi
```

### 3. Use It!
```bash
# Lock VMs (provisions automatically)
teuthology-lock --lock --machine-type openshift-vms --num 3 \
  --owner you@example.com --desc "Ceph test"

# Run tests
teuthology test.yaml

# Cleanup (automatic)
teuthology-lock --unlock --owner you@example.com
```

**That's it!** VMs are automatically created, configured, and cleaned up.

---

## Prerequisites

### OpenShift Cluster Requirements
- OpenShift 4.12+ or OKD 4.12+
- OpenShift Virtualization operator installed
- Sufficient resources (CPU, memory, storage)
- StorageClass with dynamic provisioning

### Access Requirements
- Kubeconfig with cluster access
- Service account with permissions (see RBAC section)
- SSH key pair

### Software Requirements
- Python 3.10+
- Teuthology installed
- `kubernetes` Python library (>=28.0.0)

---

## Installation

### Step 1: Install OpenShift Virtualization

#### Option A: Via OpenShift Console
1. Navigate to **Operators → OperatorHub**
2. Search for "OpenShift Virtualization"
3. Click **Install**
4. Wait for installation to complete

#### Option B: Via CLI
```bash
cat <<EOF | oc apply -f -
apiVersion: v1
kind: Namespace
metadata:
  name: openshift-cnv
---
apiVersion: operators.coreos.com/v1alpha1
kind: Subscription
metadata:
  name: hco-operatorhub
  namespace: openshift-cnv
spec:
  source: redhat-operators
  sourceNamespace: openshift-marketplace
  name: kubevirt-hyperconverged
  channel: stable
EOF

# Wait for ready
oc wait --for=condition=Available --timeout=10m \
  -n openshift-cnv hyperconverged kubevirt-hyperconverged
```

### Step 2: Create Namespace and RBAC

```bash
# Create namespace
oc new-project teuthology

# Create service account
oc create serviceaccount teuthology -n teuthology

# Apply RBAC
cat <<EOF | oc apply -f -
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: teuthology-vm-manager
  namespace: teuthology
rules:
- apiGroups: ["kubevirt.io"]
  resources: ["virtualmachines", "virtualmachineinstances"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: ["cdi.kubevirt.io"]
  resources: ["datavolumes"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
- apiGroups: [""]
  resources: ["persistentvolumeclaims", "services"]
  verbs: ["get", "list", "watch", "create", "update", "patch", "delete"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRole
metadata:
  name: teuthology-node-reader
rules:
- apiGroups: [""]
  resources: ["nodes"]
  verbs: ["get", "list"]
---
apiVersion: rbac.authorization.k8s.io/v1
kind: RoleBinding
metadata:
  name: teuthology-vm-manager-binding
  namespace: teuthology
subjects:
- kind: ServiceAccount
  name: teuthology
  namespace: teuthology
roleRef:
  kind: Role
  name: teuthology-vm-manager
  apiGroup: rbac.authorization.k8s.io
---
apiVersion: rbac.authorization.k8s.io/v1
kind: ClusterRoleBinding
metadata:
  name: teuthology-node-reader-binding
subjects:
- kind: ServiceAccount
  name: teuthology
  namespace: teuthology
roleRef:
  kind: ClusterRole
  name: teuthology-node-reader
  apiGroup: rbac.authorization.k8s.io
EOF
```

### Step 3: Create VM Images

```bash
# Ubuntu 22.04
cat <<EOF | oc apply -f -
apiVersion: cdi.kubevirt.io/v1beta1
kind: DataVolume
metadata:
  name: ubuntu-22-04
  namespace: teuthology
spec:
  source:
    registry:
      url: docker://quay.io/containerdisks/ubuntu:22.04
  pvc:
    accessModes: [ReadWriteOnce]
    resources:
      requests:
        storage: 30Gi
EOF

# Wait for ready
oc wait --for=condition=Ready --timeout=10m \
  datavolume/ubuntu-22-04 -n teuthology
```

### Step 4: Create Kubeconfig

```bash
# Get service account token
SA_TOKEN=$(oc create token teuthology -n teuthology --duration=87600h)

# Get cluster API URL
API_URL=$(oc whoami --show-server)

# Create kubeconfig
mkdir -p ~/.kube
cat > ~/.kube/teuthology-config <<EOF
apiVersion: v1
kind: Config
clusters:
- cluster:
    server: ${API_URL}
    insecure-skip-tls-verify: true
  name: teuthology-cluster
contexts:
- context:
    cluster: teuthology-cluster
    namespace: teuthology
    user: teuthology-sa
  name: teuthology
current-context: teuthology
users:
- name: teuthology-sa
  user:
    token: ${SA_TOKEN}
EOF

chmod 600 ~/.kube/teuthology-config
```

### Step 5: Install Teuthology with OpenShift Support

```bash
cd /path/to/teuthology
pip install -e '.[openshift]'
```

---

## Configuration

### Basic Configuration

Create or edit `~/.teuthology.yaml`:

```yaml
# OpenShift provider
libcloud:
  providers:
    openshift-vms:                # machine_type name
      driver: openshift           # Required
      namespace: teuthology       # Required
      kubeconfig: ~/.kube/teuthology-config
      ssh_service_type: NodePort  # NodePort|LoadBalancer|ClusterIP

# Default VM resources
openshift:
  machine:
    memory: 16Gi
    cpus: 4
    disk: 40Gi
  volumes:
    count: 2      # Additional volumes for OSD data
    size: 50Gi

# General Teuthology settings
lab_domain: example.com
archive_base: /home/teuthworker/archive
lock_server: http://paddles.example.com/
ssh_key: ~/.ssh/id_rsa
```

### Advanced Configuration

```yaml
libcloud:
  providers:
    openshift-vms:
      driver: openshift
      namespace: teuthology
      kubeconfig: ~/.kube/teuthology-config
      context: teuthology                    # Optional
      ssh_service_type: LoadBalancer         # Use LB if available
      
      # Image filtering
      exclude_image:
        - '.*-backup$'
        - 'temp-.*'
      
      # Per-OS cloud-init configuration
      userdata:
        ubuntu-22.04:
          packages:
            - git
            - python3
            - python3-pip
            - build-essential
            - ntp
            - docker.io
          runcmd:
            - systemctl enable ntp
            - systemctl start ntp
            - usermod -aG docker ubuntu
        
        centos-9:
          packages:
            - git
            - python3
            - chrony
            - podman
          runcmd:
            - systemctl enable chronyd
            - systemctl start chronyd

openshift:
  machine:
    memory: 32Gi     # High-memory VMs
    cpus: 8
    disk: 100Gi
  volumes:
    count: 4
    size: 100Gi
```

### Per-Job Configuration

Override defaults in your test YAML:

```yaml
# test-ceph-cluster.yaml
machine_type: openshift-vms
os_type: ubuntu
os_version: 22.04

# Override default resources
openshift:
  machine:
    memory: 16Gi
    cpus: 4
    disk: 40Gi
  volumes:
    count: 3
    size: 50Gi

roles:
  - [mon.a, mgr.a, osd.0]
  - [mon.b, mgr.b, osd.1]
  - [mon.c, osd.2, client.0]

tasks:
  - install:
  - ceph:
  - workunit:
      clients:
        client.0:
          - rados/test_python.sh
```

---

## Usage

### Locking VMs

```bash
# Lock 3 VMs
teuthology-lock --lock \
  --machine-type openshift-vms \
  --num 3 \
  --owner you@example.com \
  --desc "Ceph integration tests"

# Output shows:
# Locked: test-node-001.example.com
# Locked: test-node-002.example.com
# Locked: test-node-003.example.com
```

**What happens:**
1. Paddles locks 3 machines
2. Python code creates VMs in OpenShift
3. VMs boot and cloud-init runs
4. SSH services are created
5. VMs ready in 3-5 minutes

### Verifying VMs

```bash
# Check VMs in OpenShift
oc get vm -n teuthology
# NAME            STATUS    AGE
# test-node-001   Running   2m
# test-node-002   Running   2m
# test-node-003   Running   2m

# Check SSH services
oc get svc -n teuthology
# NAME                TYPE       PORT(S)
# test-node-001-ssh   NodePort   22:30001/TCP
# test-node-002-ssh   NodePort   22:30002/TCP
# test-node-003-ssh   NodePort   22:30003/TCP

# SSH to VM
NODE_IP=$(oc get nodes -o jsonpath='{.items[0].status.addresses[0].address}')
ssh -p 30001 ubuntu@${NODE_IP}
```

### Running Tests

```bash
# Run specific test
teuthology test-ceph-cluster.yaml

# Or schedule suite
teuthology-suite \
  --suite rados/singleton \
  --ceph octopus \
  --machine-type openshift-vms \
  --owner you@example.com
```

### Unlocking VMs

```bash
# Unlock all your VMs
teuthology-lock --unlock --owner you@example.com

# Or specific VMs
teuthology-lock --unlock \
  --machines test-node-001,test-node-002,test-node-003
```

**Cleanup is automatic** - all VMs, services, and volumes are deleted.

---

## How It Works

### Complete Flow

```
┌────────────────────────────────────────────┐
│ 1. USER COMMAND                            │
│ $ teuthology-lock --lock ...               │
└─────────────┬──────────────────────────────┘
              │
              ▼
┌────────────────────────────────────────────┐
│ 2. LOCK SYSTEM                             │
│ - Paddles reserves machines                │
│ - Detects machine_type is cloud type       │
└─────────────┬──────────────────────────────┘
              │
              ▼
┌────────────────────────────────────────────┐
│ 3. PROVISIONING (Python)                   │
│ OpenShiftProvisioner.create():             │
│   a. Build VirtualMachine spec             │
│   b. POST to Kubernetes API                │
│   c. Start VM                              │
│   d. Wait for Running                      │
│   e. Create SSH Service                    │
│   f. Get VM IP                             │
│   g. Wait for SSH ready                    │
│   h. Wait for cloud-init done              │
└─────────────┬──────────────────────────────┘
              │
              ▼
┌────────────────────────────────────────────┐
│ 4. VMs READY                               │
│ - 3 VMs running in OpenShift               │
│ - SSH accessible                           │
│ - Cloud-init complete                      │
│ - Ready for testing                        │
└────────────────────────────────────────────┘
```


---

## Reference

### Configuration Options

#### libcloud.providers.openshift-vms

| Option | Required | Default | Description |
|--------|----------|---------|-------------|
| `driver` | Yes | - | Must be "openshift" |
| `namespace` | Yes | - | Kubernetes namespace |
| `kubeconfig` | No | `~/.kube/config` | Path to kubeconfig |
| `context` | No | current | Kubeconfig context |
| `ssh_service_type` | No | NodePort | NodePort\|LoadBalancer\|ClusterIP |
| `exclude_image` | No | [] | Regex patterns to exclude images |
| `userdata` | No | {} | Per-OS cloud-init config |

#### openshift

| Option | Default | Description |
|--------|---------|-------------|
| `machine.memory` | 8Gi | RAM per VM |
| `machine.cpus` | 2 | vCPUs per VM |
| `machine.disk` | 20Gi | Root disk size |
| `volumes.count` | 0 | Additional volumes |
| `volumes.size` | 10Gi | Size per volume |

### Useful Commands

```bash
# List VMs
oc get vm -n teuthology

# Get VM details
oc describe vm test-node-001 -n teuthology

# Check VMI status
oc get vmi -n teuthology

# View console
virtctl console test-node-001 -n teuthology

# Check logs
oc logs -n teuthology virt-launcher-test-node-001-xxxxx

# Delete VM manually
oc delete vm test-node-001 -n teuthology

# Check storage
oc get pvc,datavolume -n teuthology

# Check services
oc get svc -n teuthology
```


### Test Commands

```bash
# Run unit tests
pytest teuthology/provision/cloud/test/test_openshift.py -v

# Test provider registration
python3 -c "from teuthology.provision import cloud; print(cloud.get_types())"

# Test Kubernetes connectivity
python3 -c "from kubernetes import client, config; config.load_kube_config(); print(client.CoreV1Api().list_node())"
```


### Resource Requirements

**Per VM:**
- CPU: Configurable (default 2 cores)
- Memory: Configurable (default 8Gi)
- Disk: Configurable (default 20Gi root + additional volumes)

**Cluster Recommendations:**
- 3+ worker nodes for HA
- 100Gi+ available storage
- Load balancer (optional, for LB SSH access)

---

## Quick Reference Card

```bash
# SETUP (once)
pip install -e '.[openshift]'
# Configure ~/.teuthology.yaml

# PROVISION
teuthology-lock --lock --machine-type openshift-vms --num 3

# VERIFY
oc get vm,vmi,svc -n teuthology

# SSH
NODE_IP=$(oc get nodes -o jsonpath='{.items[0].status.addresses[0].address}')
NODE_PORT=$(oc get svc test-node-001-ssh -o jsonpath='{.spec.ports[0].nodePort}')
ssh -p ${NODE_PORT} ubuntu@${NODE_IP}

# TEST
teuthology test.yaml

# CLEANUP
teuthology-lock --unlock
```


**Questions?** See the troubleshooting section or check:
- Implementation: `teuthology/provision/cloud/openshift.py`
- Tests: `teuthology/provision/cloud/test/test_openshift.py`
- Your config: `~/.teuthology.yaml`


.. _openshift-backend:

OpenShift Virtualization Backend
=================================

Provision VMs on OpenShift for Ceph testing using OpenShift Virtualization (KubeVirt).

Quick Start
-----------

Install::

    pip install -e '.[openshift]'

Configure ``~/.teuthology.yaml``::

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

Use::

    teuthology-lock --lock --machine-type openshift-vms --num 3
    teuthology test.yaml
    teuthology-lock --unlock

Prerequisites
-------------

* OpenShift 4.12+ with OpenShift Virtualization installed
* Kubeconfig with cluster access
* Service account with VM management permissions
* DataVolumes for OS images (Ubuntu, CentOS, etc.)

Installation
------------

1. Install OpenShift Virtualization operator::

    oc apply -f https://raw.githubusercontent.com/kubevirt/hyperconverged-cluster-operator/main/deploy/deploy.yaml

2. Create namespace and service account::

    oc new-project teuthology
    oc create serviceaccount teuthology -n teuthology

3. Apply RBAC (see :ref:`openshift-rbac`)

4. Create VM images::

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

5. Install Teuthology::

    pip install -e '.[openshift]'

.. _openshift-rbac:

RBAC Configuration
~~~~~~~~~~~~~~~~~~

Minimal required permissions::

    apiVersion: rbac.authorization.k8s.io/v1
    kind: Role
    metadata:
      name: teuthology-vm-manager
      namespace: teuthology
    rules:
    - apiGroups: ["kubevirt.io"]
      resources: ["virtualmachines", "virtualmachineinstances"]
      verbs: ["*"]
    - apiGroups: ["cdi.kubevirt.io"]
      resources: ["datavolumes"]
      verbs: ["*"]
    - apiGroups: [""]
      resources: ["persistentvolumeclaims", "services"]
      verbs: ["*"]

Apply with ``oc apply -f rbac.yaml``

Configuration
-------------

Basic Options
~~~~~~~~~~~~~

``libcloud.providers.<name>``

================= ========= ==================
Option            Required  Description
================= ========= ==================
driver            Yes       Must be "openshift"
namespace         Yes       Kubernetes namespace
kubeconfig        No        Path to kubeconfig (default: ~/.kube/config)
ssh_service_type  No        NodePort|LoadBalancer|ClusterIP (default: NodePort)
================= ========= ==================

``openshift``

================= ========= ==================
Option            Required  Description
================= ========= ==================
machine.memory    No        RAM per VM (default: 8Gi)
machine.cpus      No        vCPUs per VM (default: 2)
machine.disk      No        Disk size (default: 20Gi)
volumes.count     No        Additional volumes (default: 0)
volumes.size      No        Volume size (default: 10Gi)
================= ========= ==================

Advanced Configuration
~~~~~~~~~~~~~~~~~~~~~~

Multiple clusters::

    libcloud:
      providers:
        openshift-prod:
          driver: openshift
          namespace: teuthology-prod
          kubeconfig: ~/.kube/prod-config
        
        openshift-dev:
          driver: openshift
          namespace: teuthology-dev
          kubeconfig: ~/.kube/dev-config

Per-OS cloud-init::

    libcloud:
      providers:
        openshift-vms:
          userdata:
            ubuntu-22.04:
              packages: [git, python3, docker.io]
            centos-9:
              packages: [git, python3, podman]

Usage
-----

Lock VMs (automatically provisions)::

    teuthology-lock --lock --machine-type openshift-vms --num 3 \
      --owner you@example.com

Verify::

    oc get vm,vmi,svc -n teuthology

SSH to VM::

    NODE_IP=$(oc get nodes -o jsonpath='{.items[0].status.addresses[0].address}')
    NODE_PORT=$(oc get svc test-node-001-ssh -o jsonpath='{.spec.ports[0].nodePort}')
    ssh -p ${NODE_PORT} ubuntu@${NODE_IP}

Unlock (automatic cleanup)::

    teuthology-lock --unlock --owner you@example.com

How It Works
------------

1. ``teuthology-lock`` detects machine_type is cloud provider
2. Python code creates VirtualMachine via Kubernetes API
3. VM boots, cloud-init runs (3-5 minutes)
4. SSH Service created (NodePort/LoadBalancer)
5. Ready for testing

Resources created per VM:

* VirtualMachine + VirtualMachineInstance
* DataVolume + PersistentVolumeClaim (root disk)
* Service (SSH access)
* PersistentVolumeClaims (additional volumes, optional)

Troubleshooting
---------------

VM Not Creating
~~~~~~~~~~~~~~~

Check provider registered::

    python3 -c "from teuthology.provision import cloud; print(cloud.get_types())"

Check permissions::

    oc auth can-i create virtualmachines \
      --as system:serviceaccount:teuthology:teuthology -n teuthology

VM Stuck
~~~~~~~~

Check status::

    oc describe vmi test-node-001 -n teuthology
    oc get events -n teuthology --sort-by='.lastTimestamp'

Common issues:

* Insufficient cluster resources
* DataVolume not ready
* Storage class missing

SSH Fails
~~~~~~~~~

Check VM running::

    oc get vmi -n teuthology

Check Service::

    oc get svc test-node-001-ssh -n teuthology

Access console::

    virtctl console test-node-001 -n teuthology

Wait for cloud-init (5-10 minutes for package installs)

Useful Commands
---------------

::

    # VMs
    oc get vm,vmi -n teuthology
    oc describe vm <name> -n teuthology
    virtctl console <name> -n teuthology
    
    # Storage
    oc get pvc,datavolume -n teuthology
    
    # Networking
    oc get svc -n teuthology
    
    # Cleanup
    oc delete vm <name> -n teuthology

Performance
-----------

* VM ready: 3-5 minutes
* Cleanup: < 1 minute

Per VM resources (configurable): 2-8 CPUs, 8-32 GiB RAM, 20-100 GiB disk

See Also
--------

* Full guide: ``OPENSHIFT_GUIDE.md`` in repository
* Example config: ``examples/openshift_teuthology_config.yaml``
* :ref:`libcloud-backend` - General libcloud documentation
* `OpenShift Virtualization <https://docs.openshift.com/container-platform/latest/virt/about-virt.html>`_

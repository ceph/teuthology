# Teuthology Development Environment Instruction

The purpose of this guide is to help developers set
up a development environment for Teuthology. We will be using 
Docker to set up all the containers for
Postgres, Paddles, Pulpito, Beanstalk, and Teuthology.

Currently, it's possible to execute against two classes of test nodes: 

* Using containerized test nodes
  * Advantage: No need for a lab at all!
  * Disadvantage: Cannot run all Ceph tests; best for exercising the framework itself
* Using nodes from an existing lab (e.g. the Sepia lab)
  * Advantage: Can run all Ceph tests
  * Disadvantage: Requires lab access


Additionally, there are two modes of execution:
* One-shot (the default): Containers start up, schedule and run the `teuthology:no-ceph` suite, and shut down. Success or failure is indicated by the `start.sh` exit code.
* Wait: Containers start up, and `teuthology-dispatcher` is started, but no jobs are scheduled. Runs until the user presses Ctrl-C or `docker compose down` is run.
  
The teuthology container will be built with code from the repository clone that's currently in use.

## Prerequisites

### Installing and Running Docker

For Docker installation see: 
https://docs.docker.com/get-docker/

### Using Containerized Nodes

There's nothing special to do; see the Running Tests section below.

### Using an Existing Lab

This document assumes you have access to the lab that you intend to use, and that you're already familiar with its VPN and SSH infrastructure.

Depending on your local operating system, it may be necessary to connect to the VPN before starting Docker.

#### Using your SSH private key

In your local shell, simply:
```bash
export SSH_PRIVKEY_PATH=$HOME/.ssh/id_rsa
```
The teuthology container will write it to a file at runtime.

#### Reserving Machines in the Lab

Taking the Sepia lab as an example once again, most users will want to do something like:

```bash
ssh teuthology.front.sepia.ceph.com
~/teuthology/virtualenv/bin/teuthology-lock \
  --lock-many 1 \
  --machine-type smithi \
  --desc "teuthology dev testing"
```

When you are done, don't forget to unlock!

#### Using Lab Machines

Once you have your machines locked, you need to provide a list of their hostnames and their machine type:

```bash
export TESTNODES="smithi999.front.sepia.ceph.com,smithi123.front.sepia.ceph.com"
export MACHINE_TYPE="smithi"
```

If the lab uses a "secrets" or "inventory" repository for [ceph-cm-ansible](https://github.com/ceph/ceph-cm-ansible), you'll need to provide a URL for that. In Sepia:
```bash
export ANSIBLE_INVENTORY_REPO="https://github.com/ceph/ceph-sepia-secrets"
```
This repo will be cloned locally, using your existing `git` configuration, and copied into the teuthology container at build time.

## Running Tests

To run the default `teuthology:no-ceph` suite in one-shot mode:
```bash
./start.sh
```

To run in wait mode:
```bash
TEUTHOLOGY_WAIT=1 ./start.sh
```

To schedule tests in wait mode:
```bash
docker exec docker-compose_teuthology_1 /venv/bin/teuthology-suite ...
```

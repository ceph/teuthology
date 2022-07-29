#!/bin/bash
set -e
export TEUTHOLOGY_BRANCH=${TEUTHOLOGY_BRANCH:-$(git branch --show-current)}
export TEUTH_BRANCH=${TEUTHOLOGY_BRANCH}
if [ -n "$ANSIBLE_INVENTORY_REPO" ]; then
    basename=$(basename $ANSIBLE_INVENTORY_REPO | cut -d. -f1)
    if [ ! -d "$basename" ]; then
        git clone \
            --depth 1 \
            $ANSIBLE_INVENTORY_REPO
    fi
    mkdir -p teuthology/ansible_inventory
    cp -rf $basename/ansible/ teuthology/ansible_inventory
    if [ ! -d teuthology/ansible_inventory/hosts ]; then
        mv -f teuthology/ansible_inventory/inventory teuthology/ansible_inventory/hosts
    fi
fi
# Make the hosts and secrets directories, so that the COPY instruction in the 
# Dockerfile does not cause a build failure when not using this feature.
mkdir -p teuthology/ansible_inventory/hosts teuthology/ansible_inventory/secrets

if [ -n "$CUSTOM_CONF" ]; then
    cp "$CUSTOM_CONF" teuthology/
fi

# Generate an SSH keypair to use if necessary
if [ ! -f id_rsa ]; then
    ssh-keygen -t rsa -N '' -f id_rsa
fi

if [ -z "$TEUTHOLOGY_WAIT" ]; then
    DC_EXIT_FLAG='--abort-on-container-exit --exit-code-from teuthology'
    DC_AUTO_DOWN_CMD='docker-compose down'
fi
export TEUTHOLOGY_WAIT

trap "docker-compose down" SIGINT
docker-compose up \
    --build \
    $DC_EXIT_FLAG
$DC_AUTO_DOWN_CMD

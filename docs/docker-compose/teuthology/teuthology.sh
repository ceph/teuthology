#!/usr/bin/bash
# We don't want -x yet, in case the private key is sensitive
if [ -n "$SSH_PRIVKEY_FILE" ]; then
    echo "$SSH_PRIVKEY" > $HOME/.ssh/$SSH_PRIVKEY_FILE
fi
source /teuthology/virtualenv/bin/activate
set -x
if [ -n "$TESTNODES" ]; then
    for node in $(echo $TESTNODES | tr , ' '); do
        teuthology-update-inventory -m $MACHINE_TYPE $node
    done
    CUSTOM_CONF=${CUSTOM_CONF:-}
else
    CUSTOM_CONF=/teuthology/containerized_node.yaml
fi
export MACHINE_TYPE=${MACHINE_TYPE:-testnode}
if [ -z "$TEUTHOLOGY_WAIT" ]; then
    teuthology-suite -v \
        --teuthology-branch $TEUTH_BRANCH \
        --ceph-repo https://github.com/ceph/ceph.git \
        --suite-repo https://github.com/ceph/ceph.git \
        -c main \
        -m $MACHINE_TYPE \
        --limit 1 \
        -n 100 \
        --suite teuthology:no-ceph \
        --filter-out "libcephfs,kclient,stream,centos,rhel" \
        -d ubuntu -D 20.04 \
        --suite-branch main \
        --subset 9000/100000 \
        -p 75 \
        --seed 349 \
        --force-priority \
        $CUSTOM_CONF
    DISPATCHER_EXIT_FLAG='--exit-on-empty-queue'
fi
teuthology-dispatcher -v \
    --log-dir /teuthology/log \
    --tube $MACHINE_TYPE \
    $DISPATCHER_EXIT_FLAG
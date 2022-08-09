#!/usr/bin/bash
set -e
source /teuthology/virtualenv/bin/activate
set -x
cat /run/secrets/id_rsa > $HOME/.ssh/id_rsa
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
    if [ -n "$TEUTH_BRANCH" ]; then
      TEUTH_BRANCH_FLAG="--teuthology-branch $TEUTH_BRANCH"
    fi
    teuthology-suite -v \
        $TEUTH_BRANCH_FLAG \
        --ceph-repo https://github.com/ceph/ceph.git \
        -c main \
        -m $MACHINE_TYPE \
        --limit 1 \
        -n 100 \
        --suite ${TEUTHOLOGY_SUITE:-teuthology:no-ceph} \
        --filter-out "libcephfs,kclient" \
        -d centos -D 8.stream \
        --suite-branch osd-containers \
        -p 75 \
        --seed 349 \
        --force-priority \
        $CUSTOM_CONF
    DISPATCHER_EXIT_FLAG='--exit-on-empty-queue'
    teuthology-queue -m $MACHINE_TYPE -s | \
      python3 -c "import sys, json; assert json.loads(sys.stdin.read())['count'] > 0, 'queue is empty!'"
fi
teuthology-dispatcher -v \
    --log-dir /teuthology/log \
    --tube $MACHINE_TYPE \
    $DISPATCHER_EXIT_FLAG

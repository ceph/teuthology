#!/usr/bin/bash
set -e
source /teuthology/virtualenv/bin/activate
set -x
cat /run/secrets/id_rsa > $HOME/.ssh/id_rsa
if [ -n "$TEUTHOLOGY_TESTNODES" ]; then
    for node in $(echo $TEUTHOLOGY_TESTNODES | tr , ' '); do
        teuthology-update-inventory -m "$TEUTHOLOGY_MACHINE_TYPE" "$node"
    done
    TEUTHOLOGY_CONF=${TEUTHOLOGY_CONF:-}
else
    TEUTHOLOGY_CONF=/teuthology/containerized_node.yaml
fi
export TEUTHOLOGY_MACHINE_TYPE=${TEUTHOLOGY_MACHINE_TYPE:-testnode}
if [ "$TEUTHOLOGY_SUITE" != "none" ]; then
    if [ -n "$TEUTHOLOGY_BRANCH" ]; then
      TEUTH_BRANCH_FLAG="--teuthology-branch $TEUTHOLOGY_BRANCH"
    fi
    teuthology-suite -v \
        $TEUTH_BRANCH_FLAG \
        -m "$TEUTHOLOGY_MACHINE_TYPE" \
        --newest 100 \
        --ceph "${TEUTHOLOGY_CEPH_BRANCH:-main}" \
        --ceph-repo "${TEUTHOLOGY_CEPH_REPO:-https://github.com/ceph/ceph.git}" \
        --suite "${TEUTHOLOGY_SUITE:-teuthology:no-ceph}" \
        --suite-branch "${TEUTHOLOGY_SUITE_BRANCH:-main}" \
        --suite-repo "${TEUTHOLOGY_SUITE_REPO:-https://github.com/ceph/ceph.git}" \
        --filter-out "libcephfs,kclient" \
        --force-priority \
        --seed 349 \
        ${TEUTHOLOGY_SUITE_EXTRA_ARGS} \
        $TEUTHOLOGY_CONF
    DISPATCHER_EXIT_FLAG='--exit-on-empty-queue'
    teuthology-queue -m $TEUTHOLOGY_MACHINE_TYPE -s | \
      python3 -c "import sys, json; assert json.loads(sys.stdin.read())['count'] > 0, 'queue is empty!'"
fi
teuthology-dispatcher -v \
    --log-dir /teuthology/log \
    --tube "$TEUTHOLOGY_MACHINE_TYPE" \
    $DISPATCHER_EXIT_FLAG

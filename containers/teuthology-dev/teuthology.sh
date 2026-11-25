#!/usr/bin/bash
set -e
PATH=$PATH:/teuthology/.venv/bin
set -x
cat /run/secrets/id_rsa > $HOME/.ssh/id_rsa
if [ -n "$TEUTHOLOGY_TESTNODES" ]; then
    for node in $(echo $TEUTHOLOGY_TESTNODES | tr , ' '); do
        teuthology-update-inventory -m "$TEUTHOLOGY_MACHINE_TYPE" "$node"
    done
    # teuthology-update-inventory records each node's os_version as major.minor
    # (e.g. Rocky "10.2"), but suites request the major version (rocky "10", and
    # Shaman builds are rocky/10). For fixed, non-reimaged testnodes that would
    # make `lock_many` fail with "0 nodes available". Normalize every node of
    # this machine_type in paddles to its major os_version so the lock matches.
    python3 - "$TEUTHOLOGY_MACHINE_TYPE" <<'PY'
import sys, json, urllib.request
machine_type = sys.argv[1]
base = "http://paddles:8080"
nodes = json.load(urllib.request.urlopen(f"{base}/nodes/?machine_type={machine_type}"))
for n in nodes:
    ver = n.get("os_version") or ""
    major = ver.split(".")[0]
    if major and major != ver:
        body = json.dumps({"os_version": major}).encode()
        req = urllib.request.Request(
            f"{base}/nodes/{n['name']}/", data=body,
            headers={"Content-Type": "application/json"}, method="PUT")
        urllib.request.urlopen(req)
        print(f"normalized os_version for {n['name']}: {ver} -> {major}")
PY
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

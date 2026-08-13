.. _node_health:

===================
Marking Nodes Down
===================

Every node in the lock server (paddles) has an ``up`` flag. A node that is
marked down is never handed out to a job, so a broken machine stops eating
scheduled jobs until someone looks at it. Nodes are marked down by hand with
``teuthology-lock --update --status down <node>``, and automatically by
``teuthology-supervisor`` in the two cases described below.

All of this happens in the supervisor process, not in the job process. Tasks
never talk to paddles about node status: a job should not depend on the lock
server being reachable, and the supervisor is what owns the nodes for the
duration of a job anyway.

Repeated reimaging failures
===========================

If reimaging a node fails, the supervisor asks paddles for that node's last 10
jobs. If all 10 of them failed to reimage, the node is marked down with the
description ``reimage failed 10 times``. See
``check_for_reimage_failures_and_mark_down()`` in
``teuthology/dispatcher/supervisor.py``.

Failures reported by ansible
============================

Some ansible failures tell us right away that the node itself is broken - a
disk that is missing or dead, for example. Waiting for that node to fail ten
more jobs is a waste, so the supervisor marks it down as soon as it sees one.

Which failures count is up to the site config; nothing is marked down unless
``disable_targets.ansible_failure_patterns`` says so.

How it works
------------

#. The ``ansible`` task sets ``ANSIBLE_FAILURE_LOG`` when it runs
   ``ansible-playbook``. ceph-cm-ansible's ``failure_log`` callback plugin
   (``callback_plugins/failure_log.py``) writes every task failure to that
   file as YAML.
#. When the playbook fails, the task archives the log to
   ``ansible_failures.yaml`` in the job's archive directory.
#. After the job process exits, the supervisor reads that file back and passes
   it, along with the patterns configured for the job's machine type, to
   ``FailureAnalyzer.find_matching_failures()`` in
   ``teuthology/task/ansible.py``.
#. Any node whose failure message matches is marked down, as long as it is one
   of the job's own targets. This is
   ``check_for_ansible_failures_and_mark_down()`` in
   ``teuthology/dispatcher/supervisor.py``.

Nodes are always marked down before they're unlocked, so another job can't grab
one in the meantime. The description is set afterwards, to ``ansible failure:
<msg>``, so the reason shows up in ``teuthology-lock --list`` - it can't be set
any earlier because ``unlock_targets()`` matches on it. A node that was left
locked on purpose (``unlock_on_failure: false``) keeps its description so it
can still be unlocked later.

Expected format
---------------

The failure log is a YAML document keyed by hostname, with each value being the
ansible result dict for the failed task. Only the ``msg`` field is examined,
either on the record itself or on each entry of its ``results`` list::

    trial007.front.sepia.ceph.com:
      _ansible_no_log: false
      changed: false
      msg: 'Wanted 2 disks of ~1700 GB (rotational=False), but only matched 1: [''nvme1n1'']'

The callback plugin records the result, not the name of the task that produced
it, so matching is done on the message text. Whitespace in ``msg`` is collapsed
first, because ansible wraps long messages across lines.

Configuring the patterns
------------------------

``disable_targets.ansible_failure_patterns`` in :ref:`site_config` maps a
machine type to a list of regular expressions, matched case-insensitively
against the message. A machine type with no patterns never gets marked down
this way. This is what we use in sepia::

    disable_targets:
      ansible_failure_patterns:
        # "Ensure we found enough OSD disks" in ceph-cm-ansible's
        # roles/testnode/tasks/configure_lvm.yml
        trial: &missing_osd_devices
          - 'Wanted \d+ disks? of .+ but only matched \d+'
        gibba: *missing_osd_devices
        smithi: *missing_osd_devices

Use single quotes, or YAML will choke on the backslashes.

Keep in mind that a pattern ties us to the exact wording of a task in
ceph-cm-ansible: reword the task, and the pattern needs the same change. Only
add patterns for failures that really do mean the node is broken - a node
marked down stays down until someone brings it back up.

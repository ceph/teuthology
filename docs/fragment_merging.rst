.. _fragment_merging:

================
Fragment Merging
================

Once the matrix of YAML fragments is constructed by teuthology, the fragments
must be merged together and processed. Up until 2022, this merging process was
static: all of the YAML fragments were joined together in lexicographical order
with duplicate fragment members *deep merged* together (e.g. the "tasks"
array). Now, fragments and entire job specifications can be dynamically changed
or dropped according to Lua scripts embedded in the fragment.

premerge Scripts
================

The first phase of script execution takes place in the *premerge* step.  Each
fragment may have its own premerge script which is run before the fragment is
merged. The script is defined as follows::

    teuthology:
      premerge: |
                if yaml.os_type == 'ubuntu' then reject() end

Again, this script will run prior to the YAML fragment merging into the
complete YAML specification for a job. The script has access to the YAML job
description (the ``yaml`` variable) generated so far from the fragments merged
prior to this one (remember: fragments are ordered lexicographically).  In the
above case, the ``os_type`` is checked such that the fragment is dropped
(rejected) if the job is configured to run on Ubuntu. Note: this does not
account for a jobs' default os_type which is not yet known; only the
``os_type`` specified by the YAML fragments is usable in these scripts.

When run in the premerge step, the ``reject`` function causes the fragment to be
dropped from the job: none of its YAML will be merged into the job. The
``accept`` function causes the fragment to be merged. The default action is to
accept the fragment.

postmerge Scripts
=================

The second phase of script execution is the *postmerge* step run after all
fragments have been merged. At this point, the YAML specification for the job
is all but complete. Scripts can now make final modifications to the YAML or
reject the job completely causing it to be removed from the list of jobs to be
scheduled.  An example postmerge script::

    teuthology:
      postmerge:
        - if yaml.os_type == "ubuntu" then reject() end

This script is the same but has a different effect: after combining all the
YAML fragments for a job, if the os_type is "ubuntu" then the entire job is
dropped (filtered out / rejected). postmerge scripts are also specified as a
list of strings in the ``teuthology.postmerge`` array which may span multiple
fragments. During the postmerge step, all of these strings are concatenated and
then executed as a single script. You may use this to define variables,
functions, or anything else you need.

Scripts have access to the entire yaml object and may use it to do advanced
checks. It is also possible to programatically change the YAML definition::

    teuthology:
      postmerge:
        - |
          -- use the lupa "attrgetter" to fetch attrs not items via Lua's indexing
          local attr = py_attrgetter
          local tasks = py_list()
          for i = 1, 3 do
            local task = py_dict()
            task.exec = py_dict()
            task.exec["mon.a"] = py_list()
            attr(task.exec["mon.a"]).append("echo "..i)
            attr(tasks).append(task)
          end
          deep_merge(yaml.tasks, tasks)


This will be as if the YAML fragment contained::

    tasks:
      - exec:
          mon.a:
            - echo 1
      - exec:
          mon.a:
            - echo 2
      - exec:
          mon.a:
            - echo 3

Except the tasks are appended to the end after all fragments have been loaded.
This is opposed to the normal mode of the tasks appending when the fragment is
merged (in lexicographic order).

API
===

Scripts are well sandboxed with access to a small selection of the Lua builtin
libraries. There is also access to some Python/Lupa specific functions which
are prefixed with ``py_``. No I/O or other system functions permitted.

The Lua builtins available include::

    assert
    error
    ipairs
    pairs
    tonumber
    tostring

Additionally, the Python functions exposed via Lupa include::

    py_attrgetter = python.as_attrgetter
    py_dict = python.builtins.dict
    py_list = python.builtins.list
    py_tuple = python.builtins.tuple
    py_enumerate = python.enumerate
    py_iterex = python.iterex
    py_itemgetter = python.as_itemgetter

These are all prefixed with ``py_``. See the `Lupa documentation
<https://pypi.org/project/lupa/>`__ for more information.

Finally, teuthology exposes the following functions for scripts:

::

	accept()

The ``accept`` function stops script execution and causes the fragment to be
merged (premerge script) or the job to be accepted for scheduling (postmerge
script). The default action of a script is to accept.

::

	reject()

The ``reject`` function stops script execution and causes the fragment to be
dropped (premerge script) or the job to be rejected for scheduling (postmerge
script).


::

	deep_merge(a, b)

The ``deep_merge`` function comes from the teuthology code base. It's used to
merge YAML structures. It's provided for convenience to ease a common operation
on Python (yaml) objects. The function merges ``b`` into ``a``.


::

	log

The ``log`` Python class (object) allows Lua to leave debugging in the
``teuthology-suite`` log.

::

	yaml_load(str)

This function loads the YAML string and returns it as a Python structure (of
dicts, lists, etc.).


Concrete Example
================

The
`fs:upgrade:mds_upgrade_sequence <https://github.com/ceph/ceph/tree/edd4e553efd3934292c768b39d9ca1ff8d920ef1/qa/suites/fs/upgrade/mds_upgrade_sequence>`__
sub-suite tests that the `upgrade sequence for CephFS <https://docs.ceph.com/en/quincy/cephfs/upgrading/>`__
is followed when the cluster is managed by cephadm. The most interesting set of YAML in this suite is in ``tasks/``::

    %
    0-from/
      pacific.yaml
      v16.2.4.yaml
    1-volume/
      0-create.yaml
      1-ranks/
        1.yaml
        2.yaml
      2-allow_standby_replay/
        yes.yaml
        no.yaml
      3-inline
        yes.yaml
        no.yaml
      4-verify.yaml
    2-client.yaml
    3-upgrade-with-workload.yaml
    4-verify.yaml

Basically: upgrade the cluster from one of two versions of pacific, create a
volume (fs), possibly turn some knobs in the MDSMap, and verify the upgrade
completes correctly. This works well and is an excellent example of effective
matrix construction for testing.

The feature we want to test is a `new upgrade procedure
<https://tracker.ceph.com/issues/55715>`__ for the MDS. It only requires
"failing" the file systems which removes all running MDS from the MDSMap and
prevents any MDS from "joining" the file system (becoming active).  The upgrade
procedure then upgrades the packages, restarts the MDS, then sets the file
system to allow MDS to join (become active). Ideally, we could modify the
matrix this way::

    %
    fail_fs/
      yes.yaml
      no.yaml
    tasks/
      %
      0-from/
        pacific.yaml
        v16.2.4.yaml
      1-volume/
        0-create.yaml
        1-ranks/
          1.yaml
          2.yaml
        2-allow_standby_replay/
          yes.yaml
          no.yaml
        3-inline
          yes.yaml
          no.yaml
        4-verify.yaml
      2-client.yaml
      3-upgrade-with-workload.yaml
      4-verify.yaml

So we just change (or don't change) a single config option in ``fail_fs``
which turns on that upgrade path::

    overrides:
      ceph:
        conf:
          mgr:
            mgr/orchestrator/fail_fs: true

The complication however is that this new ``fail_fs`` config option is only
understood by the newest mgr (the ``main`` branch or possibly the latest
pacific or quincy)... and the mons won't let you set a config unknown to exist.
So, we must do a staggered upgrade to test this new upgrade path: the mgr must
be upgraded, a config option set to change how MDS upgrades are performed, and
then the cluster may continue upgrading.

**Here's the problem**: the mgr only knows how to do a staggered upgrade
beginning with v16.2.10. So, we can't even upgrade from v16.2.4 to test this
new upgrade path.

(One might be tempted to remove v16.2.4 as an upgrade path in
QA but we must continue testing this due to major (breaking) changes in the
MDSMap across v16.2.4 and v16.2.5. It would not be acceptable to remove it.)

To get around this awkward problem, we can use the new scripting of fragment
merging to control whether this ``mgr/orchestrator/fail_fs`` config option is
set. If we are upgrading from v16.2.4, then drop any jobs in the matrix that
also want to test this new MDS upgrade procedure. So we modify the yaml
fragments as::

  fail_fs/no.yaml:
    teuthology:
      variables:
        fail_fs: false
    overrides:
      ceph:
        conf:
          mgr:
            mgr/orchestrator/fail_fs: false

  fail_fs/yes.yaml:
    teuthology:
      variables:
        fail_fs: true
    overrides:
      ceph:
        conf:
          mgr:
            mgr/orchestrator/fail_fs: true

  tasks/0-from/v16.2.4.yaml:
    teuthology:
      postmerge:
        - if yaml.teuthology.variables.fail_fs then reject() end
    ...


We have set a variable (for ease of programming) in a
``teuthology['variables']`` dictionary which indicates whether the merged YAML
includes the ``fail_fs`` feature or not. Then, if we're upgrading from v16.2.4
and that variable is true, drop that set of jobs in the matrix. This
effectively prevents any testing of this upgrade procedure when the cluster is
upgraded from v16.2.4.

Note: the final merged QA code also includes a YAML fragment to perform a
staggered upgrade of the ``ceph-mgr``. This YAML fragment is dropped using a
premerge script if we're not testing ``fail_fs``; there is no reason to do a
staggered upgrade if we don't need to. See the code if you'd like to see how
that works!


Why Lua
=======

Lua is a small, extensible, and easily sandboxed scripting environment. Python
is difficult to sandbox correctly and its restrictions make it difficult to
embed in YAML (like indentation for code blocks).


Python-Lua
==========

`Lupa <https://pypi.org/project/lupa/>`__ is the most recent derivative of the
"lunatic" python project. It allows for trivial cross-talk between Python and
Lua worlds.

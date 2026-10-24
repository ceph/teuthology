.. _testplans:

=========
Testplans
=========

A testplan is a YAML file that bundles several suite runs into one canned
recipe, for example "what we run on every PR" or "what we run after a CI
build". Plans contain only *what* to test. *Which build* to test and *where*
to run it come from the command line. That way the same plan works with any
ceph revision, in any lab, including on a laptop with ceph-devstack.

Official plans live in the suite repo (ceph.git) under ``qa/testplans/``. A
plan is an ordinary YAML file, so you can also keep your own anywhere.

Format
======

::

    name: pr-smoke
    description: Fast sanity coverage for PRs
    defaults:
      limit: 20
    runs:
    - suite: rados
      subset: 1/100
      filter: [thrash]
    - suite: rbd/basic
      label: rbd_ubuntu
      distro: ubuntu
      distro_version: "22.04"

Top-level keys:

``name`` (required)
    Short name for the plan. Letters, digits, ``.``, ``_`` and ``-``.
``description``
    What the plan is for. ``teuthology-testplan list`` shows the first line.
``defaults``
    Settings applied to every run, unless the run sets them itself.
``runs`` (required)
    The runs to schedule. Each entry is exactly one suite and becomes exactly
    one teuthology run.

Keys for each run:

``suite`` (required)
    The suite to run, relative to the suites directory, e.g. ``rados`` or
    ``rbd/basic``.
``label``
    Short identifier for the run, unique within the plan. Starts with a
    letter, then letters, digits, ``.`` and ``_``.

Settings allowed both in ``defaults`` and in each run. These have the same
meaning as the ``teuthology-suite`` options of the same name:

``subset``
    Piece ``N`` of ``M`` of the suite, as ``N/M``.
``no_nested_subset``
    ``true`` to skip nested suite subsets.
``seed``
    Random seed (0 or greater). Leave it out to pick a random one each time the
    plan is scheduled. The seed used is logged and recorded in each job.
``limit``
    Schedule at most this many jobs; ``0`` means no limit.
``filter``, ``filter_out``, ``filter_all``
    Keywords, as a list or as a comma-separated string.
``filter_fragments``
    ``true`` to also match filters against yaml fragment contents.
``distro``, ``distro_version``
    The OS to run on. Both are optional, but ``distro_version`` needs a
    ``distro`` and must be a version or codename teuthology knows for it.
    Quote versions (``"22.04"``) so YAML doesn't read them as numbers.
    ``os_type`` and ``os_version`` are accepted as aliases.

Keys may be written with ``-`` instead of ``_``. Anything else is an error.
That includes settings tied to a build or a lab, such as ``machine_type``,
branches, sha1s and ``priority``, which you pass on the command line instead.

Commands
========

``teuthology-testplan run <plan>``
    Schedules one run per entry. ``<plan>`` is a file path, or a plan name such
    as ``pr-smoke``, which is looked up as ``qa/testplans/pr-smoke.yaml`` in
    the suite repo checkout being tested. The build options (``-c``, ``-S``,
    ``--suite-branch``, ...), lab options (``-m``, ``--arch``) and scheduler
    options (``-p``, ``--owner``, ...) work the same way as in
    ``teuthology-suite``.

    The plan is fully checked before anything is scheduled. Every run tests
    the same ceph and teuthology revisions and uses the same suite checkout.
    ``--job-threshold``, the priority checks and the missing-packages check
    apply to the whole plan, so either every run is scheduled or none is.
    ``--newest`` is not supported, because it would let runs of the same plan
    test different builds.

``teuthology-testplan show <plan>``
    Shows each run with defaults applied, and roughly how many jobs it would
    schedule. Counts can't account for missing packages, jobs excluded by
    arch at scheduling time, or seeds chosen at random when scheduling.

``teuthology-testplan list``
    Lists the plans in the suite repo.

``teuthology-testplan validate <file>...``
    Checks plan files without using the network. With ``--suite-dir``, it
    also checks that the suites they name exist, and with ``--jobs``, it
    builds each run's jobs and warns about runs with none (``--strict`` turns
    that into an error). For example, from the top of a ceph.git checkout::

        teuthology-testplan validate --suite-dir . --strict qa/testplans/*.yaml

Errors are reported as ``file:line: key: message``. All problems in a file
are reported at once::

    qa/testplans/pr-smoke.yaml:8: runs[0].subset: expected 'N/M' with 0 <= N < M, got '5/3'
    qa/testplans/pr-smoke.yaml:10: runs[0].machine_type: 'machine_type' can't be set in a testplan; pass --machine-type to 'teuthology-testplan run' instead

Run names and job metadata
==========================

Runs from a plan share one timestamp. If a plan runs the same suite more than
once, each of those runs gets its label, or its position in the plan, added to
the suite part of the run name, e.g. ``...-rados.second-main-...``. Other run
names look exactly like those from ``teuthology-suite``.

Every job records where it came from::

    testplan:
      name: pr-smoke
      sha256: <sha256 of the plan file>
      run: 1          # position in 'runs'
      label: second   # if the run has one

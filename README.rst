===================================================
`Teuthology` -- The Ceph integration test framework
===================================================

``teuthology`` is an automation framework for `Ceph test
<https://github.com/ceph/ceph>`__, written in `Python
<https://www.python.org/>`__. It is used to run the vast majority of its tests
and was developed because the unique requirements of testing such a highly
distributed system with active kernel development meant that no other framework
existed that could do its job.

The name '`teuthology <http://en.wikipedia.org/wiki/Teuthology>`__' refers to the
study of cephalopods.


Overview
========

The general mode of operation of ``teuthology`` is to remotely orchestrate
operations on remote hosts over SSH, as implemented by `Paramiko
<http://www.lag.net/paramiko/>`__. A typical `job` consists of multiple nested
`tasks`, each of which perform operations on a remote host over the network.

When testing, it is common to group many `jobs` together to form a `test run`.


Provided Utilities
==================
* ``teuthology`` - Run individual jobs
* ``teuthology-coverage`` - Analyze code coverage via lcov
* ``teuthology-kill`` - Kill running jobs or entire runs
* ``teuthology-lock`` - Lock, unlock, and update status of machines
* ``teuthology-ls`` - List job results by examining an archive directory
* ``teuthology-nuke`` - Attempt to return a machine to a pristine state
* ``teuthology-queue`` - List, or delete, jobs in the queue
* ``teuthology-report`` - Submit test results to a web service (we use `paddles <https://github.com/ceph/paddles/>`__)
* ``teuthology-results`` - Examing a finished run and email results
* ``teuthology-schedule`` - Schedule a single job
* ``teuthology-suite`` - Schedule a full run based on a suite (see `suites` in `ceph-qa-suite <https://github.com/ceph/ceph-qa-suite>`__)
* ``teuthology-updatekeys`` - Update SSH host keys for a mchine
* ``teuthology-worker`` - Worker daemon to monitor the queue and execute jobs

For a description of the distinct services that utilities interact with see
:ref:`components`.

Installation
============

See :ref:`installation_and_setup`.


Infrastructure
==============

These examples in this document are based on the lab machine configuration used
by the Red Hat Ceph development and quality assurance teams (see
:ref:`lab_setup`). Other instances of a Ceph Lab being used in a
development or testing environment may differ from these examples.


Test configuration
==================

An integration test run takes three items of configuration:

- ``targets``: what hosts to run on; this is a dictionary mapping
  hosts to ssh host keys, like:
  "username@hostname.example.com: ssh-rsa long_hostkey_here"
  It is possible to configure your installation so that if the targets line
  and host keys are omitted and teuthology is run with the --lock option,
  then teuthology will grab available machines from a pool of available
  test machines.
- ``roles``: how to use the hosts; this is a list of lists, where each
  entry lists all the roles to be run on a single host; for example, a
  single entry might say ``[mon.1, osd.1]``
- ``tasks``: how to set up the cluster and what tests to run on it;
  see below for examples

The format for this configuration is `YAML <http://yaml.org/>`__, a
structured data format that is still human-readable and editable.

For example, a full config for a test run that sets up a three-machine
cluster, mounts Ceph via ``ceph-fuse``, and leaves you at an interactive
Python prompt for manual exploration (and enabling you to SSH in to
the nodes & use the live cluster ad hoc), might look like this::

    roles:
    - [mon.0, mds.0, osd.0]
    - [mon.1, osd.1]
    - [mon.2, client.0]
    targets:
        ubuntu@host07.example.com: ssh-rsa host07_ssh_key
        ubuntu@host08.example.com: ssh-rsa host08_ssh_key
        ubuntu@host09.example.com: ssh-rsa host09_ssh_key
    tasks:
    - install:
    - ceph:
    - ceph-fuse: [client.0]
    - interactive:

The number of entries under ``roles`` and ``targets`` must match.

Note the colon after every task name in the ``tasks`` section. Also note the
dashes before each task. This is the YAML syntax for an ordered list and
specifies the order in which tasks are executed.

The ``install`` task needs to precede all other tasks.

The listed targets need resolvable hostnames. If you do not have a DNS server
running, you can add entries to ``/etc/hosts``. You also need to be able to SSH
in to the listed targets without passphrases, and the remote user needs to have
passwordless `sudo` access. Note that the ssh keys at the end of the
``targets`` entries are the public ssh keys for the hosts.  These are
located in /etc/ssh/ssh_host_rsa_key.pub

If you had save the above file as ``example.yaml``, you could run
teuthology on it by saying::

    ./virtualenv/bin/teuthology example.yaml

You can also pass the ``-v`` option, for more verbose execution. See
``teuthology --help`` for more.


Multiple config files
---------------------

You can pass multiple files as arguments to teuthology. Each one
will be read as a config file, and their contents will be merged. This
allows you to share definitions of what a "simple 3 node cluster"
is. The source tree comes with ``roles/3-simple.yaml``, so we could
skip the ``roles`` section in the above ``example.yaml`` and then
run::

    ./virtualenv/bin/teuthology roles/3-simple.yaml example.yaml


Reserving target machines
-------------------------

Teuthology automatically locks nodes for you if you specify the
``--lock`` option. Without this option, you must specify machines to
run on in a ``targets.yaml`` file, and lock them using
teuthology-lock.

Note that the default owner of a machine is of the form: USER@HOST where USER
is the user who issued the lock command and host is the machine on which the
lock command was run.

You can override this with the ``--owner`` option when running
teuthology or teuthology-lock.

With teuthology-lock, you can also add a description, so you can
remember which tests you were running. This can be done when
locking or unlocking machines, or as a separate action with the
``--update`` option. To lock 3 machines and set a description, run::

    ./virtualenv/bin/teuthology-lock --lock-many 3 --desc 'test foo'

If machines become unusable for some reason, you can mark them down::

    ./virtualenv/bin/teuthology-lock --update --status down machine1 machine2

To see the status of all machines, use the ``--list`` option. This can
be restricted to particular machines as well::

    ./virtualenv/bin/teuthology-lock --list machine1 machine2


Choosing machines for a job
---------------------------

It is possible to run jobs against machines of one or more  ``machine_type``
values. It is also possible to tell ``teuthology`` to only select those
machines which match the following criteria specified in the job's YAML:

* ``os_type`` (e.g. 'rhel', 'ubuntu')
* ``os_version`` (e.g. '7.0', '14.04')
* ``arch`` (e.g. 'x86_64')


Tasks
=====

A task is a Python module in the ``teuthology.task`` package, with a
callable named ``task``. It gets the following arguments:

- ``ctx``: a context that is available through the lifetime of the
  test run, and has useful attributes such as ``cluster``, letting the
  task access the remote hosts. Tasks can also store their internal
  state here. (TODO beware of namespace collisions.)
- ``config``: the data structure after the colon in the config file,
  e.g. for the above ``ceph-fuse`` example, it would be a list like
  ``["client.0"]``.

Tasks can be simple functions, called once in the order they are
listed in ``tasks``. But sometimes, it makes sense for a task to be
able to clean up after itself; for example, unmounting the filesystem
after a test run. A task callable that returns a Python `context
manager
<http://docs.python.org/library/stdtypes.html#typecontextmanager>`__
will have the manager added to a stack, and the stack will be unwound
at the end of the run. This means the cleanup actions are run in
reverse order, both on success and failure. A nice way of writing
context managers is the ``contextlib.contextmanager`` decorator; look
for that string in the existing tasks to see examples, and note where
they use ``yield``.

Further details on some of the more complex tasks such as install or workunit
can be obtained via python help. For example::

    >>> import teuthology.task.workunit
    >>> help(teuthology.task.workunit)

displays a page of more documentation and more concrete examples.

Some of the more important / commonly used tasks include:

* ``ansible``: Run the ansible task.
* ``install``: by default, the install task goes to gitbuilder and installs the
  results of the latest build. You can, however, add additional parameters to
  the test configuration to cause it to install any branch, SHA, archive or
  URL. The following are valid parameters.

- ``branch``: specify a branch (bobtail, cuttlefish...)
- ``flavor``: specify a flavor (next, unstable...). Flavors can be thought of
  as subsets of branches.  Sometimes (unstable, for example) they may have a
  predefined meaning.
- ``project``: specify a project (ceph, samba...)
- ``sha1``: install the build with this sha1 value.
- ``tag``: specify a tag/identifying text for this build (v47.2, v48.1...)

* ``ceph``: Bring up Ceph

* ``overrides``: override behavior. Typically, this includes sub-tasks being
  overridden. Overrides technically is not a task (there is no 'def task' in
  an overrides.py file), but from a user's standpoint can be described as
  behaving like one.
  Sub-tasks can nest further information.  For example, overrides
  of install tasks are project specific, so the following section of a yaml
  file would cause all ceph installation to default into using the cuttlefish
  branch::

    overrides:
      install:
        ceph:
          branch: cuttlefish

* ``workunit``: workunits are a way of grouping tasks and behavior on targets.
* ``sequential``: group the sub-tasks into a unit where the sub-tasks run
  sequentially as listed.
* ``parallel``: group the sub-tasks into a unit where the sub-task all run in
  parallel.

Sequential and parallel tasks can be nested.  Tasks run sequentially if not
specified.

The above list is a very incomplete description of the tasks available on
teuthology. The teuthology/task subdirectory contains the teuthology
specific python files that implement tasks.

Extra tasks used by teuthology can be found in ceph-qa-suite/tasks.  These
tasks are not needed for teuthology to run but do test specific independent
features.  A user who wants to define a test for a new feature can implement
new tasks in this directory.

Many of these tasks are used to run shell scripts that are defined in the
ceph/ceph-qa-suite.

If machines were locked as part of the run (with the --lock switch),
teuthology normally leaves them locked when there is any task failure
for investigation of the machine state.  When developing new teuthology
tasks, sometimes this behavior is not useful.  The ``unlock_on_failure``
global option can be set to true to make the unlocking happen unconditionally.

Troubleshooting
===============

Sometimes when a bug triggers, instead of automatic cleanup, you want
to explore the system as is. Adding a top-level::

    interactive-on-error: true

as a config file for teuthology will make that possible. With that
option, any *task* that fails, will have the ``interactive`` task
called after it. This means that before any cleanup happens, you get a
chance to inspect the system -- both through Teuthology and via extra
SSH connections -- and the cleanup completes only when you choose so.
Just exit the interactive Python session to continue the cleanup.

Interactive task facilities
===========================

The ``interactive`` task presents a prompt for you to interact with the
teuthology configuration.  The ``ctx`` variable is available to explore,
and a ``pprint.PrettyPrinter().pprint`` object is added for convenience as
``pp``, so you can do things like pp(dict-of-interest) to see a formatted
view of the dict.

This is also useful to pause the execution of the test between two tasks,
either to perform ad hoc operations, or to examine the state of the cluster.
Hit ``control-D`` to continue when done.

You need to nest ``interactive`` underneath of ``tasks`` in your config. You
can have has many ``interactive`` tasks as needed in your task list.

An example::

    tasks:
    - ceph:
    - interactive:

Test Sandbox Directory
======================

Teuthology currently places most test files and mount points in a
sandbox directory, defaulting to ``/home/$USER/cephtest``.  To change
the location of the sandbox directory, the following option can be
specified in ``$HOME/.teuthology.yaml``::

    test_path: <directory>

OpenStack backend
=================

The ``teuthology-openstack`` command is a wrapper around
``teuthology-suite`` that transparently creates the teuthology cluster
using OpenStack virtual machines.

Prerequisites
-------------

An OpenStack tenant with access to the nova and cinder API (for
instance http://entercloudsuite.com/). If the cinder API is not
available (for instance https://www.ovh.com/fr/cloud/), some jobs
won't run because they expect volumes attached to each instance.

Setup OpenStack at Enter Cloud Suite
------------------------------------

* create an account and `login the dashboard <https://dashboard.entercloudsuite.com/>`_
* `create an Ubuntu 14.04 instance
  <https://dashboard.entercloudsuite.com/console/index#/launch-instance>`_
  with 1GB RAM and a public IP and destroy it immediately afterwards.
* get $HOME/openrc.sh from `the horizon dashboard <https://horizon.entercloudsuite.com/project/access_and_security/?tab=access_security_tabs__api_access_tab>`_

The creation/destruction of an instance via the dashboard is the
shortest path to create the network, subnet and router that would
otherwise need to be created via the neutron API.

Setup OpenStack at OVH
----------------------

It is cheaper than EnterCloudSuite but does not provide volumes (as
of August 2015) and is therefore unfit to run teuthology tests that
require disks attached to the instance. Each instance has a public IP
by default.

* `create an account <https://www.ovh.com/fr/support/new_nic.xml>`_
* get $HOME/openrc.sh from `the horizon dashboard <https://horizon.cloud.ovh.net/project/access_and_security/?tab=access_security_tabs__api_access_tab>`_

Setup
-----

* Get and configure teuthology::

    $ git clone http://github.com/ceph/teuthology
    $ cd teuthology ; ./bootstrap install
    $ source virtualenv/bin/activate

Get OpenStack credentials and test it
-------------------------------------

* follow the `OpenStack API Quick Start <http://docs.openstack.org/api/quick-start/content/index.html#cli-intro>`_
* source $HOME/openrc.sh
* verify the OpenStack client works::

    $ nova list
    +----+------------+--------+------------+-------------+-------------------------+
    | ID | Name       | Status | Task State | Power State | Networks                |
    +----+------------+--------+------------+-------------+-------------------------+
    +----+------------+--------+------------+-------------+-------------------------+
* create a passwordless ssh public key with::

    $ openstack keypair create myself > myself.pem
    +-------------+-------------------------------------------------+
    | Field       | Value                                           |
    +-------------+-------------------------------------------------+
    | fingerprint | e0:a3:ab:5f:01:54:5c:1d:19:40:d9:62:b4:b3:a1:0b |
    | name        | myself                                          |
    | user_id     | 5cf9fa21b2e9406b9c4108c42aec6262                |
    +-------------+-------------------------------------------------+
    $ chmod 600 myself.pem

Usage
-----

* Create a passwordless ssh public key::

    $ openstack keypair create myself > myself.pem
    $ chmod 600 myself.pem

* Run the dummy suite (it does nothing useful but shows all works as
  expected)::

    $ teuthology-openstack --key-filename myself.pem --key-name myself --suite dummy
    Job scheduled with name ubuntu-2015-07-24_09:03:29-dummy-master---basic-openstack and ID 1
    2015-07-24 09:03:30,520.520 INFO:teuthology.suite:ceph sha1: dedda6245ce8db8828fdf2d1a2bfe6163f1216a1
    2015-07-24 09:03:31,620.620 INFO:teuthology.suite:ceph version: v9.0.2-829.gdedda62
    2015-07-24 09:03:31,620.620 INFO:teuthology.suite:teuthology branch: master
    2015-07-24 09:03:32,196.196 INFO:teuthology.suite:ceph-qa-suite branch: master
    2015-07-24 09:03:32,197.197 INFO:teuthology.repo_utils:Fetching from upstream into /home/ubuntu/src/ceph-qa-suite_master
    2015-07-24 09:03:33,096.096 INFO:teuthology.repo_utils:Resetting repo at /home/ubuntu/src/ceph-qa-suite_master to branch master
    2015-07-24 09:03:33,157.157 INFO:teuthology.suite:Suite dummy in /home/ubuntu/src/ceph-qa-suite_master/suites/dummy generated 1 jobs (not yet filtered)
    2015-07-24 09:03:33,158.158 INFO:teuthology.suite:Scheduling dummy/{all/nop.yaml}
    2015-07-24 09:03:34,045.045 INFO:teuthology.suite:Suite dummy in /home/ubuntu/src/ceph-qa-suite_master/suites/dummy scheduled 1 jobs.
    2015-07-24 09:03:34,046.046 INFO:teuthology.suite:Suite dummy in /home/ubuntu/src/ceph-qa-suite_master/suites/dummy -- 0 jobs were filtered out.

    2015-07-24 11:03:34,104.104 INFO:teuthology.openstack:
    web interface: http://167.114.242.13:8081/
    ssh access   : ssh ubuntu@167.114.242.13 # logs in /usr/share/nginx/html

* Visit the web interface (the URL is displayed at the end of the
  teuthology-openstack output) to monitor the progress of the suite.

* The virtual machine running the suite will persist for forensic
  analysis purposes. To destroy it run::

    $ teuthology-openstack --key-filename myself.pem --key-name myself --teardown

* The test results can be uploaded to a publicly accessible location
  with the ``--upload`` flag::

    $ teuthology-openstack --key-filename myself.pem --key-name myself \
                           --suite dummy --upload
    

Running the OpenStack backend integration tests
-----------------------------------------------

The easiest way to run the integration tests is to first run a dummy suite::

    $ teuthology-openstack --key-name myself --suite dummy
    ...
    ssh access   : ssh ubuntu@167.114.242.13

This will create a virtual machine suitable for the integration
test. Login wih the ssh access displayed at the end of the
``teuthology-openstack`` command and run the following::

    $ pkill -f teuthology-worker
    $ cd teuthology ; pip install "tox>=1.9"
    $ tox -v -e openstack-integration
    integration/openstack-integration.py::TestSuite::test_suite_noop PASSED
    ...
    ========= 9 passed in 2545.51 seconds ========
    $ tox -v -e openstack
    integration/test_openstack.py::TestTeuthologyOpenStack::test_create PASSED
    ...
    ========= 1 passed in 204.35 seconds =========

VIRTUAL MACHINE SUPPORT
=======================

Teuthology also supports virtual machines, which can function like
physical machines but differ in the following ways:

VPSHOST:
--------
The following description is based on the Red Hat lab used by the Ceph
development and quality assurance teams.

The teuthology database of available machines contains a vpshost field.
For physical machines, this value is null. For virtual machines, this entry
is the name of the physical machine that that virtual machine resides on.

There are fixed "slots" for virtual machines that appear in the teuthology
database.  These slots have a machine type of vps and can be locked like
any other machine.  The existence of a vpshost field is how teuthology
knows whether or not a database entry represents a physical or a virtual
machine.

In order to get the right virtual machine associations, the following needs
to be set in ~/.config/libvirt/libvirt.conf or for some older versions
of libvirt (like ubuntu precise) in ~/.libvirt/libvirt.conf::

    uri_aliases = [
        'mira001=qemu+ssh://ubuntu@mira001.front.sepia.ceph.com/system?no_tty=1',
        'mira003=qemu+ssh://ubuntu@mira003.front.sepia.ceph.com/system?no_tty=1',
        'mira004=qemu+ssh://ubuntu@mira004.front.sepia.ceph.com/system?no_tty=1',
        'mira006=qemu+ssh://ubuntu@mira006.front.sepia.ceph.com/system?no_tty=1',
        'mira007=qemu+ssh://ubuntu@mira007.front.sepia.ceph.com/system?no_tty=1',
        'mira008=qemu+ssh://ubuntu@mira008.front.sepia.ceph.com/system?no_tty=1',
        'mira009=qemu+ssh://ubuntu@mira009.front.sepia.ceph.com/system?no_tty=1',
        'mira010=qemu+ssh://ubuntu@mira010.front.sepia.ceph.com/system?no_tty=1',
        'mira011=qemu+ssh://ubuntu@mira011.front.sepia.ceph.com/system?no_tty=1',
        'mira013=qemu+ssh://ubuntu@mira013.front.sepia.ceph.com/system?no_tty=1',
        'mira014=qemu+ssh://ubuntu@mira014.front.sepia.ceph.com/system?no_tty=1',
        'mira015=qemu+ssh://ubuntu@mira015.front.sepia.ceph.com/system?no_tty=1',
        'mira017=qemu+ssh://ubuntu@mira017.front.sepia.ceph.com/system?no_tty=1',
        'mira018=qemu+ssh://ubuntu@mira018.front.sepia.ceph.com/system?no_tty=1',
        'mira020=qemu+ssh://ubuntu@mira020.front.sepia.ceph.com/system?no_tty=1',
        'mira024=qemu+ssh://ubuntu@mira024.front.sepia.ceph.com/system?no_tty=1',
        'mira029=qemu+ssh://ubuntu@mira029.front.sepia.ceph.com/system?no_tty=1',
        'mira036=qemu+ssh://ubuntu@mira036.front.sepia.ceph.com/system?no_tty=1',
        'mira043=qemu+ssh://ubuntu@mira043.front.sepia.ceph.com/system?no_tty=1',
        'mira044=qemu+ssh://ubuntu@mira044.front.sepia.ceph.com/system?no_tty=1',
        'mira074=qemu+ssh://ubuntu@mira074.front.sepia.ceph.com/system?no_tty=1',
        'mira079=qemu+ssh://ubuntu@mira079.front.sepia.ceph.com/system?no_tty=1',
        'mira081=qemu+ssh://ubuntu@mira081.front.sepia.ceph.com/system?no_tty=1',
        'mira091=qemu+ssh://ubuntu@mira091.front.sepia.ceph.com/system?no_tty=1',
        'mira098=qemu+ssh://ubuntu@mira098.front.sepia.ceph.com/system?no_tty=1',
        'vercoi01=qemu+ssh://ubuntu@vercoi01.front.sepia.ceph.com/system?no_tty=1',
        'vercoi02=qemu+ssh://ubuntu@vercoi02.front.sepia.ceph.com/system?no_tty=1',
        'vercoi03=qemu+ssh://ubuntu@vercoi03.front.sepia.ceph.com/system?no_tty=1',
        'vercoi04=qemu+ssh://ubuntu@vercoi04.front.sepia.ceph.com/system?no_tty=1',
        'vercoi05=qemu+ssh://ubuntu@vercoi05.front.sepia.ceph.com/system?no_tty=1',
        'vercoi06=qemu+ssh://ubuntu@vercoi06.front.sepia.ceph.com/system?no_tty=1',
        'vercoi07=qemu+ssh://ubuntu@vercoi07.front.sepia.ceph.com/system?no_tty=1',
        'vercoi08=qemu+ssh://ubuntu@vercoi08.front.sepia.ceph.com/system?no_tty=1',
        'senta01=qemu+ssh://ubuntu@senta01.front.sepia.ceph.com/system?no_tty=1',
        'senta02=qemu+ssh://ubuntu@senta02.front.sepia.ceph.com/system?no_tty=1',
        'senta03=qemu+ssh://ubuntu@senta03.front.sepia.ceph.com/system?no_tty=1',
        'senta04=qemu+ssh://ubuntu@senta04.front.sepia.ceph.com/system?no_tty=1',
    ]

DOWNBURST:
----------

When a virtual machine is locked, downburst is run on that machine to install a
new image.  This allows the user to set different virtual OSes to be installed
on the newly created virtual machine.  Currently the default virtual machine is
ubuntu (precise).  A different vm installation can be set using the
``--os-type`` and ``--os-version`` options in ``teuthology.lock``.

When a virtual machine is unlocked, downburst destroys the image on the
machine.

Temporary yaml files are used to downburst a virtual machine.  A typical
yaml file will look like this::

    downburst:
      cpus: 1
      disk-size: 30G
      distro: centos
      networks:
      - {source: front}
      ram: 4G

These values are used by downburst to create the virtual machine.

When locking a file, a downburst meta-data yaml file can be specified by using
the downburst-conf parameter on the command line.

To find the downburst executable, teuthology first checks the PATH environment
variable.  If not defined, teuthology next checks for
src/downburst/virtualenv/bin/downburst executables in the user's home
directory, /home/ubuntu, and /home/teuthology.  This can all be overridden if
the user specifies a downburst field in the user's .teuthology.yaml file.

HOST KEYS:
----------

Because teuthology reinstalls a new machine, a new hostkey is generated.  After
locking, once a connection is established to the new machine,
``teuthology-lock`` with the ``--list`` or ``--list-targets`` options will
display the new keys.  When vps machines are locked using the ``--lock-many``
option, a message is displayed indicating that ``--list-targets`` should be run
later.

ASSUMPTIONS:
------------

It is assumed that downburst is on the user's ``$PATH``.


Test Suites
===========

Most of the current teuthology test suite execution scripts automatically
download their tests from the master branch of the appropriate github
repository.  People who want to run experimental test suites usually modify the
download method in the ``teuthology/task`` script to use some other branch or
repository. This should be generalized in later teuthology releases.
Teuthology QA suites can be found in ``src/ceph-qa-suite``. Make sure that this
directory exists in your source tree before running the test suites.

Each suite name is determined by the name of the directory in ``ceph-qa-suite``
that contains that suite. The directory contains subdirectories and yaml files,
which, when assembled, produce valid tests that can be run. The test suite
application generates combinations of these files and thus ends up running a
set of tests based off the data in the directory for the suite.

To run a suite, enter::

    teuthology-suite -s <suite> [-c <ceph>] [-k <kernel>] [-e email] [-f flavor] [-t <teuth>] [-m <mtype>]

where:

* ``suite``: the name of the suite (the directory in ceph-qa-suite).
* ``ceph``: ceph branch to be used.
* ``kernel``: version of the kernel to be used.
* ``email``: email address to send the results to.
* ``flavor``: the kernel flavor to run against
* ``teuth``: version of teuthology to run
* ``mtype``: machine type of the run
* ``templates``: template file used for further modifying the suite (optional)

For example, consider::

     teuthology-suite -s rbd -c wip-fix -k cuttlefish -e bob.smith@foo.com -f basic -t cuttlefish -m plana

The above command runs the rbd suite using the wip-fix branch of ceph, the
cuttlefish kernel, with a 'basic' kernel flavor, and the teuthology
cuttlefish branch will be used.  It will run on plana machines and send an email
to bob.smith@foo.com when it's completed. For more details on
``teuthology-suite``, please consult the output of ``teuthology-suite --help``.

In order for a queued task to be run, a teuthworker thread on
``teuthology.front.sepia.ceph.com`` needs to remove the task from the queue.
On ``teuthology.front.sepia.ceph.com``, run ``ps aux | grep teuthology-worker``
to view currently running tasks. If no processes are reading from the test
version that you are running, additonal teuthworker tasks need to be started.
To start these tasks:

* copy your build tree to ``/home/teuthworker`` on ``teuthology.front.sepia.ceph.com``.
* Give it a unique name (in this example, xxx)
* start up some number of worker threads (as many as machines you are testing with, there are 60 running for the default queue)::

    /home/virtualenv/bin/python
    /var/lib/teuthworker/xxx/virtualenv/bin/teuthworker
    /var/lib/teuthworker/archive --tube xxx
    --log-dir /var/lib/teuthworker/archive/worker_logs

    Note: The threads on teuthology.front.sepia.ceph.com are started via
    ~/teuthworker/start.sh.  You can use that file as a model for your
    own threads, or add to this file if you want your threads to be
    more permanent.

Once the suite completes, an email message is sent to the users specified, and
a large amount of information is left on ``teuthology.front.sepia.ceph.com`` in
``/var/lib/teuthworker/archive``.

This is symbolically linked to /a for convenience. A new directory is created
whose name consists of a concatenation of the date and time that the suite was
started, the name of the suite, the ceph branch tested, the kernel used, and
the flavor. For every test run there is a directory whose name is the pid
number of the pid of that test.  Each of these directory contains a copy of the
``teuthology.log`` for that process.  Other information from the suite is
stored in files in the directory, and task-specific yaml files and other logs
are saved in the subdirectories.

These logs are also publically available at
``http://qa-proxy.ceph.com/teuthology/``.

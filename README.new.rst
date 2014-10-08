===================================================
`Teuthology` -- The Ceph integration test framework
===================================================


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


Choosing machines for a job
===========================

It is possible to run jobs against machines of one or more  ``machine_type``
values. It is also possible to tell ``teuthology`` to only select those
machines which match the following criteria specified in the job's YAML:

* ``os_type`` (e.g. 'rhel', 'ubuntu')
* ``os_version`` (e.g. '7.0', '14.04')
* ``arch`` (e.g. 'x86_64')


Installation and setup
======================

Ubuntu
------

For better or worse, ``teuthology`` was originally written with Ubuntu in mind.
Thus, a bootstrap script is provided that will do everything for you assuming
you have ``sudo``::

    ./bootstrap

MacOS X
-------

The `bootstrap` script was recently updated to support MacOS X using `homebrew <http://brew.sh/>`_::

    ./bootstrap

Other operating systems
-----------------------

Patches are welcomed to add `bootstrap` support for other operating systems. Until then, manual installs are possible

First install the non-PyPI dependencies::

    python-dev python-pip python-virtualenv libevent-dev python-libvirt

Next, clone its `git repository <https://github.com/ceph/teuthology/>`__,
create a `virtualenv <http://virtualenv.readthedocs.org/en/latest/>`__, and
install dependencies::

    git clone https://github.com/ceph/teuthology/
    cd teuthology
    virtualenv ./virtualenv
    source virtualenv/bin/activate
    pip install --upgrade pip
    pip install -r requirements.txt
    python setup.py develop


Teuthology in PyPI
------------------

However if you prefer, you may install ``teuthology`` from `PyPI <http://pypi.python.org>`__::

    pip install teuthology

.. note:: The version in PyPI can be (*far*) behind the development version.


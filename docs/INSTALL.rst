.. _installation_and_setup:

Installation and setup
======================

teuthology uses `uv <https://docs.astral.sh/uv/>`_ for project management.
Because our CI systems often use older operating systems, we use `pipx
<https://pipx.pypa.io/>`_ to install it in those contexts via our `bootstrap`
script. The simplest way to install teuthology is in development mode:

    git clone https://github.com/ceph/teuthology/
	cd teuthology
	./bootstrap

The `bootstrap` script also checks for the presence of a few system-level
packages that are required to build dependencies. It can be instructed to
install whatever is missing::

    ./bootstrap install

After installation, there are a few options for running teuthology commands.

Using uv::

    uv run teuthology --help

Activating the virtual environment::

	source ./.venv/bin/activate
	teuthology --help

Running a shell within uv::

	uv run bash


macOS
-----

**Note**: Certain features might not work properly on macOS. Patches are
encouraged, but it has never been a goal of ours to run a full ``teuthology``
setup on a Mac.

Windows
-------

Windows is not directly supported, but patches are welcome.

from setuptools import setup, find_packages

setup(
    name='teuthology',
    version='0.0.1',
    packages=find_packages(),

    author='Tommi Virtanen',
    author_email='tommi.virtanen@dreamhost.com',
    description='Ceph test runner',
    license='MIT',
    keywords='ceph testing ssh cluster',

    # to find the code associated with entry point
    # A.B:foo first cd into directory A, open file B
    # and find sub foo
    entry_points={
        'console_scripts': [
            'teuthology = teuthology.run:main',
            'teuthology-nuke = teuthology.nuke:main',
            'teuthology-suite = teuthology.suite:main',
            'teuthology-ls = teuthology.suite:ls',
            'teuthology-worker = teuthology.queue:worker',
            'teuthology-lock = teuthology.lock:main',
            'teuthology-schedule = teuthology.run:schedule',
            'teuthology-updatekeys = teuthology.lock:update_hostkeys',
            'teuthology-coverage = teuthology.coverage:analyze',
            'teuthology-results = teuthology.suite:results',
            'teuthology-build-db = teuthology.results_db:build',
            'teuthology-update-db = teuthology.results_db:update',
            ],
        },

    )

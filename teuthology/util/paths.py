"""
Path utility functions for teuthology.

This module provides functions for working with test-related paths, including:
- Getting the test directory where tests are run
- Getting the archive directory for test results
- Getting HTTP log paths for accessing archived test results

These functions are used throughout teuthology to maintain consistent
directory structures for test execution and result storage.
"""
import os

from teuthology.config import config


def get_test_user(ctx=None):
    """
    Get the user account to run tests as on remote hosts.
    
    :param ctx: Unused; accepted for compatibility
    :returns: str -- the user to run tests as on remote hosts
    """
    return config.get('test_user', 'ubuntu')


def get_testdir(ctx=None):
    """
    Get the test directory where tests are executed.
    
    This returns the configured test path, or a default path based on
    the test user if not configured.
    
    :param ctx: Unused; accepted for compatibility
    :returns: A test directory path
    """
    if 'test_path' in config:
        return config['test_path']
    return config.get(
        'test_path',
        '/home/%s/cephtest' % get_test_user()
    )


def get_archive_dir(ctx):
    """
    Get the archive directory for storing test results.
    
    The archive directory is a subdirectory of the test directory where
    test results, logs, and other artifacts are stored.
    
    :param ctx: Context object (may be used to override test directory)
    :returns: Archive directory path (a subdirectory of the test directory)
    """
    test_dir = get_testdir(ctx)
    return os.path.normpath(os.path.join(test_dir, 'archive'))


def get_http_log_path(archive_dir, job_id=None):
    """
    Get the HTTP URL path for accessing archived test logs.
    
    This constructs a URL path based on the archive server configuration
    and the archive directory structure. The URL can be used to access
    test logs via HTTP.
    
    :param archive_dir: Local archive directory path to be converted to HTTP path
    :param job_id: Optional job ID that terminates the name of the log path
    :returns: HTTP log path URL, or None if no archive server is configured
    """
    http_base = config.archive_server
    if not http_base:
        return None

    sep = os.path.sep
    archive_dir = archive_dir.rstrip(sep)
    archive_subdir = archive_dir.split(sep)[-1]
    if archive_subdir.endswith(str(job_id)):
        archive_subdir = archive_dir.split(sep)[-2]

    if job_id is None:
        return os.path.join(http_base, archive_subdir, '')
    return os.path.join(http_base, archive_subdir, str(job_id), '')

# Made with Bob

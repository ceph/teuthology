"""
Remote file manipulation utilities.

This module provides utilities for manipulating files on remote hosts through
SSH connections. These functions wrap common file operations like reading,
writing, moving, copying, and deleting files on remote systems.

Functions in this module operate on Remote objects from teuthology.orchestra
and handle the complexity of executing commands over SSH with proper error
handling and permissions management.

Main functions:
- write_file: Write content to a remote file
- sudo_write_file: Write content to a remote file with sudo privileges
- move_file: Move/rename a file on remote host
- copy_file: Copy a file between remote hosts
- delete_file: Delete a file on remote host
- append_lines_to_file: Append lines to a remote file
- prepend_lines_to_file: Prepend lines to a remote file
- remove_lines_from_file: Remove lines from a remote file based on a test function
- create_file: Create a new file on remote host with specified permissions
- get_file: Get the contents of a remote file
"""
import logging
import os

from teuthology.orchestra import run

log = logging.getLogger(__name__)


def write_file(remote, path, data):
    """
    Write data to a remote file

    :param remote: Remote site.
    :param path: Path on the remote being written to.
    :param data: Data to be written.
    """
    remote.write_file(path, data)


def sudo_write_file(remote, path, data, perms=None, owner=None):
    """
    Write data to a remote file as super user

    :param remote: Remote site.
    :param path: Path on the remote being written to.
    :param data: Data to be written.
    :param perms: Permissions on the file being written
    :param owner: Owner for the file being written

    Both perms and owner are passed directly to chmod.
    """
    remote.sudo_write_file(path, data, mode=perms, owner=owner)


def copy_file(from_remote, from_path, to_remote, to_path=None):
    """
    Copies a file from one remote to another.
    """
    if to_path is None:
        to_path = from_path
    from_remote.run(args=[
        'sudo', 'scp', '-v', from_path, "{host}:{file}".format(
            host=to_remote.name, file=to_path)
    ])


def move_file(remote, from_path, to_path, sudo=False, preserve_perms=True):
    """
    Move a file from one path to another on a remote site

    If preserve_perms is true, the contents of the destination file (to_path,
    which must already exist in this case) are replaced with the contents of the
    source file (from_path) and the permissions of to_path are preserved. If
    preserve_perms is false, to_path does not need to exist, and is simply
    clobbered if it does.
    """
    if preserve_perms:
        args = []
        if sudo:
            args.append('sudo')
        args.extend([
            'stat',
            '-c',
            '\"%a\"',
            to_path
        ])
        perms = remote.sh(args).rstrip().strip('\"')

    args = []
    if sudo:
        args.append('sudo')
    args.extend([
        'mv',
        '--',
        from_path,
        to_path,
    ])
    remote.sh(args)

    if preserve_perms:
        # reset the file back to the original permissions
        args = []
        if sudo:
            args.append('sudo')
        args.extend([
            'chmod',
            perms,
            to_path,
        ])
        remote.sh(args)


def delete_file(remote, path, sudo=False, force=False, check=True):
    """
    rm a file on a remote site. Use force=True if the call should succeed even
    if the file is absent or rm path would otherwise fail.
    """
    args = []
    if sudo:
        args.append('sudo')
    args.extend(['rm'])
    if force:
        args.extend(['-f'])
    args.extend([
        '--',
        path,
    ])
    remote.sh(args, check_status=check)


def remove_lines_from_file(remote, path, line_is_valid_test,
                           string_to_test_for):
    """
    Remove lines from a file.  This involves reading the file in, removing
    the appropriate lines, saving the file, and then replacing the original
    file with the new file.  Intermediate files are used to prevent data loss
    on when the main site goes up and down.
    """
    # read in the specified file
    in_data = remote.read_file(path, False).decode()
    out_data = ""

    first_line = True
    # use the 'line_is_valid_test' function to remove unwanted lines
    for line in in_data.split('\n'):
        if line_is_valid_test(line, string_to_test_for):
            if not first_line:
                out_data += '\n'
            else:
                first_line = False

            out_data += '{line}'.format(line=line)

        else:
            log.info('removing line: {bad_line}'.format(bad_line=line))

    # get a temp file path on the remote host to write to,
    # we don't want to blow away the remote file and then have the
    # network drop out
    temp_file_path = remote.mktemp()

    # write out the data to a temp file
    write_file(remote, temp_file_path, out_data)

    # then do a 'mv' to the actual file location
    move_file(remote, temp_file_path, path)


def append_lines_to_file(remote, path, lines, sudo=False):
    """
    Append lines to a file.
    """
    remote.write_file(path, lines, append=True, sudo=sudo)

def prepend_lines_to_file(remote, path, lines, sudo=False):
    """
    Prepend lines to a file.
    An intermediate file is used in the same manner as in
    Remove_lines_from_list.
    """

    temp_file_path = remote.mktemp()
    remote.write_file(temp_file_path, lines)
    remote.copy_file(path, temp_file_path, append=True, sudo=sudo)
    remote.move_file(temp_file_path, path, sudo=sudo)


def create_file(remote, path, data="", permissions=str(644), sudo=False):
    """
    Create a file on the remote host.
    """
    args = []
    if sudo:
        args.append('sudo')
    args.extend([
        'touch',
        path,
        run.Raw('&&')
    ])
    if sudo:
        args.append('sudo')
    args.extend([
        'chmod',
        permissions,
        '--',
        path
    ])
    remote.sh(args)
    # now write out the data if any was passed in
    if "" != data:
        append_lines_to_file(remote, path, data, sudo)


def get_file(remote, path, sudo=False, dest_dir='/tmp'):
    """
    Get the contents of a remote file. Do not use for large files; use
    Remote.get_file() instead.
    """
    local_path = remote.get_file(path, sudo=sudo, dest_dir=dest_dir)
    with open(local_path, 'rb') as file_obj:
        file_data = file_obj.read()
    os.remove(local_path)
    return file_data

# Made with Bob

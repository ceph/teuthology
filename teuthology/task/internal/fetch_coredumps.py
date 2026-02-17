#!env python3
"""
Module to fetch coredumps and their corresponding binaries.
Inject this script into the remote node pointing out the remote folder
then misc.pull_drectory() will retrieve the data produced by this script.
"""

import re
import os
import gzip
import subprocess
import sys
import logging
import shutil
import argparse

log = logging.getLogger(__name__)
DUMP_PATH = "/tmp/coredumps"


def check_gdb_installed() -> bool:
    """
    Check whether gdb is installed in the system
    """
    if shutil.which("gdb") is not None:
        log.info("gdb is installed")
        return True
    else:
        log.info(
            "gdb is not installed, please install gdb to get backtraces from coredumps"
        )
        return False


def get_backtraces_from_coredumps(
    coredump_path: str, dump_path: str, dump_program: str, dump: str
) -> None:
    """
    Get backtraces from coredumps found in coredump_path
    On a future iteration, we can expand this to inject gdb commands from the test plan yaml
    """
    gdb_output_path = os.path.join(coredump_path, dump + ".gdb.txt")
    log.info(f"Getting backtrace from core {dump} ...")
    with open(gdb_output_path, "w") as gdb_out:
        gdb_proc = subprocess.Popen(
            [
                "gdb",
                "--batch",
                "-ex",
                "set pagination 0",
                "-ex",
                "thread apply all bt full",
                dump_program,
                dump_path,
            ],
            stdout=gdb_out,
            stderr=subprocess.STDOUT,
        )
        gdb_proc.wait()
        log.info(f"core {dump} backtrace saved to {gdb_output_path}")


def fetch_binaries_for_coredumps(path: str) -> None:
    """
    Pull ELFs (debug and stripped) for each coredump found in path

    The coredumps might appear compressed, either by gzip or zstd (Centos9)
    The following are examples from the output of the 'file' command:

    # 1422917770.7450.core: ELF 64-bit LSB core file x86-64, version 1 (SYSV), SVR4-style, \
    # from 'radosgw --rgw-socket-path /home/ubuntu/cephtest/apache/tmp.client.0/fastcgi_soc'
    # Centos 9:
    # core.ceph_test_neora.0.fb62b98.zst: Zstandard compressed data (v0.8+), Dictionary ID: None
    #  ELF 64-bit LSB core file, x86-64, version 1 (SYSV), SVR4-style, \
    # from 'bin/ceph_test_neorados_snapshots --gtest_break_on_failure', real uid: 0, \
    # effective uid: 0, real gid: 0, effective gid: 0, execfn: 'bin/ceph_test_neorados_snapshots', platform: 'x86_64'
    """

    def _is_core_gziped(dump_path: str) -> bool:
        """
        Return True whether the core file is gzip compressed
        """
        with open(dump_path, "rb") as f:
            magic = f.read(2)
            if magic == b"\x1f\x8b":
                return True
        return False

    def _is_core_zstded(dump_path: str) -> bool:
        """
        Return True whether the core file is zstd compressed
        """
        with open(dump_path, "rb") as f:
            magic = f.read(4)
            if magic == b"\x28\xb5\x2f\xfd":
                return True
        return False

    # Auxiliary dict for compression types: callback to check compression type,
    # and how to uncompress the file based on the type
    csdict = {
        "gzip": {
            "check": _is_core_gziped,
            "uncompress": ["gzip", "-d "],
            "regex": r".*gzip compressed data.*",
            #'ELF.*core file from \'([^\']+)\''
        },
        "zstd": {
            "check": _is_core_zstded,
            "uncompress": ["zstd", "-d "],
            "regex": r".*Zstandard compressed data.*",
        },
    }

    # For compression, -9 on both gzip and zstd works fine
    def _get_compressed_type(dump_path: str) -> str | None:
        """
        Identify the compression type of the core file
        """
        for ck, cs in csdict.items():
            if cs["check"](dump_path):
                return ck
        return None

    def _looks_compressed(dump_out: str) -> bool:
        """
        Identify whether the core file looks compressed from 'file' output
        """
        for cs in csdict.values():
            if re.match(cs["regex"], dump_out):
                return True
        return False

    def _uncompress_file(dump_path: str, cs_type: str | None) -> str | None:
        """
        Uncompress the core file based on its compression type, in the remote machine
        """
        if cs_type is None:
            return None
        # Construct a bash cmd to uncompress the file based on its type
        try:
            cmd = csdict[cs_type]["uncompress"] + [dump_path]
            log.info(f"Uncompressing via {cmd} ...")
            unc_output_path = dump_path.rsplit(".", 1)[0] + ".unc.log"
            with open(unc_output_path, "w") as _out:
                unc = subprocess.Popen(cmd, stdout=_out, stderr=subprocess.STDOUT)
                unc.wait()
            # After uncompressing, the new file path is the original path without the compression suffix
            uncompressed_path = dump_path.rsplit(".", 1)[0]
            log.info(f"Uncompressed file path: {uncompressed_path}")
            return uncompressed_path
        except Exception as e:
            log.info("Something went wrong while attempting to uncompress the file")
            log.error(e)
            return None

    def _get_file_info(dump_path: str) -> str:
        """
        Get the 'file' command output for the core file, to identify the program that
        generated the core and whether it is compressed
        """
        dump_info = subprocess.Popen(["file", dump_path], stdout=subprocess.PIPE)
        dump_out = dump_info.communicate()[0].decode()
        return dump_out

    def _get_program_binary(dump_out: str, coredump_path: str) -> str | None:
        """
        Pull the program that generated the core
        """
        try:
            dump_command = re.findall("from '([^ ']+)", dump_out)[0]
            dump_program = dump_command.split()[0]
            log.info(f" dump_program: {dump_program}")
        except Exception as e:
            log.info("core doesn't have the desired format, moving on ...")
            log.error(e)
            return None
        program_path = shutil.which(dump_program)
        if program_path is None:
            log.info(
                f"Could not find the program {dump_program} that generated the core, moving on ..."
            )
            return None
        else:
            log.info(f"Found the program {dump_program} at {program_path}")
        # Copy the program that generated the core to the same folder as the core file,
        # to be pulled together with the core file
        local_path = os.path.join(coredump_path, dump_program.lstrip(os.path.sep))
        local_dir = os.path.dirname(local_path)
        if not os.path.exists(local_dir):
            os.makedirs(local_dir)
        shutil.copy(program_path, local_path)
        return dump_program

    def _is_elf(dump_out: str) -> bool:
        """
        Identify whether the core file is an ELF file from 'file' output
        """
        if re.match(r".*ELF.*core file.*", dump_out):
            return True
        return False

    def _get_debug_symbols(dump_program: str, coredump_path: str) -> None:
        """
        Pull the debug symbols for the program that generated the core, if they exist
        """
        debug_path = os.path.join("/usr/lib/debug", dump_program)
        debug_filename = os.path.basename(debug_path)
        local_debug_path = os.path.join(coredump_path, debug_filename)
        if os.path.exists(local_debug_path):
            log.info(
                f"Debug symbols for {dump_program} already exist at {local_debug_path}"
            )
            return
        # RPM distro's append their non-stripped ELF's with .debug
        # When deb based distro's do not.
        if shutil.which("rpm") is not None:
            debug_path_rpm = f"{debug_path}.debug"
            if os.path.exists(debug_path_rpm):
                shutil.copy(debug_path_rpm, local_debug_path)
                log.info(
                    f"Copied debug symbols for {dump_program} from {debug_path_rpm} to {local_debug_path}"
                )
                return
            if os.path.exists(debug_path):
                shutil.copy(debug_path, local_debug_path)
                log.info(
                    f"Copied debug symbols for {dump_program} from {debug_path} to {local_debug_path}"
                )
                return
        log.info(f"Could not find debug symbols for {dump_program}, moving on ...")

    # Check for Coredumps:
    coredump_path = os.path.join(path, "coredump")
    if os.path.isdir(coredump_path):
        log.info("Looking for coredumps in {coredump_path}...")
        for dump in os.listdir(coredump_path):
            # Pull program from core file
            dump_path = os.path.join(coredump_path, dump)
            dump_out = _get_file_info(dump_path)

            log.info(f" core looks like: {dump_out}")

            if _looks_compressed(dump_out):
                # if the core is compressed, recognise the type and uncompress it
                cs_type = _get_compressed_type(dump_path)
                try:
                    log.info(f"core is compressed, try accessing {cs_type} file ...")
                    uncompressed_path = _uncompress_file(dump_path, cs_type)
                    if uncompressed_path is None:
                        log.info("Could not uncompress the core file, moving on ...")
                        continue
                except Exception as e:
                    log.info("Something went wrong while opening the compressed file")
                    log.error(e)
                    continue
                dump_path = uncompressed_path
                dump_out = _get_file_info(dump_path)
                log.info(f" after uncompressing core looks like: {dump_out}")

            dump_program = _get_program_binary(dump_out, coredump_path)
            if dump_program is None:
                continue
            # Execute gdb to get the backtrace and locals
            get_backtraces_from_coredumps(coredump_path, dump_path, dump_program, dump)
            _get_debug_symbols(dump_program, coredump_path)
            # Compress the core file always to save space
            with open(dump_path, "rb") as f_in, gzip.open(
                dump_path + ".gz", "wb"
            ) as f_out:
                shutil.copyfileobj(f_in, f_out)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Standalone unit test for the coredump fetching module"
    )
    parser.add_argument(
        "--debug", help="Turn on debug messages", action="store_true", default=False
    )
    parser.add_argument(
        "--input",
        help="Provide the input dir that contains coredump files",
        default=DUMP_PATH,
    )

    args = parser.parse_args()
    DUMP_PATH = args.input

    if args.debug:
        log_level = logging.DEBUG
    else:
        log_level = logging.INFO

    logging.basicConfig(level=log_level)

    if not check_gdb_installed():
        log.info("gdb is required to run the test, exiting ...")
        sys.exit(1)
    fetch_binaries_for_coredumps(path=DUMP_PATH)
    sys.exit(0)

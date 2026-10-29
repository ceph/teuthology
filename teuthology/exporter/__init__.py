import os
import psutil

from pathlib import Path

from teuthology.config import config


PROMETHEUS_MULTIPROC_DIR = Path("~/.cache/teuthology-exporter").expanduser()
os.environ["PROMETHEUS_MULTIPROC_DIR"] = str(PROMETHEUS_MULTIPROC_DIR)

# We can't import prometheus_client until after we set PROMETHEUS_MULTIPROC_DIR
from prometheus_client import (  # noqa: E402
    multiprocess,
    CollectorRegistry,
)

MACHINE_TYPES = list(config.active_machine_types)
REGISTRY = None

def find_exporter_process() -> int | None:
    attrs = ['pid', 'uids', 'cmdline']
    for proc in psutil.process_iter(attrs=attrs):
        try:
            cmdline = proc.info['cmdline']
        except psutil.AccessDenied:
            continue
        pid = proc.info['pid']
        if not cmdline:
            continue
        if not [i for i in cmdline if i.split('/')[-1] == 'teuthology-exporter']:
            continue
        if os.getuid() not in proc.info['uids']:
            continue
        return pid



pid = find_exporter_process()
if pid:
    PROMETHEUS_MULTIPROC_DIR.mkdir(parents=True, exist_ok=True)
    REGISTRY = CollectorRegistry()
    multiprocess.MultiProcessCollector(REGISTRY)

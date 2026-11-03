import os
import logging
import sys
import time

from teuthology.exporter import (
        REGISTRY,
        PROMETHEUS_MULTIPROC_DIR,
        find_exporter_process,
        )
from teuthology.exporter.metric.dispatcher import Dispatchers
from teuthology.exporter.metric.beanstalk import BeanstalkQueue
from teuthology.exporter.metric.generic import JobProcesses
from teuthology.exporter.metric.node import Nodes

log = logging.getLogger(__name__)

from prometheus_client import (  # noqa: E402
    start_http_server,
)

class TeuthologyExporter:
    port = 61764  # int(''.join([str((ord(c) - 100) % 10) for c in "teuth"]))

    def __init__(self, interval=60):
        if REGISTRY:
            for file in PROMETHEUS_MULTIPROC_DIR.iterdir():
                file.unlink()
        self.interval = interval
        self.metrics = [
            Dispatchers(),
            BeanstalkQueue(),
            JobProcesses(),
            Nodes(),
        ]
        self._created_time = time.perf_counter()

    def start(self):
        if REGISTRY:
            start_http_server(self.port, registry=REGISTRY)
        self.loop()

    def update(self):
        log.info("Updating...")
        for metric in self.metrics:
            metric.update()
        log.info("Update finished.")

    def loop(self):
        log.info("Starting teuthology-exporter...")
        while True:
            try:
                before = time.perf_counter()
                if before - self._created_time > 24 * 60 * 60:
                    self.restart()
                try:
                    self.update()
                except Exception:
                    log.exception("Failed to update metrics")
                interval = self.interval
                # try to deliver metrics _at_ $interval, as opposed to sleeping
                # for $interval between updates
                elapsed: float = time.perf_counter() - before
                if elapsed < 0:
                    interval *= 2
                interval -= elapsed
                time.sleep(interval)
            except KeyboardInterrupt:
                log.info("Stopping.")
                raise SystemExit

    def restart(self):
        if not REGISTRY:
            return
        log.info('Restarting...')
        args = sys.argv[:]
        args.insert(0, sys.executable)
        os.execv(sys.executable, args)

def main(args) -> int:
    if pid := find_exporter_process():
        if os.getpid() != pid:
            log.error(f"teuthology-exporter is already running as PID {pid}")
            return 2
    exporter = TeuthologyExporter(interval=int(args["--interval"]))
    try:
        exporter.start()
    except Exception:
        log.exception("Exporter failed")
        return 1
    else:
        return 0



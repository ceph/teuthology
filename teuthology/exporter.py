import tracemalloc
import linecache
import itertools
import logging
import os
import psutil
import signal
import time

from pathlib import Path

import teuthology.beanstalk as beanstalk
import teuthology.dispatcher
from teuthology.config import config
from teuthology.lock.query import list_locks

tracemalloc.start()

log = logging.getLogger(__name__)


PROMETHEUS_MULTIPROC_DIR = Path("~/.cache/teuthology-exporter").expanduser()
PROMETHEUS_MULTIPROC_DIR.mkdir(parents=True, exist_ok=True)
os.environ["PROMETHEUS_MULTIPROC_DIR"] = str(PROMETHEUS_MULTIPROC_DIR)

# We can't import prometheus_client until after we set PROMETHEUS_MULTIPROC_DIR
from prometheus_client import (  # noqa: E402
    start_http_server,
    Gauge,
    Counter,
    Summary,
    multiprocess,
    CollectorRegistry,
)

registry = CollectorRegistry()
multiprocess.MultiProcessCollector(registry)

MACHINE_TYPES = list(config.active_machine_types)


class TeuthologyExporter:
    port = 61764  # int(''.join([str((ord(c) - 100) % 10) for c in "teuth"]))

    def __init__(self, interval=60):
        for file in PROMETHEUS_MULTIPROC_DIR.iterdir():
            file.unlink()
        self.interval = interval
        self.metrics = [
            Dispatchers(),
            BeanstalkQueue(),
            JobProcesses(),
            Nodes(),
        ]
        self.update_count = 0

        def checkpoint(signal_, frame):
            new_snapshot = filter_snapshot(tracemalloc.take_snapshot())
            display_top(new_snapshot)
            compare_snapshots(self.init_snapshot, new_snapshot)
        signal.signal(signal.SIGUSR2, checkpoint)

    def start(self):
        start_http_server(self.port, registry=registry)
        self.loop()

    def update(self):
        log.info("Updating...")
        for metric in self.metrics:
            metric.update()
        log.info("Update finished.")
        self.update_count += 1
        if self.update_count == 1:
            self.init_snapshot = filter_snapshot(tracemalloc.take_snapshot())
            display_top(self.init_snapshot)

    def loop(self):
        log.info("Starting teuthology-exporter...")
        while True:
            try:
                before = time.perf_counter()
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


class TeuthologyMetric:
    def __init__(self):
        pass

    def update(self):
        raise NotImplementedError


class Dispatchers(TeuthologyMetric):
    def __init__(self):
        self.metric = Gauge(
            "teuthology_dispatchers", "Teuthology Dispatchers", ["machine_type"]
        )

    def update(self):
        dispatcher_procs = teuthology.dispatcher.find_dispatcher_processes()
        for machine_type in MACHINE_TYPES:
            self.metric.labels(machine_type).set(
                len(dispatcher_procs.get(machine_type, []))
            )


class BeanstalkQueue(TeuthologyMetric):
    def __init__(self):
        self.length = Gauge(
            "beanstalk_queue_length", "Beanstalk Queue Length", ["machine_type"]
        )
        self.paused = Gauge(
            "beanstalk_queue_paused", "Beanstalk Queue is Paused", ["machine_type"]
        )

    def update(self):
        for machine_type in MACHINE_TYPES:
            queue_stats = beanstalk.stats_tube(beanstalk.connect(), machine_type)
            self.length.labels(machine_type).set(queue_stats["count"])
            self.paused.labels(machine_type).set(1 if queue_stats["paused"] else 0)


class JobProcesses(TeuthologyMetric):
    def __init__(self):
        self.metric = Gauge(
            "teuthology_job_processes",
            "Teuthology Job Processes",
        )

    def update(self):

        attrs = ["pid", "cmdline"]
        total = 0
        for proc in psutil.process_iter(attrs=attrs):
            if self._match(proc):
                total += 1
        self.metric.set(total)

    @staticmethod
    def _match(proc):
        cmdline = proc.cmdline()
        if not len(cmdline) > 1:
            return False
        if not cmdline[1].endswith("teuthology"):
            return False
        if "--archive" not in cmdline:
            return False
        if "--name" not in cmdline:
            return False
        try:
            owner_index = cmdline.index("--owner") + 1
            if not cmdline[owner_index].startswith("scheduled_"):
                return False
        except ValueError:
            return False
        return True


class Nodes(TeuthologyMetric):
    def __init__(self):
        self.metric = Gauge(
            "teuthology_nodes", "Teuthology Nodes", ["machine_type", "locked", "up"]
        )

    def update(self):
        for machine_type in MACHINE_TYPES:
            nodes = list_locks(machine_type=machine_type)
            for up, locked in itertools.product([True, False], [True, False]):
                self.metric.labels(machine_type=machine_type, up=up, locked=locked).set(
                    len([n for n in nodes if n["up"] is up and n["locked"] is locked])
                )


class _JobResults(TeuthologyMetric):
    def __init__(self):
        self.metric = Counter(
            "teuthology_job_results",
            "Teuthology Job Results",
            ["machine_type", "status"],
        )

    # As this is to be used within job processes, we implement record() rather than update()
    def record(self, machine_type, status):
        self.metric.labels(machine_type=machine_type, status=status).inc()


JobResults = _JobResults()

NodeLockingTime = Summary(
    "teuthology_node_locking_duration_seconds",
    "Time spent waiting to lock nodes",
    ["machine_type", "count"],
)

NodeReimagingTime = Summary(
    "teuthology_node_reimaging_duration_seconds",
    "Time spent reimaging nodes",
    ["machine_type", "count"],
)

JobTime = Summary(
    "teuthology_job_duration_seconds",
    "Time spent executing a job",
    ["suite"],
)

TaskTime = Summary(
    "teuthology_task_duration_seconds",
    "Time spent executing a task",
    ["name", "phase"],
)

BootstrapTime = Summary(
    "teuthology_bootstrap_duration_seconds",
    "Time spent running teuthology's bootstrap script",
)


def filter_snapshot(snapshot):
    snapshot = snapshot.filter_traces((
        tracemalloc.Filter(False, "<frozen importlib._bootstrap>"),
        tracemalloc.Filter(False, "<unknown>"),
    ))
    return snapshot


def display_top(snapshot, key_type='lineno', limit=10):
    top_stats = snapshot.statistics(key_type)

    print("Top %s lines" % limit)
    for index, stat in enumerate(top_stats[:limit], 1):
        frame = stat.traceback[0]
        print("#%s: %s:%s: %.1f KiB"
              % (index, frame.filename, frame.lineno, stat.size / 1024))
        line = linecache.getline(frame.filename, frame.lineno).strip()
        if line:
            print('    %s' % line)

    other = top_stats[limit:]
    if other:
        size = sum(stat.size for stat in other)
        print("%s other: %.1f KiB" % (len(other), size / 1024))
    total = sum(stat.size for stat in top_stats)
    print("Total allocated size: %.1f KiB" % (total / 1024))


def compare_snapshots(snap_a, snap_b):
    print("# Top 10 differences")
    top_stats = snap_b.compare_to(snap_a, 'lineno')
    for stat in top_stats[:10]:
        print(stat)


def main(args):
    exporter = TeuthologyExporter(interval=int(args["--interval"]))
    exporter.start()

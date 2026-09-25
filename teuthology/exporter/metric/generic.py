import psutil

from teuthology.exporter.metric import TeuthologyMetric
from prometheus_client import (  # noqa: E402
    Gauge,
    Counter,
    Summary,
)

class JobProcesses(TeuthologyMetric):
    def _init(self):
        self.metric = Gauge(
            "teuthology_job_processes",
            "Teuthology Job Processes",
        )

    def _update(self):
        attrs = ["pid", "cmdline"]
        total = 0
        for proc in psutil.process_iter(attrs=attrs):
            if self._match(proc):
                total += 1
        self.metric.set(total)

    @staticmethod
    def _match(proc):
        try:
            cmdline = proc.cmdline()
        except psutil.ZombieProcess:
            return False
        except psutil.AccessDenied:
            return False
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


class JobResults(TeuthologyMetric):
    def _init(self):
        self.metric = Counter(
            "teuthology_job_results",
            "Teuthology Job Results",
            ["machine_type", "status"],
        )

    # As this is to be used within job processes, we implement record() rather than update()
    def _record(self, **labels):
        self.metric.labels(**labels).inc()


class JobTime(TeuthologyMetric):
    def _init(self):
        self.metric = Summary(
            "teuthology_job_duration_seconds",
            "Time spent executing a job",
            ["suite"],
        )

    def _time(self, **labels):
        yield self.metric.labels(**labels).time()


class TaskTime(TeuthologyMetric):
    def _init(self):
        self.metric = Summary(
            "teuthology_task_duration_seconds",
            "Time spent executing a task",
            ["name", "phase"],
        )

    def _time(self, **labels):
        yield self.metric.labels(**labels).time()


class BootstrapTime(TeuthologyMetric):
    def _init(self):
        self.metric = Summary(
            "teuthology_bootstrap_duration_seconds",
            "Time spent running teuthology's bootstrap script",
        )

    def _time(self, **labels):
        yield self.metric.labels(**labels).time()


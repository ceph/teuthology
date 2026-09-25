import itertools

from teuthology.exporter.metric import TeuthologyMetric
from teuthology.exporter import MACHINE_TYPES, REGISTRY
from prometheus_client import (  # noqa: E402
    Gauge,
    Counter,
    Summary,
)

from teuthology.lock.query import list_locks

class Nodes(TeuthologyMetric):
    def _init(self):
        self.metric = Gauge(
            "teuthology_nodes",
            "Teuthology Nodes",
            ["machine_type", "locked", "up"],
        )

    def _update(self):
        for machine_type in MACHINE_TYPES:
            nodes = list_locks(machine_type=machine_type)
            for up, locked in itertools.product([True, False], [True, False]):
                self.metric.labels(machine_type=machine_type, up=up, locked=locked).set(
                    len([n for n in nodes if n["up"] is up and n["locked"] is locked])
                )


class NodeReimagingResults(TeuthologyMetric):
    def _init(self):
        self.metric = Counter(
            "teuthology_reimaging_results",
            "Teuthology Reimaging Results",
            ["machine_type", "status"],
        )

    # As this is to be used within job processes, we implement record() rather than update()
    def _record(self, **labels):
        if REGISTRY:
            self.metric.labels(**labels).inc()


class NodeLockingTime(TeuthologyMetric):
    def _init(self):
        self.metric = Summary(
            "teuthology_node_locking_duration_seconds",
            "Time spent waiting to lock nodes",
            ["machine_type", "count"],
        )

    def _time(self, **labels):
        yield self.metric.labels(**labels).time()


class NodeReimagingTime(TeuthologyMetric):
    def _init(self):
        self.metric = Summary(
            "teuthology_node_reimaging_duration_seconds",
            "Time spent reimaging nodes",
            ["machine_type", "count"],
        )

    def _time(self, **labels):
        yield self.metric.labels(**labels).time()



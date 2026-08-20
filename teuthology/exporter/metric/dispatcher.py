from teuthology.exporter.metric import TeuthologyMetric
from teuthology.exporter import MACHINE_TYPES
import teuthology.dispatcher

from prometheus_client import (  # noqa: E402
    Gauge,
)

class Dispatchers(TeuthologyMetric):
    def _init(self):
        self.metric = Gauge(
            "teuthology_dispatchers",
            "Teuthology Dispatchers",
            ["machine_type"],
        )

    def _update(self):
        dispatcher_procs = teuthology.dispatcher.find_dispatcher_processes()
        for machine_type in MACHINE_TYPES:
            self.metric.labels(machine_type).set(
                len(dispatcher_procs.get(machine_type, []))
            )

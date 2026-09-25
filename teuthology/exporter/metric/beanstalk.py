from teuthology.exporter import MACHINE_TYPES
from teuthology.exporter.metric import TeuthologyMetric

import teuthology.beanstalk as beanstalk

from prometheus_client import (  # noqa: E402
    Gauge,
)

class BeanstalkQueue(TeuthologyMetric):
    def _init(self):
        self.length = Gauge(
            "beanstalk_queue_length",
            "Beanstalk Queue Length",
            ["machine_type"],
        )
        self.paused = Gauge(
            "beanstalk_queue_paused", "Beanstalk Queue is Paused", ["machine_type"]
        )

    def _update(self):
        for machine_type in MACHINE_TYPES:
            queue_stats = beanstalk.stats_tube(beanstalk.connect(), machine_type)
            self.length.labels(machine_type).set(queue_stats["count"])
            self.paused.labels(machine_type).set(1 if queue_stats["paused"] else 0)


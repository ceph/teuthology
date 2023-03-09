.. _exporter:

==================================
The Teuthology Prometheus Exporter
==================================

To help make it easier to determine the status of the lab, we've created a
`Prometheus <https://prometheus.io/>`__ exporter (helpfully named
`teuthology-exporter`. We use `Grafana <https://grafana.com/>`__ to visualize
the data we collect.

It listens on port 61764, and scrapes every 60 seconds by default.


Exposed Metrics
===============

.. list-table::

  * - Name
    - Type
    - Description
    - Labels
  * - beanstalk_queue_length
    - Gauge
    - The number of jobs in the beanstalkd queue
    - machine type
  * - beanstalk_queue_paused
    - Gauge
    - Whether or not the beanstalkd queue is paused
    - machine type
  * - teuthology_dispatchers
    - Gauge
    - The number of running teuthology-dispatcher instances
    - machine type
  * - teuthology_job_processes
    - Gauge
    - The number of running job *processes*
    - 
  * - teuthology_job_results_total
    - Gauge
    - The number of completed jobs
    - status (pass/fail/dead)
  * - teuthology_nodes
    - Gauge
    - The number of test nodes
    - up, locked
  * - teuthology_job_duration_seconds
    - Summary
    - The time it took to run a job
    - suite
  * - teuthology_task_duration_seconds
    - Summary
    - The time it took for each phase of each task to run
    - name, phase (enter/exit)
  * - teuthology_bootstrap_duration_seconds
    - Summary
    - The time it took to run teuthology's bootstrap script
    - 
  * - teuthology_node_locking_duration_seconds
    - Summary
    - The time it took to lock nodes
    - machine type, count
  * - teuthology_node_reimaging_duration_seconds
    - Summary
    - The time it took to reimage nodes
    - machine type, count

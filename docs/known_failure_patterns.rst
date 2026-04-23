Known Failure Patterns
======================

When using the ``--skip-known-failures`` option with ``teuthology-suite --rerun``,
teuthology can filter out jobs with known failure patterns. The known patterns are
loaded from a JSON or YAML file specified with ``--known-failure-patterns``, or from
the default bundled file ``teuthology/suite/patterns/known-failures.json``.

File Format
-----------

The file format supports both JSON and YAML. The file must contain a ``patterns``
key with a list of regex patterns (strings) that will be matched against job
failure reasons.

JSON format example::

    {
        "patterns": [
            "Command failed on .* with status 1:",
            "clocks not synchronized",
            "cluster \\[WRN\\] Health check failed:.*OBJECT_UNFOUND"
        ]
    }

YAML format example::

    patterns:
      - "Command failed on .* with status 1:"
      - "clocks not synchronized"
      - "cluster \\[WRN\\] Health check failed:.*OBJECT_UNFOUND"

Pattern Matching
----------------

Patterns are matched using Python's ``re.search()`` function, so they support
full regular expression syntax. If a job's ``failure_reason`` matches any of
the patterns, it is considered a known failure and will be skipped during
rerun when ``--skip-known-failures`` is enabled.

Only jobs with failure reasons that don't match any known pattern will be
scheduled for rerun.

Usage
-----

To use known failure patterns during rerun::

    teuthology-suite --rerun <run_name> --skip-known-failures

To specify a custom patterns file::

    teuthology-suite --rerun <run_name> --skip-known-failures --known-failure-patterns /path/to/patterns.json


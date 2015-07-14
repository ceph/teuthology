import logging

log = logging.getLogger(__name__)


class TestSSH(object):
    """
    Does paramiko work?
    """
    def test_exec_many_procs(self, ctx, config):
        config = config or dict()
        attempts_per_host = config.get('attempts_per_host', 1000)
        for i in range(1, attempts_per_host + 1):
            log.debug("Attempt %s of %s", i, attempts_per_host)
            ctx.cluster.run(args="echo attempt %s" % i)
        assert i == attempts_per_host

"""
Monkey patches (paramiko support)
"""
import logging

log = logging.getLogger(__name__)

def patch_100_paramiko_log():
    """
    Silence some noise paramiko likes to log.

    Not strictly a monkeypatch.
    """
    logging.getLogger('paramiko.transport').setLevel(logging.WARNING)


def patch_all():
    """
    Run all the patch_* functions in this module.
    """
    monkeys = [(k, v) for (k, v) in globals().items() if k.startswith('patch_') and k != 'patch_all']
    monkeys.sort()
    for k, v in monkeys:
        log.debug('Patching %s', k)
        v()

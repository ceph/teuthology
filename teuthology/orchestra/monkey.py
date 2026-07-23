"""
Monkey patches (paramiko support)
"""
import logging

log = logging.getLogger(__name__)

def patch_001_paramiko_deprecation() -> None:
    """
    Silence an an unhelpful Deprecation Warning triggered by Paramiko.

    Not strictly a monkeypatch.
    """
    import warnings
    warnings.filterwarnings(
        category=DeprecationWarning,
        message='This application uses RandomPool,',
        action='ignore',
        )


def patch_100_paramiko_log() -> None:
    """
    Silence some noise paramiko likes to log.

    Not strictly a monkeypatch.
    """
    logging.getLogger('paramiko.transport').setLevel(logging.WARNING)


def patch_100_trigger_rekey() -> None:
    # Fixes http://tracker.ceph.com/issues/15236
    from paramiko.packet import Packetizer
    Packetizer._trigger_rekey = lambda _: True  # ty: ignore[invalid-assignment]


def patch_all() -> None:
    """
    Run all the patch_* functions in this module.
    """
    monkeys = [(k, v) for (k, v) in globals().items() if k.startswith('patch_') and k != 'patch_all']
    monkeys.sort()
    for k, v in monkeys:
        log.debug('Patching %s', k)
        v()

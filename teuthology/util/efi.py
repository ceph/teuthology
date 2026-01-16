

def is_uefi(remote):
    """Return True if the remote is booted in UEFI mode."""
    try:
        remote.run(args=['test', '-d', '/sys/firmware/efi'])
        return True
    except Exception:
        return False
-
-


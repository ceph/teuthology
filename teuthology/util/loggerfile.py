import logging

class LoggerFile(object):
    """
    A thin wrapper around a logging.Logger instance that provides a file-like
    interface.

    Used by Ansible.execute_playbook() when it calls pexpect.run()
    """
    def __init__(self, logger: logging.Logger, level: int):
        self.logger = logger
        self.level = level

    def write(self, string: bytes) -> None:
        self.logger.log(self.level, string.decode('utf-8', 'ignore'))

    def flush(self) -> None:
        pass


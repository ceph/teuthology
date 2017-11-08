import teuthology.orchestra.remote


class Console(object):
    def __init__(self, name):
        self.name = name
        self.shortname = teuthology.orchestra.remote.getShortName(name)

    def check_power(self, state, timeout=None):
        pass

    def check_status(self, timeout=None):
        pass

    def hard_reset(self):
        pass

    def power_cycle(self):
        pass

    def power_on(self):
        pass

    def power_off(self):
        pass

    def power_off_for_interval(self, interval=30):
        pass

from teuthology.config import config

def pytest_runtest_setup():
    config.load({})

from copy import deepcopy

from mock import patch, DEFAULT, PropertyMock
from pytest import raises, mark

from teuthology.config import config
from teuthology.exceptions import MaxWhileTries
from teuthology.provision import pelagos


test_config = dict(pelagos=dict(
    endpoint='http://pelagos.example.com/pelagos',
    machine_types='type1,type2',
))

class TestPelagios(object):
    klass = pelagos.Pelagos

    def setup(self):
        config.load(deepcopy(test_config))


    #    def teardown(self):

    def test_get_types(self):
        #with patch('teuthology.provision.pelagos.enabled') as m_enabled:
        #    m_enabled.return_value = enabled

        types = pelagos.get_types()
        assert types == test_config['pelagos']['machine_types'].split(',')

    def test_do_request(self):
        obj = self.klass('name.fqdn', 'type', '1.0')
        obj.do_request('/nodes', data='', method='GET')

#    def test_get_node(self):
#        obj = self.klass
#        types =  pelagos. \
#            #fog.get_types()


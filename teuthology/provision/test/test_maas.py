from copy import deepcopy
from mock import patch, DEFAULT, PropertyMock
from pytest import raises, mark
from requests.models import Response

from teuthology.config import config
from teuthology.orchestra.opsys import OS
from teuthology.provision import maas


test_config = dict(
    maas=dict(
        api_url="http://maas.example.com:5240/MAAS/api/2.0/",
        api_key="CONSUMER_KEY:ACCESS_TOKEN:SECRET",
        machine_types=["typeA", "typeB"],
        timeout=900,
        user_data="teuthology/maas/maas-{os_type}-{os_version}-user-data.txt"
    )
)

class TestMaas(object):
    klass = maas.MAAS

    def setup_method(self):
        config.load()
        config.update(deepcopy(test_config))
        self.start_patchers()

    def start_patchers(self):
        self.patchers = dict()
        self.patchers["m_Remote_hostname"] = patch(
            "teuthology.orchestra.remote.Remote.hostname",
            new_callable=PropertyMock,
        )
        self.patchers["m_Remote_machine_os"] = patch(
            "teuthology.orchestra.remote.Remote.os",
            new_callable=PropertyMock,
        )
        self.patchers["m_Remote_opsys_os"] = patch(
            "teuthology.orchestra.opsys.OS",
            new_callable=PropertyMock,
        )

        self.mocks = dict()
        for name, patcher in self.patchers.items():
            self.mocks[name] = patcher.start()

    def teardown_method(self):
        for patcher in self.patchers.values():
            patcher.stop()

    def _get_mock_response(self, status_code=200, content=None, headers=None):
        response = Response()
        response.status_code = status_code
        response._content = content
        if headers is not None:
            response.headers = headers
        return response

    def test_api_url_missing(self):
        config.maas["api_url"] = None
        with raises(RuntimeError):
            self.klass("name.fqdn")

    def test_api_key_missing(self):
        config.maas["api_key"] = None
        with raises(RuntimeError):
            self.klass("name.fqdn")

    @mark.parametrize("enabled", [True, False])
    def test_get_types(self, enabled):
        with patch("teuthology.provision.maas.enabled") as m_enabled:
            m_enabled.return_value = enabled
            types = maas.get_types()

        if enabled:
            assert types == test_config["maas"]["machine_types"]
        else:
            assert types == []

    @mark.parametrize("status_name, osystem, distro_series", [
        ("ready", "ubuntu", "jammy"),
        ("deployed", "ubuntu", "jammy"),
    ])
    def test_init(self, status_name, osystem, distro_series):
        self.mocks["m_Remote_hostname"].return_value = "name.fqdn"
        with patch(
            "teuthology.provision.maas.MAAS.get_machines_data"
        ) as maas_machine:
            maas_machine.return_value = {
                "status_name": status_name,
                "system_id": "abc123",
                "osystem": osystem,
                "distro_series": distro_series,
            }
            if not (osystem and distro_series):
                with raises(RuntimeError):
                    obj = self.klass(
                        name="name.fqdn",
                        os_type=osystem,
                        os_version=distro_series
                    )
            else:
                obj = self.klass(
                    name="name.fqdn",
                    os_type=osystem,
                    os_version=distro_series
                )
                assert obj.name == "name.fqdn"
                assert obj.shortname == "name"
                assert obj.os_type == osystem
                assert obj.os_version == distro_series
                assert obj.system_id == "abc123"

    @mark.parametrize("os_name, os_version, codename", [
        ("ubuntu", "24.04", "noble"), ("centos", "8", "core"),
    ])
    def test_get_image_data(self, os_name, os_version, codename):
        with patch.multiple(
            "teuthology.provision.maas.MAAS",
            do_request=DEFAULT,
            get_machines_data=DEFAULT,
        ) as local_mocks:
            local_mocks["do_request"].return_value = self._get_mock_response(
                content=b'[{"name": "%s/%s"}]' % (
                    os_name.encode(), codename.encode()
                )
            )
            local_mocks["get_machines_data"].return_value = {
                "status_name": "ready"
            }
            obj = self.klass(
                name="name.fqdn", os_type=os_name, os_version=os_version
            )
            assert obj.get_image_data() == {"name": f"{os_name}/{codename}"}

    def test_lock_machine(self):
        with patch.multiple(
            "teuthology.provision.maas.MAAS",
            do_request=DEFAULT,
            get_machines_data=DEFAULT,
        ) as local_mocks:
            local_mocks["get_machines_data"].return_value = {
                "system_id": "1234abc"
            }
            local_mocks["do_request"].return_value = self._get_mock_response(
                content=b'{"locked": "true"}'
            )
            assert self.klass(name="name.fqdn").lock_machine() is None

    def test_unlock_machine(self):
        self.mocks["m_Remote_hostname"].return_value = "name.fqdn"
        with patch.multiple(
            "teuthology.provision.maas.MAAS",
            do_request=DEFAULT,
            get_machines_data=DEFAULT,
        ) as local_mocks:
            local_mocks["get_machines_data"].return_value = {
                "system_id": "1234abc"
            }
            local_mocks["do_request"].return_value = self._get_mock_response(
                content=b'{"locked": "true"}'
            )
            with raises(RuntimeError):
                self.klass(name="name.fqdn").unlock_machine()

    @mark.parametrize("type, status_name", [
        ("uploaded", ""), ("synced", "deploying"), ("synced", "ready"),
    ])
    def test_deploy_machine(self, type, status_name):
        with patch.multiple(
            "teuthology.provision.maas.MAAS",
            get_image_data=DEFAULT,
            _get_user_data=DEFAULT,
            get_machines_data=DEFAULT,
            do_request=DEFAULT,
        ) as local_mocks:
            local_mocks["get_machines_data"].return_value = {
                "system_id": "1234abc"
            }
            local_mocks["get_image_data"].return_value = {
                "name": "ubuntu/noble", "type": type
            }
            local_mocks["_get_user_data"].return_value = "init-host-data"
            local_mocks["do_request"].return_value = self._get_mock_response(
                content=b'{"status_name": "%s"}' % status_name.encode()
            )
            obj = self.klass(name="name.fqdn")
            if (status_name != "deploying" or type != "synced"):
                with raises(RuntimeError):
                    obj.deploy_machine()
            else:
                assert obj.deploy_machine() is None

    @mark.parametrize("response", [b'{}', ])
    def test_release_machine(self, response):
        with patch.multiple(
            "teuthology.provision.maas.MAAS",
            get_machines_data=DEFAULT,
            do_request=DEFAULT,
        ) as local_mocks:
            local_mocks["get_machines_data"].return_value = {
                "system_id": "1234abc"
            }
            local_mocks["do_request"].return_value = self._get_mock_response(
                content=b'{"status_name": "disk erasing"}'
            )
            assert self.klass(name="name.fqdn").release_machine() is None

    @mark.parametrize("status_name", ["deploying", "ready"])
    def test_abort_deploy(self, status_name):
        with patch.multiple(
            "teuthology.provision.maas.MAAS",
            get_machines_data=DEFAULT,
            do_request=DEFAULT,
        ) as local_mocks:
            local_mocks["get_machines_data"].return_value = {
                "status_name": status_name, "system_id": "1234abc"
            }
            local_mocks["do_request"].return_value = self._get_mock_response(
                content=b'{"status_name": "allocated"}'
            )
            assert self.klass(name="name.fqdn").abort_deploy() is None

    @mark.parametrize("lock_status, machine_status", [
        (False, "ready"), (False, "allocated"),
        (True, "deployed"), (False, "deployed"),
        (False, "releasing"),
    ])
    def test_release(self, lock_status, machine_status):
        with patch.multiple(
            "teuthology.provision.maas.MAAS",
            get_machines_data=DEFAULT,
            unlock_machine=DEFAULT,
            release_machine=DEFAULT,
            _wait_for_status=DEFAULT,
        ) as local_mocks:
            local_mocks["get_machines_data"].return_value = {
                "status_name": machine_status,
                "locked": lock_status,
                "system_id": "1234abc",
            }
            obj = self.klass(name="name.fqdn")
            if machine_status in ["ready", "allocated"]:
                obj.release()

            elif machine_status == "deployed":
                local_mocks["unlock_machine"].return_value = None
                local_mocks["release_machine"].return_value = None
                local_mocks["_wait_for_status"].return_value = None
                obj.release()

            else:
                with raises(RuntimeError):
                    obj.release()

    @mark.parametrize("user_data", [True, False])
    def test_get_user_data(self, user_data):
        with patch(
            "teuthology.provision.maas.MAAS.get_machines_data"
        ) as maas_machine:
            maas_machine.return_value = { "system_id": "1234abc" }
            obj = self.klass(name="name.fqdn")
            if user_data:
                assert user_data is not None
            else:
                config.maas["user_data"] = None
                user_data = obj._get_user_data()
                assert user_data is None
    
    @mark.parametrize(
        "os_type, os_version, remote_os_type, remote_os_version", [
        ("centos", "8", "centos", "8"),
        ("", "", "ubuntu", "22.04")
    ])
    def test_verify_installed_os(
        self, os_type, os_version, remote_os_type, remote_os_version
    ):
        self.mocks["m_Remote_machine_os"].return_value = OS(
            name=remote_os_type, version=remote_os_version
        )
        with patch(
            "teuthology.provision.maas.MAAS.get_machines_data"
        ) as maas_machine:
            maas_machine.return_value = { "system_id": "1234abc" }
            if os_type and os_version:
                self.klass(
                    name="name.fqdn", os_type=os_type, os_version=os_version
                )._verify_installed_os()
            else:
                self.klass(name="name.fqdn")._verify_installed_os()
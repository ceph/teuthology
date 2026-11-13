import os
import pytest
import tempfile

from mock import Mock, patch

from teuthology.config import config
from teuthology.orchestra.opsys import OS
from teuthology.suite import util
from teuthology.exceptions import (
    BranchNotFoundError, CommitValidationError, ScheduleFailError,
)


REPO_PROJECTS_AND_URLS = [
    'ceph',
    'https://github.com/not_ceph/ceph.git',
]


@pytest.mark.parametrize('project_or_url', REPO_PROJECTS_AND_URLS)
@patch('subprocess.check_output')
def test_git_branch_exists(m_check_output, project_or_url):
    m_check_output.return_value = ''
    assert False == util.git_branch_exists(
        project_or_url, 'nobranchnowaycanthappen')
    m_check_output.return_value = b'HHH branch'
    assert True == util.git_branch_exists(project_or_url, 'main')


@pytest.fixture
def git_repository(request):
    d = tempfile.mkdtemp()
    os.system("""
    cd {d}
    git init
    touch A
    git config user.email 'you@example.com'
    git config user.name 'Your Name'
    git add A
    git commit -m 'A' A
    git rev-parse --abbrev-ref main || git checkout -b main
    """.format(d=d))

    def fin():
        os.system("rm -fr " + d)
    request.addfinalizer(fin)
    return d


class TestUtil(object):
    @patch('teuthology.suite.util.smtplib.SMTP')
    def test_schedule_fail(self, m_smtp):
        config.results_email = "example@example.com"
        with pytest.raises(ScheduleFailError) as exc:
            util.schedule_fail(message="error msg", dry_run=False)
        assert str(exc.value) == "Scheduling failed: error msg"
        m_smtp.assert_called()

    @patch('teuthology.suite.util.smtplib.SMTP')
    def test_schedule_fail_dryrun(self, m_smtp):
        config.results_email = "example@example.com"
        with pytest.raises(ScheduleFailError) as exc:
            util.schedule_fail(message="error msg", dry_run=True)
        assert str(exc.value) == "Scheduling failed: error msg"
        m_smtp.assert_not_called()

    @patch('teuthology.suite.util.fetch_qa_suite')
    @patch('teuthology.suite.util.smtplib.SMTP')
    def test_fetch_repo_no_branch(self, m_smtp, m_fetch_qa_suite):
        m_fetch_qa_suite.side_effect = BranchNotFoundError(
            "no-branch", "https://github.com/ceph/ceph-ci.git")
        config.results_email = "example@example.com"
        with pytest.raises(ScheduleFailError) as exc:
            util.fetch_repos("no-branch", "test1", dry_run=False)
        assert str(exc.value) == "Scheduling test1 failed: \
Branch 'no-branch' not found in repo: https://github.com/ceph/ceph-ci.git!"
        m_smtp.assert_called()

    @patch('teuthology.suite.util.fetch_qa_suite')
    @patch('teuthology.suite.util.smtplib.SMTP')
    def test_fetch_repo_no_branch_dryrun(self, m_smtp, m_fetch_qa_suite):
        m_fetch_qa_suite.side_effect = BranchNotFoundError(
            "no-branch", "https://github.com/ceph/ceph-ci.git")
        config.results_email = "example@example.com"
        with pytest.raises(ScheduleFailError) as exc:
            util.fetch_repos("no-branch", "test1", dry_run=True)
        assert str(exc.value) == "Scheduling test1 failed: \
Branch 'no-branch' not found in repo: https://github.com/ceph/ceph-ci.git!"
        m_smtp.assert_not_called()

    @patch('requests.get')
    def test_get_branch_info(self, m_get):
        mock_resp = Mock()
        mock_resp.ok = True
        mock_resp.json.return_value = "some json"
        m_get.return_value = mock_resp
        result = util.get_branch_info("teuthology", "main")
        m_get.assert_called_with(
            "https://api.github.com/repos/ceph/teuthology/git/refs/heads/main"
        )
        assert result == "some json"

    @patch('teuthology.lock.query')
    def test_get_arch_fail(self, m_query):
        m_query.list_locks.return_value = False
        util.get_arch('magna')
        m_query.list_locks.assert_called_with(machine_type="magna", count=1, tries=1)

    @patch('teuthology.lock.query')
    def test_get_arch_success(self, m_query):
        m_query.list_locks.return_value = [{"arch": "arch"}]
        result = util.get_arch('magna')
        m_query.list_locks.assert_called_with(
            machine_type="magna",
            count=1, tries=1
        )
        assert result == "arch"

    def test_build_git_url_github(self):
        assert 'project' in util.build_git_url('project')
        owner = 'OWNER'
        git_url = util.build_git_url('project', project_owner=owner)
        assert owner in git_url

    @patch('teuthology.config.TeuthologyConfig.get_ceph_qa_suite_git_url')
    def test_build_git_url_ceph_qa_suite_custom(
            self,
            m_get_ceph_qa_suite_git_url):
        url = 'http://foo.com/some'
        m_get_ceph_qa_suite_git_url.return_value = url + '.git'
        assert url == util.build_git_url('ceph-qa-suite')

    @patch('teuthology.config.TeuthologyConfig.get_ceph_git_url')
    def test_build_git_url_ceph_custom(self, m_get_ceph_git_url):
        url = 'http://foo.com/some'
        m_get_ceph_git_url.return_value = url + '.git'
        assert url == util.build_git_url('ceph')

    @patch('teuthology.config.TeuthologyConfig.get_ceph_cm_ansible_git_url')
    def test_build_git_url_ceph_cm_ansible_custom(self, m_get_ceph_cm_ansible_git_url):
        url = 'http://foo.com/some'
        m_get_ceph_cm_ansible_git_url.return_value = url + '.git'
        assert url == util.build_git_url('ceph-cm-ansible')

    @patch('teuthology.config.TeuthologyConfig.get_ceph_git_url')
    def test_git_ls_remote(self, m_get_ceph_git_url, git_repository):
        m_get_ceph_git_url.return_value = git_repository
        assert util.git_ls_remote('ceph', 'nobranch') is None
        assert util.git_ls_remote('ceph', 'main') is not None

    @patch('teuthology.suite.util.requests.get')
    def test_find_git_parents(self, m_requests_get):
        history_resp = Mock(ok=True)
        history_resp.json.return_value = {'sha1s': ['sha1', 'sha1_p']}
        m_requests_get.return_value = history_resp
        parent_sha1s = util.find_git_parents('ceph', 'sha1')
        assert m_requests_get.call_count == 1
        assert parent_sha1s == ['sha1_p']


SHA1 = '3f6447e33197885289cfc3fe0f41b9daa15698ef'


def head_resp(status_code):
    return Mock(status_code=status_code, ok=status_code < 400)


@patch('teuthology.suite.util.time.sleep')
@patch('teuthology.suite.util.requests.head')
class TestGitValidateSha1(object):
    def setup_method(self):
        config.ceph_git_url = 'https://github.com/ceph/ceph.git'
        self.githelper_base_url = config.githelper_base_url
        config.githelper_base_url = None

    def teardown_method(self):
        config.ceph_git_url = None
        config.githelper_base_url = self.githelper_base_url

    def test_github_found(self, m_head, m_sleep):
        m_head.return_value = head_resp(200)
        assert util.git_validate_sha1('ceph', SHA1) == SHA1
        url = m_head.call_args[0][0]
        assert url == 'https://github.com/ceph/ceph/commit/' + SHA1
        assert m_head.call_args[1]['allow_redirects'] is True

    def test_github_not_found(self, m_head, m_sleep):
        m_head.return_value = head_resp(404)
        assert util.git_validate_sha1('ceph', SHA1) is None
        assert m_head.call_count == 1

    def test_gitweb_uses_https(self, m_head, m_sleep):
        config.ceph_git_url = 'https://git.ceph.com/ceph.git'
        m_head.return_value = head_resp(200)
        assert util.git_validate_sha1('ceph', SHA1) == SHA1
        url = m_head.call_args[0][0]
        assert url.startswith('https://git.ceph.com/?p=ceph.git;')
        assert url.endswith('hb=' + SHA1)

    def test_retries_rate_limit(self, m_head, m_sleep):
        m_head.side_effect = [head_resp(429), head_resp(502), head_resp(200)]
        assert util.git_validate_sha1('ceph', SHA1) == SHA1
        assert m_head.call_count == 3
        assert m_sleep.call_count == 2

    def test_retries_connection_error(self, m_head, m_sleep):
        m_head.side_effect = [
            util.requests.ConnectionError('boom'), head_resp(200)]
        assert util.git_validate_sha1('ceph', SHA1) == SHA1
        assert m_head.call_count == 2

    def test_persistent_failure_raises(self, m_head, m_sleep):
        m_head.return_value = head_resp(503)
        with pytest.raises(CommitValidationError) as exc:
            util.git_validate_sha1('ceph', SHA1)
        assert m_head.call_count == 5
        assert 'HTTP 503' in str(exc.value)
        assert SHA1 in str(exc.value)

    def test_other_4xx_raises_without_retry(self, m_head, m_sleep):
        m_head.return_value = head_resp(403)
        with pytest.raises(CommitValidationError):
            util.git_validate_sha1('ceph', SHA1)
        assert m_head.call_count == 1
        assert m_sleep.call_count == 0


def githelper_resp(sha1, status_code=200):
    resp = Mock(status_code=status_code, ok=status_code < 400)
    resp.json.return_value = {'sha1': sha1, 'err': '', 'shortmsg': None}
    if status_code >= 400:
        resp.raise_for_status.side_effect = util.requests.HTTPError(
            '%d' % status_code)
    return resp


@patch('teuthology.suite.util.time.sleep')
@patch('teuthology.suite.util.requests.head')
@patch('teuthology.suite.util.requests.get')
class TestGithelperValidateSha1(object):
    def setup_method(self):
        config.ceph_git_url = 'https://github.com/ceph/ceph.git'
        self.githelper_base_url = config.githelper_base_url
        config.githelper_base_url = 'https://githelper.example.com/'

    def teardown_method(self):
        config.ceph_git_url = None
        config.githelper_base_url = self.githelper_base_url

    def test_found(self, m_get, m_head, m_sleep):
        m_get.return_value = githelper_resp(SHA1)
        assert util.git_validate_sha1('ceph', SHA1[:8]) == SHA1
        assert m_get.call_count == 1
        url, kwargs = m_get.call_args[0][0], m_get.call_args[1]
        assert url == 'https://githelper.example.com/ceph.git/sha1/'
        assert kwargs['params'] == {'sha1': SHA1[:8]}
        assert m_head.call_count == 0

    def test_found_after_refresh(self, m_get, m_head, m_sleep):
        m_get.side_effect = [
            githelper_resp(None), Mock(ok=True), githelper_resp(SHA1)]
        assert util.git_validate_sha1('ceph', SHA1) == SHA1
        urls = [c[0][0] for c in m_get.call_args_list]
        assert urls[1] == 'https://githelper.example.com/ceph.git/refresh/'
        assert m_head.call_count == 0

    def test_unknown_falls_back_to_http(self, m_get, m_head, m_sleep):
        m_get.side_effect = [
            githelper_resp(None), Mock(ok=True), githelper_resp(None)]
        m_head.return_value = head_resp(404)
        assert util.git_validate_sha1('ceph', SHA1) is None
        assert m_head.call_count == 1

    def test_http_error_falls_back_to_http(self, m_get, m_head, m_sleep):
        # e.g. a repo githelper does not mirror
        m_get.return_value = githelper_resp(None, status_code=500)
        m_head.return_value = head_resp(200)
        assert util.git_validate_sha1('ceph', SHA1) == SHA1
        assert m_get.call_count == 1
        assert m_head.call_count == 1

    def test_unreachable_falls_back_to_http(self, m_get, m_head, m_sleep):
        m_get.side_effect = util.requests.ConnectionError('boom')
        m_head.return_value = head_resp(200)
        assert util.git_validate_sha1('ceph', SHA1) == SHA1
        assert m_head.call_count == 1

    def test_unconfigured_skips_githelper(self, m_get, m_head, m_sleep):
        config.githelper_base_url = None
        m_head.return_value = head_resp(200)
        assert util.git_validate_sha1('ceph', SHA1) == SHA1
        assert m_get.call_count == 0


class TestFlavor(object):

    def test_get_install_task_flavor_bare(self):
        config = dict(
            tasks=[
                dict(
                    install=dict(),
                ),
            ],
        )
        assert util.get_install_task_flavor(config) == 'default'

    def test_get_install_task_flavor_simple(self):
        config = dict(
            tasks=[
                dict(
                    install=dict(
                        flavor='notcmalloc',
                    ),
                ),
            ],
        )
        assert util.get_install_task_flavor(config) == 'notcmalloc'

    def test_get_install_task_flavor_override_simple(self):
        config = dict(
            tasks=[
                dict(install=dict()),
            ],
            overrides=dict(
                install=dict(
                    flavor='notcmalloc',
                ),
            ),
        )
        assert util.get_install_task_flavor(config) == 'notcmalloc'

    def test_get_install_task_flavor_override_project(self):
        config = dict(
            tasks=[
                dict(install=dict()),
            ],
            overrides=dict(
                install=dict(
                    ceph=dict(
                        flavor='notcmalloc',
                    ),
                ),
            ),
        )
        assert util.get_install_task_flavor(config) == 'notcmalloc'


class TestMissingPackages(object):
    """
    Tests the functionality that checks to see if a
    scheduled job will have missing packages in shaman.
    """
    @patch("teuthology.packaging.ShamanProject._get_package_version")
    def test_distro_has_packages(self, m_gpv):
        m_gpv.return_value = "v1"
        result = util.package_version_for_hash(
            "sha1",
            "basic",
            "ubuntu",
            "14.04",
            "mtype",
        )
        assert result

    @patch("teuthology.packaging.ShamanProject._get_package_version")
    def test_distro_does_not_have_packages(self, m_gpv):
        m_gpv.return_value = None
        result = util.package_version_for_hash(
            "sha1",
            "basic",
            "rhel",
            "7.0",
            "mtype",
        )
        assert not result


class TestDistroDefaults(object):
    def test_distro_defaults_plana(self):
        expected = ('x86_64', 'ubuntu/22.04',
                    OS(name='ubuntu', version='22.04', codename='jammy'))
        assert util.get_distro_defaults('ubuntu', 'plana') == expected

    def test_distro_defaults_debian(self):
        expected = ('x86_64', 'debian/8.0',
                    OS(name='debian', version='8.0', codename='jessie'))
        assert util.get_distro_defaults('debian', 'magna') == expected

    def test_distro_defaults_centos(self):
        expected = ('x86_64', 'centos/9',
                    OS(name='centos', version='9.stream', codename='stream'))
        assert util.get_distro_defaults('centos', 'magna') == expected

    def test_distro_defaults_fedora(self):
        expected = ('x86_64', 'fedora/25',
                    OS(name='fedora', version='25', codename='25'))
        assert util.get_distro_defaults('fedora', 'magna') == expected

    def test_distro_defaults_default(self):
        expected = ('x86_64', 'centos/9',
                    OS(name='centos', version='9.stream', codename='stream'))
        assert util.get_distro_defaults('rhel', 'magna') == expected

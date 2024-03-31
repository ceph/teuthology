from __future__ import with_statement

import glob
import gzip
import os
import shutil
import tempfile
import yaml
from teuthology import scrape

class FakeResultDir(object):
    """Mocks a Result Directory"""

    def __init__(self,
                failure_reason="Dummy reason",
                assertion="FAILED assert 1 == 2\n",
                blank_backtrace=False,
                assertion_osd=False,
    ):
        self.failure_reason = failure_reason
        self.assertion = assertion
        self.blank_backtrace = blank_backtrace
        self.path = tempfile.mkdtemp()
        
        with open(os.path.join(self.path, "config.yaml"), "w") as f:
            yaml.dump({"description": "Dummy test"}, f)
        
        with open(os.path.join(self.path, "summary.yaml"), "w") as f:
            yaml.dump({
                "success": "false",
                "failure_reason": self.failure_reason
            }, f)

        with open(os.path.join(self.path, "teuthology.log"), "w") as f:
            if not self.blank_backtrace:
                f.write(" ceph version 1000\n")
                f.write(".stderr: Dummy error\n")
                f.write(self.assertion)
            f.write(" NOTE: a copy of the executable dummy text\n")

        if assertion_osd:
            host = "host1"
            rem_log_dir = os.path.join(self.path, "remote", host, "log")
            os.makedirs(rem_log_dir, exist_ok=True)
            ceph_mon_log = os.path.join(rem_log_dir, "ceph-osd.0.log")
            with open(ceph_mon_log, "w") as f:
                f.write("ceph version 1000\n")
                f.write(self.assertion)

    def __enter__(self):
        return self

    def __exit__(self, exc_typ, exc_val, exc_tb):
        shutil.rmtree(self.path)

class TestScrape(object):
    """Tests for teuthology.scrape"""

    def test_grep(self):
        with FakeResultDir() as d:
            filepath = os.path.join(d.path, "scrapetest.txt")
            with open(filepath, 'w') as f:
                f.write("Ceph is an open-source software storage platform\n\
                        Teuthology is used for testing.")

            #System level grep is called
            value1 = scrape.grep(filepath, "software")
            value2 = scrape.grep(filepath, "device")

            assert value1 ==\
                ['Ceph is an open-source software storage platform', '']
            assert value2 == []

    def test_job(self):
        with FakeResultDir() as d:
            job = scrape.Job(d.path, 1)
            assert job.get_success() == "false"
            assert job.get_assertion() == "FAILED assert 1 == 2"
            assert job.get_last_tlog_line() ==\
                b"NOTE: a copy of the executable dummy text"
            assert job.get_failure_reason() == "Dummy reason"

    def test_timeoutreason(self):
        with FakeResultDir(failure_reason=\
            "status 124:  timeout '123 /home/ubuntu/cephtest/workunit.client.0/cephtool/test.sh'") as d:
            job = scrape.Job(d.path, 1)
            assert scrape.TimeoutReason.could_be(job)
            assert scrape.TimeoutReason(job).match(job)

    def test_deadreason(self):
        with FakeResultDir() as d:
            job = scrape.Job(d.path, 1)
            #Summary is present
            #So this cannot be a DeadReason
            assert not scrape.DeadReason.could_be(job)

    def test_lockdepreason(self):
        lkReason = None
        with FakeResultDir(assertion=\
            "FAILED assert common/lockdep reason\n") as d:
            job = scrape.Job(d.path, 1)
            assert scrape.LockdepReason.could_be(job)

            lkReason = scrape.LockdepReason(job)
            #Backtraces of same jobs must match 100%
            assert lkReason.match(job)
        with FakeResultDir(blank_backtrace=True) as d:
            #Corresponding to 0% match
            assert not lkReason.match(scrape.Job(d.path, 2))

    def test_assertionreason(self):
        with FakeResultDir() as d:
            job = scrape.Job(d.path, 1)
            assert scrape.AssertionReason.could_be(job)

    def test_genericreason(self):
        d1 = FakeResultDir(blank_backtrace=True)
        d2 = FakeResultDir(failure_reason="Dummy dummy")
        d3 = FakeResultDir()

        job1 = scrape.Job(d1.path, 1)
        job2 = scrape.Job(d2.path, 2)
        job3 = scrape.Job(d3.path, 3)

        reason = scrape.GenericReason(job3)

        assert reason.match(job2)
        assert not reason.match(job1)

        shutil.rmtree(d1.path)
        shutil.rmtree(d2.path)
        shutil.rmtree(d3.path)

    def test_valgrindreason(self):
        vreason = None
        with FakeResultDir(
            failure_reason="saw valgrind issues",
            assertion="2014-08-22T20:07:18.668 ERROR:tasks.ceph:saw valgrind issue   <kind>Leak_DefinitelyLost</kind> in /var/log/ceph/valgrind/osd.3.log.gz\n"
        ) as d:
            job = scrape.Job(d.path, 1)
            assert scrape.ValgrindReason.could_be(job)
            
            vreason = scrape.ValgrindReason(job)
            assert vreason.match(job)

    def test_give_me_a_reason(self):
        with FakeResultDir() as d:
            job = scrape.Job(d.path, 1)
            
            assert type(scrape.give_me_a_reason(job)) == scrape.AssertionReason

        #Test the lockdep ordering
        with FakeResultDir(assertion=\
        "FAILED assert common/lockdep reason\n") as d:
            job = scrape.Job(d.path, 1)
            assert type(scrape.give_me_a_reason(job)) == scrape.LockdepReason

    def test_scraper(self):
        d = FakeResultDir()
        os.mkdir(os.path.join(d.path, "test"))
        shutil.move(
            os.path.join(d.path, "config.yaml"),
            os.path.join(d.path, "test", "config.yaml")
        )
        shutil.move(
            os.path.join(d.path, "summary.yaml"),
            os.path.join(d.path, "test", "summary.yaml")
        )
        shutil.move(
            os.path.join(d.path, "teuthology.log"),
            os.path.join(d.path, "test", "teuthology.log")
        )

        scrape.Scraper(d.path).analyze()

        #scrape.log should be created
        assert os.path.exists(os.path.join(d.path, "scrape.log"))

        shutil.rmtree(d.path)

    def test_gzip_backtrace_decode(self):
        with FakeResultDir(assertion="FAILED assert dummy backtrace line",
                        blank_backtrace=True,
                        assertion_osd=True) as d:

            with open(os.path.join(d.path, "teuthology.log"), "a") as root_log:
                root_log.write(
                    "command crashed with signal SIGSEGV tasks.ceph.osd.0.host1.stderr\n"
                )

            pattern = os.path.join(d.path, "**", "ceph-osd.0.log")
            raws = glob.glob(pattern, recursive=True)
            assert len(raws) == 1, f"expected one raw log, found: {raws}"
            raw_log = raws[0]
            gz_log = raw_log + ".gz"

            with gzip.open(gz_log, "wb") as out:
                out.write(open(raw_log, "rb").read())
            os.remove(raw_log)

            assert not os.path.exists(raw_log)
            assert os.path.exists(gz_log)

            job = scrape.Job(d.path, 1)
            assert job.get_assertion() == "FAILED assert dummy backtrace line"
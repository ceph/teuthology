from .. import results_db
import os
import random
import yaml
import datetime
import io

def test_xtract_date_bad_text():
    # test bad input
    got = results_db._xtract_date('foo')
    assert not got

def test_xtract_date_bad_date():
    # test bad date field
    got = results_db._xtract_date('foo-2013-aa-aa_12:12:12-xxxxxxxxxxxxx')
    assert not got

def test_xtract_date_bad_time():
    # test bad time field
    got = results_db._xtract_date('foo-2013-09-20_12:68:12-xxxxxxxxxxxxx')
    assert not got

def test_xtract_date_good():
    # test valid date
    got = results_db._xtract_date('foo-2013-09-20_12:18:12-xxxxxxxxxxxxx')
    assert got == '2013-09-20 12:18:12'


class TestDirectStore(object):

    def setup(self):
        dtfield = datetime.datetime.now()
        udate = dtfield.date().isoformat()
        utime = dtfield.time().replace(microsecond=0).isoformat()
        self.udir = "unittest-%s_%s-xxx-yyy-aaa-bbb-ccc" % (udate, utime)
        self.piddir = str(random.randint(1,32767))

    def teardown(self):
        dbase = results_db.connect_db()
        cursor = dbase.cursor()
        pattern1 = 'DELETE FROM rados_bench WHERE SUITE="%s"' % self.udir
        assert cursor.execute(pattern1) == 1
        cursor.execute("COMMIT")
 
    def test_storeDirect(self):
        pattern1 = 'SELECT * FROM rados_bench'
        dbase = results_db.connect_db()
        cursor = dbase.cursor()
        oldsz = cursor.execute(pattern1)
        with io.StringIO() as outfile:
            outfile.write(u'xxx Bandwidth (MB/sec): 100.1\n')
            outfile.write(u'xxx Stddev Bandwidth: 1500.1\n')
            results_db.process_suite_data(self.udir, self.piddir, outfile,
                    'teuthology.log')
        dbase.commit()
        cursor = dbase.cursor()
        newsz = cursor.execute(pattern1)
        dbase.commit()
        assert newsz == oldsz + 1 

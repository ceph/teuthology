from .. import results_db
import os
import random
import shutil
import yaml
import datetime

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

    TESTDIR = "/tmp"

    def setup(self):
        dtfield = datetime.datetime.now()
        udate = dtfield.date().isoformat()
        utime = dtfield.time().replace(microsecond=0).isoformat()
        self.udir = "unittest-%s_%s-xxx-yyy-aaa-bbb-ccc" % (udate, utime)
        self.path_header = "%s/%s" % (self.TESTDIR, self.udir)
        self.piddir = str(random.randint(1,32767))
        self.fullpath = os.path.join(self.path_header,self.piddir)
        os.makedirs(self.fullpath)
        summary = os.path.join(self.fullpath,"summary.yaml")
        teuthlog = os.path.join(self.fullpath,"teuthology.log")
        with open(teuthlog,'w+') as outfile:
            outfile.write('xxx Bandwidth (MB/sec): 100.1\n')
            outfile.write('xxx Stddev Bandwidth: 1500.1\n')
        ddata = {'success': 'False', 'description': 'unit test sample',
                'duration': 17.1, 'failure_reason': 'too many aardvarks',
                'owner': 'me'}
        with open(summary,'w+') as outfile:
            yaml.dump(ddata, outfile)

    def teardown(self):
        shutil.rmtree(self.path_header)
        dbase = results_db.connect_db()
        cursor = dbase.cursor()
        for _,_,tablev in results_db.get_table_info(dbase):
            pattern1 = 'DELETE FROM %s WHERE SUITE="%s"' % (tablev, self.udir)
            assert cursor.execute(pattern1) == 1
        cursor.execute("COMMIT")
 
    def test_storeDirect(self):
        dbase = results_db.connect_db()
        cursor = dbase.cursor()
        prev_size = {}
        for _,_,tablev in results_db.get_table_info(dbase):
            pattern1 = 'SELECT * FROM %s' % tablev
            prev_size[tablev] = cursor.execute(pattern1)
        results_db.store_in_database(self.fullpath)
        dbase = results_db.connect_db()
        cursor = dbase.cursor()
        for _,_,tablev in results_db.get_table_info(dbase):
            pattern1 = 'SELECT * FROM %s' % tablev
            newsz = cursor.execute(pattern1)
            oldsz = prev_size[tablev]+1
            assert newsz == oldsz 

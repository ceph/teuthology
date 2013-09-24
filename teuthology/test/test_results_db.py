from .. import results_db
import os
import random
import shutil
import yaml

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
        self.path_header = "/a/%s" % self.udir
        self.piddir = str(random.randint(1,32767))
        self.fullpath = os.join(self.path_header,self.piddir)
        summary = os.join(self.fullpath,"summary.yaml")
        teuthlog = os.join(self.fullpath,"teuthology.log")
        with open(teuthlog,'w') as outfile:
            write('Bandwidth (MB/sec): 100.1\n')
            write('Stddev Bandwidth: 1500.1\n')
        ddata = {'success': 'False', 'description': 'unit test sample',
                'duration': 17.1, 'failure_reason': 'too many aardvarks',
                'owner': 'me'}
        with open(summary,'w') as outfile:
            yaml.dump(ddata, outfile)

    def teardown(self):
        dbase = results_db.connect_db()
        cursor = dbase.cursor()
        for _,_,tablev in results_db.get_table_info(dbase):
            pattern1 = 'DELETE FROM %s WHERE SUITE="%s"' % (tablev, dsuites)
            assert cursor.execute(pattern1) == 1
        shutil.rmtree(self.path_header)
 
    def test_storeDirect(self):
        dbase = results_db.connect_db()
        cursor = dbase.cursor()
        prev_size = {}
        for _,_,tablev in results_db.get_table_info(dbase):
            pattern1 = 'SELECT * FROM %s' % tablev
            prev_size[tablev] = cursor.execute(pattern1)
        results_db.store_in_database(self.fullpath)
        for _,_,tablev in results_db.get_table_info(dbase):
            pattern1 = 'SELECT * FROM %s' % tablev
            assert prev_size[tablev]+1 == cursor.execute(pattern1)

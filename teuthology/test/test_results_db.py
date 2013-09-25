from .. import results_db
import random
import datetime
import StringIO

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
    
    # test adding of a record to all tables.
    # (currently only rados_bench and suite_results tables)
    def setup(self):
        dtfield = datetime.datetime.now()
        udate = dtfield.date().isoformat()
        utime = dtfield.time().replace(microsecond=0).isoformat()
        self.udir = "unittest-%s_%s-xxx-yyy-aaa-bbb-ccc" % (udate, utime)
        self.piddir = str(random.randint(1, 32767))
        self.testcases = {}
        self.testcases['rados_bench'] = \
            u'xxx Bandwidth (MB/sec): 100.1\nxxx Stddev Bandwidth: 1500.1\n'
        self.testcases['suite_results'] = \
            u'description: aardvarks\nduration: 0.9\nfailure_reason: foo\n' +\
            u'success: false\n'
        self.testfile = {'rados_bench': 'teuthology.log',
                         'suite_results': 'summary.yaml'}

    def teardown(self):
        for db_table in self.testcases:
            dbase = results_db.connect_db()
            cursor = dbase.cursor()
            pattern1 = 'DELETE FROM %s WHERE SUITE="%s"' % (db_table, self.udir)
            assert cursor.execute(pattern1) == 1
            cursor.execute("COMMIT")
 
    def test_store_direct(self):
        for db_table in self.testcases:
            pattern1 = 'SELECT * FROM %s' % db_table
            dbase = results_db.connect_db()
            cursor = dbase.cursor()
            oldsz = cursor.execute(pattern1)
            outfile = StringIO.StringIO()
            outfile.write(self.testcases[db_table])
            outfile.seek(0)
            results_db.process_suite_data(self.udir, self.piddir, outfile,
                    self.testfile[db_table])
            dbase.commit()
            cursor = dbase.cursor()
            newsz = cursor.execute(pattern1)
            dbase.commit()
            assert newsz == oldsz + 1 

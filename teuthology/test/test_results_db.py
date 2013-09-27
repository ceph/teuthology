from .. import results_db
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

def test_xtract_date_bad_datetime():
    # test bad date field with datetime return
    got = results_db._xtract_date('foo-2013-aa-aa_12:12:12-xxxxxxxxxxxxx', True)
    assert not got

def test_xtract_date_good():
    # test valid date with datetime return
    got = results_db._xtract_date('foo-2013-09-20_12:18:12-xxxxxxxxxxxxx', True)
    assert got.year == 2013
    assert got.month == 9
    assert got.day == 20
    assert got.hour == 12
    assert got.minute == 18
    assert got.second == 12

def test_get_tables():
    # test _get_tables output
    tbl_set = results_db._get_tables()
    assert 'suite_results' in tbl_set
    assert 'rados_bench' in tbl_set
    assert not 'aardvark' in tbl_set

def test_txtfind_found_0words():
    # test _txtfind with no following words
    assert results_db._txtfind('aardvarks\n', 'va') == 'varks'

def test_txtfind_found_1word():
    # test _txtfind with one following word
    assert results_db._txtfind('aardvarks and \n', 'va') == 'and'

def test_txtfind_found_2word():
    # test _txtfind with more than one following word
    assert results_db._txtfind('aardvarks and wombats\n', 'va') == 'wombats'

def test_txtfind_found_bad():
    # test _txtfind with more no matches
    assert not results_db._txtfind('aardvarks and wombats\n', 'xxx')

def test_get_next_data_file():
    # test _get_nex_data_file execution -- don't die for simple input
    for foo, bar in results_db._get_next_data_file('/tmp'):
        pass

def dummy(parts2, parts1, in_file, filen):
    pass

def test_find_files():
    # test _find_files execution -- make sure it doesn't die for simple input
    results_db._find_files('/tmp',dummy)

def test_get_bandwidth_found():
    # test _get_bandwidth when bandwidth data exists
    outfile = StringIO.StringIO()
    outfile.write(
            u'xxx Bandwidth (MB/sec): 100.1\nxxx Stddev Bandwidth: 1500.1\n')
    outfile.seek(0)
    bw1, bw2 = results_db._get_bandwidth(outfile,'unit-test')
    assert bw1 == u'100.1'
    assert bw2 == u'1500.1'

def test_get_bandwidth_notfound():
    # test _get_bandwidth when bandwidth data does not exists
    outfile = StringIO.StringIO()
    outfile.write(u'time has come the Walrus said to speak of many things.1\n')
    outfile.seek(0)
    assert not results_db._get_bandwidth(outfile,'unit-test')

def test_get_summary_found():
    # test _get_summary when summary data is good.
    outfile = StringIO.StringIO()
    outfile.write(u'success:   False\nduration:   100.0\n')
    outfile.seek(0)
    res = results_db._get_summary(outfile,'unit-test')
    assert res[0] == False
    assert res[2] == 100.0

def test_get_summary_notfound():
    # test _get_summary when summary data is bad.
    outfile = StringIO.StringIO()
    outfile.write(u'time has come the Walrus said to speak of many things.1\n')
    outfile.seek(0)
    assert not results_db._get_summary(outfile,'unit-test')

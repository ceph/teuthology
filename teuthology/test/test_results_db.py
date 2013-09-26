from .. import results_db

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

"""
Save teuthology information into a database.

External entry points are:
    store_in_database() -- called from other python modules.
    update() -- Main-line entry point.  Adds information from the
                specified run to the database
    build() -- Main-line entry point.  Scans all saved teuthology runs.
"""
import MySQLdb
import os
import re
import yaml
import argparse


def _xtract_date(text):
    """
    Given a suite name, extract the date.

    :param text: suite name
    :returns: date extracted from the text input.
    """
    pmtch = re.match('.*\-[-0-9]*_[:0-9]*', text)
    pdate = pmtch.group(0)
    pdate = pdate[pdate.find('-') + 1:]
    return pdate.replace('_', ' ')


def _add2db(suite, pid, db_data, table, dbase):
    """
    Perform the actual insert into the database.  First this checks to make
    sure that the data to be added is not already in the database.  If it is,
    the operation is not performed.  Since each suite run occurs only once
    (the name is timestamped), then adding more than one entry of the same
    test should be avoided.

    :param suite: suite name (first directory under /a)
    :param pid: test run (second directory under /a)
    :param db_data: information to be stored in the database that is unique
                    for this tbl_val (see next parameter).
    :param table: details of the table being updated.  A list of mixed items
                  unique to this table entry.  table[2] is the name of the
                  sql table,  table[0] is the sql insert statement that
                  corresponds to this table.
    :param dbase: Database connection.
    """
    date = _xtract_date(suite)
    cursor = dbase.cursor()
    pattern1 = 'SELECT * FROM %s WHERE SUITE="%s" AND PID=%s'
    if cursor.execute(pattern1 % (table[2], suite, pid)) > 0:
        return
    cursor = dbase.cursor()
    olist = [date, suite, pid] + list(db_data)
    cursor.execute(table[0].format(*olist))
    dbase.commit()


def _scan_files(indir):
    """
    Search al files in the directory, returning ones that match the pattern
    suite-name/pid-number.

    :param indir: input directory (/a from main routine)
    :returns: generator that returns a directory to be searched for data to add
              to the database.
    """
    for suite in os.listdir(indir):
        dir1 = "%s/%s" % (indir, suite)
        for pid in os.listdir(dir1):
            if pid.isdigit():
                rfile = "%s/%s" % (dir1, pid)
                yield rfile


def _save_data(dbase, filename, tbl_info):
    """
    All database entries wih have a file name (test suite directory) and an
    associated number for the directory containing the logs and yaml files
    being read (a pid number).

    :param dbase: database connection
    :param filename: directory containing the info we want to save on the
                     database.
    :param tbl_info: list of information pertaining to this table. The first
                     entry in the ist is the string used by sql commands to
                     insert an entry into this table.  The second entry is
                     a routine that is used to find the data to add to the
                     table.  The third entry is the name of the table.
    :returns: False if filename cannot be split into database suite and pid
              values (these values effectively act as keys).
    """
    parts = filename.split('/')[::-1]
    if len(parts) < 3:
        return False
    for tbl in tbl_info:
        retval = tbl[1](filename)
        if retval:
            _add2db(parts[1], parts[0], retval, tbl, dbase)
    return True


def _connect_db():
    """
    Establish a connection to a MySQL database.

    Database parameters are:
        1. read from a yaml file whose name is in the
           environemnent variabe TEUTH_DB_YAML
        2. read from HOME/db.yaml.
        3. default to fixed values.

    :returns: databse connection.
    """
    info = {}
    yaml_file = os.environ.get('TEUTH_DB_YAML',
            '%s/db.yaml' % os.getenv('HOME'))
    if os.path.exists(yaml_file):
        with open(yaml_file, 'r') as yfile:
            info = yaml.load(yfile)
    dbase = MySQLdb.connect(
        host=info.get('host', 'deeby.inktank.com'),
        user=info.get('user', 'perf_test'),
        db=info.get('db', 'perf_test'),
        passwd=info.get('passwd'),
        )
    dbase.autocommit(False)
    return dbase


#
# This routine is used to collect data stored in the suite_results table.
#
# The suite_results table was created using the following command:
#
#   CREATE TABLE suite_results (
#       id BIGINT(20) NOT NULL AUTO_INCREMENT,
#       date DATETIME,
#       suite VARCHAR(255) NOT NULL,
#       pid INTEGER NOT NULL,
#       success VARCHAR(255),
#       description VARCHAR(255),
#       duration FLOAT,
#       failure_reason VARCHAR(255),
#       flavor VARCHAR(255),
#       owner VARCHAR(255),
#       PRIMARY KEY('id'))
#       ENGINE=InnoDB DEFAULT CHARSET=utf8);
#
def _get_summary(filename):
    """
    Collect information from summary files that are found.  This function is
    used to collect data that is added to the suite_results database table.

    :param filename: Filename being searched.
    :returns: list of column entries in the SuiteResults table.
    """
    sfile = "%s/summary.yaml" % filename
    rdct = {}
    if os.path.exists(sfile):
        with open(sfile, 'r') as fyaml:
            rdct = yaml.load(fyaml)
    retv = []
    for col in ['success', 'description', 'duration', 'failure_reason',
            'flavor', 'owner']:
        try:
            retv.append(rdct[col])
        except KeyError:
            retv.append('')
    # Little bit of a hack here.  Make sure that missing duration fields
    # are numeric, and make sure all quote marks are removed from the
    # text in failure_reason because they affect the sql queries made
    # later.
    if retv[2] == '':
        retv[2] = 0
    retv[3] = retv[3].replace('"', ' ').replace("'", " ")
    return retv


def _txtfind(ftext, stext):
    """
    Scan for some text inside some other text.  If found, return the last
    word on the line of the text found.

    :param ftext: text to be scanned.
    :param stext: text to be searched for.
    :returns: last word on the line or False if not found.
    """
    indx = ftext.find(stext)
    if indx < 1:
        return False
    tstrng = ftext[indx:]
    tstrng = tstrng[:tstrng.find('\n')]
    return tstrng.split()[::-1][0].strip()

#
# This routine is used to collect data stored in the rados_bench table.
#
# The suite_results table was created using the following command:
#
#   CREATE TABLE suite_results (
#       id BIGINT(20) NOT NULL AUTO_INCREMENT,
#       date DATETIME,
#       suite VARCHAR(255) NOT NULL,
#       pid INTEGER NOT NULL,
#       bandwidth FLOAT,
#       stddev FLOAT,
#       PRIMARY KEY('id'))
#       ENGINE=InnoDB DEFAULT CHARSET=utf8);
#


def _get_bandwidth(filename):
    """
    Collect information from teuthology.log files that are found.
    Bandwidth messages are extracted from the log.  This function
    is used to collect data for the rados_bench database table.

    :param filename: Directory being searched.
    :returns: list of column entries in the RadosBench table.
    """
    tfile = "%s/teuthology.log" % filename
    if os.path.exists(tfile):
        with open(tfile, 'r') as tlogfile:
            txt = tlogfile.read()
            bandwidth = _txtfind(txt, 'Bandwidth (MB/sec):')
            if bandwidth:
                stddev = _txtfind(txt, 'Stddev Bandwidth:')
                return (bandwidth, stddev)


def _get_insert_cmd(dbase, name):
    """
    Generate an insert sql command string for a table.  Look in the
    database and extract the columns to generate this string.  The
    insert string will be of the form

    'INSERT table-name (x1, x2, x3...) VALUES ({0},{1},{2}...)'

    where x1, x2, x3... are the names of the columns.

    The entries after values can be set later using the format string method.

    :param dbase: database connection to use.
    :param name: name of the sql table
    """
    cursor = dbase.cursor()
    cursor.execute('SHOW COLUMNS FROM {0}'.format(name))
    col_info = cursor.fetchall()
    first_string = ''
    second_string = ''
    for cnt, col in enumerate(col_info):
        cfld = col[0]
        ftype = col[1]
        if cfld == 'id':
            continue
        first_string = '{0}, {1}'.format(first_string, cfld)
        if (ftype.startswith('varchar') or ftype.startswith('datetime')
                or ftype.startswith('enum')):
            second_string = '{0}, "<{1}>"'.format(second_string, cnt - 1)
        else:
            second_string = '{0}, <{1}>'.format(second_string, cnt - 1)
    first_string = first_string[1:]
    second_string = second_string[1:].replace('<', '{').replace('>', '}')
    return 'INSERT {0} ({1}) VALUES ({2})'.format(name, first_string,
            second_string)


def _get_table_info(dbase):
    """
    Get a list of table information (each entry in this list will correspond
    to an sql table, and each entry will contain three parts).
        1. A string that is used for insert statements.
        2. A reference to a function that is used to find the data unique
           to this database table.
        3. The name of the table on sql

    :param dbase: database connection
    :returns: table information (insert string, function, name)
    """
    tbl_infoorg = {'suite_results': _get_summary,
                   'rados_bench': _get_bandwidth}
    cursor = dbase.cursor()
    cursor.execute('SHOW TABLES')
    tbinfo = cursor.fetchall()
    tbl_info = {}
    for lbl in tbl_infoorg:
        if (lbl,) in tbinfo:
            tbl_info[lbl] = tbl_infoorg[lbl]
    ret_tbl_vec = []
    for tbl in tbl_info:
        ret_tbl_vec.append((_get_insert_cmd(dbase, tbl), tbl_info[tbl], tbl,))
    return ret_tbl_vec


def build():
    """
    Main entry point for teuthology-build-db command.

    Walk through all the files on /a, and write all appropriate data into
    the database.

    running teuthology-build-db will update all the databases with all the
    available information on /a.
    """
    dbase = _connect_db()
    tbl_info = _get_table_info(dbase)
    for filename in _scan_files('/a'):
        _save_data(dbase, filename, tbl_info)


def store_in_database(testrun):
    """
    Wrapper for _save_data used by update and as an entry point from
    other python modules (teuthology/suite.py for instance).

    :param testrun: directory of information from a suite run.

    :returns: False if filename cannot be split into database suite and pid
              values (these values effectively act as keys).
    """
    dbase = _connect_db()
    tbl_info = _get_table_info(dbase)
    return _save_data(dbase, testrun, tbl_info)


def update():
    """
    Main entry point for teuthology-update-db command.

    Write all appropriate data to the database from the directory passed
    (or /a/parm1/parm2 if two parameters are passed).

    The following commands will both update all tables with the data in
    /a/foo-2013-01-01_23:23:23-performance/1211.

    teuthology-update-db /a/foo-2013-01-01_23:23:23-performance/1211
    teuthology-update-db foo-2013-01-01_23:23:23-performance 1211

    :returns: False on a parameter error.
    """
    parser = argparse.ArgumentParser()
    parser.add_argument('suite', help='suite name (or /a/suite_name/pid)')
    parser.add_argument('pid', help='pid (if suite specified as first arg')
    args = parser.parse_args()
    testrun = args.suite
    if args.pid:
        testrun = "/a/%s/%s" % (args.suite, args.pid)
    return store_in_database(testrun)

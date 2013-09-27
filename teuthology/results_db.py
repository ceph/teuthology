"""
Save teuthology information into a database.

External entry points are:
    update() -- Main-line entry point.  Adds information from the
                specified run to the database
    build() -- Main-line entry point.  Scans all saved teuthology runs.
"""
import MySQLdb
import os
import re
import yaml
import argparse
import logging
import datetime
import random
import StringIO

log = logging.getLogger(__name__)
LOG_DIR = '/a/'


def _xtract_date(text, retdt=False):
    """
    Given a suite name, extract the date.

    :param text: suite name
    :returns: date extracted from the text input.
    """
    pmtch = re.match('.*\-[-0-9]*_[:0-9]*', text)
    if not pmtch:
        return
    pdate = pmtch.group(0)
    pdate = pdate[pdate.find('-') + 1:]
    try:
        rldate = datetime.datetime.strptime(pdate, "%Y-%m-%d_%H:%M:%S")
        if retdt:
            return rldate
    except ValueError:
        return
    return pdate.replace('_', ' ')


def connect_db():
    """
    Establish a connection to a MySQL database.

    Database parameters are:
        1. read from a yaml file whose name is in the
           environment variable TEUTH_DB_YAML
        2. read from HOME/db.yaml.
        3. default to fixed values.

    :returns: database connection.
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
        passwd=info.get('passwd', 'passwd'),
        )
    dbase.autocommit(True)
    return dbase


#
# This routine is used to collect data stored in the suite_results table.
#
# The suite_results table was created using the following command:
#
#   CREATE TABLE suite_results (
#       id INTEGER NOT NULL AUTO_INCREMENT,
#       date DATETIME,
#       suite VARCHAR(255) NOT NULL,
#       pid INTEGER NOT NULL,
#       success VARCHAR(255),
#       description VARCHAR(255),
#       duration FLOAT,
#       failure_reason VARCHAR(255),
#       flavor VARCHAR(255),
#       owner VARCHAR(255),
#       PRIMARY KEY(id))
#       ENGINE=InnoDB DEFAULT CHARSET=utf8);
#
def _get_summary(filename, suite):
    """
    Collect information from summary files that are found.  This function is
    used to collect data that is added to the suite_results database table.

    :param filename: Filename being searched.
    :returns: list of column entries in the SuiteResults table.
    """
    rdct = yaml.load(filename)
    if not rdct:
        log.info('cannot find yaml file for %s' % suite)
        return
    if not isinstance(rdct, dict):
        log.info('invalid yaml file found in %s' % suite)
        return
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
    word on the line of the text found.  Note that this code scans for text
    inside multi-line strings and expects to find the data, if it exists, in
    a internal line.

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
#   CREATE TABLE rados_bench (
#       id INTEGER NOT NULL AUTO_INCREMENT,
#       date DATETIME,
#       suite VARCHAR(255) NOT NULL,
#       pid INTEGER NOT NULL,
#       bandwidth FLOAT,
#       stddev FLOAT,
#       PRIMARY KEY(id))
#       ENGINE=InnoDB DEFAULT CHARSET=utf8);
#
def _get_bandwidth(filename, suite):
    """
    Collect information from teuthology.log files that are found.
    Bandwidth messages are extracted from the log.  This function
    is used to collect data for the rados_bench database table.

    :param filename: Directory being searched.
    :returns: list of column entries in the RadosBench table.
    """
    try:
        txt = filename.read()
    except MemoryError:
        log.info("MemoryError occured reading %s" % suite)
        return
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


RESULTS_MAP = {'teuthology.log': [('rados_bench', _get_bandwidth)],
               'summary.yaml': [('suite_results', _get_summary)]}


def _get_tables():
    lyst = []
    for tfyle in RESULTS_MAP:
        for ttuple in RESULTS_MAP[tfyle]:
            lyst.append(ttuple[0])
    return set(lyst)


def process_suite_data(suite, pid, in_file, filen):
    """
    Perform the actual insert into the database.  First this checks to make
    sure that the data to be added is not already in the database.  If it is,
    the operation is not performed.  Since each suite run occurs only once
    (the name is timestamped), then adding more than one entry of the same
    test should be avoided.

    :param suite: suite name (first directory under /a)
    :param pid: test run (second directory under /a)
    :param in_file: Open file that we are reading from.
    :param filen: Name of the file from which the information is read
    """
    date = _xtract_date(suite)
    dbase = connect_db()
    for tables in RESULTS_MAP[filen]:
        cursor = dbase.cursor()
        pattern1 = 'SELECT id FROM %s WHERE SUITE="%s" AND PID=%s'
        if cursor.execute(pattern1 % (tables[0], suite, pid)) > 0:
            continue
        cursor = dbase.cursor()
        this_data = tables[1](in_file, suite)
        if not this_data:
            continue
        olist = [date, suite, pid] + list(this_data)
        cursor.execute(_get_insert_cmd(dbase, tables[0]).format(*olist))
        dbase.commit()


def _get_next_data_file(root_dir):
    """
    Walk through a directory.  Return the next file found that is an
    entry in the RESULTS_MAP table.

    :param root_dir: Directory to be searched.
    :returns: yields the next entry found.
    """
    for rootd, _, fyles in os.walk(root_dir):
        for data_file in fyles:
            if data_file in RESULTS_MAP:
                yield rootd, data_file


def _find_files(root_dir, xrtn=process_suite_data):
    """
    Calls process_suite_data for all files under root_dir.

    :param root_dir: base of tree containing files to be written to the
                     database.
    """
    for fpath, filen in _get_next_data_file(root_dir):
        full_path = os.path.join(fpath, filen)
        with open(full_path, 'r') as in_file:
            parts = full_path.split('/')[::-1]
            if len(parts) < 3:
                continue
            xrtn(parts[2], parts[1], in_file, filen)


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
    logging.basicConfig(level=logging.INFO,)

    parser = argparse.ArgumentParser()
    help_msg = 'suite name (or %ssuite_name/pid)' % LOG_DIR
    parser.add_argument('suite', help=help_msg)
    parser.add_argument('pid', nargs='?',
            help='pid (if suite specified as first arg)')
    args = parser.parse_args()
    testrun = args.suite
    if args.pid:
        hdr = ''
        if not testrun.startswith(LOG_DIR):
            hdr = LOG_DIR
        testrun = "%s%s/%s" % (hdr, args.suite, args.pid)
    _find_files(testrun)


def update_file(in_file):
    """
    Update the databases with a specific file

    :param in_file: input file
    """
    _find_files(in_file)


def build():
    """
    Main entry point for teuthology-build-db command.

    If -f specified, walk through all the files on /a, and write all
    appropriate data into the database (takes a long time)

    If -f is not specified, only data newer than the lastest record in any
    of the databases will be recorded.
    """
    logging.basicConfig(level=logging.INFO,)

    parser = argparse.ArgumentParser()
    parser.add_argument(
        '-f', '--force',
        action='store_true',
        default=False,
        help='update all entries in the database',
        )
    args = parser.parse_args()
    if args.force:
        _find_files(LOG_DIR)
    else:
        lastd = datetime.datetime(1,1,1,1,1,1)
        for dbtab in _get_tables():
            dbase = connect_db()
            cursor = dbase.cursor()
            cursor.execute('SELECT COUNT(*) FROM %s' % dbtab)
            indx = cursor.fetchone()[0]
            cursor.execute('SELECT date FROM %s WHERE id >= %s' %
                    (dbtab, indx))
            for odate in cursor.fetchall():
                if odate[0] > lastd:
                    lastd = odate[0]
        check_these = os.listdir(LOG_DIR)
        for chck_file in check_these:
            ddate = _xtract_date(chck_file, True)
            if not ddate:
                continue
            if ddate > lastd:
                log.info("Storing data from %s" % chck_file)
                _find_files("%s%s" % (LOG_DIR, chck_file))

#
# Functional Test 
#

class TestDirectStore(object):
    """
    testcases -- sample file values for testing known sql tables.
    udir -- artificiially constructed suite directory
    piddir -- artificially constructed subdiretory of udir
    """
    testcases = {}
    testfile = {}
    udir = ''
    piddir = 0
    def __init__(self):
        dtfield = datetime.datetime.now()
        udate = dtfield.date().isoformat()
        utime = dtfield.time().replace(microsecond=0).isoformat()
        self.udir = "unittest-%s_%s-xxx-yyy-aaa-bbb-ccc" % (udate, utime)
        self.piddir = str(random.randint(1, 32767))
        self.testcases['rados_bench'] = \
            u'xxx Bandwidth (MB/sec): 100.1\nxxx Stddev Bandwidth: 1500.1\n'
        self.testcases['suite_results'] = \
            u'description: aardvarks\nduration: 0.9\nfailure_reason: foo\n' +\
            u'success: false\n'
        self.testfile = {'rados_bench': 'teuthology.log',
                         'suite_results': 'summary.yaml'}

    def teardown(self):
        """
        Get rid of the records that we created for this test.
        """
        for db_table in self.testcases:
            dbase = connect_db()
            cursor = dbase.cursor()
            pattern1 = 'DELETE FROM %s WHERE SUITE="%s"' % (db_table, self.udir)
            assert cursor.execute(pattern1) == 1
            cursor.execute("COMMIT")
 
    def test_store_direct(self):
        """
        For each table, use process_suite_data to add a fake record.
        Note that this measurement may not be accurate if another task is
        updating the table.
        """
        for db_table in self.testcases:
            pattern1 = 'SELECT id FROM %s' % db_table
            dbase = connect_db()
            cursor = dbase.cursor()
            oldsz = cursor.execute(pattern1)
            outfile = StringIO.StringIO()
            outfile.write(self.testcases[db_table])
            outfile.seek(0)
            process_suite_data(self.udir, self.piddir, outfile,
                self.testfile[db_table])
            dbase.commit()
            cursor = dbase.cursor()
            newsz = cursor.execute(pattern1)
            dbase.commit()
            assert newsz == oldsz + 1 


def functional_test():
    """
    Test process_suite_data for all known tables.
    """
    testdir = TestDirectStore()
    testdir.test_store_direct()
    testdir.teardown()

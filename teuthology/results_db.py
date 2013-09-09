import logging
import MySQLdb
import os
import re
import sys
import yaml
import teuthology.db_classes as db_classes

log = logging.getLogger(__name__)

def xtract_date(text):
    """
    Given a suite name, extract the date.

    :param: text -- suite name
    :returns: date extracted from the text input.
    """
    p = re.match('.*\-[-0-9]*_[:0-9]*',text)
    pdate = p.group(0)
    pdate = pdate[pdate.find('-')+1:]
    return pdate.replace('_',' ')
    
def add2db(suite, pid, db_data, tbl_val, db):
    """
    Perform the actual insert into the database.  First this checks to make
    sure that the data to be added is not already in the database.  If it is,
    the operation is not performed.  Since each suite run occurs only once
    (the name is timestamped), then adding more than one entry of the same
    test should be avoided.

    :param: suite -- suite name (first directory under /a)
    :param: pid -- test run (second directory under /a)
    :param: db_data -- information to be stored in the database that is unique
                       for this tbl_val (see next parameter).
    :param: tbl_val -- Table entry.  One of these exists for each table in 
                       the database.  Tbl_info (see save_data below) is a list
                       of all table entries.
    :param: db -- Database connection.
    """
    date = xtract_date(suite)
    c = db.cursor()
    pattern1 = 'select * from %s where suite="%s" and pid=%s'
    if c.execute(pattern1 % (tbl_val.get_name(), suite, pid)) > 0:
        return
    c = db.cursor()
    olist = [date, suite, pid] + list(db_data)
    c.execute(tbl_val.get_insert_pattern().format(*olist))
    db.commit()

def scan_files(indir):
    """
    Search al files in the directory, returning ones that match the pattern
    suite-name/pid-number.

    :param: input directory (/a from main routine)
    :returns: generator that returns a directory to be searched for data to add
              to the database.
    """
    for suite in os.listdir(indir):
        dir1 = "%s/%s" % (indir,suite)
        for pid in os.listdir(dir1):
            if pid.isdigit():
                rfile = "%s/%s" % (dir1,pid)
                yield rfile

def save_data(db, filename, tbl_info):
    """
    All database entries wih have a file name (test suite directory) and an
    associated number for the directory containing the logs and yaml files
    being read (a pid number).

    :param: db -- database connection
    :param: filename -- directory containing the info we want to save on the
                        database.
    :param: tbl_info -- list of table entries.  The values stored here are
                        fixed tables, one corresponding to each table in
                        the complete set of tables in the database. Each
                        entry here is a db_tables object (See db_classes.py).
   
    :returns: False if filename cannot be split into database suite and pid
              values (these values effectively act as keys).
    """
    parts = filename.split('/')[::-1]
    if len(parts) < 2:
        return False
    for tbl in tbl_info:
        retval = tbl.get_data(filename)
        if retval:
             add2db(parts[1], parts[0], retval, tbl, db)
    return True

def config_db():
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
    yaml_file = os.environ.get('TEUTH_DB_YAML', '%s/db.yaml' % os.getenv('HOME'))
    if os.path.exists(yaml_file):
        with open(yaml_file, 'r') as f:
            info = yaml.load(f)
    db = MySQLdb.connect(
        host=info.get('host', 'deeby.inktank.com'),
        user=info.get('user', 'perf_test'),
        db=info.get('db', 'perf_test'),
        passwd=info.get('passwd'),
        )
    db.autocommit(False)
    return db

def build():
    """
    Main entry point for teuthology-build-db command.

    Walk through all the files on /a, and write all appropriate data into
    the database.

    At this point, two tables are supported.  rados_bench contains records of
    bandwidth values from rados_runs.  suite_results contains records of run
    information extracted from summary.yaml files. 
    """
    logging.basicConfig( level=logging.INFO,)
    db = config_db()
    tbl_info = (db_classes.rados_bench(db), db_classes.suite_results(db))
    for filename in scan_files('/a'):
        save_data(db, filename, tbl_info)

def update():
    """
    Main entry point for teuthology-update-db command.

    Write all approrpiate data to the database from the directory passed
    (or /a/parm1/parm2 if two parameters are passed).

    At this point, two tables are supported.  rados_bench contains records of
    bandwidth values from rados_runs.  suite_results contains records of run
    information extracted from summary.yaml files. 

    :returns: False on a parameter error.
    """
    logging.basicConfig( level=logging.INFO,)
    if len(sys.argv) < 2 or len(sys.argv) > 3:
        log.error("Usage: update_db [ filename | suite-name pid-number]")
        return False
    db = config_db()
    tbl_info = (db_classes.rados_bench(db), db_classes.suite_results(db))
    suite = sys.argv[1]
    if len(sys.argv)  == 3:
        suite = "/a/%s/%s" % (arv[1], argv[2])
    return save_data(db, suite, tbl_info)


import os
import MySQLdb
import yaml

class db_tables(object):
    """
    Super class of tables used in the database.
    """
    def __init__(self, db, name):
        """
        Important local variables stored here are:
            self.name -- the name of the table.
            self.ipattern -- text pattern of the insert command to run on
                             MySQL when a record is inserted to a tabble.
                             The format of the information here is extracted
                             after looking at the table.

        :input: db -- database connection.
        :input: name -- name of the table.
        """ 
        self.name = name
        c = db.cursor()
        c.execute('show columns from {0}'.format(name))
        col_info = c.fetchall()
        first_string = ''
        second_string = ''
        for cnt, col in enumerate(col_info):
            cfld = col[0]
            ftype = col[1]
            if cfld == 'id':
                continue
            first_string = '{0}, {1}'.format(first_string, cfld)
            if ftype.startswith('varchar') or ftype.startswith('datetime') or ftype.startswith('enum'):
                second_string = '{0}, "<{1}>"'.format(second_string, cnt-1) 
            else:
                second_string = '{0}, <{1}>'.format(second_string, cnt-1) 
        first_string = first_string[1:]
        second_string = second_string[1:].replace('<','{').replace('>','}')
        self.ipattern = 'insert {0} ({1}) values ({2})'.format(name,first_string,second_string)

    def get_name(self):
        return self.name

    def get_insert_pattern(self):
        return self.ipattern

def txtfind(ftext, stext):
    """
    Scan for some text inside some other text.  If found, return the last
    word on the line of the text found.

    :param: ftext -- text to be scanned.
    :param: stext -- text to be searched for.
    :returns: last word on the line or False if not found. 
    """
    indx = ftext.find(stext)
    if indx < 1:
        return False
    tstrng = ftext[indx:]
    tstrng = tstrng[:tstrng.find('\n')]
    return tstrng.split()[::-1][0].strip()

class suite_results(db_tables):
    """
    Implementation of db_tables used to update the suite_results table.
    """
    def __init__(self, db):
        super(suite_results, self).__init__(db, 'suite_results')

    def get_data(self, filename):
        """
        Collect information from summary files that are found.
        
        :param: filename -- Directory being searched.
        :returns: list of column entries in the suite_results table.
        """
        sfile = "%s/summary.yaml" % filename
        rdct = {}
        if os.path.exists(sfile):
            with open(sfile, 'r') as f:
                rdct = yaml.load(f)
        retv = []
        for col in ['success', 'description', 'duration', 'failure_reason', 'flavor', 'owner']:
           try:
               retv.append(rdct[col])
           except KeyError:
               retv.append('')
        if retv[2] == '':
            retv[2] = 0 
        retv[3] = retv[3].replace('"',' ').replace("'"," ")
        return retv

class rados_bench(db_tables):
    """
    Implementation of db_tables used to update the rados_bench table.
    """
    def __init__(self, db):
        super(rados_bench, self).__init__(db, 'rados_bench')
    def get_data(self, filename):
        """
        Collect information from teuthology.log files that are found.
        Bandwidth messages are extracted from the log.
        
        :param: filename -- Directory being searched.
        :returns: list of column entries in the rados_bench table.
        """
        tfile = "%s/teuthology.log" % filename
        if os.path.exists(tfile):
            with open(tfile, 'r') as f:
                txt = f.read()
                bandwidth = txtfind(txt,'Bandwidth (MB/sec):')
                if bandwidth:
                    stddev = txtfind(txt,'Stddev Bandwidth:')
                    return (bandwidth,stddev)
        return None

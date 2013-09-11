import argparse
import os
import logging
import httplib2
import urllib
import json
import sys

log = logging.getLogger(__name__)

def send_request(method, url, body=None, headers=None):
    """
    Send a request using http2lib to the Apache server on which the MySQL
    database resides.
    """
    http = httplib2.Http()
    resp, content = http.request(url, method=method, body=body, headers=headers)
    if resp.status == 200:
        return (True, content, resp.status)
    log.info("%s request to '%s' with body '%s' failed with response code %d",
             method, url, body, resp.status)
    return (False, None, resp.status)

def display(content):
    """
    Display the results of a read operation.
    """
    lyst = json.loads(content)
    for row in lyst:
        print json.dumps(row,indent=4)

def split_up_filename(in_file):
    dirct,pid = os.path.split(in_file)
    if not dirct:
        log.info("%s is an invalid directory" % in_file)
        return (null, pid, False)
    if not pid.isdigit():
        log.info("%s is an invalid pid value" % pid)
        return (None, 0, False)
    _,name = os.path.split(dirct)
    return (name, pid, True)
    
def get_summary_data(in_file):
    """
    Get data from summary files. Use values to set fields in POST calls.
    """
    columns = ['success', 'description', 'duration', 'failure_reason', 'flavor', 'owner']
    fname = os.path.abspath(in_file)
    try:
        with open(fname):
            pass
    except IOError:
        log.info("%s not found" % fname)
        return (False, None)
    dirnm = os.path.dirname(fname)
    name, pid, reslt = split_up_filename(dirnm)
    if not reslt:
        return (False, None)
    rdct = {}
    with open(in_file) as f:
        lyne = f.readline()     
        while lyne:
            colloc = lyne.find(':')
            field1 = lyne[0:colloc].strip()
            field2 = lyne[colloc+1:].strip()
            if field1 in columns:
                rdct[field1] = field2
            lyne = f.readline()     
    rdct['name'] = name
    rdct['pid'] = int(pid)
    return True, rdct

def view():
    """
    teuthology-viewdb executable.
    """
    loglevel = logging.INFO
    logging.basicConfig(level=loglevel,)
    parser = argparse.ArgumentParser(description="""
Read the suite database.

Usage:
    teuthology-viewdb -k <key>
    teuthology-viewdb [-a <date>]  [-b <date>]
""")
    parser.add_argument(
        '-k', '--key',
        default=None,
        help='search key (name field of database)',
        )
    parser.add_argument(
        '-b', '--before',
        default='',
        help='the suite was run before this date',
        )
    parser.add_argument(
        '-a', '--after',
        default='',
        help='the suite was run after this date',
        )
    ctx = parser.parse_args()
    db_site = os.environ.get('TEUTH_DB_SITE','teuthology')
    db_url = "%s.front.sepia.ceph.com" % db_site
    if ctx.before or ctx.after:
        fld = '%s_%s' % (ctx.after, ctx.before)
        success, content, _ = send_request('GET', 
            "http://%s/suitedb/access/FindInRange%s" % (db_url,fld))
        if not success:
            log.info('Unable to read database records.')
        else:
            display(content)
        return
    if ctx.key:
        success, content, _ = send_request('GET', 
            "http://%s/suitedb/access/%s" % (db_url,ctx.key))
        if success:
            display(content)
        else:
            log.info('Unable to read database records.')
    else:
        success, content, _ = send_request('GET', 
            "http://%s/suitedb/access" % db_url)
        if success:
            display(content)
        else:
            log.info('Unable to read database.')

def main():
    """
    teuthology-updatedb executable.
    """
    loglevel = logging.INFO
    logging.basicConfig(level=loglevel,)
    db_site = os.environ.get('TEUTH_DB_SITE','teuthology')
    db_url = "%s.front.sepia.ceph.com" % db_site
    for yml in sys.argv[1:]:
    	success, parms = get_summary_data(yml)
        if not success:
            continue
    	success, content, status = send_request('POST', 
            "http://%s/suitedb/access" % db_url,
            urllib.urlencode(parms))
        if content == "duplicate":
            log.info("Record already exists in database -- no update made")
    	if not success:
            log.info("Unable to update database.")


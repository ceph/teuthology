import argparse
import os
import logging
import httplib2
import urllib
import json
import sys
import yaml
import httprequest

log = logging.getLogger(__name__)

def display(content):
    """
    Display the results of a read operation.
    """
    lyst = json.loads(content)
    for row in lyst:
        print json.dumps(row,indent=4)

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
        aftr = ctx.after
        if not aftr:
            aftr = "1000-01-01"
        bfor = ctx.before
        if not bfor:
            bfor = "9999-12-31"
        fld = '%s_%s' % (aftr, bfor)
        success, content, _ = httprequest.send_request('GET', 
            "http://%s/suitedb/access/FindInRange%s" % (db_url,fld))
        if not success:
            log.info('Unable to read database records.')
        else:
            display(content)
        return
    if ctx.key:
        success, content, _ = httprequest.send_request('GET', 
            "http://%s/suitedb/access/%s" % (db_url,ctx.key))
        if success:
            display(content)
        else:
            log.info('Unable to read database records.')
    else:
        success, content, _ = httprequest.send_request('GET', 
            "http://%s/suitedb/access" % db_url)
        if success:
            display(content)
        else:
            log.info('Unable to read database.')


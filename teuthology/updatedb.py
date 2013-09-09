import os
import logging
import httplib2
import urllib
import json
import sys
import yaml
import httprequest

log = logging.getLogger(__name__)

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
    with open(in_file, 'r') as f:
        rdct = yaml.load(f)
    rdct['name'] = name
    rdct['pid'] = int(pid)
    return True, rdct

def updatedb():
    """
    teuthology-updatedb executable.
    
    Usage:
        teuthology-updatedb <summary.yaml file>
    """
    loglevel = logging.INFO
    logging.basicConfig(level=loglevel,)
    db_site = os.environ.get('TEUTH_DB_SITE','teuthology')
    db_url = "%s.front.sepia.ceph.com" % db_site
    for yml in sys.argv[1:]:
        success, parms = get_summary_data(yml)
        if not success:
            continue
        success, content, status = httprequest.send_request('POST', 
            "http://%s/suitedb/access" % db_url,
            urllib.urlencode(parms))
        if content == "duplicate":
            log.info("Record already exists in database -- no update made")
        if not success:
            log.info("Unable to update database.")


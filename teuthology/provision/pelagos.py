import json
import logging
import requests
import socket
import time
import shutil
import urllib2
from urllib2 import urlopen, HTTPError
import re

import teuthology.orchestra
from teuthology.config import config
from teuthology.contextutil import safe_while
from teuthology.exceptions import MaxWhileTries
from teuthology import misc

log = logging.getLogger(__name__)
config_section = 'pelagos'


def enabled(warn=False):
    """
    Check for required Pelagos settings

    :param warn: Whether or not to log a message containing unset parameters
    :returns: True if they are present; False if they are not
    """
    conf = config.get(config_section, dict())
    params = ['endpoint', 'machine_types']
    unset = [param for param in params if not conf.get(param)]
    if unset and warn:
        log.warn(
            "Pelagos is disabled; set the following config options to enable: %s",
            ' '.join(unset),
        )
    return (unset == [])


def get_types():
    """
    Fetch and parse config.pelagos['machine_types']

    :returns: The list of Pelagos-configured machine types. An empty list if Pelagos is
              not configured.
    """
    if not enabled():
        return []
    conf = config.get(config_section, dict())
    types = conf.get('machine_types', '')
    if not isinstance(types, list):
        types = types.split(',')
    return [type_ for type_ in types if type_]


class Pelagos(object):

    def __init__(self, name, os_type, os_version):
        #for service should be a hostname, not a user@host
        split_uri = re.search(r'(\w*)@(.+)', name)
        if split_uri is not None:
            self.name = split_uri.groups()[1]
        else:
            self.name = name

        self.os_type = os_type
        self.os_version = os_version
        self.os_name = os_type + "-" + os_version
        self.log = log.getChild(self.name)

    def create(self):
        """
        Initiate deployment via REST requests and wait until completion

        """
        if not enabled():
            raise RuntimeError("Pelagos is not configured!")
        try:
            response = self.do_request('node/provision',
                                      data={'os': self.os_name,
                                            'node': self.name},
                                      method='POST')
            location = response.headers.get('Location')
            self.log.info("Waiting for deploy to finish")
            self.log.info("Observe location: " + location)
            time.sleep(2)
            with safe_while(sleep=15, tries=60) as proceed:
                while proceed():
                    if not self.is_task_active(location):
                        break
        except Exception as e:
            # TODO implement cancel task
            raise e
        self.log.info("Deploy completed")
        if self.task_status_response.status_code != 200:
            raise Exception("Provisioning failed")
        return self.task_status_response


    def cancel_deploy_task(self,  task_id):
        # TODO implement it
        return

    def is_task_active(self, task_url):
        try:
            status_response = self.do_request('', url=task_url, verify=False)
        except HTTPError as err:
            self.log.error("Task fail reason: " + err.reason)
            if err.status_code == 404:
                self.log.error(err.reason)
                self.task_status_response = 'faield'
                return False
            else:
                raise HTTPError(err.code, err.reason)
        self.log.info("Response code:[" +
                          str(status_response.status_code) + "]")
        self.task_status_response = status_response
        if status_response.status_code == 202:
            self.log.info("Status response:[" +
                          status_response.headers['status'] + "]")
            if status_response.headers['status'] == 'not completed':
                return True
        return False

    def destroy(self):
        """A no-op; we just leave idle nodes as-is"""
        pass

    def do_request(self, url_suffix, url="" , data=None, method='GET', verify=True):
        """
        A convenience method to submit a request to the Pelagos server
        :param url_suffix: The portion of the URL to append to the endpoint,
                           e.g.  '/system/info'
        :param data: Optional JSON data to submit with the request
        :param method: The HTTP method to use for the request (default: 'GET')
        :param verify: Whether or not to raise an exception if the request is
                       unsuccessful (default: True)
        :returns: A requests.models.Response object
        """
        prepared_url = config.pelagos['endpoint'] + url_suffix
        if url != '':
            prepared_url = url
        self.log.info("Connect to :" + prepared_url)
        if data is not None:
            self.log.info("Send data  :" + str(data))
        req = requests.Request(
            method,
            prepared_url,
            data=data
        )
        prepared = req.prepare()
        resp = requests.Session().send(prepared)
        self.log.error("do_request code %s text %s", resp.status_code, resp.text)
        if not resp.ok and resp.text:
            self.log.error("%s: %s", resp.status_code, resp.text)
        if verify:
            resp.raise_for_status()
        return resp

    def destroy(self):
        """A no-op; we just leave idle nodes as-is"""
        pass


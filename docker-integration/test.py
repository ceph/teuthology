#!/usr/bin/env python
#
# Copyright (C) 2015 <contact@redhat.com>
#
# Author: Loic Dachary <loic@dachary.org>
#
# Permission is hereby granted, free of charge, to any person obtaining a copy
# of this software and associated documentation files (the "Software"), to deal
# in the Software without restriction, including without limitation the rights
# to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
# copies of the Software, and to permit persons to whom the Software is
# furnished to do so, subject to the following conditions:
#
# The above copyright notice and this permission notice shall be included in
# all copies or substantial portions of the Software.
#
# THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
# IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
# FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT. IN NO EVENT SHALL THE
# AUTHORS OR COPYRIGHT HOLDERS BE LIABLE FOR ANY CLAIM, DAMAGES OR OTHER
# LIABILITY, WHETHER IN AN ACTION OF CONTRACT, TORT OR OTHERWISE, ARISING FROM,
# OUT OF OR IN CONNECTION WITH THE SOFTWARE OR THE USE OR OTHER DEALINGS IN
# THE SOFTWARE.
#
import logging
import shutil
import subprocess
import testtools
import sys
import tempfile
import teuthology.lock
import scripts.lock
from cStringIO import StringIO
import json

class Integration(testtools.TestCase):
    def setUp(self):
        super(Integration, self).setUp()
        self.d = tempfile.mkdtemp()
        config = self.d + '/teuthology-config.yaml'
        open(config, 'w').write("""\
lock_server: http://localhost:8080/
queue_host: 127.0.0.1
results_server:
""")
        self.options = ['--verbose',
                        '--config-file', config]

    def tearDown(self):
        shutil.rmtree(self.d)
        super(Integration, self).tearDown()

class TestLock(Integration):

    def test_list(self):
        my_stream = StringIO()
        self.patch(sys, 'stdout', my_stream)
        args = scripts.lock.parse_args(self.options + ['--list', '--all'])
        teuthology.lock.main(args)
        out = my_stream.getvalue()
        self.assertIn('machine_type', out);
        status = json.loads(out)
        self.assertEquals(3, len(status))

# Local Variables:
# compile-command: "cd .. ; tox -e docker-delegate"
# End:

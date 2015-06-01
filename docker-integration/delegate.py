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
import subprocess
import sys

logging.basicConfig(format='%(asctime)s %(levelname)s %(message)s',
                    level=logging.DEBUG)


def run(os):
    name = 'teuthology-' + os
    script = """\
user_id=$(id -u) perl -p -e 's/%%(\w+)%%/$ENV{$1}/g' < docker-integration/{os}.dockerfile > docker-integration/{os}.dockerfile.real
docker build -t {name} --file docker-integration/{os}.dockerfile.real .
docker run -v $HOME:$HOME -w $(pwd) --user $(id -u) {name} env HOME=$HOME tox -e docker-integration
""".replace('{name}', name).replace('{os}', os)
    return subprocess.check_call(script, shell=True)

def main():
    if subprocess.call(['docker', 'ps']) != 0:
        logging.info("docker ps return on error"
                     "docker is not available, do not run tests")
        return 1
    return run('ubuntu-14.04')

sys.exit(main())

# Local Variables:
# compile-command: "cd .. ; tox -e docker-delegate"
# End:

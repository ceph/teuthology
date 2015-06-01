#!/bin/bash
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
if ! test -d paddles ; then
    git clone https://github.com/ceph/paddles.git
fi

cd paddles

git pull --rebase
git clean -ffqdx

perl -p -e "s|^address.*|address = 'http://localhost'|" < config.py.in > config.py
virtualenv ./virtualenv
source ./virtualenv/bin/activate
pip install -r requirements.txt 
pip install sqlalchemy tzlocal requests
python setup.py develop
pecan populate config.py
for id in 1 2 3 ; do sqlite3 dev.db "insert into nodes (id,name,machine_type,is_vm,locked,up) values ($id, 'testmachine00$id', 'testmachine', 0, 0, 1);" ; done
pecan serve config.py &
sleep 2

cd ..

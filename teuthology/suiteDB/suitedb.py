#!/usr/bin/env python

import os
import sys
import web

abspath = os.path.dirname(__file__)
if abspath not in sys.path:
    sys.path.append(abspath)

from api import AccessDB, AccessRecs
urls = (
    '/access', 'AccessDB',
    '/access/(.*)', 'AccessRecs',
    )

app = web.application(urls, globals())
application = app.wsgifunc()

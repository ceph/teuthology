import json
import web
import subprocess

from config import DB

class AccessDB:
    def GET(self):
        results = list(DB.select('suite_info'))
        if not results:
            raise web.NotFound()
        web.header('Content-type', 'text/json')
        return json.dumps(results)
    def POST(self):
        webin = web.input()
        results = list(DB.select('suite_info',webin,where="name = $name and pid = $pid"))
        if len(results) > 0:
            return "duplicate"
        indxe = webin['name'].find('_')
        indxb = webin['name'].find('-')
        if indxb > 0 and indxe > indxb:
            webin['date'] = webin['name'][indxb+1:indxe]
        DB.insert('suite_info',**webin)
        return "OK"

class AccessRecs:
    def GET(self,name):
        if name.startswith('FindInRange'):
            nname = name[len('FindInRange'):]
            sploc = nname.find('_')
            if not sploc:
                raise web.NotFound()
            if nname.startswith('_'):
                bloc = '1000-01-01'
            else:
                bloc = nname[0:sploc]
            if nname.endswith('_'):
                eloc = '9999-12-31'
            else:
                eloc = nname[sploc+1:]
            results = list(DB.select('suite_info',
                    dict(eloc=eloc,bloc=bloc),
                    where='date >= $bloc and date <= $eloc'))
            if not results:
                raise web.NotFound()
            web.header('Content-type', 'text/json')
            return json.dumps(results)
        results = list(DB.select('suite_info',dict(name=name),where="name = $name"))
        if not results:
            raise web.NotFound()
        web.header('Content-type', 'text/json')
        return json.dumps(results)


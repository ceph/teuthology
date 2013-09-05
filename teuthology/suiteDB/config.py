"""
This file contains database configuration.

The schema can be created with::

    CREATE TABLE suite_info (
        id integer not null auto_increment,
        name varchar(255),
        pid integer,
        success enum('pass','fail', 'hung', 'not-run'),
        description varchar(255),
        duration float,
        failure_reason varchar(255),
        flavor varchar(255),
        owner varchar(255),
        PRIMARY KEY (id));

If using MySQL, be sure to use an engine that supports
transactions, like InnoDB.
"""
import yaml
import web

dconfig = {}
with open('teuthology/teuthology/suiteDB/config.yaml','r') as file_conf:
    dconfig = yaml.safe_load(file_conf)
DB = web.database(dbn=dconfig['dbn'], db=dconfig['db'], user=dconfig['user'], pw=dconfig['pw'], host=dconfig['host'])

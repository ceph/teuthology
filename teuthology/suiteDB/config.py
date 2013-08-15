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
import web

# Change these values to the connection info for your database.
DB = web.database(dbn='dbn', db='db', user='user', pw='pw', host='host')

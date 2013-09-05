The following is a guide to setting up the teuthology suite database on
a new site.  The information applies in general to other services that use
http2 connections to a remote MySQL database (the locking code, for example).

Note that in most cases where a new type of service is started,
actions here are only performed once and never performed again.  Also, if
existing services that use MySQL already exist on a site, many of the
operations below should not be performed (they are already done and we
should not affect the other services).

Step 1. Install the Apache2 web server and mod_wsgi on the new site.

	sudo apt-get install apache2
        sudo apt-get install libapache2-mod-wsgi

Step 2: Install teuthology on /var/lib/teuthsuitedb

    /var/lib/teuthsuitedb/teuthology/teuthology/suiteDB should at least
    match teuthology/suiteDB on the source machine.

Step 3: Create teuthsuitedb user and group on new site (Unix users). Make
        sure that the home directory for teuthsuitedb is /var/lib/teuthsuitedb.

Step 4: Install teuthology-suitedb (a new virtual host)
   
    Copy teuthology/suiteDB/teuthology-suitedb to /etc/apache2/sites-available.
    Symbolically link /etc/apache2/sites-enabled/teuthology-suitedb.
    Edit the first line in the files in /etc/apache2/sites-enabled so that
    all the virtual hosts use a unique port number.
    sudo a2ensite teuthology-suitedb
    sudo /etc/init.d/apache2 restart

Step 5: Install MySQL

    sudo apt-get update
    sudo apt-get install mysql-server mysql-client

Step 6: Setup Database

    The following example creates a database named wusui_suite_results.
    A user named machl with password aardvark is created.

    sudo mysql -p'password' (root password was set when you installed mysql).
    create database wusui_suite_results;
    grant usage on *.* to machl@localhost identified by 'aardvark';
    grant all privileges on wusui_suite_results.* to machl;

    Now define the suite information table (see teuthology/suiteDB/config.py).

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

Step 7: Install python web and mysql modules.

        sudo apt-get install python-mysqldb
        sudo apt-get install python-setuptools
        sudo easy_install web.py
        sudo /etc/init.d/apache2 restart

Step 8: On your server, create a file named config.yaml in
        teuthlogy/suiteDB.  Add the appropriate entries for dbn, db, user,
        pw, and host.  A sample config.yaml file looks like:

        dbn: mysql
        db: wusui_suite_results
        user: machl
        pw: aardvark
        host: localhost 

        Also, on the client machine, one should run set the TEUTH_DB_SITE
        environment variable to the machine on which you have your server
        database.  (export TEUTH_DB_SITE=vpm008, for example)


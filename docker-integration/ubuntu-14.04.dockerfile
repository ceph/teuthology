FROM ubuntu:14.04

RUN apt-get update
# http://stackoverflow.com/questions/27341064/how-do-i-fix-importerror-cannot-import-name-incompleteread
RUN apt-get install -y python-setuptools && easy_install -U pip
RUN apt-get install -y python-virtualenv python-tox libmysqlclient-dev beanstalkd git
RUN apt-get install -y python2.7-dev
RUN apt-get install -y libevent-dev
RUN apt-get install -y sqlite3 jq
RUN useradd -M --uid %%user_id%% %%USER%% && echo '%%USER%% ALL=(ALL) NOPASSWD:ALL' >> /etc/sudoers

#!/usr/bin/python3

from docopt import docopt
import logging
import re
import os
import sys

doc = """
usage: 
	teuthology-open-failed -h --help
	teuthology-open-failed <job_name>

Options:
	-h, --help            show this help message and exit
	-v					  Shows 
	<job_name>              The job_id of the job to teuthology logs of failed
						  jobspec's

opens all failed jobs using scrape.log in vim editor:
from job name, finds all the failed and dead job and opens them in vim tabs.

NOTE: Must be run on the same machine that is executing the teuthology job
processes.

"""

def open_failed(job_name):
	archive = "/ceph/teuthology-archive/" + job_name + "/"

	scrape = archive + "scrape.log"

	with open(scrape,'r') as f:
		job_id = re.findall(r"\'\b[0-9]{7}\b\'", f.read())
		print("")
		print("jobs that failed...\n")

	for idx, item in enumerate(job_id):
		job_id[idx] = archive + item.strip("'")+ "/teuthology.log"
		print("job id " + job_id[idx])

	os.system("vim -p " +" ".join(job_id))
		
def main():
	args = docopt(doc)
	job_name = args["<job_name>"]
	open_failed(job_name)

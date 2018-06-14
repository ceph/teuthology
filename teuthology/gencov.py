import os
import sys
import logging
import subprocess
import shlex

import coverage_report

log=logging.getLogger()
hdlr=logging.FileHandler('/a/code_coverage_logs/coverage.log')
formatter = logging.Formatter('%(asctime)s %(levelname)s %(message)s')
hdlr.setFormatter(formatter)
log.addHandler(hdlr)
log.setLevel(logging.INFO)

def generate_coverage_compile(cover_dir):
	log.info("Inside generate_coverage_compile")
	merged_total=cover_dir+"/total.info"
	filtered_total=cover_dir+"/filtered_total.info"
#	cmd="lcov --rc lcov_branch_coverage=1 "
	cmd="lcov  "
	ilist=os.listdir(cover_dir)
	for ent in ilist:
		if '*.info' in ent:
			subprocess.Popen(
				args=[
				    'sed', '-i','s/\/sourcebuild/\/tmp\/build\/{}/'.format(\
					os.path.basename(cover_dir)), \
					cover_dir+"/"+ent]
			)

	for ent in ilist:
		if 'info' in ent:
			addstr= " -a " + cover_dir+"/"+ent
			tstr=" -t "+ ent.split("_")[0]
			cmd = cmd + addstr+tstr
			log.info(cmd)
	cmd=cmd + " -o "+ merged_total
	log.info(cmd)
	proc=subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE)
	proc_stdout=proc.communicate()[0]
	log.info(proc_stdout)
	assert(os.path.exists(merged_total))

	proc=subprocess.Popen(
		args=[
			'sed', '-i','s/\/sourcebuild/\/tmp\/build\/{}/'.format(\
				os.path.basename(cover_dir)), \
				merged_total]
		)
	proc_stdout=proc.communicate()[0]
	log.info(proc_stdout)

	cmd="lcov --remove "+merged_total+" '/usr/include/*' '/usr/lib/*' " +\
		" -o "+ filtered_total
	log.info(cmd)
	proc=subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE)
	proc_stdout=proc.communicate()[0]
	log.info(proc_stdout)
	assert(os.path.exists(filtered_total))

	cmd="genhtml " + " -o "+cover_dir+" {}".format(filtered_total)
	log.info(cmd)
	proc=subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE)
	proc_stdout=proc.communicate()[0]
	log.info(proc_stdout)
	assert(os.path.exists(cover_dir+"/index.html"))



def main(args):
	log = logging.getLogger(__name__)
	basedir="/a/code_coverage_logs/"
	coverdir=basedir+args['<run-name>']
	generate_coverage_compile(coverdir)
	gen_path="/a/code_coverage_logs/"
	coverage_report.gen_html(gen_path, 10)

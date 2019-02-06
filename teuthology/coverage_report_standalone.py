'''
This module generates code coverage reports in standalone fashion.
This will be used for aggregation of coverage reports across automated
and manual tests.
'''
import os
import subprocess
import shlex
import argparse
import glob

import coverage_report
genpath="/a/code_coverage_logs/"

def gen_results(data_src, outdir):
    '''
    data_src: directorry which contains .info lcov files
    outdir: where genhtml should put the results
    '''
    merged_info = "{dsrc}/merged_total.info".format(dsrc=data_src)
    merged_filterd = "{dsrc}/filtered_merged.info".format(dsrc=data_src)

    cmd = "lcov "
    ilist = os.listdir(data_src)
    for ent in ilist:
	if 'info' in ent:
	    addstr = " -a {dsrc}/{ent}".format(dsrc=data_src, ent=ent)
	    cmd = cmd + addstr

    cmd = "{cmd} -o {merg_info}".format(cmd=cmd, merg_info=merged_info)
    print cmd
    proc = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE)
    proc_stdout = proc.communicate()[0]
    assert(os.path.exists(merged_info))

    ''' remove unncessary includes '''
    cmd = "lcov --remove {merge_file} '/usr/include/*' '*/boost*' -o {fltr}".\
						format( merge_file=merged_info,
							fltr=merged_filterd)
    print cmd
    proc = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE)
    proc_stdout = proc.communicate()[0]
    assert(os.path.exists(merged_filterd))

    '''genhtml report and put it in outdir'''
    cmd = "genhtml {merged_filterd} --ignore-errors source -o {outdir}".format(\
					merged_filterd=merged_filterd,
					outdir=outdir)
    print cmd
    proc = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE)
    proc_stdout = proc.communicate()[0]
    assert(os.path.exists(outdir+ "/index.html"))



def parse_init():
    '''
    parse all the arguments
    -r: is directory from teuthology run which has
	gcda files, expected directory structure will be
	different from -d option
    '''
    parser = argparse.ArgumentParser()
    parser.add_argument("-r", "--rundir", type=str,\
			help="Directory which has gcda \
			files from teuthology runs")
    parser.add_argument("-s", "--src", type=str,\
			help="Directory which contains source files and gcno")
    parser.add_argument("-o", "--output", type=str,\
			help="Directory where you want aggregated tracefile\
			 and results should be stored")
    parser.add_argument("-t", "--title", type=str,\
			help="Title for this coverage report")
    parser.add_argument("-d", "--dir", type=str,\
			help="Directory which has gcda files, in case if its not\
			    from teuthology run ")
    parser.add_argument("--suffix", type=str,\
			help="version number to be suffixed, required for genhtml\
			      which will search for src dir during report gen")
    args = parser.parse_args()
    return args

def iterate_and_sync(args, srcdir, bldprefix):
    '''
    Iterate over teuthology jobs in a run
    rsync gcda tree to source
    gen info file and put it int output dir
    '''
    rundir = args.rundir
    jids = filter(os.path.isdir, [os.path.join(rundir, ent) for ent in os.listdir(rundir)])
    print 'jids are {}'.format(jids)
    if not args.output:
	outdir = bldprefix
    else:
	outdir = args.output
    for jid in jids:
	path_to_remotes = "{jid}/ceph/remote/".format(\
			    jid=jid)
	remotes_of_jid = os.listdir(path_to_remotes)
	print 'remotes are {}'.format(remotes_of_jid)
	for remote in remotes_of_jid:
	    print 'current remote is {}'.format(remote)
	    abs_path = "{ptr}/{rnode}/coverage/{bldprefix}/ceph-{ver}/".\
			format(ptr=path_to_remotes,\
				rnode=remote,\
				bldprefix=bldprefix,\
				ver=args.suffix)
	    print 'abs_path = {}'.format(abs_path)
	    ''' rsync gcda from abs_path to src directory '''
	    sync = "rsync -avz {gcda_dir} {src}".format(\
					gcda_dir=abs_path,
					src=srcdir)
	    proc = subprocess.Popen(shlex.split(sync), stdout=subprocess.PIPE)
	    proc_stdout = proc.communicate()[0]
	    print proc_stdout
	    '''
	    run lcov to generate .info file for this remote node
	    naming convention: runid_jid_remote.info
	    '''
	    info_file = "{jid}-{remote}.info".format(
					jid=os.path.basename(jid),
					remote=remote)
	    lcov="lcov -c -d {srcdir} -o {outdir}/{info}".format(\
					srcdir=srcdir,
					outdir=outdir,
					info=info_file)
	    proc = subprocess.Popen(shlex.split(lcov), stdout=subprocess.PIPE)
	    proc_stdout = proc.communicate()[0]
	    print proc_stdout

	    ''' clean up gcda in src dir so that we can copy gcda from other\
		nodes'''
	    purge_list = [y for x in os.walk(srcdir) for y in glob.glob(os.path.join(x[0], '*.gcda'))]
	    for ent in purge_list:
		print 'purging {}'.format(ent)
		os.remove(ent)


def do_coverage(args):
    '''
    iterate through dirs, sync gcda tree into source
    generate .info files and finally gen report
    '''
    bldprefix = "/builddir/build/BUILD/"

    if args.rundir:
	'''
	This is teuthology run and hence will have
	directory heirarchy similar to
	/run_name_dir/job/ceph/remote/remote_name/coverage/<builddir>.
	<builddir> follows convention /builddir/build/BUILD/<ceph-version>/
	'''
	rundir = args.rundir
	if args.src:
	    srcdir = args.src
	else:
	    '''
	    default to /builddir/build/BUILD/usr/src/coverage/ceph/
	    inside this we should be able to find build/ and src/
	    dirs
	    '''
	    srcdir = "/builddir/build/BUILD/usr/src/coverage/ceph"

	'''
	create softlink inside bldprefix dir so \
	that genhtml doesn't fail.
	this looks something like
	"/builddir/build/BUILD/ceph-12.x.x -> \
	/builddir/build/BUILD/usr/src/coverage/ceph/"
	'''
	tlink = os.path.join(bldprefix, "ceph-"+args.suffix)
	create_lnk = "ln -s {srcdir} {lnkname}".format(srcdir=srcdir, lnkname=tlink)
	print 'running cmd = {}'.format(create_lnk)
	proc = subprocess.Popen(shlex.split(create_lnk),\
				stdout=subprocess.PIPE)
	proc_stdout = proc.communicate()[0]
	print proc_stdout
	iterate_and_sync(args, srcdir, bldprefix)



if __name__ == "__main__":
    args = parse_init()
    if not args.rundir and not args.dir:
	print "Please provides atleast one gcda source"
	print "Either --rundir or --dir"
    if not args.suffix:
	print "need --suffix: Please provide version suffix: ex: 12.x.x"
    do_coverage(args)
    if not args.title:
	title = "CEPH-{ver}-COVERAGE-REPORT-{run}".format(ver=args.suffix,\
						run=args.rundir)
    else:
	title = args.title+"CEPH-{ver}-COVERAGE-REPORT".format(ver=args.suffix)
    os.mkdir(os.path.join(args.output, title))
    gen_results(args.output, os.path.join(args.output, title))
    cmd = "cp -ar {report} {cov_repo}".format(\
		report=os.path.join(args.output, title),
		cov_repo=genpath)
    proc = subprocess.Popen(shlex.split(cmd), stdout=subprocess.PIPE)
    proc_stdout = proc.communicate()[0]
    print proc_stdout
    coverage_report.gen_html(genpath, 10)









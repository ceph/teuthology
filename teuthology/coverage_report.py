import os

N_ENTRIES=10
genpath="/a/code_coverage_logs/"


def gen_html(genpath, N_ENTRIES):
	if not os.path.exists(genpath):
		print 'path doesnt exists'
	files = sorted([genpath+ent for ent in os.listdir(genpath)],key=os.path.getctime, reverse=True)
	for ent in files:
		pass
		#print os.path.basename(ent)
	body=""
	for ent in files:
		if not os.path.isdir(ent):
			pass
		else:
			body=body+\
			"<TR>\n"+"<TD>"+\
			"<a href=\"{}\">".format(os.path.basename(ent)+"/index.html")+os.path.basename(ent)+"</a></TD>"+\
			"<TD>"+\
			"<a href=\"http://pulpito.ceph.redhat.com/{}\">".format(os.path.basename(ent))+"Run"+"</a></TD>"+\
			"</TR>\n"

	page="	<html>\n \
		<title> Code Coverage</title>\n \
		<body>\n \
		<h1><u>Downstream: CEPH Code Coverage</u></h1><br/>\n\
		<TABLE BORDER=5>\n \
		<TR>\n\
		<TH COLSPAN=\"2\">\n\
		 <H3><BR>CEPH COVERAGE RUNS</H3>\n\
		</TH>\n\
		</TR>\n\
		<TR>\n\
		<TH>Coverage results </TH>\n\
		<TH> Teuthology results </TH>\n\
		</TR>\n\
		{} \
		</body>\n \
		</html>\n ".format(body)
	fd=open(genpath+"index.html", "w+")
	fd.writelines(page)
	fd.close()



if __name__ =="__main__":
	gen_html(genpath, N_ENTRIES)

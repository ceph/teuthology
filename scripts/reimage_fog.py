import docopt

from teuthology.misc import reimage_fog
import sys

doc = """
usage: teuthology-reimage-fog -h
       teuthology-reimage-fog --nodes node1,node2 --os-type distro --os-version version

Reimage nodes using FOG without locking the nodes

standard arguments:
  -h, --help                           Show this help message and exit
  --nodes node1,node2                  List of nodes to reimage
  --os-type <os-type>                  Distribution type eg: rhel, ubuntu
  --os-version <os-version>            OS version eg: 7.6, 16.04 etc
"""


def main(argv=sys.argv[1:]):
    args = docopt.docopt(doc, argv=argv)
    reimage_fog(args)

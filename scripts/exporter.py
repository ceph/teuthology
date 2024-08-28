import docopt

doc = """
usage: teuthology-exporter --help
       teuthology-exporter [--interval INTERVAL]

optional arguments:
  -h, --help                     show this help message and exit
  --interval INTERVAL            update metrics this often, in seconds
                                 [default: 60]
"""


def main():
    args = docopt.docopt(doc)
    import teuthology.exporter
    teuthology.exporter.main(args)

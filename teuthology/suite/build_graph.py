import logging
import os
import random
import yaml

from teuthology.suite import graph

log = logging.getLogger(__name__)


def build_graph(path, subset=None, no_nested_subset=False, seed=None, suite_repo_path=None, config=None):


    """
    Return a list of items descibed by path such that if the list of
    items is chunked into mincyclicity pieces, each piece is still a
    good subset of the suite.

    A good subset of a product ensures that each facet member appears
    at least once.  A good subset of a sum ensures that the subset of
    each sub collection reflected in the subset is a good subset.

    A mincyclicity of 0 does not attempt to enforce the good subset
    property.

    The input is just a path.  The output is an array of (description,
    [file list]) tuples.

    For a normal file we generate a new item for the result list.

    For a directory, we (recursively) generate a new item for each
    file/dir.

    For a directory with a magic '+' file, we generate a single item
    that concatenates all files/subdirs (A Sum).

    For a directory with a magic '%' file, we generate a result set
    for each item in the directory, and then do a product to generate
    a result list with all combinations (A Product). If the file
    contains an integer, it is used as the divisor for a random
    subset.

    For a directory with a magic '$' file, or for a directory whose name
    ends in '$', we generate a list of all items that we will randomly
    choose from.

    The final description (after recursion) for each item will look
    like a relative path.  If there was a % product, that path
    component will appear as a file with braces listing the selection
    of chosen subitems.

    :param path:        The path to search for yaml fragments
    :param subset:	(index, outof)
    :param no_nested_subset:	disable nested subsets
    :param seed:        The seed for repeatable random test
    """

    if subset:
        log.info(
            'Subset=%s/%s' %
            (str(subset[0]), str(subset[1]))
        )
    if no_nested_subset:
        log.info("no_nested_subset")
    random.seed(seed)
    (which, divisions) = (0,1) if subset is None else subset
    G = graph.Graph()
    log.info("building graph")
    _build_graph(G, path, suite_repo_path=suite_repo_path, config=config)
    #log.debug("graph:\n%s", G.print()) This is expensive with the print as an arg.
    configs = []
    log.info("walking graph")
    for desc, paths in G.walk(which, divisions, no_nested_subset):
        log.debug("generated %s", desc)
        configs.append((desc, paths))
    log.info("generated %d configs", len(configs))
    return configs

# To start: let's plug git into Lua so we can inspect versions of Ceph!
# - Use Lua to control how large the subset should be.. based on a target number of jobs..
# - Use Lua to tag parts of a suite suite that should be included in a broader smoke run.
# - Use Lua to create the graph.

#Graph
#Lua rewrite
#Change edge randomization based on visitation. Prune before adding to nodes list during walk.
#Set tags at root of graph. Then Lua code in dir prunes at graph creation time.
#Set subset based on target # of jobs
# TODO: maybe reimplement graph.lua so that we can have the graph expand / prune with lua code provided by qa/ suite
# reef.lua:
#   git = lupa.git
#   function generate()
#     ...
#   end
#   function prune()
#   end
def _build_graph(G, path, **kwargs):
    flatten = kwargs.pop('flatten', False)
    suite_repo_path = kwargs.get('suite_repo_path', None)
    config = kwargs.get('config', None)

    if os.path.basename(path)[0] == '.':
        return None
    if not os.path.exists(path):
        raise IOError('%s does not exist (abs %s)' % (path, os.path.abspath(path)))
    if os.path.isfile(path):
        if path.endswith('.yaml'):
            node = graph.Node(path, G)
            with open(path) as f:
                txt = f.read()
                node.set_content(yaml.safe_load(txt))
            return node
        if path.endswith('.lua'):
            if suite_repo_path is not None:
                import git
                Gsuite = git.Repo(suite_repo_path)
            else:
                Gsuite = None
            log.info("%s", Gsuite)
            node = graph.LuaGraph(path, G, Gsuite)
            node.load()
            return node
        return None
    if os.path.isdir(path):
        if path.endswith('.disable'):
            return None
        files = sorted(os.listdir(path))
        if len(files) == 0:
            return None
        subg = graph.SubGraph(path, G)
        specials = ('+', '$', '%')
        if '+' in files:
            # concatenate items
            for s in specials:
                if s in files:
                    files.remove(s)

            current = subg.source
            for fn in sorted(files):
                node = _build_graph(G, os.path.join(path, fn), flatten=True, **kwargs)
                if node:
                    current.add_edge(node)
                    current = node
            subg.link_node_to_sink(current)
        elif path.endswith('$') or '$' in files:
            # pick a random item -- make sure we don't pick any magic files
            for s in specials:
                if s in files:
                    files.remove(s)

            for fn in sorted(files):
                node = _build_graph(G, os.path.join(path, fn), flatten=False, **kwargs)
                if node:
                    subg.source.add_edge(node) # to source
                    subg.link_node_to_sink(node) # to sink
            subg.set_subset(len(files), force=True)
        elif '%' in files:
            # convolve items
            for s in specials:
                if s in files:
                    files.remove(s)

            with open(os.path.join(path, '%')) as f:
                divisions = f.read()
                if len(divisions) == 0:
                    divisions = 1
                else:
                    divisions = int(divisions)
                    assert divisions > 0
                subg.set_subset(divisions)

            current = subg.source
            for fn in sorted(files):
                node = _build_graph(G, os.path.join(path, fn), flatten=False, **kwargs)
                if node:
                    current.add_edge(node)
                    current = node
            subg.link_node_to_sink(current)
            subg.set_subset(divisions)
        else:
            # list items
            for s in specials:
                if s in files:
                    files.remove(s)

            current = subg.source
            for fn in sorted(files):
                node = _build_graph(G, os.path.join(path, fn), flatten=flatten, **kwargs)
                if node:
                    current.add_edge(node) # to source
                    if flatten:
                        current = node
                    else:
                        subg.link_node_to_sink(node) # to sink
            if flatten:
                subg.link_node_to_sink(current) # to sink

        return subg

    raise RuntimeError(f"Invalid path {path} seen in _build_graph")

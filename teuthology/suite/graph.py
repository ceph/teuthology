# TODO Tests:
# - that all subsets produce the full suite, no overlap
# - $ behavior
# - % behavior
# - nested dirs

import bisect
import logging
import os
import random
import re

log = logging.getLogger(__name__)

class Graph(object):
    def __init__(self):
        self.nodes = []
        self.root = None
        self.epoch = 0

    def add_node(self, node):
        if 0 == len(self.nodes):
            self.root = node
        self.nodes.append(node)
        self.epoch += 1

    def add_edge(self, n1, n2):
        self.epoch += 1

    @staticmethod
    def collapse_desc(desc):
       desc = re.sub(r" +", " ", desc)
       desc = re.sub(r"/ {", "/{", desc)
       desc = re.sub(r"{ ", "{", desc)
       desc = re.sub(r" }", "}", desc)
       return desc

    # N.B. avoid recursion because Python function calls are criminally slow.
    def walk(self, which, divisions, no_nested_subset):
        log.info(f"walking graph {self.root} with {self.path_count()} paths and subset = {which}/{divisions}")
        l = random.sample(self.root.outgoing_sorted, k=len(self.root.outgoing_sorted))
        nodes = [(x, 1) for x in l]
        path = [(self.root, self.root.subset)]
        count = 0
        while nodes:
            (node, backtrack) = nodes.pop()
            del path[backtrack:]

            parent_divisions = path[-1][1]
            nested_divisions = parent_divisions * divisions
            current_subset = count % nested_divisions
            next_path = (((nested_divisions - current_subset) + which) % nested_divisions)
            if node.count <= next_path:
                # prune
                count = count + node.count
                continue

            child_divisions = node.subset if not no_nested_subset or node.force_subset else 1
            path.append((node, parent_divisions * child_divisions))
            if len(node.outgoing) == 0:
                assert next_path == 0
                assert current_subset == which
                count = count + 1
                desc = []
                frags = []
                for (n, _) in path:
                    desc.append(n.desc())
                    if n.content:
                        frags.append((n.path, n.content))
                yield Graph.collapse_desc(" ".join(desc)), frags
            else:
                backtrack_to = len(path)
                for n in random.sample(node.outgoing_sorted, k=len(node.outgoing_sorted)):
                    nodes.append((n, backtrack_to))

    def path_count(self):
        return self.root.path_count(self.epoch)

    def print(self, *args, **kwargs):
        return self.root.print(*args, **kwargs)

class Node(object):
    def __init__(self, path, graph):
        self.path = path
        self.basename = os.path.basename(self.path)
        self.name, self.extension = os.path.splitext(self.basename)
        self.content = None
        self.graph = graph
        self.outgoing = set()
        self.outgoing_sorted = []
        self.count = 1
        self.subset = 1
        self.force_subset = False
        self.draw = True
        self.epoch = 0
        self.graph.add_node(self)
        self.birth = self.graph.epoch

    def desc(self):
        return self.name

    def add_edge(self, node):
        if node not in self.outgoing:
            self.outgoing.add(node)
            # N.B.: a Python set is unordered and we will need to randomize during
            # path walks. To make that reproducible with the same seed, the
            # shuffled set must be (arbitrarily) ordered first.
            bisect.insort(self.outgoing_sorted, node)
            self.graph.add_edge(self, node)

    def set_content(self, content):
        self.content = content

    def path_count(self, epoch):
        if self.epoch < epoch:
            count = 0
            for node in self.outgoing:
                count = count + node.path_count(epoch)
            self.count = max(1, count)
            self.epoch = epoch
        return self.count

    def __hash__(self):
        return hash(id(self))

    def __eq__(self, other):
        if isinstance(other, Node):
            return False
        return self.path == other.path

    def __lt__(self, other):
        if not isinstance(other, Node):
            raise TypeError("not comparable")
        return self.birth < other.birth

    def __str__(self):
        return f"[node paths={self.count} edges={len(self.outgoing)} `{self.path}']"

class NullNode(Node):
    def __init__(self, name, graph):
        super().__init__(name, graph)
        self.draw = False

    def desc(self):
        raise NotImplemented("no desc")

class SourceNode(NullNode):
    def __init__(self, name, graph):
        super().__init__(f"source:{name}", graph)

    def desc(self):
        return "{"

class SinkNode(NullNode):
    def __init__(self, name, graph):
        super().__init__(f"sink:{name}", graph)

    def desc(self):
        return "}"

class SubGraph(Node):
    def __init__(self, path, graph):
        super().__init__(path, graph)
        self.source = SourceNode(path, graph)
        self.outgoing.add(self.source)
        self.outgoing_sorted = sorted(self.outgoing)
        self.sink = SinkNode(path, graph)
        self.nodes = set()
        self.combinations = 0
        self.count = 0

    def desc(self):
        return f"{self.name}/"

    def set_subset(self, subset, force=False):
        # force subset if necessary for e.g. "$" implementation
        self.subset = subset
        self.force_subset = force

    def add_edge(self, node):
        return self.sink.add_edge(node)

    def link_source_to_node(self, node):
        self.source.add_edge(node)

    def link_node_to_sink(self, node):
        node.add_edge(self.sink)

    @staticmethod
    def _nx_add_edge(nxG, node, other, force=False):
        if not force and not other.draw:
            log.debug(f"_nx_add_edge: skip {other}")
            for out in other.outgoing:
                SubGraph._nx_add_edge(nxG, node, out, force=force)
        else:
            log.debug(f"_nx_add_edge: {node} {other}")
            nxG.add_edge(node, other)
            SubGraph._nx_add_edges(nxG, other, force=force)

    @staticmethod
    def _nx_add_edges(nxG, node, force=False):
        for out in node.outgoing:
            #log.info(f"_nx_add_edges: {node}: {out}")
            SubGraph._nx_add_edge(nxG, node, out, force=force)

    def print(self, force=False):
        import networkx as nx
        #import matplotlib.pyplot as plt

        nxG = nx.DiGraph()
        SubGraph._nx_add_edges(nxG, self, force=force)
        #log.debug("%s", nxG)

        return "\n".join(nx.generate_network_text(nxG, vertical_chains=True))

        #pos = nx.spring_layout(nxG)
        #nx.draw_networkx_nodes(nxG, pos, node_color='blue', node_size=800)
        #nx.draw_networkx_edges(nxG, pos, arrowsize=15)
        #nx.draw_networkx_labels(nxG, pos, font_size=12, font_color='black')

        #plt.savefig('graph.svg')



import lupa
import git
import sys
import yaml

class LuaGraph(SubGraph):
    FRAGMENT_GENERATE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fragment-generate.lua")

    with open(FRAGMENT_GENERATE) as f:
        FRAGMENT_GENERATE_SCRIPT = f.read()

    def __init__(self, path, graph, gSuite):
        super().__init__(path, graph)
        self.L = lupa.LuaRuntime()
        with open(path) as f:
            self.script = f.read()
            log.info("%s", self.script)
        self.gSuite = gSuite

    def load(self):
        self.L.execute(self.FRAGMENT_GENERATE_SCRIPT)
        new_script = self.L.eval('new_script')
        self.env, self.func = new_script(self.script, log)
        self.env['graph'] = sys.modules[__name__]
        self.env['myself'] = self
        self.env['ceph'] = self.gSuite
        self.env['yaml'] = yaml
        self.func()

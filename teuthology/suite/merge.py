import copy
import logging
import lupa
import os
from types import MappingProxyType
import yaml

from teuthology.config import JobConfig
from teuthology.suite.build_matrix import combine_path
from teuthology.suite.util import strip_fragment_path
from teuthology.misc import deep_merge

log = logging.getLogger(__name__)

TEUTHOLOGY_TEMPLATE = MappingProxyType({
  "teuthology": {
    "fragments_dropped": [],
    "meta": {},
    "postmerge": [],
  }
})

L = lupa.LuaRuntime()
FRAGMENT_MERGE = os.path.join(os.path.dirname(os.path.abspath(__file__)), "fragment-merge.lua")
with open(FRAGMENT_MERGE) as f:
    L.execute(f.read())

def config_merge(configs, suite_name=None, **kwargs):
    """
    This procedure selects and merges YAML fragments for each job in the
    configs array generated for the matrix of jobs.

    The primary task here is to run premerge and postmerge scripts specified
    with the YAML fragments as part of filtering out jobs or individual YAML
    fragments. This is done with Lua scripting (via "lupa", a "lunatic"
    derivative).

    A premerge script looks like:

    <foo.yaml>
    teuthology:
      premerge: |
                if yaml.os_type == 'ubuntu' then reject() end
    </foo.yaml>

    This script runs prior to a YAML fragment merging into the complete YAML
    specification for a job.  The script has access to the complete YAML
    description generated so far as part of merging earlier fragments
    (remember: fragments are ordered lexicographically). In the above case, the
    os_type is checked with the foo.yaml fragment dropped if the job is
    configured to run on Ubuntu (note: this does not account for a jobs'
    default os_type which is not yet known).

    The postmerge scripts look like:

    <bar.yaml>
    teuthology:
      postmerge:
        - if yaml.os_type == "ubuntu" then reject() end
    </bar.yaml>

    This script is the same but has a different effect: if, after combining all
    the YAML fragments for a job, the os_type is "ubuntu", then the entire job
    is dropped (filtered out / rejected). postmerge scripts are also specified
    as a list of strings in the teuthology.postmerge array. All of these
    strings are concatenated and then executed as a single script. So,
    postmerge scripts from multiple fragments are all combined. You may use
    this to define variables, functions, or anything else you need.

    Scripts have access to the entire yaml object and may do any desired advanced
    checks. It is also possible to programatically change the YAML definition:

    <foo.yaml>
    teuthology:
      postmerge:
        - |
          local attr = py_attrgetter
          local tasks = py_list()
          for i = 1, 3 do
            local task = py_dict(
              exec = py_dict(py_list(
                py_tuple("mon.a", py_list(
                  "echo "..i
                )
              ))
            )
            attr(tasks).append(task)
          end
          deep_merge(yaml.tasks, tasks)
    </foo.yaml>

    This will be as if the yaml file contained:

    <foo.yaml>
    tasks:
      exec:
        mon.a:
          - echo 1
      exec:
        mon.a:
          - echo 2
      exec:
        mon.a:
          - echo 3
    </foo.yaml>

    Which will be merged normally (via deep_merge) after the script is run.

    Scripts are well sandboxed with access to a small selection of the Lua
    builtin libraries. There is also access to some python/lupa specific
    functions which are prefixed with "py_". No I/O or other system functions
    permitted.

    The teuthology-suite filtering options are now implemented via builtin
    postmerge scripts. Logically, if a filter matches then reject will drop
    the entire job (config) from the list.
    """
    seed = kwargs.setdefault('seed', 1)
    base_config = kwargs.setdefault('base_config', JobConfig())
    if not isinstance(seed, int):
        log.debug("no valid seed input: using 1")
        seed = 1
    log.debug("configuring Lua randomseed to %d", seed)
    L.execute(f'local math = require"math"; math.randomseed({seed});')
    new_script = L.eval('new_script')
    yaml_cache = {}
    for desc, paths in configs:
        log.debug("merging config %s", desc)

        if suite_name is not None:
            desc = combine_path(suite_name, desc)

        yaml_complete_obj = copy.deepcopy(base_config.to_dict())
        deep_merge(yaml_complete_obj, dict(TEUTHOLOGY_TEMPLATE))
        for path in paths:
            if path not in yaml_cache:
                with open(path) as f:
                    txt = f.read()
                    yaml_cache[path] = (txt, yaml.safe_load(txt))

            yaml_fragment_txt, yaml_fragment_obj = yaml_cache[path]
            if yaml_fragment_obj is None:
                continue
            yaml_fragment_obj = copy.deepcopy(yaml_fragment_obj)
            premerge = yaml_fragment_obj.get('teuthology', {}).pop('premerge', '')
            if premerge:
                log.debug("premerge script running:\n%s", premerge)
                env, script = new_script(premerge, log, deep_merge, yaml.safe_load)
                env['base_frag_paths'] = [strip_fragment_path(x) for x in paths]
                env['description'] = desc
                env['frag_paths'] = paths
                env['suite_name'] = suite_name
                env['yaml'] = yaml_complete_obj
                env['yaml_fragment'] = yaml_fragment_obj
                for k,v in kwargs.items():
                    env[k] = v
                if not script():
                    log.debug("skipping merge of fragment %s due to premerge filter", path)
                    yaml_complete_obj['teuthology']['fragments_dropped'].append(path)
                    continue
            deep_merge(yaml_complete_obj, yaml_fragment_obj)

        postmerge = yaml_complete_obj.get('teuthology', {}).get('postmerge', [])
        postmerge = "\n".join(postmerge)
        log.debug("postmerge script running:\n%s", postmerge)
        env, script = new_script(postmerge, log, deep_merge, yaml.safe_load)
        env['base_frag_paths'] = [strip_fragment_path(x) for x in paths]
        env['description'] = desc
        env['frag_paths'] = paths
        env['suite_name'] = suite_name
        env['yaml'] = yaml_complete_obj
        for k,v in kwargs.items():
            env[k] = v
        if not script():
            log.debug("skipping config %s due to postmerge filter", desc)
            continue
        yield desc, paths, yaml_complete_obj

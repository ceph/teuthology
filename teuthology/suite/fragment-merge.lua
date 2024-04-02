-- accept a fragment/config (or just return true from the script!)
local function accept()
  coroutine.yield(true)
end

-- reject a fragment/config (or just return false from the script!)
local function reject()
  coroutine.yield(false)
end

-- this implements logic for filtering (via teuthology-suite CLI flags)
local function matches(_ENV, f)
  if description:find(f, 1, true) then
    return true
  end
  if filter_fragments then
    for i, path in py_enumerate(base_frag_paths) do
      if path:find(f) then
        return true
      end
    end
  end
end

local function check_filters(_ENV)
  if filter_all then
    for i, f in py_enumerate(filter_all) do
      if not matches(_ENV, f) then
        reject()
      end
    end
  end
  if filter_in then
    local found, tried = false, false
    for i, f in py_enumerate(filter_all) do
      tried = true
      if matches(_ENV, f) then
        found = true
        break
      end
    end
    if tried and not found then
      reject()
    end
  end
  if filter_out then
    for i, f in py_enumerate(filter_out) do
      if matches(_ENV, f) then
        reject()
      end
    end
  end
end

-- Define py_enumerate, py_iterex, py_attrgetter, py_itemgetter, py_dict, py_list, and py_tuple globally
py_enumerate = python.enumerate
py_iterex = python.iterex
py_attrgetter = python.as_attrgetter
py_itemgetter = python.as_itemgetter
py_dict = python.builtins.dict
py_list = python.builtins.list
py_tuple = python.builtins.tuple

function new_script(script, log, deep_merge, yaml_load)
  -- create a restricted sandbox for the script:
  local env = setmetatable({
    accept = accept,
    deep_merge = deep_merge,
    log = log,
    reject = reject,
    yaml_load = yaml_load,
    python = python, -- Assuming python module is available
    ["python.builtins"] = python.builtins, -- Assuming python.builtins module is available
    py_enumerate = py_enumerate,
    py_iterex = py_iterex,
    py_attrgetter = py_attrgetter,
    py_itemgetter = py_itemgetter,
    py_dict = py_dict,
    py_list = py_list,
    py_tuple = py_tuple,
  }, {
    __index = function(t, k)
      -- Allow only specified Python functions
      if k == "py_enumerate" or k == "py_iterex" or k == "py_attrgetter" or k == "py_itemgetter" then
        return python[k]
      elseif k == "py_dict" or k == "py_list" or k == "py_tuple" then
        return python.builtins[k]
      else
        return _G[k]
      end
    end
  })

  -- avoid putting check_filters in _ENV
  -- try to keep line numbers correct:
  local header = [[do local check_filters = ...; accept(); check_filters(_ENV) end local function main() do ]]
  local footer = [[ end return true end return main()]]
  local function chunks()
    coroutine.yield(header)
    if #script > 0 then
      coroutine.yield(script)
    end
    coroutine.yield(footer)
  end

  -- put the script in a coroutine so we can yield success/failure from
  -- anywhere in the script, including in nested function calls.
  local f, err = load(coroutine.wrap(chunks), 'teuthology', 't', env)
  if f == nil then
    error("failure to load script: "..err)
  end
  f = coroutine.wrap(f)
  f(check_filters)
  return env, f
end

-- allow only some Lua (and lunatic) builtins for use by scripts
local SCRIPT_ENV = {
  assert = assert,
  error = error,
  ipairs = ipairs,
  next = next,
  pairs = pairs,
  tonumber = tonumber,
  tostring = tostring,
  py_attrgetter = python.as_attrgetter,
  py_dict = python.builtins.dict,
  py_len = python.builtins.len,
  py_list = python.builtins.list,
  py_tuple = python.builtins.tuple,
  py_enumerate = python.enumerate,
  py_iterex = python.iterex,
  py_itemgetter = python.as_itemgetter,
  math = math,
}
local SCRIPT_MT = {
  __index = SCRIPT_ENV,
}

function new_script(script, log, deep_merge, yaml_load)
  -- create a restricted sandbox for the script:
  local env = setmetatable({
    --deep_merge = deep_merge,
    log = log,
    --yaml_load = yaml_load,
  }, SCRIPT_MT)

  -- avoid putting check_filters in _ENV
  -- try to keep line numbers correct:
  local header = [[local function main(...) ]]
  local footer = [[ end return main]]
  local function chunks()
    --coroutine.yield(header)
    if #script > 0 then
      coroutine.yield(script)
    end
    --coroutine.yield(footer)
  end

  print('new_script', script)

  -- put the script in a coroutine so we can yield success/failure from
  -- anywhere in the script, including in nested function calls.
  local f, err = load(coroutine.wrap(chunks), 'teuthology', 't', env)
  if f == nil then
    error("failure to load script: "..err)
  end
  return env, f
end

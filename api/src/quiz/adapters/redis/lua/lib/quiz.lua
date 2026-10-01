-- AI-ASSISTED: helpers the loader puts in front of every quiz script (docs/spec/redis.md §1-§2).
-- KEYS follow quiz_keys(): 1 meta ... 12 scored are the data keys, 13 tick, 14 events, 15 control.
local K = {meta = 1, key = 2, names = 3, present = 4, totals = 5, board = 6, serve = 7,
  subs = 8, answered = 9, seq = 10, dirty = 11, scored = 12, tick = 13, events = 14, control = 15}

-- The one server clock, in integer ms.
local function now_ms()
  local t = redis.call('TIME')
  return tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
end

-- Give every data key the quiz TTL, so a quiz expires as a whole (the tick token keeps its own).
local function refresh(ttl_ms)
  for i = K.meta, K.scored do
    redis.call('PEXPIRE', KEYS[i], ttl_ms)
  end
end

-- The sorted-set score of docs/spec/redis.md §4, as an exact integer string for ZADD.
local function board_score(total, reached_rel_ms)
  return string.format('%.0f', (1073741824 - total) * 4194304 + reached_rel_ms)
end

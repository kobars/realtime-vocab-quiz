-- AI-ASSISTED: helpers the loader puts in front of every quiz script (docs/spec/redis.md §1-§2).
-- The loader defines K (the KEYS index of each QuizKeys field), DATA_KEYS and QUIZ_TTL_MS above
-- this file, from keys.py, so the KEYS order and the TTL exist once.

-- The one server clock, in integer ms.
local function now_ms()
  local t = redis.call('TIME')
  return tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
end

-- Give every data key the quiz TTL, so a quiz expires as a whole (the tick token keeps its own).
local function refresh()
  for _, i in ipairs(DATA_KEYS) do
    redis.call('PEXPIRE', KEYS[i], QUIZ_TTL_MS)
  end
end

-- The sorted-set score of docs/spec/redis.md §4, as an exact integer string for ZADD.
local function board_score(total, reached_rel_ms)
  return string.format('%.0f', (1073741824 - total) * 4194304 + reached_rel_ms)
end

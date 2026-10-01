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

-- The deadline check, then the player and presence checks of docs/spec/redis.md §3, for a meta
-- read as HMGET startMs, deadlineMs, endedMs, endSeq, ... Returns an error reply, or nil and the
-- player's serve entry {cursor, serveMs, finished}.
local function check_player(meta, now, uid, conn)
  if meta[3] or now >= tonumber(meta[2]) then
    return {'QUIZ_ENDED', meta[4] or false}
  end
  local serve = redis.call('HGET', KEYS[K.serve], uid)
  local held = redis.call('HGET', KEYS[K.present], uid)
  if not serve or not held then
    return {'NOT_JOINED'}
  end
  if cjson.decode(held)[1] ~= conn then
    return {'SESSION_REPLACED'}
  end
  return nil, cjson.decode(serve)
end

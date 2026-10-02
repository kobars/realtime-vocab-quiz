-- AI-ASSISTED: helpers the loader puts in front of every quiz script (docs/spec/redis.md §1-§2).
-- The loader defines K (the KEYS index of each QuizKeys field) and DATA_KEYS from keys.py,
-- QUIZ_TTL_MS from the store port and REFRESH_MARGIN_MS from scripts.py above this file, so the
-- KEYS order and the TTL exist once. The standings limits are settings: each script that needs
-- them takes them through ARGV.

-- The one server clock, in integer ms.
local function now_ms()
  local t = redis.call('TIME')
  return tonumber(t[1]) * 1000 + math.floor(tonumber(t[2]) / 1000)
end

-- Mark the standings or counts changed: dirty keeps the time of the first change since the last
-- frame, from which publish_leaderboard measures its lag.
local function set_dirty(now)
  redis.call('SET', KEYS[K.dirty], now, 'NX')
end

-- Keep every data key on the quiz TTL, so a quiz expires as a whole (the tick and sweep tokens keep
-- their own). Once the meta TTL has dropped by REFRESH_MARGIN_MS, every data key gets the full TTL
-- again; until then only the keys a script may have created (the KEYS indexes it passes) need one,
-- and a new key gets the meta's, so no key outlives the quiz.
local function refresh(...)
  local ttl = redis.call('PTTL', KEYS[K.meta])
  if ttl < QUIZ_TTL_MS - REFRESH_MARGIN_MS then
    for _, i in ipairs(DATA_KEYS) do
      redis.call('PEXPIRE', KEYS[i], QUIZ_TTL_MS)
    end
    return
  end
  for _, i in ipairs({...}) do
    if redis.call('PTTL', KEYS[i]) == -1 then
      redis.call('PEXPIRE', KEYS[i], ttl)
    end
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

-- The standings from index first to last (0-based, inclusive) as {rank, uid, name, total}.
local function standing_rows(first, last)
  local ids = redis.call('ZRANGE', KEYS[K.board], first, last)
  if #ids == 0 then
    return {}
  end
  local names = redis.call('HMGET', KEYS[K.names], unpack(ids))
  local totals = redis.call('HMGET', KEYS[K.totals], unpack(ids))
  local rows = {}
  for n, uid in ipairs(ids) do
    rows[n] = {first + n, uid, names[n], tonumber(totals[n])}
  end
  return rows
end

-- The last index a broadcast carries: every player up to full_list_max, else the top top_n.
local function frame_last(count, top_n, full_list_max)
  return (count <= full_list_max and full_list_max or top_n) - 1
end

-- A JSON array of each item (cjson writes an empty table as {}).
local function json_list(items)
  local out = {}
  for n, item in ipairs(items) do
    out[n] = cjson.encode(item)
  end
  return '[' .. table.concat(out, ',') .. ']'
end

-- PUBLISH one broadcast on events: {"frame": <head fields + entries>, "ranks": [...]}.
local function publish_frame(head, rows, ranks)
  local entries = {}
  for n, r in ipairs(rows) do
    entries[n] = {rank = r[1], userId = r[2], displayName = r[3], score = r[4]}
  end
  local frame = cjson.encode(head):sub(1, -2) .. ',"entries":' .. json_list(entries) .. '}'
  redis.call('PUBLISH', KEYS[K.events], '{"frame":' .. frame .. ',"ranks":' .. json_list(ranks) .. '}')
end

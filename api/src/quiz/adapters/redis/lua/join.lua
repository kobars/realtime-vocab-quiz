-- AI-ASSISTED: join of docs/spec/redis.md §3: first-join player state, presence, dirty, replacement.
-- ARGV: uid, displayName, connId. Never increments seq and never publishes on events:
-- the next leaderboard frame carries the new player.
local uid, name, conn = ARGV[1], ARGV[2], ARGV[3]
local meta = redis.call('HMGET', KEYS[K.meta], 'startMs', 'deadlineMs', 'endedMs', 'endSeq',
  'questionCount', 'timeLimitMs')
if not meta[1] then
  return {'QUIZ_NOT_FOUND'}
end
local now = now_ms()
local start, deadline = tonumber(meta[1]), tonumber(meta[2])
if meta[3] or now >= deadline then
  return {'QUIZ_ENDED', meta[4] or false}
end

if redis.call('HSETNX', KEYS[K.serve], uid, '[-1,0,0]') == 1 then  -- the first join
  redis.call('HSETNX', KEYS[K.names], uid, name)
  redis.call('HSETNX', KEYS[K.totals], uid, 0)
  redis.call('ZADD', KEYS[K.board], 'NX', board_score(0, math.max(0, now - start)), uid)
end
local old = redis.call('HGET', KEYS[K.present], uid)
local replaced = old and cjson.decode(old)[1] or false
if replaced == conn then
  replaced = false
end
redis.call('HSET', KEYS[K.present], uid, cjson.encode({conn, now}))
redis.call('SET', KEYS[K.dirty], 1)
if replaced then
  redis.call('PUBLISH', KEYS[K.control],
    cjson.encode({type = 'session_replaced', uid = uid, connId = replaced}))
end
refresh()

local serve = cjson.decode(redis.call('HGET', KEYS[K.serve], uid))
local cursor, finished = serve[1], serve[3]
local open = cursor >= 0 and finished == 0
  and redis.call('HEXISTS', KEYS[K.answered], uid .. '|' .. cursor) == 0
return {'ok', tonumber(redis.call('GET', KEYS[K.seq])) or 0, cursor, open and 1 or 0, finished,
  tonumber(redis.call('HGET', KEYS[K.totals], uid)), tonumber(meta[5]), tonumber(meta[6]),
  deadline - now, replaced}

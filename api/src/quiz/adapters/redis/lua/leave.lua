-- AI-ASSISTED: leave of docs/spec/redis.md §3: compare-and-delete of the presence entry.
-- ARGV: uid, connId. Only the connection that holds the entry removes it; the score stays.
local uid, conn = ARGV[1], ARGV[2]
local meta = redis.call('HMGET', KEYS[K.meta], 'deadlineMs', 'endedMs')
if not meta[1] then
  return {'QUIZ_NOT_FOUND'}
end
local held = redis.call('HGET', KEYS[K.present], uid)
if not held or cjson.decode(held)[1] ~= conn then
  return {'stale'}  -- a newer connection took over, or the player already left
end
redis.call('HDEL', KEYS[K.present], uid)
local now = now_ms()
if not meta[2] and now < tonumber(meta[1]) then
  set_dirty(now)  -- the next frame carries the lower onlineCount
end
refresh(K.dirty)
return {'ok'}

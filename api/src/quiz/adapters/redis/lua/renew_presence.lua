-- AI-ASSISTED: renew_presence of docs/spec/redis.md §3: renew one node's entries, drop stale ones.
-- ARGV: staleMs, then pairs uid, connId. An entry is renewed only while that connId holds it.
local meta = redis.call('HMGET', KEYS[K.meta], 'deadlineMs', 'endedMs')
if not meta[1] then
  return {'QUIZ_NOT_FOUND'}
end
local now = now_ms()
if meta[2] or now >= tonumber(meta[1]) then
  return {'ended'}
end
for i = 2, #ARGV, 2 do
  local held = redis.call('HGET', KEYS[K.present], ARGV[i])
  if held and cjson.decode(held)[1] == ARGV[i + 1] then
    redis.call('HSET', KEYS[K.present], ARGV[i], cjson.encode({ARGV[i + 1], now}))
  end
end
local cutoff, removed = now - tonumber(ARGV[1]), 0
local entries = redis.call('HGETALL', KEYS[K.present])
for i = 1, #entries, 2 do
  if cjson.decode(entries[i + 1])[2] < cutoff then
    redis.call('HDEL', KEYS[K.present], entries[i])
    removed = removed + 1
  end
end
if removed > 0 then
  redis.call('SET', KEYS[K.dirty], 1)  -- the next frame carries the lower onlineCount
end
refresh()
return {'ok', removed}

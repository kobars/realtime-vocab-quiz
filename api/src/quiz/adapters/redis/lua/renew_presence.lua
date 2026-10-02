-- AI-ASSISTED: renew_presence of docs/spec/redis.md §3: renew one node's entries, drop stale ones.
-- ARGV: staleMs, sweepMs, then pairs uid, connId. An entry is renewed only while that connId holds
-- it. Only the call that takes the sweep token scans the whole hash: one node per sweep window.
local sweep_ms = tonumber(ARGV[2])
local meta = redis.call('HMGET', KEYS[K.meta], 'deadlineMs', 'endedMs')
if not meta[1] then
  return {'QUIZ_NOT_FOUND'}
end
local now = now_ms()
if meta[2] or now >= tonumber(meta[1]) then
  return {'ended'}
end
for i = 3, #ARGV, 2 do
  local held = redis.call('HGET', KEYS[K.present], ARGV[i])
  if held and cjson.decode(held)[1] == ARGV[i + 1] then
    redis.call('HSET', KEYS[K.present], ARGV[i], cjson.encode({ARGV[i + 1], now}))
  end
end
local removed = 0
if redis.call('SET', KEYS[K.sweep], 1, 'NX', 'PX', sweep_ms) then
  local cutoff = now - tonumber(ARGV[1])
  local entries = redis.call('HGETALL', KEYS[K.present])
  for i = 1, #entries, 2 do
    if cjson.decode(entries[i + 1])[2] < cutoff then
      redis.call('HDEL', KEYS[K.present], entries[i])
      removed = removed + 1
    end
  end
else
  local ttl = redis.call('PTTL', KEYS[K.sweep])
  if ttl == -1 or ttl > sweep_ms then  -- expiry is wall-clock: a clock step back stretches it
    redis.call('PEXPIRE', KEYS[K.sweep], sweep_ms)
  end
end
if removed > 0 then
  set_dirty(now)  -- the next frame carries the lower onlineCount
end
refresh(K.dirty)
return {'ok', removed}

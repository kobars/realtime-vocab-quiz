-- AI-ASSISTED: end_quiz of docs/spec/redis.md §3 and §3.1: the idempotent, once-only announcement.
-- ARGV: reason (deadline or host), topN. A first host call only marks the end; the next host call,
-- or a deadline call once due, publishes quiz_ended. Later calls return the same endSeq.
local reason = ARGV[1]
local meta = redis.call('HMGET', KEYS[K.meta], 'deadlineMs', 'endedMs', 'endSeq')
if not meta[1] then
  return {'QUIZ_NOT_FOUND'}
end
if meta[3] then
  return {'ended', tonumber(meta[3])}
end
local now, deadline = now_ms(), tonumber(meta[1])
if reason == 'deadline' and now < deadline then
  return {'not_due'}
end

redis.call('HSET', KEYS[K.meta], 'endedMs', meta[2] or math.min(now, deadline))
redis.call('DEL', KEYS[K.dirty])
if reason == 'host' and not meta[2] then
  refresh()
  return {'marked'}
end
local seq = redis.call('INCR', KEYS[K.seq])
redis.call('HSET', KEYS[K.meta], 'endSeq', seq)
publish_frame({v = 1, type = 'quiz_ended', seq = seq,
  playerCount = redis.call('ZCARD', KEYS[K.board]), you = cjson.null},
  standing_rows(0, tonumber(ARGV[2]) - 1), {})
refresh()
return {'ended', seq}

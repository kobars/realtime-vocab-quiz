-- AI-ASSISTED: serve_question of docs/spec/redis.md §3 and the rows of docs/spec/domain.md §5.1.
-- ARGV: uid, i, connId. The serve time comes from TIME; the reply never holds the answer
-- key. Never increments seq.
local uid, i, conn = ARGV[1], tonumber(ARGV[2]), ARGV[3]
local meta = redis.call('HMGET', KEYS[K.meta], 'startMs', 'deadlineMs', 'endedMs', 'endSeq',
  'questionCount', 'timeLimitMs', 'questionIds')
if not meta[1] then
  return {'QUIZ_NOT_FOUND'}
end
local now = now_ms()
local deadline, n, limit = tonumber(meta[2]), tonumber(meta[5]), tonumber(meta[6])
local refused, serve = check_player(meta, now, uid, conn)
if refused then
  return refused
end
local c, serve_ms, finished = serve[1], serve[2], serve[3]
local seq = tonumber(redis.call('GET', KEYS[K.seq])) or 0

local function question(index, served_at)
  local left = math.max(0, math.min(served_at + limit, deadline) - now)
  return {'ok', 'question', index, cjson.decode(meta[7])[index + 1], left, seq}
end

local function finished_reply()
  return {'ok', 'finished', n, false, 0, seq, tonumber(redis.call('HGET', KEYS[K.totals], uid)),
    redis.call('ZRANK', KEYS[K.board], uid) + 1, redis.call('ZCARD', KEYS[K.board])}
end

if finished == 1 and i == n then  -- a repeat of the finishing request
  return finished_reply()
end
if i == c and c >= 0 then  -- a retry of the serve: the stored serve time
  return question(c, serve_ms)
end
if i ~= n and (i ~= c + 1 or finished == 1) then  -- i = N finishes from any cursor
  return {'INVALID_STATE'}
end

if c >= 0 then  -- close question c as a skip unless it is already answered
  redis.call('HSETNX', KEYS[K.answered], uid .. '|' .. c,
    cjson.encode({-1, 0, math.max(0, now - serve_ms)}))
end
if i == n then
  redis.call('HSET', KEYS[K.serve], uid, cjson.encode({c, serve_ms, 1}))
  refresh(K.answered)
  return finished_reply()
end
redis.call('HSET', KEYS[K.serve], uid, cjson.encode({i, now, 0}))
refresh(K.answered)
return question(i, now)

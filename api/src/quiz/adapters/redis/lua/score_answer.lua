-- AI-ASSISTED: score_answer of docs/spec/redis.md §3 in the check order of docs/spec/domain.md §5.2.
-- ARGV: uid, i, choiceIndex, submissionId, connId. points() comes from lib/points.lua.
-- One TIME read for the deadline and the elapsed time. Never increments seq: atSeq = GET seq.
-- Returns ok, the 8 stored reply fields, then stepBack (never stored, 0 on a replay).
local uid, i, choice, sid, conn = ARGV[1], tonumber(ARGV[2]), tonumber(ARGV[3]), ARGV[4], ARGV[5]
local meta = redis.call('HMGET', KEYS[K.meta], 'startMs', 'deadlineMs', 'endedMs', 'endSeq',
  'questionCount', 'timeLimitMs')
if not meta[1] then
  return {'QUIZ_NOT_FOUND'}
end

local sub_field = uid .. '|' .. sid
local stored = redis.call('HGET', KEYS[K.subs], sub_field)
if stored then  -- idempotency layer 1: the submissionId
  local r = cjson.decode(stored)
  if r[1] ~= i then
    return {'INVALID_MESSAGE'}
  end
  r[9] = 0
  return {'ok', unpack(r)}
end

local now = now_ms()
local start, n, limit = tonumber(meta[1]), tonumber(meta[5]), tonumber(meta[6])
local refused, serve = check_player(meta, now, uid, conn)
if refused then
  return refused
end
local c, serve_ms = serve[1], serve[2]
if i < 0 or i > c then
  return {'QUESTION_NOT_OPEN'}
end
local answered_field = uid .. '|' .. i
if redis.call('HEXISTS', KEYS[K.answered], answered_field) == 1 then  -- idempotency layer 2
  return {'ALREADY_ANSWERED'}
end

local elapsed = now - serve_ms
local step_back = elapsed < 0 and 1 or 0
elapsed = math.max(0, elapsed)
local key = tonumber(redis.call('HGET', KEYS[K.key], i))
local correct = choice == key
local pts = points(correct, elapsed, limit)
local total = tonumber(redis.call('HGET', KEYS[K.totals], uid))
redis.call('HSET', KEYS[K.answered], answered_field, cjson.encode({choice, pts, elapsed}))
if pts > 0 then
  total = redis.call('HINCRBY', KEYS[K.totals], uid, pts)
  redis.call('ZADD', KEYS[K.board], board_score(total, math.max(0, now - start)), uid)
  redis.call('SADD', KEYS[K.scored], uid)
  redis.call('SET', KEYS[K.dirty], 1)
end
if i == n - 1 then
  redis.call('HSET', KEYS[K.serve], uid, cjson.encode({c, serve_ms, 1}))
end
local reply = {i, choice, key, correct and 1 or 0, elapsed > limit and 1 or 0, pts, total,
  tonumber(redis.call('GET', KEYS[K.seq])) or 0}
redis.call('HSET', KEYS[K.subs], sub_field, cjson.encode(reply))
refresh()
reply[9] = step_back
return {'ok', unpack(reply)}

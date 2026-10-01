-- AI-ASSISTED: create_quiz of docs/spec/redis.md §3: validate the shape, then write meta, key and seq.
-- ARGV: questionIds (JSON array), answer key (JSON array), timeLimitMs, windowMs, ttlMs.
local MAX_MS, MAX_QUESTIONS = 3600000, 100

local function int_in(value, low, high)
  local n = tonumber(value)
  return n ~= nil and n == math.floor(n) and n >= low and n <= high and n or nil
end

if redis.call('EXISTS', KEYS[K.meta]) == 1 then
  return {'INVALID_STATE'}
end
local ok_ids, ids = pcall(cjson.decode, ARGV[1])
local ok_key, answers = pcall(cjson.decode, ARGV[2])
local limit, window = int_in(ARGV[3], 1, MAX_MS), int_in(ARGV[4], 1, MAX_MS)
if not (ok_ids and ok_key and limit and window) or type(ids) ~= 'table'
    or type(answers) ~= 'table' or #ids < 1 or #ids > MAX_QUESTIONS or #answers ~= #ids then
  return {'INVALID_MESSAGE'}
end
local seen = {}
for i = 1, #ids do
  if type(ids[i]) ~= 'string' or seen[ids[i]] or not int_in(answers[i], 0, 3) then
    return {'INVALID_MESSAGE'}
  end
  seen[ids[i]] = true
end

local now = now_ms()
redis.call('HSET', KEYS[K.meta], 'questionCount', #ids, 'timeLimitMs', limit,
  'windowMs', window, 'startMs', now, 'deadlineMs', now + window, 'questionIds', ARGV[1])
for i = 1, #ids do
  redis.call('HSET', KEYS[K.key], i - 1, answers[i])
end
redis.call('SET', KEYS[K.seq], 0)
refresh(ARGV[5])
return {'ok', now, now + window}

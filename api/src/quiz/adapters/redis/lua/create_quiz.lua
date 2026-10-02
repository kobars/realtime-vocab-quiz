-- AI-ASSISTED: create_quiz of docs/spec/redis.md §3: validate the shape, then write meta, key and seq.
-- ARGV: questionIds (JSON array), answer key (JSON array of integers), timeLimitMs, windowMs,
-- bankQuizId (the question bank's quiz that it plays), hostHash (the host token's SHA-256 of a
-- self-hosted quiz, else empty).
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
local bank = ARGV[5]
if not (ok_ids and ok_key and limit and window and bank and bank ~= '') or type(ids) ~= 'table'
    or type(answers) ~= 'table' or #ids < 1 or #ids > MAX_QUESTIONS or #answers ~= #ids then
  return {'INVALID_MESSAGE'}
end
local seen, choices = {}, {}
for i = 1, #ids do
  -- A JSON number only: tonumber() alone would let "0x2" or " 1" through and store the string.
  choices[i] = type(answers[i]) == 'number' and int_in(answers[i], 0, 3)
  if type(ids[i]) ~= 'string' or seen[ids[i]] or not choices[i] then
    return {'INVALID_MESSAGE'}
  end
  seen[ids[i]] = true
end

local now = now_ms()
redis.call('HSET', KEYS[K.meta], 'questionCount', #ids, 'timeLimitMs', limit,
  'windowMs', window, 'startMs', now, 'deadlineMs', now + window, 'questionIds', ARGV[1],
  'bankQuizId', bank)
if ARGV[6] and ARGV[6] ~= '' then
  redis.call('HSET', KEYS[K.meta], 'hostHash', ARGV[6])
end
for i = 1, #ids do
  redis.call('HSET', KEYS[K.key], i - 1, string.format('%d', choices[i]))
end
redis.call('SET', KEYS[K.seq], 0)
refresh()
return {'ok', now, now + window}

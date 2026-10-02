-- AI-ASSISTED: hold_hosted of docs/spec/redis.md §3: count a self-hosted quiz unless the cap is reached.
-- KEYS[1] is quiz:hosted, shared by every quiz, not a quiz's keys. ARGV: quizId, windowMs, cap.
-- A member is scored by when it stops counting (now + windowMs); the expired ones go first.
local now = now_ms()
local window, cap = tonumber(ARGV[2]), tonumber(ARGV[3])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now)
if not redis.call('ZSCORE', KEYS[1], ARGV[1]) and redis.call('ZCARD', KEYS[1]) >= cap then
  return {'full'}
end
redis.call('ZADD', KEYS[1], now + window, ARGV[1])
-- The key lives until its last member stops counting: a shorter window, after a change of the
-- setting, must not cut the longer ones short.
local last = redis.call('ZRANGE', KEYS[1], -1, -1, 'WITHSCORES')
redis.call('PEXPIREAT', KEYS[1], last[2])
return {'ok'}

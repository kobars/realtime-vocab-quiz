-- AI-ASSISTED: read_standings of docs/spec/redis.md §3: every standings read at one seq.
-- ARGV: offset, limit (0: the broadcast rows; -1: no rows), topN, fullListMax, then user ids. Returns ok, seq,
-- playerCount, onlineCount, status, the rows, then per user {rank, total} or nil. Writes nothing.
-- The status is ended once quiz_ended is announced or the deadline passed: a host mark alone is not
-- durable yet, and clients act on ended for good (redis.md §3.1).
local meta = redis.call('HMGET', KEYS[K.meta], 'deadlineMs', 'endSeq')
if not meta[1] then
  return {'QUIZ_NOT_FOUND'}
end
local offset, limit = tonumber(ARGV[1]), tonumber(ARGV[2])
local count = redis.call('ZCARD', KEYS[K.board])
local rows = {}
if limit >= 0 then
  local last = limit == 0 and frame_last(count, tonumber(ARGV[3]), tonumber(ARGV[4]))
    or offset + limit - 1
  rows = standing_rows(offset, last)
end
local status = (meta[2] or now_ms() >= tonumber(meta[1])) and 'ended' or 'open'
local asked = {}
for n = 5, #ARGV do
  local uid = ARGV[n]
  local rank = redis.call('ZRANK', KEYS[K.board], uid)
  asked[n - 4] = rank and {rank + 1, tonumber(redis.call('HGET', KEYS[K.totals], uid))} or false
end
return {'ok', tonumber(redis.call('GET', KEYS[K.seq])) or 0, count,
  redis.call('HLEN', KEYS[K.present]), status, rows, asked}

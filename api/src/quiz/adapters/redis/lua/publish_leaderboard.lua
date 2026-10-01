-- AI-ASSISTED: publish_leaderboard of docs/spec/redis.md §3 and §5: the dirty gate and tick token.
-- ARGV: nodeId, tickMs, topN, fullListMax. At most one frame per tick window across all nodes, and only while dirty;
-- INCR seq and PUBLISH happen here together, so seq grows by 1 per broadcast (C2).
local tick_ms, top_n, full_list_max = tonumber(ARGV[2]), tonumber(ARGV[3]), tonumber(ARGV[4])
local meta = redis.call('HMGET', KEYS[K.meta], 'deadlineMs', 'endedMs', 'endSeq')
if not meta[1] then
  return {'QUIZ_NOT_FOUND'}
end
if meta[2] or now_ms() >= tonumber(meta[1]) then
  return {'ended', meta[3] or false}
end
local ttl = redis.call('PTTL', KEYS[K.tick])
if ttl ~= -2 then
  return {'busy', math.max(ttl, 1)}
end
if redis.call('DEL', KEYS[K.dirty]) == 0 then
  return {'clean'}
end

redis.call('SET', KEYS[K.tick], ARGV[1], 'NX', 'PX', tick_ms)
local seq = redis.call('INCR', KEYS[K.seq])
local count = redis.call('ZCARD', KEYS[K.board])
local ranks = {}
if count > full_list_max then  -- each scorer outside the top N gets its rank from this frame
  for _, uid in ipairs(redis.call('SMEMBERS', KEYS[K.scored])) do
    local rank = redis.call('ZRANK', KEYS[K.board], uid)
    if rank and rank >= top_n then
      ranks[#ranks + 1] = {uid, rank + 1, tonumber(redis.call('HGET', KEYS[K.totals], uid))}
    end
  end
end
publish_frame({v = 1, type = 'leaderboard', seq = seq, rebase = false, playerCount = count,
  onlineCount = redis.call('HLEN', KEYS[K.present])}, standing_rows(0, frame_last(count, top_n, full_list_max)), ranks)
redis.call('DEL', KEYS[K.scored])
refresh()
return {'published', seq}

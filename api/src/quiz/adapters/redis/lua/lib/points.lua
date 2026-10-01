-- AI-ASSISTED: the integer scoring rule of docs/spec/domain.md §4, the only Lua copy of it.
-- Points for a first answer: 0 if wrong or late (e > T), else 100 + (50 * (T - e)) // T.
local function points(correct, elapsed_ms, time_limit_ms)
  local e = math.max(0, elapsed_ms)
  if not correct or e > time_limit_ms then
    return 0
  end
  return 100 + math.floor(50 * (time_limit_ms - e) / time_limit_ms)
end

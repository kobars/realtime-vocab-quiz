# AI-ASSISTED: lua/lib/points.lua, as the loader prepends it, against the Python scoring rule.
import pytest
from redis.asyncio import Redis

from quiz.adapters.redis.scripts import SCORING_LIBS, compose
from quiz.domain.scoring import score_answer

# Every elapsed value from -1,000 (a clock step back) to T + 1, in one script run per limit.
BODY = """
local t, out = tonumber(ARGV[1]), {}
for e = -1000, t + 1 do
  out[#out + 1] = points(true, e, t)
end
out[#out + 1] = points(false, 0, t)
return out
"""


@pytest.mark.parametrize("limit_ms", [1, 3, 7, 1000, 20_000])
async def test_lua_points_match_python_for_every_elapsed(
    redis_client: Redis, limit_ms: int
) -> None:
    lua = await redis_client.eval(compose(BODY, SCORING_LIBS["score_answer"]), 0, limit_ms)
    python = [
        score_answer(correct=True, elapsed_ms=e, time_limit_ms=limit_ms)
        for e in range(-1000, limit_ms + 2)
    ]
    assert lua == [*python, 0]

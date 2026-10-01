# AI-ASSISTED: the composition root on Redis: the start hook loads every Lua script.
import hashlib

from redis.asyncio import Redis

from quiz.adapters.redis.scripts import SCRIPTS, source
from quiz.config import Settings
from quiz.main import create_app


async def test_start_hook_loads_every_script(redis_url: str) -> None:
    shas = [hashlib.sha1(source(name).encode()).hexdigest() for name in SCRIPTS]  # noqa: S324
    async with Redis.from_url(redis_url) as probe:
        await probe.script_flush()
        app = create_app(Settings(store="redis", redis_url=redis_url))
        async with app.router.lifespan_context(app):
            assert await probe.script_exists(*shas) == [True] * len(shas)

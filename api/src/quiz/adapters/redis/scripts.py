# AI-ASSISTED: the Lua script loader: SCRIPT LOAD at startup, EVALSHA, one reload on NOSCRIPT.
"""Every quiz script is ``lib/quiz.lua``, then the libraries it needs, then its own body."""

from collections.abc import Iterable, Sequence
from importlib.resources import files

from redis.asyncio import Redis
from redis.exceptions import NoScriptError

_LUA = files("quiz.adapters.redis") / "lua"
SCRIPTS = ("create_quiz", "join")
SCORING_LIBS: dict[str, tuple[str, ...]] = {"score_answer": ("points",)}

type Reply = list[str | int | None]


def compose(body: str, libs: Iterable[str] = ()) -> str:
    """Put ``lib/quiz.lua``, then each library (``points`` for a script that scores), first."""
    parts = [(_LUA / "lib" / f"{lib}.lua").read_text() for lib in ("quiz", *libs)]
    return "\n".join([*parts, body])


def source(name: str) -> str:
    return compose((_LUA / f"{name}.lua").read_text(), SCORING_LIBS.get(name, ()))


class Scripts:
    def __init__(self, client: Redis) -> None:
        self._client = client
        self._shas: dict[str, str] = {}

    async def load(self) -> None:
        """SCRIPT LOAD every script; run at startup and again after a NOSCRIPT."""
        for name in SCRIPTS:
            self._shas[name] = await self._client.script_load(source(name))

    async def call(self, name: str, keys: Sequence[str], *args: str | int) -> Reply:
        """EVALSHA the script; on NOSCRIPT (Redis restarted) reload all scripts and retry once."""
        try:
            reply: Reply = await self._client.evalsha(self._shas[name], len(keys), *keys, *args)
        except NoScriptError:
            await self.load()
            reply = await self._client.evalsha(self._shas[name], len(keys), *keys, *args)
        return reply

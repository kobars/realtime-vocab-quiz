# AI-ASSISTED: the Lua script loader: SCRIPT LOAD at startup, EVALSHA, one reload on NOSCRIPT.
"""Every quiz script is the key constants, ``lib/quiz.lua``, its libraries, then its body."""

from collections.abc import Iterable, Sequence
from importlib.resources import files

from redis.asyncio import Redis
from redis.exceptions import NoScriptError

from quiz.adapters.redis.keys import NO_QUIZ_TTL, QUIZ_TTL_MS, TICK_MS, QuizKeys
from quiz.contracts.messages import FULL_LIST_MAX, TOP_N

_LUA = files("quiz.adapters.redis") / "lua"
# Every .lua file beside lib/ is one script, named after its file.
SCRIPTS = tuple(sorted(f.name.removesuffix(".lua") for f in _LUA.iterdir() if f.is_file()))
SCORING_LIBS: dict[str, tuple[str, ...]] = {"score_answer": ("points",)}

type Reply = list[str | int | None]


def _constants() -> str:
    """``K``, ``DATA_KEYS`` and the constants for Lua, from keys.py and the contracts."""
    index = {name: i for i, name in enumerate(QuizKeys._fields, 1)}
    k = ", ".join(f"{name} = {i}" for name, i in index.items())
    data = ", ".join(str(i) for name, i in index.items() if name not in NO_QUIZ_TTL)
    names = "QUIZ_TTL_MS, TICK_MS, FULL_LIST_MAX, TOP_N"
    values = f"{QUIZ_TTL_MS}, {TICK_MS}, {FULL_LIST_MAX}, {TOP_N}"
    return f"local K = {{{k}}}\nlocal DATA_KEYS = {{{data}}}\nlocal {names} = {values}"


def compose(body: str, libs: Iterable[str] = ()) -> str:
    """Put the constants, ``lib/quiz.lua``, then each library (``points`` to score), first."""
    parts = [(_LUA / "lib" / f"{lib}.lua").read_text() for lib in ("quiz", *libs)]
    return "\n".join([_constants(), *parts, body])


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

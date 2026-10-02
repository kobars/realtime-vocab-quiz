# AI-ASSISTED: the Lua script loader: SCRIPT LOAD at startup, EVALSHA, a script reload on NOSCRIPT.
"""Every quiz script is the key constants, ``lib/quiz.lua``, its libraries, then its body.

The sources are composed once, at import, so recovering from ``NOSCRIPT`` reads no file."""

from collections.abc import Iterable, Sequence
from importlib.resources import files
from importlib.resources.abc import Traversable

from redis.asyncio import Redis
from redis.exceptions import NoScriptError

from quiz.adapters.redis.keys import NO_QUIZ_TTL, QuizKeys
from quiz.ports.store import QUIZ_TTL_MS

_LUA = files("quiz.adapters.redis") / "lua"
REFRESH_MARGIN_MS = 60_000  # how far the meta TTL drops before a write re-expires every data key


def script_names(folder: Traversable) -> tuple[str, ...]:
    """Every .lua file beside lib/ is one script, named after its file; other files are not."""
    lua = (f.name for f in folder.iterdir() if f.is_file() and f.name.endswith(".lua"))
    return tuple(sorted(name.removesuffix(".lua") for name in lua))


SCRIPTS = script_names(_LUA)
SCORING_LIBS: dict[str, tuple[str, ...]] = {"score_answer": ("points",)}

type Reply = list[str | int | None]


def _constants() -> str:
    """``K``, ``DATA_KEYS``, ``QUIZ_TTL_MS`` and ``REFRESH_MARGIN_MS`` for Lua, from keys.py,
    the store port and this module.

    The standings limits are settings, not constants: the store passes them through ARGV."""
    index = {name: i for i, name in enumerate(QuizKeys._fields, 1)}
    k = ", ".join(f"{name} = {i}" for name, i in index.items())
    data = ", ".join(str(i) for name, i in index.items() if name not in NO_QUIZ_TTL)
    ttl = f"local QUIZ_TTL_MS, REFRESH_MARGIN_MS = {QUIZ_TTL_MS}, {REFRESH_MARGIN_MS}"
    return f"local K = {{{k}}}\nlocal DATA_KEYS = {{{data}}}\n{ttl}"


def compose(body: str, libs: Iterable[str] = ()) -> str:
    """Put the constants, ``lib/quiz.lua``, then each library (``points`` to score), first."""
    parts = [(_LUA / "lib" / f"{lib}.lua").read_text() for lib in ("quiz", *libs)]
    return "\n".join([_constants(), *parts, body])


def source(name: str) -> str:
    return compose((_LUA / f"{name}.lua").read_text(), SCORING_LIBS.get(name, ()))


SOURCES = {name: source(name) for name in SCRIPTS}


class Scripts:
    def __init__(self, client: Redis) -> None:
        self._client = client
        self._shas: dict[str, str] = {}

    async def load(self) -> None:
        """SCRIPT LOAD every script; run at startup."""
        for name, text in SOURCES.items():
            self._shas[name] = await self._client.script_load(text)

    async def call(
        self, name: str, keys: Sequence[str], *args: str | int, on: Redis | None = None
    ) -> Reply:
        """EVALSHA the script (on the client ``on`` if given); on NOSCRIPT (Redis restarted)
        load that script alone again and retry once."""
        client = on or self._client
        try:
            reply: Reply = await client.evalsha(self._shas[name], len(keys), *keys, *args)
        except NoScriptError:
            self._shas[name] = await self._client.script_load(SOURCES[name])
            reply = await client.evalsha(self._shas[name], len(keys), *keys, *args)
        return reply

# AI-ASSISTED: the redis-py errors that mean the store cannot serve now, raised as the built-ins.
"""Redis unreachable, slow, or refusing writes (a read-only replica, ``maxmemory`` with
``noeviction``, a failed AOF or RDB write) leaves as the built-in ``ConnectionError`` or
``TimeoutError``, which callers answer with ``UNAVAILABLE`` or HTTP 503 and need no redis import
for. Any other ``ResponseError``, a script defect say, passes through as a fault."""

from collections.abc import Iterator
from contextlib import contextmanager

from redis import exceptions as redis_errors

WRITE_REFUSALS = (redis_errors.ReadOnlyError, redis_errors.OutOfMemoryError)
MISCONF = "MISCONF "  # redis-py has no class for it: its ResponseError keeps the error code


@contextmanager
def reachable() -> Iterator[None]:
    try:
        yield
    except redis_errors.TimeoutError as error:
        raise TimeoutError(str(error)) from error
    except (redis_errors.ConnectionError, *WRITE_REFUSALS) as error:
        raise ConnectionError(str(error)) from error
    except redis_errors.ResponseError as error:
        if not str(error).startswith(MISCONF):
            raise
        raise ConnectionError(str(error)) from error

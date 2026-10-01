# AI-ASSISTED: the clock port; the in-memory store takes one, the Redis store reads TIME instead.
from typing import Protocol


class Clock(Protocol):
    def __call__(self) -> int:
        """Return the current time in integer milliseconds."""
        ...

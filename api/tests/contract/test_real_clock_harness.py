# AI-ASSISTED: the real-clock harness of the store contract waits out the Redis clock's skew.
import time

from tests.contract.conftest import CLOCK_SKEW_MS, real_advance


async def test_a_real_advance_sleeps_past_the_step_by_the_skew_allowance() -> None:
    start = time.monotonic()
    await real_advance(50)
    assert (time.monotonic() - start) * 1000 >= 50 + CLOCK_SKEW_MS / 2  # the host sleeps longer


async def test_a_real_advance_back_does_not_wait() -> None:
    start = time.monotonic()
    await real_advance(-1)
    assert (time.monotonic() - start) * 1000 < CLOCK_SKEW_MS / 2

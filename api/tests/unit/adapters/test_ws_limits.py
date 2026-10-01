# AI-ASSISTED: the client address behind the default trusted proxies and the per-address limit.
from quiz.adapters.ws.limits import AddressRateLimiter, client_ip
from quiz.config import Settings


def test_a_private_range_client_cannot_pick_its_address_with_the_default_proxies() -> None:
    proxies = Settings().trusted_proxies
    forged = ["203.0.113.1, 192.168.1.20"]  # a made-up client, then a made-up private proxy
    assert client_ip("172.18.0.2", forged, proxies) == "172.18.0.2"
    assert client_ip("192.168.1.20", ["203.0.113.1"], proxies) == "192.168.1.20"
    assert client_ip("127.0.0.1", forged, proxies) == "192.168.1.20"  # nginx on the local host


def test_each_address_gets_its_own_burst_then_refills_at_the_rate() -> None:
    now = [0]
    limit = AddressRateLimiter(2, 3, lambda: now[0])  # 2 per second, burst 3
    assert [limit.allow("10.0.0.1") for _ in range(4)] == [True, True, True, False]
    assert limit.allow("10.0.0.2")  # another address keeps its whole burst
    now[0] += 499
    assert not limit.allow("10.0.0.1")
    now[0] += 1  # half a second: one token back
    assert limit.allow("10.0.0.1")
    assert not limit.allow("10.0.0.1")


def test_a_bucket_that_has_refilled_is_dropped() -> None:
    now = [0]
    limit = AddressRateLimiter(2, 3, lambda: now[0])
    limit.allow("10.0.0.1")
    now[0] += 400
    limit.allow("10.0.0.2")
    now[0] += 99  # 10.0.0.1 is a hair short of full: kept
    limit.allow("10.0.0.3")
    assert list(limit.buckets) == ["10.0.0.1", "10.0.0.2", "10.0.0.3"]
    now[0] += 1  # 10.0.0.1 is full again, the same as a new bucket
    limit.allow("10.0.0.3")
    assert list(limit.buckets) == ["10.0.0.2", "10.0.0.3"]

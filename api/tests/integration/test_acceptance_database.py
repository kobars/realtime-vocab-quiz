# AI-ASSISTED: the Redis acceptance tests flush their database, so they get one of their own and
# refuse it when it holds keys.
import uuid
from urllib.parse import urlparse

import pytest
from redis import Redis


def test_acceptance_tests_get_database_15_never_the_one_redis_url_names(
    request: pytest.FixtureRequest, redis_url: str
) -> None:
    url = request.getfixturevalue("acceptance_redis_url")
    assert url == urlparse(redis_url)._replace(path="/15").geturl() != redis_url


def test_acceptance_tests_refuse_a_database_that_holds_keys(
    request: pytest.FixtureRequest, redis_url: str
) -> None:
    probe = f"test:{uuid.uuid4().hex}:probe"
    with Redis.from_url(urlparse(redis_url)._replace(path="/15").geturl()) as client:
        client.set(probe, 1)
        try:
            with pytest.raises(pytest.fail.Exception, match="database 15 of the test Redis"):
                request.getfixturevalue("acceptance_redis_url")
            assert client.exists(probe)  # refused before any flush
        finally:
            client.delete(probe)

# AI-ASSISTED: an in-process app on a free port for the load tools' tests.
import threading
import time
from collections.abc import Iterator

import pytest
import uvicorn
from pydantic import SecretStr

from bots import parse
from quiz.config import Settings
from quiz.main import create_app


@pytest.fixture
def app_url() -> Iterator[str]:
    """The app's base URL; its mock admin token is ``load-token``, its origin the bots' default."""
    token = SecretStr("load-token")
    origins = (parse([]).origin,)
    app = create_app(Settings(admin_mock=True, admin_token=token, allowed_origins=origins))
    server = uvicorn.Server(uvicorn.Config(app, host="127.0.0.1", port=0, log_level="warning"))
    thread = threading.Thread(target=server.run)
    thread.start()
    while not server.started:
        assert thread.is_alive()  # noqa: S101
        time.sleep(0.01)
    yield f"http://127.0.0.1:{server.servers[0].sockets[0].getsockname()[1]}"
    server.should_exit = True
    thread.join()

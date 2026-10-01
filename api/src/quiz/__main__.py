# AI-ASSISTED: the server entry point of the image: one node on port 8000.
"""``python -m quiz`` runs one node: the module app on uvicorn, with the heartbeat and the
transport limits from the settings."""

import uvicorn

from quiz.adapters.ws.heartbeat import server_config
from quiz.main import module_app, services_of

HOST, PORT = "0.0.0.0", 8000  # noqa: S104 - all interfaces of the container


def main() -> None:
    app = module_app()
    uvicorn.Server(server_config(app, services_of(app).settings, HOST, PORT)).run()


if __name__ == "__main__":
    main()

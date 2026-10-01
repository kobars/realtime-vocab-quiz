# AI-ASSISTED: the server entry point: one node, on port 8000 in the image or as the flags say.
"""``python -m quiz`` runs one node: the module app on uvicorn, with the heartbeat and the
transport limits from the settings. ``--host`` and ``--port`` move it, for example to the API
node that the Vite dev server proxies to (``make dev-api``)."""

import argparse
from collections.abc import Sequence

import uvicorn

from quiz.adapters.ws.heartbeat import server_config
from quiz.main import module_app, services_of

HOST, PORT = "0.0.0.0", 8000  # noqa: S104 - all interfaces of the container


def main(argv: Sequence[str] | None = None) -> None:
    parser = argparse.ArgumentParser(prog="python -m quiz")
    parser.add_argument("--host", default=HOST)
    parser.add_argument("--port", type=int, default=PORT)
    args = parser.parse_args(argv)
    app = module_app()
    uvicorn.Server(server_config(app, services_of(app).settings, args.host, args.port)).run()


if __name__ == "__main__":
    main()

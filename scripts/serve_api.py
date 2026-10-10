"""Run one API worker with a short HTTP drain before the eight-second MCP cleanup.

Uvicorn drains HTTP connections before invoking lifespan shutdown. Its default
unbounded wait would defeat the application deadline on SIGTERM. Allow at most
0.5 seconds here, leaving room for MCP cancellation repair and child teardown.
"""

import uvicorn

from veridex.config import settings


def main():
    uvicorn.run(
        "veridex.api.app:app",
        host="0.0.0.0",
        port=settings.port,
        workers=1,
        lifespan="on",
        timeout_graceful_shutdown=0.5,
        log_level=settings.log_level.lower(),
    )


if __name__ == "__main__":
    main()

"""Packaged, loopback-only desktop sidecar with an authenticated lifecycle."""
import os

os.environ["ENVIRONMENT"] = "desktop"

import uvicorn
from backend.app.main import app
from backend.app.desktop_lifecycle import install_desktop_lifecycle

if __name__ == "__main__":
    server = uvicorn.Server(uvicorn.Config(
        app, host="127.0.0.1", port=int(os.environ.get("PORT", "8000")),
        log_level="info", access_log=False, timeout_graceful_shutdown=10,
    ))
    install_desktop_lifecycle(app, server)
    server.run()

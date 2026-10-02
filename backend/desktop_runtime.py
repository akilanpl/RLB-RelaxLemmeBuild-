"""Packaged desktop runtime sidecar entrypoint."""

import os

os.environ.setdefault("ENVIRONMENT", "development")
os.environ.setdefault("HOST", "127.0.0.1")

import uvicorn

from backend.app.main import app

if __name__ == "__main__":
    uvicorn.run(
        app,
        host="127.0.0.1",
        port=int(os.environ.get("PORT", "8000")),
        log_level="info",
        access_log=False,
    )

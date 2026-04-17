"""Module: main.py

VQMS FastAPI application entry point.

Thin wrapper that delegates to app/factory.py for the full
application setup. Keeps the uvicorn entry point at main:app.

Run with:
    uv run uvicorn main:app --reload --port 8000

Then visit:
    http://localhost:8000/docs   (Swagger UI)
    http://localhost:8000/redoc  (ReDoc)
    http://localhost:8000/health (Health check)
"""

from __future__ import annotations

import sys

# Ensure both root (for config/) and src/ are importable
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from utils.logger import LoggingSetup

# Configure structured logging before anything else
LoggingSetup.configure()

from app import create_app  # noqa: E402

app = create_app()

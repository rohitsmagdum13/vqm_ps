"""Package: app

VQMS FastAPI application bootstrap — split into focused modules.

Provides create_app() which assembles the full FastAPI application
with lifespan hooks, middleware, routes, and OpenAPI configuration.

Re-exports so ``from app import create_app`` works.
"""

from app.factory import create_app

__all__ = ["create_app"]

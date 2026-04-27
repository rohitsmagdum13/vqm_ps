"""Module: run_reviewer_mcp.py

Launcher for the Path C Reviewer Copilot MCP server.

Mirrors main.py: prepends both the project root and src/ to sys.path
so internal imports (`from db.connection import ...`, etc.) resolve
the same way they do under the FastAPI process.

Run with:
    uv run python run_reviewer_mcp.py

The MCP server then listens on http://127.0.0.1:8765/mcp by default
(configurable via MCP_REVIEWER_HOST and MCP_REVIEWER_PORT in .env).
"""

from __future__ import annotations

import sys

# Same path setup as main.py — keep them in lockstep so identical
# import paths work in both processes.
sys.path.insert(0, ".")
sys.path.insert(0, "src")

from mcp_servers.reviewer.server import main  # noqa: E402

if __name__ == "__main__":
    sys.exit(main())

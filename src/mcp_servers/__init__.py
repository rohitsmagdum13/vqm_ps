"""Package: mcp_servers

MCP servers exposed by VQMS for agent-driven copilots.

Each server runs as a separate Python process and presents a tool
surface that an MCP client (LangGraph ReAct agent in FastAPI, Claude
Desktop, etc.) can discover and call.

Servers in this package:
- reviewer/ — Path C reviewer copilot (read-only investigation tools).
"""

"""
Minimal remote MCP server with Streamable HTTP.

Tools:
  - ping
  - add
  - echo

Run locally:
  uvicorn minimal_mcp.server:app --host 0.0.0.0 --port 8000

MCP endpoint:
  http://localhost:8000/mcp/
"""

from __future__ import annotations

import os

from mcp.server.fastmcp import FastMCP
from starlette.applications import Starlette
from starlette.requests import Request
from starlette.responses import JSONResponse, PlainTextResponse
from starlette.routing import Mount, Route

mcp = FastMCP(
    "minimal-mcp",
    stateless_http=True,
)

# Optional path secret so the URL is not guessable
MCP_SECRET = os.environ.get("MCP_PATH_SECRET", "").strip()
MCP_PATH = f"/mcp/{MCP_SECRET}/" if MCP_SECRET else "/mcp/"


@mcp.tool()
def ping() -> str:
    """Health check tool. Returns pong."""
    return "pong"


@mcp.tool()
def add(a: float, b: float) -> float:
    """Add two numbers and return the sum."""
    return a + b


@mcp.tool()
def echo(message: str) -> str:
    """Echo a message back to the caller."""
    return message


mcp_app = mcp.streamable_http_app()


async def health(_: Request) -> PlainTextResponse:
    return PlainTextResponse("ok")


async def root(_: Request) -> JSONResponse:
    return JSONResponse(
        {
            "name": "minimal-mcp-server",
            "mcp_path": MCP_PATH.rstrip("/") or "/mcp",
            "tools": ["ping", "add", "echo"],
        }
    )


app = Starlette(
    routes=[
        Route("/", root),
        Route("/health", health),
        Mount(MCP_PATH.rstrip("/") + "/", app=mcp_app),
        Mount(MCP_PATH.rstrip("/"), app=mcp_app),
    ],
)

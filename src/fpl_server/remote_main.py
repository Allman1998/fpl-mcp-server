import contextlib
import os

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from .mcp_tools import mcp
from .web import app as auth_app

PORT = int(os.environ.get("PORT", "10000"))
PATH_SECRET = os.environ.get("MCP_PATH_SECRET", "").strip().strip("/")

if not PATH_SECRET:
    raise RuntimeError("MCP_PATH_SECRET must be set")

try:
    from mcp.server.transport_security import TransportSecuritySettings
    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
except (ImportError, AttributeError):
    pass

mcp.settings.stateless_http = True
mcp.settings.streamable_http_path = "/mcp"
mcp_http_app = mcp.streamable_http_app()

async def health(_request):
    return JSONResponse({"status": "ok"})

@contextlib.asynccontextmanager
async def lifespan(_app):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(mcp.session_manager.run())
        yield

routes = [
    Route("/health", health, methods=["GET"]),
    Mount(f"/mcp/{PATH_SECRET}", app=mcp_http_app),
    Mount("/", app=auth_app),
]

app = Starlette(routes=routes, lifespan=lifespan)

if __name__ == "__main__":
    uvicorn.run(app, host="0.0.0.0", port=PORT, log_level="info")
import contextlib
import os

import uvicorn
from starlette.applications import Starlette
from starlette.responses import JSONResponse, RedirectResponse
from starlette.routing import Mount, Route

from .mcp_tools import mcp
from .web import app as auth_app
from .oauth import FPLOAuthProvider

PORT = int(os.environ.get("PORT", "10000"))
PATH_SECRET = os.environ.get("MCP_PATH_SECRET", "").strip().strip("/")

if not PATH_SECRET:
    raise RuntimeError("MCP_PATH_SECRET must be set")

BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    f"https://fpl-mcp-server-kaol.onrender.com",
).rstrip("/")

OAUTH_ISSUER = f"{BASE_URL}/mcp/{PATH_SECRET}"

oauth_provider = FPLOAuthProvider(OAUTH_ISSUER)

try:
    from mcp.server.transport_security import TransportSecuritySettings

    mcp.settings.transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )
except (ImportError, AttributeError):
    pass

mcp.settings.stateless_http = True
mcp.settings.streamable_http_path = "/"

mcp_http_app = mcp.streamable_http_app()


async def health(_request):
    return JSONResponse({"status": "ok"})


async def oauth_metadata(request):
    return JSONResponse(
        {
            "issuer": OAUTH_ISSUER,
            "authorization_endpoint": f"{OAUTH_ISSUER}/authorize",
            "token_endpoint": f"{OAUTH_ISSUER}/token",
            "registration_endpoint": f"{OAUTH_ISSUER}/register",
            "scopes_supported": ["read"],
            "response_types_supported": ["code"],
            "grant_types_supported": [
                "authorization_code",
                "refresh_token",
            ],
            "code_challenge_methods_supported": ["S256"],
            "token_endpoint_auth_methods_supported": ["none"],
        }
    )


async def login_complete(request):
    request_id = request.path_params["request_id"]

    session_id = request.query_params.get("session_id")

    if not session_id:
        return JSONResponse(
            {"error": "session_id_required"},
            status_code=400,
        )

    redirect_uri = oauth_provider.complete_fpl_login(
        request_id,
        session_id,
    )

    if not redirect_uri:
        return JSONResponse(
            {"error": "invalid_or_expired_request"},
            status_code=400,
        )

    return RedirectResponse(redirect_uri)


@contextlib.asynccontextmanager
async def lifespan(_app):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(
            mcp.session_manager.run()
        )
        yield


routes = [
    Route("/health", health, methods=["GET"]),
    Route(
        "/.well-known/oauth-authorization-server",
        oauth_metadata,
        methods=["GET"],
    ),
    Route(
        "/oauth/callback/{request_id}",
        login_complete,
        methods=["GET"],
    ),
    Mount(
        f"/mcp/{PATH_SECRET}",
        app=mcp_http_app,
    ),
    Mount(
        "/",
        app=auth_app,
    ),
]

app = Starlette(
    routes=routes,
    lifespan=lifespan,
)


if __name__ == "__main__":
    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",
    )
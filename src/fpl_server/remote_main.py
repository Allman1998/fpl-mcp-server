import contextlib
import os
import uuid

import uvicorn
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.applications import Starlette
from starlette.responses import JSONResponse, Response
from starlette.routing import Mount, Route

from mcp.server.auth import routes as mcp_auth_routes
from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.server.auth.settings import ClientRegistrationOptions

from . import mcp_tools
from .mcp_tools import mcp, oauth_provider
from .web import app as auth_app
from .auth import FPLAutomation
from .client import FPLClient
from .state import store


# ============================================================
# CONFIGURATION
# ============================================================

PORT = int(os.environ.get("PORT", "10000"))

PATH_SECRET = os.environ.get(
    "MCP_PATH_SECRET",
    "",
).strip().strip("/")

if not PATH_SECRET:
    raise RuntimeError("MCP_PATH_SECRET must be set")


PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    "https://fpl-mcp-server-kaol.onrender.com",
).rstrip("/")


MCP_PUBLIC_PATH = f"/mcp/{PATH_SECRET}"

MCP_PUBLIC_URL = (
    f"{PUBLIC_BASE_URL}{MCP_PUBLIC_PATH}"
)

OAUTH_ISSUER = MCP_PUBLIC_URL


# ============================================================
# MCP AUTH CONFIGURATION
# ============================================================

mcp._auth_server_provider = oauth_provider
mcp._token_verifier = ProviderTokenVerifier(
    oauth_provider
)


if mcp.settings.auth is not None:
    mcp.settings.auth.client_registration_options = (
        ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["read"],
            default_scopes=["read"],
        )
    )


# ============================================================
# PUBLIC OAUTH CLIENT COMPATIBILITY
#
# MCP SDK 1.28.1 does not advertise "none" in the OAuth
# discovery metadata even though public PKCE clients need it.
#
# Claude is a public OAuth client, so advertise "none".
# ============================================================

_original_build_metadata = (
    mcp_auth_routes.build_metadata
)


def _build_metadata_with_public_client(
    *args,
    **kwargs,
):
    metadata = _original_build_metadata(
        *args,
        **kwargs,
    )

    existing_methods = (
        metadata.token_endpoint_auth_methods_supported
        or []
    )

    if "none" not in existing_methods:
        metadata.token_endpoint_auth_methods_supported = [
            "none",
            *existing_methods,
        ]

    return metadata


mcp_auth_routes.build_metadata = (
    _build_metadata_with_public_client
)


# ============================================================
# OAUTH LOGIN REDIRECT
# ============================================================

_original_authorize = oauth_provider.authorize


async def _oauth_authorize(
    client,
    params,
):
    login_url = await _original_authorize(
        client,
        params,
    )

    login_url = login_url.replace(
        f"{PUBLIC_BASE_URL}/login/",
        f"{PUBLIC_BASE_URL}/oauth/login/",
        1,
    )

    return login_url


oauth_provider.authorize = _oauth_authorize


# ============================================================
# MCP TRANSPORT
#
# IMPORTANT:
# The public URL is mounted at:
#
#   /mcp/<secret>
#
# Therefore the MCP application itself must use "/" as its
# internal path.
# ============================================================

try:
    from mcp.server.transport_security import (
        TransportSecuritySettings,
    )

    transport_security = TransportSecuritySettings(
        enable_dns_rebinding_protection=False
    )

except (ImportError, AttributeError):
    transport_security = None


# IMPORTANT:
# In MCP 1.28.1 the streamable HTTP route is configured on FastMCP itself.
# The mounted public URL is /mcp/<secret>, so the inner app must use "/".
mcp.settings.streamable_http_path = "/"
mcp.settings.stateless_http = True
if transport_security is not None:
    mcp.settings.transport_security = transport_security

mcp_http_app = mcp.streamable_http_app()


# ============================================================
# PROTECTED RESOURCE METADATA
#
# Claude asks these URLs before OAuth registration:
#
# /.well-known/oauth-protected-resource
#
# /.well-known/oauth-protected-resource/mcp/<secret>
#
# They must resolve on the OUTER application because the
# resource is the public MCP URL.
# ============================================================

def protected_resource_metadata():
    return {
        "resource": MCP_PUBLIC_URL,
        "authorization_servers": [
            OAUTH_ISSUER
        ],
        "scopes_supported": [
            "read"
        ],
        "bearer_methods_supported": [
            "header"
        ],
    }



async def oauth_authorization_server_metadata(_request):
    """RFC 8414 authorization-server metadata (path-insertion URL)."""
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
            "token_endpoint_auth_methods_supported": [
                "none",
                "client_secret_post",
                "client_secret_basic",
            ],
            "code_challenge_methods_supported": ["S256"],
        }
    )


async def protected_resource_metadata_root(
    _request,
):
    return JSONResponse(
        protected_resource_metadata()
    )


async def protected_resource_metadata_mcp(
    _request,
):
    return JSONResponse(
        protected_resource_metadata()
    )


# ============================================================
# FPL LOGIN PAGE
# ============================================================

LOGIN_PAGE = """
<!DOCTYPE html>
<html lang="en">

<head>

<meta charset="utf-8">

<meta
    name="viewport"
    content="width=device-width, initial-scale=1"
>

<title>FPL Manager Login</title>

<style>

body {
    margin: 0;
    min-height: 100vh;
    display: grid;
    place-items: center;
    background: #e9ebe5;
    font-family: system-ui, sans-serif;
    color: #17211b;
}

main {
    width: min(90%, 420px);
    padding: 36px;
    border-radius: 24px;
    background: #f9f9f5;
    box-shadow: 0 25px 70px rgba(0,0,0,.15);
}

h1 {
    margin: 0 0 10px;
    font-size: 32px;
}

p {
    color: #68726c;
    line-height: 1.5;
}

label {
    display: block;
    margin-top: 18px;
    color: #68726c;
    font-size: 13px;
}

input {
    width: 100%;
    box-sizing: border-box;
    margin-top: 7px;
    padding: 13px;
    border: 1px solid #ccd1ca;
    border-radius: 10px;
    font-size: 16px;
}

button {
    width: 100%;
    margin-top: 24px;
    padding: 14px;
    border: 0;
    border-radius: 999px;
    background: #17211b;
    color: white;
    font-size: 15px;
    font-weight: 700;
    cursor: pointer;
}

.note {
    margin-top: 20px;
    font-size: 12px;
    color: #68726c;
}

.error {
    padding: 12px;
    border-radius: 10px;
    background: #f6dfdc;
    color: #8b332c;
}

</style>

</head>

<body>

<main>

<h1>Connect your FPL account</h1>

<p>
Sign in with your Fantasy Premier League credentials.
Your password is used only to authenticate with FPL.
</p>

{error}

<form method="post">

<label>

FPL email

<input
    type="email"
    name="email"
    autocomplete="username"
    required
>

</label>

<label>

FPL password

<input
    type="password"
    name="password"
    autocomplete="current-password"
    required
>

</label>

<button type="submit">
Connect FPL account
</button>

</form>

<div class="note">
This login is being requested by your FPL Manager
MCP connection.
</div>

</main>

</body>

</html>
"""


def login_error(
    message: str,
):
    return HTMLResponse(
        LOGIN_PAGE.replace(
            "{error}",
            f'<div class="error">{message}</div>',
        ),
        status_code=400,
    )


async def oauth_login_page(
    request,
):
    request_id = request.path_params[
        "request_id"
    ]

    pending = oauth_provider.pending.get(
        request_id
    )

    if not pending:
        return HTMLResponse(
            "<h1>Login request expired</h1>"
            "<p>Please reconnect the FPL Manager connector.</p>",
            status_code=400,
        )

    return HTMLResponse(
        LOGIN_PAGE.replace(
            "{error}",
            "",
        )
    )



async def oauth_login_status(request):
    """Poll FPL login progress for the OAuth flow."""
    request_id = request.path_params["request_id"]
    pending = oauth_provider.pending.get(request_id)
    if not pending:
        # may have completed and been popped
        return HTMLResponse(
            "<h1>Login request expired</h1>"
            "<p>Please reconnect the FPL Manager connector.</p>",
            status_code=400,
        )
    status = getattr(pending, "login_status", None) or "pending"
    if status == "pending":
        return HTMLResponse(
            """<!DOCTYPE html><html><head>
<meta charset="utf-8">
<meta http-equiv="refresh" content="2">
<title>Signing in…</title>
<style>
body{margin:0;min-height:100vh;display:grid;place-items:center;background:#e9ebe5;font-family:system-ui,sans-serif;color:#17211b}
main{padding:36px;border-radius:24px;background:#f9f9f5;box-shadow:0 25px 70px rgba(0,0,0,.15);text-align:center}
</style></head><body><main>
<h1>Signing in to FPL…</h1>
<p>This can take up to a minute. This page will update automatically.</p>
</main></body></html>"""
        )
    if status == "failed":
        msg = getattr(pending, "login_error", None) or "FPL authentication failed."
        return login_error(msg)
    if status == "success":
        session_id = getattr(pending, "login_session_id", None)
        if not session_id:
            return login_error(
                "OAuth request expired before authentication completed."
            )
        redirect_uri = oauth_provider.complete_fpl_login(
            request_id, session_id
        )
        if redirect_uri:
            return RedirectResponse(redirect_uri, status_code=302)
        return login_error(
            "OAuth request expired before authentication completed."
        )
    return login_error("Unexpected login state.")


async def oauth_login_submit(request):
    request_id = request.path_params["request_id"]

    pending = oauth_provider.pending.get(request_id)

    if not pending:
        return HTMLResponse(
            "<h1>Login request expired</h1>"
            "<p>Please reconnect the FPL Manager connector.</p>",
            status_code=400,
        )

    try:
        form = await request.form()
        email = (form.get("email") or "").strip()
        password = form.get("password") or ""
        if not email or not password:
            return login_error("Email and password are required.")

        # Mark pending login and run Playwright in the background so the
        # HTTP response is not killed by Render's request timeout.
        pending.login_status = "pending"
        pending.login_error = None
        pending.login_redirect = None

        import asyncio

        async def _run_login():
            try:
                auth = FPLAutomation(email, password)
                token = await asyncio.wait_for(
                    auth.login_and_get_token(),
                    timeout=90.0,
                )
                if not token:
                    pending.login_status = "failed"
                    pending.login_error = (
                        auth.failure_reason
                        or "FPL authentication failed."
                    )
                    return

                session_id = str(uuid.uuid4())
                client = FPLClient(store=store)
                client.set_api_token(token)
                await store.set_login_success(
                    request_id, session_id, client
                )
                mcp_tools._active_session_id = session_id
                # Defer complete_fpl_login until status page redirects,
                # so pending remains available for polling.
                pending.login_session_id = session_id
                pending.login_status = "success"
            except asyncio.TimeoutError:
                pending.login_status = "failed"
                pending.login_error = (
                    "FPL login timed out. Please try again."
                )
            except Exception as exc:
                pending.login_status = "failed"
                pending.login_error = (
                    f"FPL authentication failed: {exc}"
                )

        asyncio.create_task(_run_login())

        # Redirect to status page (auto-refreshes until done)
        return RedirectResponse(
            f"/oauth/login/{request_id}/status",
            status_code=302,
        )

    except Exception as exc:
        return login_error(
            f"FPL authentication failed: {exc}"
        )


# ============================================================
# HEALTH
# ============================================================

async def health(
    _request,
):
    return JSONResponse(
        {
            "status": "ok",
            "mcp": "available",
        }
    )


# ============================================================
# MCP GET
#
# Stateless Streamable HTTP clients use POST for MCP messages.
# ============================================================

async def mcp_get_not_supported(
    _request,
):
    return Response(
        status_code=405,
        headers={
            "Allow": "POST",
        },
    )


# ============================================================
# APPLICATION LIFESPAN
# ============================================================

@contextlib.asynccontextmanager
async def lifespan(
    _app,
):

    async with contextlib.AsyncExitStack() as stack:

        await stack.enter_async_context(
            mcp.session_manager.run()
        )

        yield



# ============================================================
# MCP PATH NORMALIZATION
#
# Clients and OAuth resource URLs use /mcp/<secret> (no trailing
# slash). FastMCP's Route("/") matches more reliably when the
# remaining path is "/". This middleware rewrites the exact
# non-trailing path to the trailing form before routing.
# ============================================================

class NormalizeMcpPathMiddleware:
    """Rewrite exact /mcp/<secret> -> /mcp/<secret>/ for routing."""

    def __init__(self, app):
        self.app = app
        self.target = MCP_PUBLIC_PATH
        self.target_slash = MCP_PUBLIC_PATH + "/"

    async def __call__(self, scope, receive, send):
        if scope.get("type") == "http":
            path = scope.get("path") or ""
            if path == self.target:
                # Mutate a copy of the scope
                scope = dict(scope)
                scope["path"] = self.target_slash
                if "raw_path" in scope:
                    scope["raw_path"] = (self.target_slash).encode("utf-8")
        await self.app(scope, receive, send)


# ============================================================
# ROUTES
# ============================================================

routes = [

    # Health
    Route(
        "/health",
        health,
        methods=["GET"],
    ),

    # Protected Resource Metadata - root fallback
    Route(
        "/.well-known/oauth-protected-resource",
        protected_resource_metadata_root,
        methods=["GET"],
    ),

    # Protected Resource Metadata - MCP path
    Route(
        f"/.well-known/oauth-protected-resource{MCP_PUBLIC_PATH}",
        protected_resource_metadata_mcp,
        methods=["GET"],
    ),

    # RFC 8414 path-insertion form (issuer has a path component):
    #   /.well-known/oauth-authorization-server/mcp/<secret>
    # Claude and other clients use this; the SDK only serves the
    # path-appended form under the mount.
    Route(
        f"/.well-known/oauth-authorization-server{MCP_PUBLIC_PATH}",
        oauth_authorization_server_metadata,
        methods=["GET"],
    ),

    # OAuth login UI
    Route(
        "/oauth/login/{request_id}",
        oauth_login_page,
        methods=["GET"],
    ),

    Route(
        "/oauth/login/{request_id}",
        oauth_login_submit,
        methods=["POST"],
    ),

    # MCP application (path normalized by NormalizeMcpPathMiddleware)
    Mount(
        MCP_PUBLIC_PATH + "/",
        app=mcp_http_app,
    ),

    # Existing web application
    Mount(
        "/",
        app=auth_app,
    ),
]


# ============================================================
# STARLETTE APPLICATION
# ============================================================

_starlette_app = Starlette(
    routes=routes,
    lifespan=lifespan,
)

# Normalize /mcp/<secret> -> /mcp/<secret>/ so FastMCP Route("/") matches
app = NormalizeMcpPathMiddleware(_starlette_app)


# ============================================================
# LOCAL EXECUTION
# ============================================================

if __name__ == "__main__":

    uvicorn.run(
        app,
        host="0.0.0.0",
        port=PORT,
        log_level="info",
    )
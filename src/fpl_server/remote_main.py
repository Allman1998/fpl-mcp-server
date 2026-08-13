import contextlib
import os
import uuid

import uvicorn
from fastapi import Form
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


async def oauth_login_submit(
    request,
    email: str = Form(...),
    password: str = Form(...),
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

    try:

        auth = FPLAutomation(
            email,
            password,
        )

        token = await auth.login_and_get_token()

        if not token:
            return login_error(
                auth.failure_reason
                or "FPL authentication failed."
            )

        session_id = str(uuid.uuid4())

        client = FPLClient(
            store=store,
        )

        client.set_api_token(token)

        await store.set_login_success(
            request_id,
            session_id,
            client,
        )

        mcp_tools._active_session_id = (
            session_id
        )

        redirect_uri = (
            oauth_provider.complete_fpl_login(
                request_id,
                session_id,
            )
        )

        if not redirect_uri:
            return login_error(
                "OAuth request expired before "
                "authentication completed."
            )

        return RedirectResponse(
            redirect_uri,
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
# External clients call POST /mcp/<secret> (no trailing slash).
# The FastMCP Streamable HTTP app registers Route("/") which
# matches the remaining path "/" after a trailing-slash Mount.
# This ASGI wrapper rewrites the path so both forms work.
# ============================================================

async def _mcp_root_asgi(scope, receive, send):
    """Forward exact /mcp/<secret> requests into the MCP app as path=/."""
    if scope["type"] != "http":
        await mcp_http_app(scope, receive, send)
        return

    # Rewrite so FastMCP's Route("/") matches the non-trailing public URL.
    new_scope = dict(scope)
    new_scope["path"] = "/"
    new_scope["raw_path"] = b"/"
    root = (scope.get("root_path") or "") + MCP_PUBLIC_PATH
    new_scope["root_path"] = root
    # Ensure path matching inside Starlette sees a root request
    if "path_info" in new_scope:
        new_scope["path_info"] = "/"
    await mcp_http_app(new_scope, receive, send)


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

    # MCP application.
    #
    # Because mcp_http_app uses streamable_http_path="/",
    # the mounted URL itself is the MCP endpoint.
    #
    # Starlette Mount path matching + Route("/") inside the SDK app only
    # reliably matches the trailing-slash form of the mount point. External
    # MCP clients (and OAuth resource identifiers) use the non-trailing
    # form. Serve both by mounting under the trailing-slash path and adding
    # an explicit passthrough Route for the exact non-trailing path.
    # Exact non-trailing path first (clients use this form)
    Route(
        MCP_PUBLIC_PATH,
        endpoint=_mcp_root_asgi,
    ),
    # Trailing-slash + all subpaths (OAuth routes, well-known, etc.)
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

app = Starlette(
    routes=routes,
    lifespan=lifespan,
)


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
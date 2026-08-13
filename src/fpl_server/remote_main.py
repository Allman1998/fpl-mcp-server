import contextlib
import os
import uuid

import uvicorn
from fastapi import Form
from fastapi.responses import HTMLResponse, RedirectResponse
from starlette.applications import Starlette
from starlette.responses import JSONResponse
from starlette.routing import Mount, Route

from mcp.server.auth.provider import ProviderTokenVerifier
from mcp.server.auth.settings import ClientRegistrationOptions

from . import mcp_tools
from .mcp_tools import mcp, oauth_provider
from .web import app as auth_app
from .auth import FPLAutomation
from .client import FPLClient
from .state import store


PORT = int(os.environ.get("PORT", "10000"))
PATH_SECRET = os.environ.get("MCP_PATH_SECRET", "").strip().strip("/")

if not PATH_SECRET:
    raise RuntimeError("MCP_PATH_SECRET must be set")


PUBLIC_BASE_URL = os.environ.get(
    "PUBLIC_BASE_URL",
    "https://fpl-mcp-server-kaol.onrender.com",
).rstrip("/")


OAUTH_ISSUER = f"{PUBLIC_BASE_URL}/mcp/{PATH_SECRET}"


# ---------------------------------------------------------------------------
# IMPORTANT:
# The existing mcp_tools.py already creates the FastMCP object with OAuth
# settings and a token verifier. It was missing the authorization-server
# provider connection. The official MCP SDK only creates the OAuth routes
# when this provider is supplied.
# ---------------------------------------------------------------------------

mcp._auth_server_provider = oauth_provider
mcp._token_verifier = ProviderTokenVerifier(oauth_provider)


# Enable Dynamic Client Registration for Claude.
if mcp.settings.auth is not None:
    mcp.settings.auth.client_registration_options = (
        ClientRegistrationOptions(
            enabled=True,
            valid_scopes=["read"],
            default_scopes=["read"],
        )
    )


# ---------------------------------------------------------------------------
# The existing OAuth provider originally sends the browser to:
#
#   /login/<request_id>
#
# We deliberately redirect OAuth login requests to a dedicated OAuth login
# page so the existing normal FPL login flow remains untouched.
# ---------------------------------------------------------------------------

_original_authorize = oauth_provider.authorize


async def _oauth_authorize(client, params):
    login_url = await _original_authorize(client, params)

    login_url = login_url.replace(
        f"{PUBLIC_BASE_URL}/login/",
        f"{PUBLIC_BASE_URL}/oauth/login/",
        1,
    )

    return login_url


oauth_provider.authorize = _oauth_authorize


# ---------------------------------------------------------------------------
# MCP HTTP configuration
# ---------------------------------------------------------------------------

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


# ---------------------------------------------------------------------------
# OAuth login page
# ---------------------------------------------------------------------------

LOGIN_PAGE = """
<!DOCTYPE html>
<html lang="en">
<head>
    <meta charset="utf-8">
    <meta name="viewport" content="width=device-width, initial-scale=1">
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
        This login is being requested by your FPL Manager MCP connection.
    </div>
</main>
</body>
</html>
"""


def login_error(message: str):
    return HTMLResponse(
        LOGIN_PAGE.replace(
            "{error}",
            f'<div class="error">{message}</div>',
        ),
        status_code=400,
    )


async def oauth_login_page(request):
    request_id = request.path_params["request_id"]

    pending = oauth_provider.pending.get(request_id)

    if not pending:
        return HTMLResponse(
            "<h1>Login request expired</h1>"
            "<p>Please reconnect the FPL Manager connector.</p>",
            status_code=400,
        )

    return HTMLResponse(
        LOGIN_PAGE.replace("{error}", "")
    )


async def oauth_login_submit(
    request,
    email: str = Form(...),
    password: str = Form(...),
):
    request_id = request.path_params["request_id"]

    pending = oauth_provider.pending.get(request_id)

    if not pending:
        return HTMLResponse(
            "<h1>Login request expired</h1>"
            "<p>Please reconnect the FPL Manager connector.</p>",
            status_code=400,
        )

    try:
        auth = FPLAutomation(email, password)

        token = await auth.login_and_get_token()

        if not token:
            return login_error(
                auth.failure_reason
                or "FPL authentication failed."
            )

        session_id = str(uuid.uuid4())

        client = FPLClient(store=store)
        client.set_api_token(token)

        await store.set_login_success(
            request_id,
            session_id,
            client,
        )

        # Make the authenticated FPL session available to the existing
        # read-only FPL tools.
        mcp_tools._active_session_id = session_id

        redirect_uri = oauth_provider.complete_fpl_login(
            request_id,
            session_id,
        )

        if not redirect_uri:
            return login_error(
                "OAuth request expired before authentication completed."
            )

        return RedirectResponse(
            redirect_uri,
            status_code=302,
        )

    except Exception as exc:
        return login_error(
            f"FPL authentication failed: {exc}"
        )


# ---------------------------------------------------------------------------
# Health endpoint
# ---------------------------------------------------------------------------

async def health(_request):
    return JSONResponse({"status": "ok"})


# ---------------------------------------------------------------------------
# Application lifespan
# ---------------------------------------------------------------------------

@contextlib.asynccontextmanager
async def lifespan(_app):
    async with contextlib.AsyncExitStack() as stack:
        await stack.enter_async_context(
            mcp.session_manager.run()
        )
        yield


# ---------------------------------------------------------------------------
# Routes
# ---------------------------------------------------------------------------

routes = [
    Route(
        "/health",
        health,
        methods=["GET"],
    ),

    # OAuth human login
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

    # MCP OAuth + MCP endpoint
    Mount(
        f"/mcp/{PATH_SECRET}",
        app=mcp_http_app,
    ),

    # Existing FPL login/application routes remain available.
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
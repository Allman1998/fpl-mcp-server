from __future__ import annotations

import secrets
import time
from dataclasses import dataclass

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken


@dataclass
class PendingAuthorization:
    client: OAuthClientInformationFull
    params: AuthorizationParams
    expires_at: float


class FPLOAuthProvider(
    OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]
):
    def __init__(self, issuer_url: str):
        self.issuer_url = issuer_url.rstrip("/")
        self.clients = {}
        self.pending = {}
        self.codes = {}
        self.access_tokens = {}
        self.refresh_tokens = {}

    async def get_client(self, client_id):
        return self.clients.get(client_id)

    async def register_client(self, client_info):
        self.clients[client_info.client_id] = client_info

    async def authorize(self, client, params):
        request_id = secrets.token_urlsafe(32)

        self.pending[request_id] = PendingAuthorization(
            client=client,
            params=params,
            expires_at=time.time() + 600,
        )

        base = self.issuer_url.rsplit("/mcp/", 1)[0]
        return f"{base}/login/{request_id}?oauth=1"

    async def load_authorization_code(self, client, authorization_code):
        code = self.codes.get(authorization_code)

        if not code:
            return None

        if code.expires_at < time.time():
            self.codes.pop(authorization_code, None)
            return None

        if code.client_id != client.client_id:
            return None

        return code

    async def exchange_authorization_code(self, client, authorization_code):
        self.codes.pop(authorization_code.code, None)

        access_token = secrets.token_urlsafe(48)
        refresh_token = secrets.token_urlsafe(48)

        expires_in = 3600
        now = time.time()

        self.access_tokens[access_token] = AccessToken(
            token=access_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=now + expires_in,
            resource=authorization_code.resource,
            subject=authorization_code.subject,
        )

        self.refresh_tokens[refresh_token] = RefreshToken(
            token=refresh_token,
            client_id=client.client_id,
            scopes=authorization_code.scopes,
            expires_at=now + 30 * 24 * 3600,
            subject=authorization_code.subject,
        )

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=expires_in,
            refresh_token=refresh_token,
            scope=" ".join(authorization_code.scopes),
        )

    async def load_refresh_token(self, client, refresh_token):
        token = self.refresh_tokens.get(refresh_token)

        if not token:
            return None

        if token.expires_at and token.expires_at < time.time():
            return None

        if token.client_id != client.client_id:
            return None

        return token

    async def exchange_refresh_token(self, client, refresh_token, scopes):
        self.refresh_tokens.pop(refresh_token.token, None)

        access_token = secrets.token_urlsafe(48)
        new_refresh = secrets.token_urlsafe(48)

        expires_in = 3600
        granted_scopes = scopes or refresh_token.scopes

        self.access_tokens[access_token] = AccessToken(
            token=access_token,
            client_id=client.client_id,
            scopes=granted_scopes,
            expires_at=time.time() + expires_in,
            subject=refresh_token.subject,
        )

        self.refresh_tokens[new_refresh] = RefreshToken(
            token=new_refresh,
            client_id=client.client_id,
            scopes=granted_scopes,
            expires_at=time.time() + 30 * 24 * 3600,
            subject=refresh_token.subject,
        )

        return OAuthToken(
            access_token=access_token,
            token_type="Bearer",
            expires_in=expires_in,
            refresh_token=new_refresh,
            scope=" ".join(granted_scopes),
        )

    async def load_access_token(self, token):
        access = self.access_tokens.get(token)

        if not access:
            return None

        if access.expires_at and access.expires_at < time.time():
            self.access_tokens.pop(token, None)
            return None

        return access

    async def revoke_token(self, token):
        self.access_tokens.pop(getattr(token, "token", ""), None)
        self.refresh_tokens.pop(getattr(token, "token", ""), None)

    def complete_fpl_login(self, request_id, session_id):
        pending = self.pending.pop(request_id, None)

        if not pending or pending.expires_at < time.time():
            return None

        params = pending.params
        code = secrets.token_urlsafe(48)

        self.codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or ["read"],
            expires_at=time.time() + 600,
            client_id=pending.client.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            subject=session_id,
        )

        return construct_redirect_uri(
            str(params.redirect_uri),
            code=code,
            state=params.state,
        )
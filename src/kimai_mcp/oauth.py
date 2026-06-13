"""Embedded OAuth 2.1 Authorization Server for the Kimai MCP streamable HTTP server.

Implements the ``OAuthAuthorizationServerProvider`` protocol from the MCP SDK:

- Dynamic Client Registration (RFC 7591) with an in-memory client store
  (optionally persisted to a JSON state file).
- Authorization Code flow with mandatory PKCE (S256).
- A simple HTML login form where users authenticate with their user slug
  and a per-user ``auth_secret`` (constant-time comparison).
- Opaque access tokens (~1h TTL) and refresh tokens (~30 days TTL),
  stored in memory and bound to the authenticated user (``subject``).
"""

import asyncio
import html
import json
import logging
import secrets
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Union

from starlette.requests import Request
from starlette.responses import HTMLResponse, RedirectResponse, Response
from starlette.routing import Route

from mcp.server.auth.provider import (
    AccessToken,
    AuthorizationCode,
    AuthorizationParams,
    OAuthAuthorizationServerProvider,
    RefreshToken,
    TokenError,
    construct_redirect_uri,
)
from mcp.shared.auth import OAuthClientInformationFull, OAuthToken

from .oidc import OIDCClient, OIDCConfig, OIDCError, OIDCLoginState
from .user_config import UsersConfig, _env_key_for_slug

logger = logging.getLogger(__name__)

# Token lifetimes
ACCESS_TOKEN_TTL_SECONDS = 3600  # 1 hour
REFRESH_TOKEN_TTL_SECONDS = 30 * 24 * 3600  # 30 days
AUTH_CODE_TTL_SECONDS = 600  # 10 minutes
LOGIN_TXN_TTL_SECONDS = 600  # 10 minutes

# Registered DCR clients are kept around so long as they keep being used.
# A client that has not been seen for this long is pruned by cleanup_expired().
CLIENT_TTL_SECONDS = 30 * 24 * 3600  # 30 days

LOGIN_PATH = "/oauth/login"
OIDC_CALLBACK_PATH = "/oauth/oidc/callback"


@dataclass
class PendingAuthorization:
    """An authorization request waiting for the user to log in."""

    client_id: str
    params: AuthorizationParams
    created_at: float = field(default_factory=time.time)

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > LOGIN_TXN_TTL_SECONDS


_LOGIN_PAGE_TEMPLATE = """<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>Kimai MCP - Sign in</title>
  <style>
    body {{ font-family: system-ui, sans-serif; background: #f5f5f5; display: flex;
           justify-content: center; align-items: center; min-height: 100vh; margin: 0; }}
    .card {{ background: #fff; padding: 2rem; border-radius: 8px;
             box-shadow: 0 2px 8px rgba(0,0,0,.1); width: 100%; max-width: 360px; }}
    h1 {{ font-size: 1.25rem; margin-top: 0; }}
    label {{ display: block; margin: .75rem 0 .25rem; font-weight: 600; font-size: .9rem; }}
    input {{ width: 100%; padding: .5rem; border: 1px solid #ccc; border-radius: 4px;
             box-sizing: border-box; }}
    button {{ margin-top: 1.25rem; width: 100%; padding: .6rem; background: #2563eb;
              color: #fff; border: none; border-radius: 4px; font-size: 1rem; cursor: pointer; }}
    .error {{ background: #fee2e2; color: #991b1b; padding: .5rem .75rem;
              border-radius: 4px; font-size: .9rem; margin-bottom: .5rem; }}
    .hint {{ color: #666; font-size: .8rem; margin-top: 1rem; }}
  </style>
</head>
<body>
  <div class="card">
    <h1>Kimai MCP &ndash; Authorize access</h1>
    {error_block}
    <form method="post" action="{action}">
      <input type="hidden" name="txn" value="{txn}">
      <label for="username">User slug</label>
      <input type="text" id="username" name="username" autocomplete="username" required>
      <label for="secret">Auth secret</label>
      <input type="password" id="secret" name="secret" autocomplete="current-password" required>
      <button type="submit">Sign in</button>
    </form>
    <p class="hint">Sign in with your configured user slug and auth secret to grant
    the connecting application access to your Kimai account.</p>
  </div>
</body>
</html>"""


class KimaiOAuthProvider(OAuthAuthorizationServerProvider[AuthorizationCode, RefreshToken, AccessToken]):
    """OAuth 2.1 Authorization Server provider backed by the users.json configuration.

    Users authenticate with their user slug and the per-user ``auth_secret``.
    Issued tokens carry the user slug as ``subject`` so the resource endpoint
    can map a verified token to the corresponding UserMCPSession.
    """

    def __init__(
        self,
        users_config: UsersConfig,
        public_url: str,
        state_file: Optional[Union[str, Path]] = None,
        oidc_config: Optional[OIDCConfig] = None,
    ):
        """Initialize the provider.

        Args:
            users_config: Multi-user configuration (slug -> UserConfig).
            public_url: Public base URL of the server (issuer), no trailing slash.
            state_file: Optional path to a JSON file used to persist registered
                OAuth clients across restarts (tokens are always in-memory).
            oidc_config: Optional OIDC relying-party config. When set, users
                authenticate against an external OIDC provider instead of the
                built-in slug + auth_secret login form.
        """
        self.users_config = users_config
        self.public_url = public_url.rstrip("/")
        self.state_file = Path(state_file) if state_file else None
        # Federated OIDC login backend (None -> built-in local login form).
        self.oidc: Optional[OIDCClient] = OIDCClient(oidc_config) if oidc_config else None
        # Pending federated logins keyed by the OIDC `state` we sent to the IdP.
        self._oidc_logins: Dict[str, OIDCLoginState] = {}

        self._clients: Dict[str, OAuthClientInformationFull] = {}
        # Last time each client was seen (registered or looked up). Used to
        # expire idle DCR clients in cleanup_expired() so the store can't grow
        # without bound.
        self._client_last_seen: Dict[str, float] = {}
        self._pending: Dict[str, PendingAuthorization] = {}
        self._auth_codes: Dict[str, AuthorizationCode] = {}
        self._access_tokens: Dict[str, AccessToken] = {}
        self._refresh_tokens: Dict[str, RefreshToken] = {}
        # The SDK RefreshToken model has no `resource` field, so we keep the
        # RFC 8707 audience binding for refresh tokens in a side mapping.
        self._refresh_token_resource: Dict[str, Optional[str]] = {}
        # Pairing for revocation/rotation: access <-> refresh
        self._access_to_refresh: Dict[str, str] = {}
        self._refresh_to_access: Dict[str, str] = {}

        self._load_clients()

    # ------------------------------------------------------------------
    # Client store (Dynamic Client Registration)
    # ------------------------------------------------------------------

    def _load_clients(self) -> None:
        """Load persisted clients from the state file, if configured."""
        if not self.state_file or not self.state_file.exists():
            return
        try:
            with open(self.state_file, "r", encoding="utf-8") as f:
                data = json.load(f)
            now = time.time()
            for client_id, client_data in data.get("clients", {}).items():
                self._clients[client_id] = OAuthClientInformationFull.model_validate(client_data)
                # Treat a freshly loaded client as just-seen so a restart does
                # not immediately expire still-valid clients.
                self._client_last_seen[client_id] = now
            logger.info(f"Loaded {len(self._clients)} OAuth client(s) from {self.state_file}")
        except Exception as e:
            logger.error(f"Failed to load OAuth state file {self.state_file}: {e}")

    def _persist_clients(self) -> None:
        """Persist registered clients to the state file, if configured."""
        if not self.state_file:
            return
        try:
            data = {
                "clients": {
                    client_id: client.model_dump(mode="json", exclude_none=True)
                    for client_id, client in self._clients.items()
                }
            }
            self.state_file.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.state_file.with_suffix(self.state_file.suffix + ".tmp")
            with open(tmp_path, "w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
            tmp_path.replace(self.state_file)
        except Exception as e:
            logger.error(f"Failed to persist OAuth state file {self.state_file}: {e}")

    async def get_client(self, client_id: str) -> Optional[OAuthClientInformationFull]:
        client = self._clients.get(client_id)
        if client is not None:
            # Renew last-seen on every use so actively used clients never expire.
            self._client_last_seen[client_id] = time.time()
        return client

    async def register_client(self, client_info: OAuthClientInformationFull) -> None:
        if client_info.client_id is None:
            raise ValueError("client_id must be set for registration")
        self._clients[client_info.client_id] = client_info
        self._client_last_seen[client_info.client_id] = time.time()
        # Persist off the event loop so a registration storm can't block other requests.
        await asyncio.to_thread(self._persist_clients)
        logger.info(
            f"Registered OAuth client '{client_info.client_name or client_info.client_id}' "
            f"({client_info.client_id})"
        )

    # ------------------------------------------------------------------
    # Authorization endpoint (redirects to the login form)
    # ------------------------------------------------------------------

    async def authorize(self, client: OAuthClientInformationFull, params: AuthorizationParams) -> str:
        """Store the request and redirect the user agent to the login step.

        Local backend -> the built-in HTML login form. OIDC backend -> the
        external identity provider's authorization endpoint.
        """
        txn = secrets.token_urlsafe(32)
        self._pending[txn] = PendingAuthorization(client_id=client.client_id or "", params=params)

        if self.oidc is None:
            return f"{self.public_url}{LOGIN_PATH}?txn={txn}"

        # Federated OIDC: create per-login state/nonce/PKCE, then redirect to the IdP.
        oidc_state = secrets.token_urlsafe(32)
        login_state, code_challenge = self.oidc.make_login_state(txn)
        self._oidc_logins[oidc_state] = login_state
        return await self.oidc.build_authorization_url(
            state=oidc_state,
            nonce=login_state.nonce,
            code_challenge=code_challenge,
            redirect_uri=f"{self.public_url}{OIDC_CALLBACK_PATH}",
        )

    # ------------------------------------------------------------------
    # Login form (HTML)
    # ------------------------------------------------------------------

    def _render_login_page(self, txn: str, error: Optional[str] = None, status_code: int = 200) -> Response:
        error_block = f'<div class="error">{html.escape(error)}</div>' if error else ""
        page = _LOGIN_PAGE_TEMPLATE.format(
            action=LOGIN_PATH,
            txn=html.escape(txn),
            error_block=error_block,
        )
        return HTMLResponse(page, status_code=status_code)

    def _get_pending(self, txn: Optional[str]) -> Optional[PendingAuthorization]:
        if not txn:
            return None
        pending = self._pending.get(txn)
        if pending is None:
            return None
        if pending.expired:
            del self._pending[txn]
            return None
        return pending

    def _issue_auth_code(self, pending: PendingAuthorization, subject: str) -> RedirectResponse:
        """Issue a single-use authorization code for an authenticated subject and
        redirect back to the client. The caller must have already removed the
        pending transaction. The redirect target is the SDK-validated client
        redirect_uri from the stored request (open-redirect safe)."""
        params = pending.params
        code = secrets.token_urlsafe(32)
        self._auth_codes[code] = AuthorizationCode(
            code=code,
            scopes=params.scopes or [],
            expires_at=time.time() + AUTH_CODE_TTL_SECONDS,
            client_id=pending.client_id,
            code_challenge=params.code_challenge,
            redirect_uri=params.redirect_uri,
            redirect_uri_provided_explicitly=params.redirect_uri_provided_explicitly,
            resource=params.resource,
            subject=subject,
        )
        redirect_url = construct_redirect_uri(str(params.redirect_uri), code=code, state=params.state)
        return RedirectResponse(redirect_url, status_code=302, headers={"Cache-Control": "no-store"})

    async def handle_login_page(self, request: Request) -> Response:
        """GET /oauth/login - render the login form."""
        txn = request.query_params.get("txn")
        if self._get_pending(txn) is None:
            return HTMLResponse(
                "<h1>Invalid or expired authorization request</h1>"
                "<p>Please restart the authorization flow from your client.</p>",
                status_code=400,
            )
        return self._render_login_page(txn)

    async def handle_login_submit(self, request: Request) -> Response:
        """POST /oauth/login - verify credentials and redirect back to the client."""
        form = await request.form()
        txn = form.get("txn")
        username = form.get("username")
        provided_secret = form.get("secret")
        txn = txn if isinstance(txn, str) else ""
        username = username.strip() if isinstance(username, str) else ""
        provided_secret = provided_secret if isinstance(provided_secret, str) else ""

        pending = self._get_pending(txn)
        if pending is None:
            return HTMLResponse(
                "<h1>Invalid or expired authorization request</h1>"
                "<p>Please restart the authorization flow from your client.</p>",
                status_code=400,
            )

        user = self.users_config.get_user(username)

        if user is not None and not user.auth_secret:
            # Log a precise hint for the administrator, but do NOT reveal in the
            # response that this slug exists (that would defeat the constant-time
            # comparison below and enable slug enumeration -> legacy-slug access).
            env_key = _env_key_for_slug(username, "AUTH_SECRET")
            logger.warning(
                f"OAuth login rejected for existing user '{username}': no auth_secret configured. "
                f"Set 'auth_secret' in users.json or the {env_key} environment variable."
            )

        # Constant-time comparison; compare against a dummy if the user is unknown
        # or has no secret, so the response timing does not reveal whether the slug exists.
        expected_secret = user.auth_secret if (user and user.auth_secret) else secrets.token_urlsafe(32)
        secrets_match = secrets.compare_digest(provided_secret.encode(), expected_secret.encode())

        if user is None or not user.auth_secret or not secrets_match:
            logger.warning(f"Failed OAuth login attempt for user slug '{username}'")
            return self._render_login_page(txn, error="Invalid user slug or auth secret.", status_code=401)

        # Success: consume the transaction and issue an authorization code.
        del self._pending[txn]
        logger.info(f"OAuth login successful for user '{username}' (client {pending.client_id})")
        return self._issue_auth_code(pending, username)

    # ------------------------------------------------------------------
    # Federated OIDC callback
    # ------------------------------------------------------------------

    def _get_oidc_login(self, state: Optional[str]) -> Optional[OIDCLoginState]:
        """Pop a pending OIDC login by state (single-use); None if missing/expired."""
        if not state:
            return None
        login = self._oidc_logins.pop(state, None)
        if login is None or login.expired:
            return None
        return login

    @staticmethod
    def _oidc_error(message: str, status_code: int) -> Response:
        return HTMLResponse(
            f"<h1>Sign-in failed</h1><p>{html.escape(message)}</p>"
            "<p>Please restart the authorization flow from your client.</p>",
            status_code=status_code,
        )

    async def handle_oidc_callback(self, request: Request) -> Response:
        """GET /oauth/oidc/callback - complete the federated login and issue an auth code."""
        params = request.query_params
        if params.get("error"):
            # The IdP rejected the login; do not echo provider internals to the user.
            logger.warning(f"OIDC provider returned error: {params.get('error')}")
            return self._oidc_error("The identity provider denied the sign-in request.", 400)

        login = self._get_oidc_login(params.get("state"))
        if login is None:
            return self._oidc_error("Invalid or expired sign-in state.", 400)

        pending = self._get_pending(login.txn)
        if pending is None:
            return self._oidc_error("Invalid or expired authorization request.", 400)

        code = params.get("code")
        if not code:
            return self._oidc_error("Missing authorization code from the identity provider.", 400)

        assert self.oidc is not None  # routes() only mounts this handler when OIDC is enabled
        try:
            tokens = await self.oidc.exchange_code(
                code=code,
                code_verifier=login.code_verifier,
                redirect_uri=f"{self.public_url}{OIDC_CALLBACK_PATH}",
            )
            id_token = tokens.get("id_token")
            if not id_token:
                raise OIDCError("token response did not contain an id_token")
            claims = await self.oidc.validate_id_token(id_token, expected_nonce=login.nonce)
        except OIDCError as e:
            logger.warning(f"OIDC sign-in failed: {e}")
            return self._oidc_error("Could not verify your identity with the identity provider.", 401)

        identity = self.oidc.extract_identity(claims)
        if not identity:
            logger.warning("OIDC id_token had no usable identity claim")
            return self._oidc_error("The identity provider did not return a usable identity.", 401)

        match = self.users_config.get_user_by_oidc_identity(identity)
        if match is None:
            # Detailed reason is logged server-side only; the response stays generic
            # (consistent with the local login form's deliberate non-disclosure).
            logger.warning(f"OIDC login: no Kimai user linked to identity '{identity}'")
            return self._oidc_error("Your account is not authorized for this application.", 403)
        slug, _user = match

        # Success: consume the transaction and issue an authorization code (same
        # path as the local login form, with the OIDC-resolved slug as subject).
        del self._pending[login.txn]
        logger.info(f"OIDC login successful for user '{slug}' (client {pending.client_id})")
        return self._issue_auth_code(pending, slug)

    def routes(self) -> list:
        """Starlette routes for the active login backend."""
        if self.oidc is not None:
            return [Route(OIDC_CALLBACK_PATH, endpoint=self.handle_oidc_callback, methods=["GET"])]
        return [
            Route(LOGIN_PATH, endpoint=self.handle_login_page, methods=["GET"]),
            Route(LOGIN_PATH, endpoint=self.handle_login_submit, methods=["POST"]),
        ]

    # ------------------------------------------------------------------
    # Token issuance
    # ------------------------------------------------------------------

    def _issue_token_pair(
        self, client_id: str, scopes: list, subject: Optional[str], resource: Optional[str]
    ) -> OAuthToken:
        """Issue a new opaque access/refresh token pair bound to a user."""
        now = int(time.time())
        access_token_str = secrets.token_urlsafe(32)
        refresh_token_str = secrets.token_urlsafe(32)

        self._access_tokens[access_token_str] = AccessToken(
            token=access_token_str,
            client_id=client_id,
            scopes=scopes,
            expires_at=now + ACCESS_TOKEN_TTL_SECONDS,
            resource=resource,
            subject=subject,
        )
        self._refresh_tokens[refresh_token_str] = RefreshToken(
            token=refresh_token_str,
            client_id=client_id,
            scopes=scopes,
            expires_at=now + REFRESH_TOKEN_TTL_SECONDS,
            subject=subject,
        )
        # Preserve the RFC 8707 audience binding for the refresh token; the SDK
        # RefreshToken model has no `resource` field, so we keep it on the side.
        self._refresh_token_resource[refresh_token_str] = resource
        self._access_to_refresh[access_token_str] = refresh_token_str
        self._refresh_to_access[refresh_token_str] = access_token_str

        return OAuthToken(
            access_token=access_token_str,
            token_type="Bearer",
            expires_in=ACCESS_TOKEN_TTL_SECONDS,
            scope=" ".join(scopes) if scopes else None,
            refresh_token=refresh_token_str,
        )

    async def load_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: str
    ) -> Optional[AuthorizationCode]:
        code = self._auth_codes.get(authorization_code)
        if code is None:
            return None
        if code.expires_at < time.time():
            del self._auth_codes[authorization_code]
            return None
        return code

    async def exchange_authorization_code(
        self, client: OAuthClientInformationFull, authorization_code: AuthorizationCode
    ) -> OAuthToken:
        # Single use: remove the code.
        self._auth_codes.pop(authorization_code.code, None)
        return self._issue_token_pair(
            client_id=authorization_code.client_id,
            scopes=authorization_code.scopes,
            subject=authorization_code.subject,
            resource=authorization_code.resource,
        )

    async def load_refresh_token(
        self, client: OAuthClientInformationFull, refresh_token: str
    ) -> Optional[RefreshToken]:
        token = self._refresh_tokens.get(refresh_token)
        if token is None:
            return None
        if token.expires_at is not None and token.expires_at < time.time():
            self._remove_refresh_token(refresh_token)
            return None
        return token

    async def exchange_refresh_token(
        self,
        client: OAuthClientInformationFull,
        refresh_token: RefreshToken,
        scopes: list,
    ) -> OAuthToken:
        # Client binding: a public client must not be able to redeem a refresh
        # token that was issued to a different client. The SDK token handler
        # already compares against the request's client_id, but we defend in
        # depth against the authenticated client here as well.
        if refresh_token.client_id != client.client_id:
            raise TokenError(
                error="invalid_grant",
                error_description="refresh token was not issued to this client",
            )
        # Preserve the RFC 8707 audience binding across rotation. Read it before
        # removing the old token, which clears the side mapping.
        resource = self._refresh_token_resource.get(refresh_token.token)
        # Rotate: revoke the old pair, issue a new one.
        self._remove_refresh_token(refresh_token.token)
        return self._issue_token_pair(
            client_id=refresh_token.client_id,
            scopes=scopes or refresh_token.scopes,
            subject=refresh_token.subject,
            resource=resource,
        )

    async def load_access_token(self, token: str) -> Optional[AccessToken]:
        access = self._access_tokens.get(token)
        if access is None:
            return None
        if access.expires_at is not None and access.expires_at < int(time.time()):
            self._remove_access_token(token)
            return None
        return access

    # ------------------------------------------------------------------
    # Revocation
    # ------------------------------------------------------------------

    def _remove_access_token(self, token: str) -> None:
        self._access_tokens.pop(token, None)
        refresh = self._access_to_refresh.pop(token, None)
        if refresh:
            self._refresh_to_access.pop(refresh, None)

    def _remove_refresh_token(self, token: str) -> None:
        self._refresh_tokens.pop(token, None)
        self._refresh_token_resource.pop(token, None)
        access = self._refresh_to_access.pop(token, None)
        if access:
            self._access_to_refresh.pop(access, None)

    async def revoke_token(self, token) -> None:
        """Revoke an access or refresh token together with its counterpart."""
        if isinstance(token, AccessToken):
            refresh = self._access_to_refresh.get(token.token)
            self._remove_access_token(token.token)
            if refresh:
                self._refresh_tokens.pop(refresh, None)
                self._refresh_token_resource.pop(refresh, None)
        elif isinstance(token, RefreshToken):
            access = self._refresh_to_access.get(token.token)
            self._remove_refresh_token(token.token)
            if access:
                self._access_tokens.pop(access, None)

    # ------------------------------------------------------------------
    # Maintenance
    # ------------------------------------------------------------------

    def cleanup_expired(self) -> int:
        """Remove expired transactions, codes and tokens. Returns removal count."""
        now = time.time()
        removed = 0

        for txn in [t for t, p in self._pending.items() if p.expired]:
            del self._pending[txn]
            removed += 1

        for state in [s for s, login in self._oidc_logins.items() if login.expired]:
            del self._oidc_logins[state]
            removed += 1

        for code in [c for c, ac in self._auth_codes.items() if ac.expires_at < now]:
            del self._auth_codes[code]
            removed += 1

        for token in [
            t for t, at in self._access_tokens.items() if at.expires_at is not None and at.expires_at < now
        ]:
            self._remove_access_token(token)
            removed += 1

        for token in [
            t for t, rt in self._refresh_tokens.items() if rt.expires_at is not None and rt.expires_at < now
        ]:
            self._remove_refresh_token(token)
            removed += 1

        # Prune idle / expired DCR clients so the client store (and its state
        # file) can't grow without bound. A client is removed when it has not
        # been seen for CLIENT_TTL_SECONDS, or when its client_secret has a
        # defined expiry that already lies in the past. Last-seen is renewed on
        # every get_client()/register_client(), so active clients never expire.
        stale_clients = []
        for client_id, client in self._clients.items():
            last_seen = self._client_last_seen.get(client_id, 0.0)
            idle_expired = now - last_seen > CLIENT_TTL_SECONDS
            secret_expires_at = client.client_secret_expires_at
            secret_expired = secret_expires_at is not None and 0 < secret_expires_at < now
            if idle_expired or secret_expired:
                stale_clients.append(client_id)

        for client_id in stale_clients:
            del self._clients[client_id]
            self._client_last_seen.pop(client_id, None)
            removed += 1

        # Persist once after pruning so the state file reflects the removals.
        if stale_clients:
            self._persist_clients()

        if removed:
            logger.debug(f"OAuth cleanup removed {removed} expired entries")
        return removed

    async def aclose(self) -> None:
        """Release resources held by the OIDC client (if any)."""
        if self.oidc is not None:
            await self.oidc.aclose()

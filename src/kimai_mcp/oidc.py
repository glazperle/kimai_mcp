"""Generic, provider-agnostic OpenID Connect (OIDC) relying-party helper.

This module lets the embedded OAuth server (``oauth.py``) authenticate end users
against ANY standard OIDC provider (Azure AD / Entra ID, Keycloak, Auth0, Google,
Okta, ...) during the Authorization-Code-with-PKCE flow. It performs ONLY the
federated user-authentication step:

1. redirect the browser to the provider's authorization endpoint,
2. exchange the returned code for tokens at the provider's token endpoint,
3. verify the ``id_token`` (signature via JWKS, ``iss``/``aud``/``exp``/``iat``
   and ``nonce``), and
4. extract the configured identity claim (e.g. ``email``).

The MCP server keeps issuing its own opaque access/refresh tokens — this module
never mints tokens for the MCP client. Provider endpoints are discovered via
``<issuer>/.well-known/openid-configuration`` so nothing is hardcoded.

Requires the ``[server]`` extra (``PyJWT[crypto]``) for id_token signature
verification.
"""

from __future__ import annotations

import base64
import hashlib
import hmac
import logging
import secrets
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import httpx
from pydantic import BaseModel, Field

# NOTE: PyJWT (``jwt``) is only needed for id_token signature verification and is
# part of the optional ``[server]`` extra. It is imported lazily inside the
# methods that use it so that ``import kimai_mcp.oidc`` (and therefore the OAuth
# server module) works on a base install without PyJWT.

logger = logging.getLogger(__name__)

# How long a federated login transaction (state/nonce/PKCE) stays valid.
OIDC_LOGIN_TTL_SECONDS = 600  # 10 minutes
# Caches for the provider discovery document and its signing keys.
DISCOVERY_TTL_SECONDS = 3600  # 1 hour
JWKS_TTL_SECONDS = 3600  # 1 hour
# Asymmetric algorithms we are willing to accept for id_tokens. "none" and the
# HMAC family are intentionally excluded (an attacker who knows the client_id
# could otherwise forge HS256 tokens).
DEFAULT_ALLOWED_ALGS = ["RS256", "RS384", "RS512", "ES256", "ES384", "PS256"]


def _b64url(data: bytes) -> str:
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode("ascii")


def generate_pkce_pair() -> tuple[str, str]:
    """Return a (code_verifier, code_challenge) PKCE pair using S256 (RFC 7636)."""
    verifier = _b64url(secrets.token_bytes(32))
    challenge = _b64url(hashlib.sha256(verifier.encode("ascii")).digest())
    return verifier, challenge


class OIDCError(Exception):
    """Base class for OIDC relying-party errors."""


class OIDCDiscoveryError(OIDCError):
    """Provider discovery or JWKS retrieval failed."""


class OIDCTokenExchangeError(OIDCError):
    """The authorization-code exchange at the token endpoint failed."""


class OIDCValidationError(OIDCError):
    """The id_token failed validation (signature, claims or nonce)."""


class OIDCConfig(BaseModel):
    """Configuration for the OIDC relying party.

    Built from CLI flags / environment variables by the server. The redirect/
    callback URL registered at the provider is the server's
    ``<public-url>/oauth/oidc/callback`` and is supplied per request, not here.
    """

    issuer: str = Field(..., description="OIDC issuer URL, e.g. https://login.microsoftonline.com/<tenant>/v2.0")
    client_id: str = Field(..., description="OAuth client ID registered at the provider")
    client_secret: Optional[str] = Field(
        None, description="Client secret for confidential clients; omit for public (PKCE-only) clients"
    )
    scopes: List[str] = Field(
        default_factory=lambda: ["openid", "email", "profile"],
        description="Scopes requested from the provider (must include 'openid')",
    )
    identity_claims: List[str] = Field(
        default_factory=lambda: ["email", "preferred_username", "upn"],
        description="Ordered id_token claims to try when resolving the user identity",
    )
    require_verified_email: bool = Field(
        True,
        description=(
            "When the matched identity claim is 'email', require the id_token's "
            "'email_verified' claim to be true. Disable only for providers that "
            "do not emit email_verified but are trusted to assert verified emails."
        ),
    )
    allowed_algorithms: List[str] = Field(
        default_factory=lambda: list(DEFAULT_ALLOWED_ALGS),
        description="Permitted id_token signing algorithms (never 'none'/HS*)",
    )
    discovery_url: Optional[str] = Field(
        None, description="Override for the discovery document URL (default: <issuer>/.well-known/openid-configuration)"
    )
    clock_skew_seconds: int = Field(60, description="Allowed clock skew when validating exp/iat")


@dataclass
class OIDCProviderMetadata:
    """The subset of the discovery document we use."""

    issuer: str
    authorization_endpoint: str
    token_endpoint: str
    jwks_uri: str


@dataclass
class OIDCLoginState:
    """Per-login state bridging /authorize -> provider -> /oauth/oidc/callback.

    Stored server-side keyed by ``state``; single-use and short-lived.
    """

    txn: str  # links back to the OAuth provider's PendingAuthorization
    nonce: str
    code_verifier: str
    created_at: float = field(default_factory=time.time)

    @property
    def expired(self) -> bool:
        return time.time() - self.created_at > OIDC_LOGIN_TTL_SECONDS


class OIDCClient:
    """Minimal async OIDC relying party: discovery, auth URL, code exchange, id_token validation."""

    def __init__(self, config: OIDCConfig, http_client: Optional[httpx.AsyncClient] = None):
        self.config = config
        self._external_client = http_client is not None
        self._http = http_client
        self._metadata: Optional[OIDCProviderMetadata] = None
        self._metadata_at: float = 0.0
        self._jwks: Optional[dict] = None
        self._jwks_at: float = 0.0

    @property
    def _client(self) -> httpx.AsyncClient:
        if self._http is None:
            self._http = httpx.AsyncClient(timeout=15.0)
        return self._http

    async def aclose(self) -> None:
        if self._http is not None and not self._external_client:
            await self._http.aclose()
            self._http = None

    @property
    def _discovery_url(self) -> str:
        return self.config.discovery_url or f"{self.config.issuer.rstrip('/')}/.well-known/openid-configuration"

    # ------------------------------------------------------------------
    # Discovery + JWKS (cached)
    # ------------------------------------------------------------------

    async def discover(self) -> OIDCProviderMetadata:
        """Fetch (and cache) the provider's discovery document."""
        if self._metadata is not None and time.monotonic() - self._metadata_at < DISCOVERY_TTL_SECONDS:
            return self._metadata
        try:
            resp = await self._client.get(self._discovery_url)
            resp.raise_for_status()
            doc = resp.json()
        except Exception as e:
            if self._metadata is not None:  # stale-if-error: keep serving the cached doc
                logger.warning(f"OIDC discovery refresh failed, using cached metadata: {e}")
                return self._metadata
            raise OIDCDiscoveryError(f"Failed to fetch OIDC discovery document: {e}") from e

        # Per the OIDC spec the discovered issuer MUST match the configured one;
        # this prevents a swapped/spoofed discovery document.
        if str(doc.get("issuer", "")).rstrip("/") != self.config.issuer.rstrip("/"):
            raise OIDCDiscoveryError(
                f"Discovery issuer mismatch: configured '{self.config.issuer}', document '{doc.get('issuer')}'"
            )
        try:
            metadata = OIDCProviderMetadata(
                issuer=doc["issuer"],
                authorization_endpoint=doc["authorization_endpoint"],
                token_endpoint=doc["token_endpoint"],
                jwks_uri=doc["jwks_uri"],
            )
        except KeyError as e:
            raise OIDCDiscoveryError(f"Discovery document missing required field: {e}") from e
        self._metadata, self._metadata_at = metadata, time.monotonic()
        return metadata

    async def _get_jwks(self, force_refresh: bool = False) -> dict:
        if (
            not force_refresh
            and self._jwks is not None
            and time.monotonic() - self._jwks_at < JWKS_TTL_SECONDS
        ):
            return self._jwks
        metadata = await self.discover()
        try:
            resp = await self._client.get(metadata.jwks_uri)
            resp.raise_for_status()
            jwks = resp.json()
        except Exception as e:
            if self._jwks is not None:
                logger.warning(f"JWKS refresh failed, using cached keys: {e}")
                return self._jwks
            raise OIDCDiscoveryError(f"Failed to fetch JWKS: {e}") from e
        self._jwks, self._jwks_at = jwks, time.monotonic()
        return jwks

    # ------------------------------------------------------------------
    # Login flow
    # ------------------------------------------------------------------

    def make_login_state(self, txn: str) -> tuple[OIDCLoginState, str]:
        """Create a per-login state object and the matching PKCE code_challenge."""
        verifier, challenge = generate_pkce_pair()
        state = OIDCLoginState(txn=txn, nonce=secrets.token_urlsafe(32), code_verifier=verifier)
        return state, challenge

    async def build_authorization_url(
        self, *, state: str, nonce: str, code_challenge: str, redirect_uri: str
    ) -> str:
        """Build the provider authorization URL (Authorization Code + PKCE S256)."""
        metadata = await self.discover()
        params = {
            "client_id": self.config.client_id,
            "response_type": "code",
            "redirect_uri": redirect_uri,
            "scope": " ".join(self.config.scopes),
            "state": state,
            "nonce": nonce,
            "code_challenge": code_challenge,
            "code_challenge_method": "S256",
        }
        return f"{metadata.authorization_endpoint}?{httpx.QueryParams(params)}"

    async def exchange_code(self, *, code: str, code_verifier: str, redirect_uri: str) -> Dict[str, Any]:
        """Exchange an authorization code for tokens. Returns the raw token response."""
        metadata = await self.discover()
        data = {
            "grant_type": "authorization_code",
            "code": code,
            "redirect_uri": redirect_uri,
            "client_id": self.config.client_id,
            "code_verifier": code_verifier,
        }
        if self.config.client_secret:
            data["client_secret"] = self.config.client_secret
        try:
            resp = await self._client.post(metadata.token_endpoint, data=data)
        except Exception as e:
            raise OIDCTokenExchangeError(f"Token endpoint request failed: {e}") from e
        if resp.status_code != 200:
            # Do not log the response body verbatim (may echo the code); log status only.
            raise OIDCTokenExchangeError(f"Token endpoint returned HTTP {resp.status_code}")
        try:
            return resp.json()
        except ValueError as e:  # non-JSON body on a 200 (e.g. a misconfigured proxy)
            raise OIDCTokenExchangeError("Token endpoint returned a non-JSON response") from e

    async def validate_id_token(self, id_token: str, *, expected_nonce: str) -> Dict[str, Any]:
        """Verify the id_token signature and claims; return the validated claims.

        Verifies: JWKS signature, ``iss`` == discovered issuer, ``aud`` == client_id,
        ``exp``/``iat`` (with leeway), required claims, and ``nonce``.
        """
        import jwt  # lazy: part of the [server] extra (PyJWT[crypto])

        try:
            header = jwt.get_unverified_header(id_token)
        except jwt.InvalidTokenError as e:
            raise OIDCValidationError(f"Malformed id_token header: {e}") from e

        alg = header.get("alg")
        if alg not in self.config.allowed_algorithms:
            raise OIDCValidationError(f"Disallowed id_token signing algorithm: {alg!r}")
        kid = header.get("kid")

        signing_key = await self._resolve_signing_key(kid)
        metadata = await self.discover()
        try:
            claims = jwt.decode(
                id_token,
                key=signing_key.key,
                algorithms=self.config.allowed_algorithms,
                audience=self.config.client_id,
                issuer=metadata.issuer,
                leeway=self.config.clock_skew_seconds,
                options={"require": ["exp", "iat", "iss", "aud"]},
            )
        except jwt.InvalidTokenError as e:
            raise OIDCValidationError(f"id_token validation failed: {e}") from e

        # azp (authorized party): per OIDC Core 3.1.3.7, if present it MUST equal
        # our client_id. PyJWT only checks that client_id is contained in `aud`,
        # which is insufficient for multi-audience tokens.
        azp = claims.get("azp")
        if azp is not None and azp != self.config.client_id:
            raise OIDCValidationError("id_token azp does not match client_id")

        # PyJWT does not check the OIDC nonce; do it here, constant-time.
        token_nonce = claims.get("nonce", "")
        if not expected_nonce or not hmac.compare_digest(str(token_nonce), expected_nonce):
            raise OIDCValidationError("id_token nonce mismatch")
        return claims

    async def _resolve_signing_key(self, kid: Optional[str]):
        """Find the JWK matching ``kid`` (refresh JWKS once on a miss for key rotation)."""
        from jwt import PyJWKSet  # lazy: part of the [server] extra

        for force in (False, True):
            jwks = await self._get_jwks(force_refresh=force)
            try:
                key_set = PyJWKSet.from_dict(jwks)
            except Exception as e:
                raise OIDCValidationError(f"Invalid JWKS: {e}") from e
            if kid is None:
                if len(key_set.keys) == 1:
                    return key_set.keys[0]
            else:
                for key in key_set.keys:
                    if key.key_id == kid:
                        return key
            if force:
                break
        raise OIDCValidationError(f"No JWKS signing key for kid={kid!r}")

    # ------------------------------------------------------------------
    # Identity extraction
    # ------------------------------------------------------------------

    def extract_identity(self, claims: Dict[str, Any]) -> Optional[str]:
        """Resolve the federated identity from the configured claim fallback list.

        For username-style fallback claims (``preferred_username``/``upn``) a value
        is only accepted if it looks like an email (contains ``@``), to avoid
        matching an opaque username against an email-keyed user mapping.

        The ``email`` claim is only honored when the id_token also asserts
        ``email_verified`` is true (unless ``require_verified_email`` is disabled),
        so an IdP that lets users self-assert an unverified address cannot be used
        to impersonate a user mapped by email.
        """
        for claim in self.config.identity_claims:
            value = claims.get(claim)
            if not isinstance(value, str) or not value.strip():
                continue
            value = value.strip()
            if claim in ("preferred_username", "upn") and "@" not in value:
                continue
            if claim == "email" and self.config.require_verified_email:
                if claims.get("email_verified") is not True:
                    logger.warning(
                        "OIDC: ignoring 'email' claim because 'email_verified' is not true "
                        "(set require_verified_email=false / --oidc-allow-unverified-email to override)"
                    )
                    continue
            return value
        return None

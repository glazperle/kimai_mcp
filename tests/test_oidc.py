"""Unit tests for the generic OIDC relying-party helper (kimai_mcp.oidc).

Network I/O (discovery, JWKS, token endpoint) is faked with pytest-httpx.
id_tokens are signed with a real RSA key (cryptography) so signature
verification is exercised end-to-end.
"""

import json
import time

import pytest

# PyJWT[crypto] is part of the optional [server] extra; skip these tests if the
# server dependencies are not installed (e.g. a base/[dev]-only environment).
jwt = pytest.importorskip("jwt")
pytest.importorskip("cryptography")
from cryptography.hazmat.primitives.asymmetric import rsa  # noqa: E402

from kimai_mcp.oidc import (  # noqa: E402
    OIDCClient,
    OIDCConfig,
    OIDCDiscoveryError,
    OIDCTokenExchangeError,
    OIDCValidationError,
    generate_pkce_pair,
)

# Relax pytest-httpx strictness: discovery/JWKS responses are cached and may be
# matched zero or many times depending on the test path.
pytestmark = pytest.mark.httpx_mock(
    assert_all_responses_were_requested=False,
    can_send_already_matched_responses=True,
)

ISSUER = "https://idp.example.com"
CLIENT_ID = "kimai-mcp-client"
KID = "test-key-1"
DISCOVERY_URL = f"{ISSUER}/.well-known/openid-configuration"
AUTH_ENDPOINT = f"{ISSUER}/authorize"
TOKEN_ENDPOINT = f"{ISSUER}/token"
JWKS_URI = f"{ISSUER}/jwks"

DISCOVERY_DOC = {
    "issuer": ISSUER,
    "authorization_endpoint": AUTH_ENDPOINT,
    "token_endpoint": TOKEN_ENDPOINT,
    "jwks_uri": JWKS_URI,
}

# A single RSA keypair for the whole module; a second, unrelated key for
# bad-signature tests.
_PRIV = rsa.generate_private_key(public_exponent=65537, key_size=2048)
_OTHER_PRIV = rsa.generate_private_key(public_exponent=65537, key_size=2048)


def _jwks_for(priv, kid=KID):
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(priv.public_key()))
    jwk.update({"kid": kid, "use": "sig", "alg": "RS256"})
    return {"keys": [jwk]}


JWKS = _jwks_for(_PRIV)


def make_id_token(
    priv=_PRIV,
    *,
    kid=KID,
    alg="RS256",
    iss=ISSUER,
    aud=CLIENT_ID,
    nonce="the-nonce",
    email="alice@firma.de",
    exp_delta=300,
    iat_delta=0,
    extra=None,
):
    now = int(time.time())
    payload = {
        "iss": iss,
        "aud": aud,
        "iat": now + iat_delta,
        "exp": now + exp_delta,
        "nonce": nonce,
        "email": email,
    }
    if extra:
        payload.update(extra)
    if alg == "none":
        return jwt.encode(payload, None, algorithm="none")
    return jwt.encode(payload, priv, algorithm=alg, headers={"kid": kid})


def make_client(httpx_mock, *, add_discovery=True, add_jwks=True, jwks=None, **config_kwargs):
    if add_discovery:
        httpx_mock.add_response(url=DISCOVERY_URL, json=DISCOVERY_DOC)
    if add_jwks:
        httpx_mock.add_response(url=JWKS_URI, json=jwks or JWKS)
    cfg = OIDCConfig(issuer=ISSUER, client_id=CLIENT_ID, **config_kwargs)
    return OIDCClient(cfg)


# ---------------------------------------------------------------------------
# PKCE + identity extraction (no network)
# ---------------------------------------------------------------------------


def test_pkce_pair_is_s256():
    import base64
    import hashlib

    verifier, challenge = generate_pkce_pair()
    expected = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    assert challenge == expected


def test_extract_identity_prefers_email():
    cfg = OIDCConfig(issuer=ISSUER, client_id=CLIENT_ID)
    cl = OIDCClient(cfg)
    assert cl.extract_identity({"email": "a@b.de", "preferred_username": "x"}) == "a@b.de"


def test_extract_identity_username_fallback_requires_at():
    cfg = OIDCConfig(issuer=ISSUER, client_id=CLIENT_ID)
    cl = OIDCClient(cfg)
    assert cl.extract_identity({"preferred_username": "plainuser"}) is None
    assert cl.extract_identity({"upn": "u@b.de"}) == "u@b.de"
    assert cl.extract_identity({"sub": "123"}) is None


def test_extract_identity_custom_claim():
    cfg = OIDCConfig(issuer=ISSUER, client_id=CLIENT_ID, identity_claims=["sub"])
    cl = OIDCClient(cfg)
    assert cl.extract_identity({"sub": "user-123", "email": "a@b.de"}) == "user-123"


# ---------------------------------------------------------------------------
# Discovery
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_discovery_is_cached(httpx_mock):
    cl = make_client(httpx_mock, add_jwks=False)
    m1 = await cl.discover()
    m2 = await cl.discover()
    assert m1.token_endpoint == TOKEN_ENDPOINT and m2.issuer == ISSUER
    discovery_calls = [r for r in httpx_mock.get_requests() if "openid-configuration" in str(r.url)]
    assert len(discovery_calls) == 1
    await cl.aclose()


@pytest.mark.asyncio
async def test_discovery_issuer_mismatch_rejected(httpx_mock):
    httpx_mock.add_response(url=DISCOVERY_URL, json={**DISCOVERY_DOC, "issuer": "https://evil.example.com"})
    cl = OIDCClient(OIDCConfig(issuer=ISSUER, client_id=CLIENT_ID))
    with pytest.raises(OIDCDiscoveryError):
        await cl.discover()
    await cl.aclose()


# ---------------------------------------------------------------------------
# Authorization URL + code exchange
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_build_authorization_url(httpx_mock):
    cl = make_client(httpx_mock, add_jwks=False)
    url = await cl.build_authorization_url(
        state="st", nonce="no", code_challenge="ch", redirect_uri="https://mcp.example.com/oauth/oidc/callback"
    )
    assert url.startswith(AUTH_ENDPOINT + "?")
    assert "code_challenge_method=S256" in url
    assert "client_id=kimai-mcp-client" in url
    assert "state=st" in url and "nonce=no" in url
    await cl.aclose()


@pytest.mark.asyncio
async def test_exchange_code_public_vs_confidential(httpx_mock):
    # public client (no secret)
    cl = make_client(httpx_mock, add_jwks=False)
    httpx_mock.add_response(url=TOKEN_ENDPOINT, method="POST", json={"id_token": "x", "access_token": "y"})
    out = await cl.exchange_code(code="abc", code_verifier="ver", redirect_uri="https://m/cb")
    assert out["id_token"] == "x"
    body = httpx_mock.get_requests(url=TOKEN_ENDPOINT)[-1].read().decode()
    assert "code_verifier=ver" in body and "client_secret" not in body
    await cl.aclose()

    # confidential client (secret included)
    cl2 = make_client(httpx_mock, add_discovery=False, add_jwks=False, client_secret="s3cr3t")
    httpx_mock.add_response(url=TOKEN_ENDPOINT, method="POST", json={"id_token": "x"})
    await cl2.exchange_code(code="abc", code_verifier="ver", redirect_uri="https://m/cb")
    body2 = httpx_mock.get_requests(url=TOKEN_ENDPOINT)[-1].read().decode()
    assert "client_secret=s3cr3t" in body2
    await cl2.aclose()


@pytest.mark.asyncio
async def test_exchange_code_error_status(httpx_mock):
    cl = make_client(httpx_mock, add_jwks=False)
    httpx_mock.add_response(url=TOKEN_ENDPOINT, method="POST", status_code=400, json={"error": "invalid_grant"})
    with pytest.raises(OIDCTokenExchangeError):
        await cl.exchange_code(code="abc", code_verifier="ver", redirect_uri="https://m/cb")
    await cl.aclose()


# ---------------------------------------------------------------------------
# id_token validation
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_validate_id_token_happy_path(httpx_mock):
    cl = make_client(httpx_mock)
    claims = await cl.validate_id_token(make_id_token(), expected_nonce="the-nonce")
    assert claims["email"] == "alice@firma.de"
    await cl.aclose()


@pytest.mark.asyncio
async def test_validate_rejects_bad_signature(httpx_mock):
    cl = make_client(httpx_mock)  # JWKS holds _PRIV's public key
    token = make_id_token(_OTHER_PRIV)  # signed by a different key
    with pytest.raises(OIDCValidationError):
        await cl.validate_id_token(token, expected_nonce="the-nonce")
    await cl.aclose()


@pytest.mark.asyncio
async def test_validate_rejects_wrong_audience(httpx_mock):
    cl = make_client(httpx_mock)
    with pytest.raises(OIDCValidationError):
        await cl.validate_id_token(make_id_token(aud="someone-else"), expected_nonce="the-nonce")
    await cl.aclose()


@pytest.mark.asyncio
async def test_validate_rejects_wrong_issuer(httpx_mock):
    cl = make_client(httpx_mock)
    with pytest.raises(OIDCValidationError):
        await cl.validate_id_token(make_id_token(iss="https://evil.example.com"), expected_nonce="the-nonce")
    await cl.aclose()


@pytest.mark.asyncio
async def test_validate_rejects_expired(httpx_mock):
    cl = make_client(httpx_mock)
    with pytest.raises(OIDCValidationError):
        await cl.validate_id_token(make_id_token(exp_delta=-3600), expected_nonce="the-nonce")
    await cl.aclose()


@pytest.mark.asyncio
async def test_validate_accepts_within_leeway(httpx_mock):
    cl = make_client(httpx_mock, clock_skew_seconds=120)
    # expired 30s ago, but within the 120s leeway
    claims = await cl.validate_id_token(make_id_token(exp_delta=-30), expected_nonce="the-nonce")
    assert claims["email"] == "alice@firma.de"
    await cl.aclose()


@pytest.mark.asyncio
async def test_validate_rejects_nonce_mismatch(httpx_mock):
    cl = make_client(httpx_mock)
    with pytest.raises(OIDCValidationError):
        await cl.validate_id_token(make_id_token(nonce="wrong"), expected_nonce="the-nonce")
    await cl.aclose()


@pytest.mark.asyncio
async def test_validate_rejects_alg_none(httpx_mock):
    # alg:none must be rejected before any network/JWKS lookup.
    cl = make_client(httpx_mock, add_discovery=False, add_jwks=False)
    with pytest.raises(OIDCValidationError):
        await cl.validate_id_token(make_id_token(alg="none"), expected_nonce="the-nonce")
    await cl.aclose()


@pytest.mark.asyncio
async def test_validate_handles_key_rotation(httpx_mock):
    # First JWKS lacks the token's kid; a refresh returns the right key set.
    stale_jwks = _jwks_for(_OTHER_PRIV, kid="old-key")
    httpx_mock.add_response(url=DISCOVERY_URL, json=DISCOVERY_DOC)
    httpx_mock.add_response(url=JWKS_URI, json=stale_jwks)  # first fetch (cold cache)
    httpx_mock.add_response(url=JWKS_URI, json=JWKS)  # forced refresh on kid miss
    cl = OIDCClient(OIDCConfig(issuer=ISSUER, client_id=CLIENT_ID))
    claims = await cl.validate_id_token(make_id_token(), expected_nonce="the-nonce")
    assert claims["email"] == "alice@firma.de"
    await cl.aclose()

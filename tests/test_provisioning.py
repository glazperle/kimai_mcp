"""Tests for automatic Kimai onboarding of federated (OIDC) logins.

The matching rules are the security-relevant part here: a wrong match would hand
one employee another employee's API token, so every rule is tested for the
single-match case *and* for the ambiguous case that must refuse to guess.
"""

import json
import stat
import sys
from typing import ClassVar

import pytest

from kimai_mcp import provisioning
from kimai_mcp.client import KimaiAPIError
from kimai_mcp.models import AccessTokenCreated, User
from kimai_mcp.provisioning import (
    ProvisionedUserStore,
    normalize,
    provision_token,
    resolve_kimai_user,
)
from kimai_mcp.user_config import SLUG_PATTERN, UserConfig, UsersConfig

KIMAI_URL = "https://kimai.example.com"


def user(
    user_id: int,
    username: str,
    alias: str | None = None,
    email: str | None = None,
    enabled: bool = True,
) -> User:
    return User(id=user_id, username=username, alias=alias, email=email, enabled=enabled)


# ---------------------------------------------------------------------------
# normalize()
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("value", "expected"),
    [
        ("Anna von Dorf", "annavondorf"),
        ("anna.vondorf", "annavondorf"),
        ("A.von-Dorf", "avondorf"),
        ("Jörg Müller", "joergmueller"),
        ("Weiß", "weiss"),
        ("José", "jose"),
        (None, ""),
        ("", ""),
    ],
)
def test_normalize(value, expected):
    assert normalize(value) == expected


# ---------------------------------------------------------------------------
# resolve_kimai_user() - one rule per test, strongest first
# ---------------------------------------------------------------------------


def test_matches_on_email():
    users = [user(1, "someone.else"), user(7, "asm", email="Anna.Smith@example.com")]
    result = resolve_kimai_user(users, "anna.smith@example.com")
    assert result.matched
    assert result.user.id == 7
    assert result.rule == "email"


def test_matches_on_username_equal_to_identity():
    users = [user(3, "anna.smith@example.com")]
    result = resolve_kimai_user(users, "anna.smith@example.com")
    assert result.user.id == 3
    assert result.rule == "username==identity"


def test_matches_on_username_equal_to_local_part():
    users = [user(4, "anna.smith")]
    result = resolve_kimai_user(users, "anna.smith@example.com")
    assert result.user.id == 4
    assert result.rule == "username==local-part"


def test_matches_normalized_alias():
    """anna.vondorf@ vs. the Kimai alias 'Anna von Dorf'."""
    users = [user(9, "avd", alias="Anna von Dorf")]
    result = resolve_kimai_user(users, "anna.vondorf@example.com")
    assert result.user.id == 9
    assert result.rule == "normalized"


def test_matches_display_name_claim():
    users = [user(11, "as2", alias="Anna Smith")]
    result = resolve_kimai_user(
        users, "a.smith.extern@example.com", display_name="Anna Smith", match_mode="fuzzy"
    )
    assert result.user.id == 11
    assert result.rule == "display-name"


def test_matches_given_and_family_name():
    users = [user(12, "jm", alias="Jörg Müller")]
    result = resolve_kimai_user(
        users, "jmueller99@example.com", given_name="Jörg", family_name="Müller",
        match_mode="fuzzy",
    )
    assert result.user.id == 12
    assert result.rule == "display-name"


def test_matches_short_alias_address_by_name_part():
    """anna@ vs. anna.vondorf@ - the same person with a shorter address."""
    users = [
        user(20, "anna.vondorf", email="anna.vondorf@example.com"),
        user(21, "sabine.schmidt", email="sabine.schmidt@example.com"),
    ]
    result = resolve_kimai_user(users, "anna@example.com", match_mode="fuzzy")
    assert result.user.id == 20
    assert result.rule == "name-part"


def test_matches_when_the_kimai_login_is_only_a_first_name():
    users = [user(23, "annabel")]
    result = resolve_kimai_user(users, "annabel.vondorf@example.com", match_mode="fuzzy")
    assert result.user.id == 23
    assert result.rule == "name-part"


def test_name_part_rule_ignores_too_short_fragments():
    """'avd' must not silently match 'avdhoffmann'."""
    users = [user(22, "avdhoffmann", email="avdhoffmann@example.com")]
    result = resolve_kimai_user(users, "avd@example.com", match_mode="fuzzy")
    assert not result.matched
    assert result.reason == "not_found"


def test_name_part_rule_does_not_match_a_mere_character_prefix():
    """maria@ must NOT be handed Mariana's account.

    This rule only ever runs for people who have no Kimai account of their own,
    i.e. exactly those who would silently receive a colleague's token.
    """
    users = [user(24, "mariana.schmidt", email="mariana.schmidt@example.com")]
    result = resolve_kimai_user(users, "maria@example.com", match_mode="fuzzy")
    assert not result.matched
    assert result.reason == "not_found"


def test_ambiguous_name_part_refuses_to_guess():
    users = [
        user(30, "anna.vondorf", email="anna.vondorf@example.com"),
        user(31, "anna.schmidt", email="anna.schmidt@example.com"),
    ]
    result = resolve_kimai_user(users, "anna@example.com", match_mode="fuzzy")
    assert not result.matched
    assert result.reason == "ambiguous"
    assert result.candidates == ["anna.schmidt", "anna.vondorf"]


def test_ambiguity_does_not_fall_through_to_weaker_rules():
    """Two users share the email; a weaker rule must not 'resolve' that for us."""
    users = [
        user(40, "a.smith", email="anna.smith@example.com"),
        user(41, "anna.smith", email="anna.smith@example.com"),
    ]
    result = resolve_kimai_user(users, "anna.smith@example.com")
    assert result.reason == "ambiguous"
    assert result.rule == "email"


def test_disabled_users_are_ignored():
    users = [user(50, "anna.smith", email="anna.smith@example.com", enabled=False)]
    result = resolve_kimai_user(users, "anna.smith@example.com")
    assert not result.matched
    assert result.reason == "not_found"


def test_no_users_at_all():
    assert resolve_kimai_user([], "anna.smith@example.com").reason == "not_found"


def test_email_match_is_case_insensitive():
    users = [user(60, "as", email="Anna.Smith@Example.COM")]
    assert resolve_kimai_user(users, "ANNA.SMITH@example.com").user.id == 60


# ---------------------------------------------------------------------------
# Match modes
# ---------------------------------------------------------------------------


def test_normalized_mode_does_not_apply_the_name_rules():
    """The default must not reach the two heuristics."""
    users = [user(20, "anna.vondorf", email="anna.vondorf@example.com")]
    assert resolve_kimai_user(users, "anna@example.com").reason == "not_found"


def test_exact_mode_does_not_apply_the_local_part_rule():
    users = [user(4, "anna.smith")]
    assert resolve_kimai_user(users, "anna.smith@example.com", match_mode="exact").reason == (
        "not_found"
    )


def test_an_identity_that_is_not_an_address_is_refused():
    """--oidc-identity-claim sub would otherwise feed a GUID to the name rules."""
    users = [user(1, "9f1c8b2e-0000-4a3d-9f11-abcdef012345")]
    result = resolve_kimai_user(users, "9f1c8b2e-0000-4a3d-9f11-abcdef012345", match_mode="fuzzy")
    assert not result.matched
    assert result.reason == "unsupported_identity"


# ---------------------------------------------------------------------------
# provision_token()
# ---------------------------------------------------------------------------


class FakeAdminClient:
    """Admin-side client: only create_api_token() is exercised."""

    def __init__(self, result=None, error: KimaiAPIError | None = None):
        self._result = result
        self._error = error
        self.calls: list[dict] = []

    async def create_api_token(self, user_id: int, name: str, replace_existing: bool = True):
        self.calls.append(
            {"user_id": user_id, "name": name, "replace_existing": replace_existing}
        )
        if self._error is not None:
            raise self._error
        return self._result


class FakeProbeClient:
    """Stands in for the KimaiClient built from the freshly minted token."""

    def __init__(self, me: User | None = None, error: KimaiAPIError | None = None):
        self.me = me
        self.error = error
        self.closed = False

    def __call__(self, base_url, api_token, **kwargs):
        self.base_url = base_url
        self.api_token = api_token
        self.kwargs = kwargs
        return self

    async def get_current_user(self):
        if self.error is not None:
            raise self.error
        return self.me

    async def close(self):
        self.closed = True


@pytest.fixture
def target_user():
    return user(7, "anna.smith", email="anna.smith@example.com")


@pytest.mark.asyncio
async def test_provision_token_returns_verified_token(monkeypatch, target_user):
    admin = FakeAdminClient(
        AccessTokenCreated(id=1, name="Kimai MCP (auto)", token="secret-token")
    )
    probe = FakeProbeClient(me=target_user)
    monkeypatch.setattr(provisioning, "KimaiClient", probe)

    token = await provision_token(
        admin, KIMAI_URL, target_user, token_name="Kimai MCP (auto)"
    )

    assert token == "secret-token"
    assert admin.calls == [
        {"user_id": 7, "name": "Kimai MCP (auto)", "replace_existing": True}
    ]
    assert probe.api_token == "secret-token"
    assert probe.closed


@pytest.mark.asyncio
async def test_provision_token_passes_ssl_verify_to_the_probe(monkeypatch, target_user):
    admin = FakeAdminClient(AccessTokenCreated(id=1, name="n", token="tok"))
    probe = FakeProbeClient(me=target_user)
    monkeypatch.setattr(provisioning, "KimaiClient", probe)

    await provision_token(admin, KIMAI_URL, target_user, ssl_verify="/etc/ssl/corp.pem")

    assert probe.kwargs["ssl_verify"] == "/etc/ssl/corp.pem"


@pytest.mark.asyncio
async def test_provision_token_missing_plugin_returns_none(monkeypatch, target_user):
    admin = FakeAdminClient(error=KimaiAPIError("Not Found", 404))
    monkeypatch.setattr(provisioning, "KimaiClient", FakeProbeClient(me=target_user))

    assert await provision_token(admin, KIMAI_URL, target_user) is None


@pytest.mark.asyncio
async def test_provision_token_without_permission_returns_none(monkeypatch, target_user):
    admin = FakeAdminClient(error=KimaiAPIError("Forbidden", 403))
    monkeypatch.setattr(provisioning, "KimaiClient", FakeProbeClient(me=target_user))

    assert await provision_token(admin, KIMAI_URL, target_user) is None


@pytest.mark.asyncio
async def test_provision_token_discards_token_of_a_different_user(monkeypatch, target_user):
    """The safety net: a token that resolves elsewhere is never handed out."""
    admin = FakeAdminClient(AccessTokenCreated(id=1, name="MCP", token="wrong-token"))
    other = user(99, "someone.else")
    monkeypatch.setattr(provisioning, "KimaiClient", FakeProbeClient(me=other))

    assert await provision_token(admin, KIMAI_URL, target_user) is None


@pytest.mark.asyncio
async def test_provision_token_unverifiable_token_returns_none(monkeypatch, target_user):
    admin = FakeAdminClient(AccessTokenCreated(id=1, name="MCP", token="tok"))
    probe = FakeProbeClient(error=KimaiAPIError("Unauthorized", 401))
    monkeypatch.setattr(provisioning, "KimaiClient", probe)

    assert await provision_token(admin, KIMAI_URL, target_user) is None
    assert probe.closed


# ---------------------------------------------------------------------------
# Slug generation
# ---------------------------------------------------------------------------


def test_generated_slug_is_url_safe_and_not_low_entropy():
    from kimai_mcp.streamable_http_server import is_low_entropy_slug

    slug = provisioning.KimaiProvisioner.generate_slug()
    assert SLUG_PATTERN.match(slug)
    assert not is_low_entropy_slug(slug)


def test_generated_slug_avoids_taken_ones():
    taken = {provisioning.KimaiProvisioner.generate_slug() for _ in range(5)}
    assert provisioning.KimaiProvisioner.generate_slug(taken) not in taken


# ---------------------------------------------------------------------------
# ProvisionedUserStore
# ---------------------------------------------------------------------------


def _config(token: str = "tok") -> UserConfig:
    return UserConfig(kimai_url=KIMAI_URL, kimai_token=token, oidc_identity="anna@example.com")


def test_store_round_trip(tmp_path):
    path = tmp_path / "provisioned.json"
    store = ProvisionedUserStore(path)
    store.add("Anna@Example.com", "sLuG-1", _config())

    users = UsersConfig()
    assert store.load_into(users) == 1
    slug, config = users.get_user_by_oidc_identity("anna@example.com")
    assert slug == "sLuG-1"
    assert config.kimai_token == "tok"
    # Identity is stored folded, so a differently cased login still matches.
    assert json.loads(path.read_text())["anna@example.com"]["slug"] == "sLuG-1"


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")
def test_store_file_is_not_world_readable(tmp_path):
    path = tmp_path / "provisioned.json"
    ProvisionedUserStore(path).add("anna@example.com", "slug1", _config())
    assert stat.S_IMODE(path.stat().st_mode) == 0o600


def test_store_never_overrides_a_configured_user(tmp_path):
    path = tmp_path / "provisioned.json"
    ProvisionedUserStore(path).add("anna@example.com", "provisioned", _config("stale"))

    users = UsersConfig(
        users={
            "handwritten": UserConfig(
                kimai_url=KIMAI_URL, kimai_token="real", oidc_identity="anna@example.com"
            )
        }
    )
    assert ProvisionedUserStore(path).load_into(users) == 0
    slug, config = users.get_user_by_oidc_identity("anna@example.com")
    assert slug == "handwritten"
    assert config.kimai_token == "real"


def test_store_survives_a_corrupt_file(tmp_path):
    path = tmp_path / "provisioned.json"
    path.write_text("{ not json")
    users = UsersConfig()
    assert ProvisionedUserStore(path).load_into(users) == 0
    assert users.users == {}


def test_missing_store_file_is_not_an_error(tmp_path):
    assert ProvisionedUserStore(tmp_path / "absent.json").load_into(UsersConfig()) == 0


# ---------------------------------------------------------------------------
# KimaiProvisioner.provision()
# ---------------------------------------------------------------------------


class FakeProvisioningKimai:
    """Serves as both the admin client and the probe built from the new token."""

    calls: ClassVar[list[dict]] = []

    def __init__(self, base_url, api_token, **kwargs):
        self.api_token = api_token

    async def get_users(self, **kwargs):
        return [user(7, "anna.smith", email="anna.smith@example.com")]

    async def create_api_token(self, user_id, name, replace_existing=True):
        type(self).calls.append({"user_id": user_id, "name": name})
        return AccessTokenCreated(id=1, name=name, token=f"minted-{user_id}")

    async def get_current_user(self):
        return user(7, "anna.smith", email="anna.smith@example.com")

    async def close(self):
        pass


@pytest.mark.asyncio
async def test_parallel_sign_ins_mint_exactly_one_token(monkeypatch):
    """Two callbacks racing for the same identity must not create two tokens."""
    import asyncio

    FakeProvisioningKimai.calls = []
    monkeypatch.setattr(provisioning, "KimaiClient", FakeProvisioningKimai)

    provisioner = provisioning.KimaiProvisioner(
        provisioning.ProvisioningConfig(kimai_url=KIMAI_URL, admin_token="admin")
    )
    users = UsersConfig()
    claims = {"email": "anna.smith@example.com"}

    results = await asyncio.gather(
        provisioner.provision("anna.smith@example.com", claims, users),
        provisioner.provision("anna.smith@example.com", claims, users),
    )

    assert len(FakeProvisioningKimai.calls) == 1
    assert len(users.users) == 1
    assert results[0][0] == results[1][0]


# ---------------------------------------------------------------------------
# _build_provisioning_config()
# ---------------------------------------------------------------------------


def _args(**overrides):
    import argparse

    defaults = {
        "auto_provision": False,
        "provision_kimai_url": None,
        "provision_admin_token": None,
        "provision_token_name": None,
        "provision_match": None,
        "provision_store": None,
        "provision_ssl_verify": None,
    }
    return argparse.Namespace(**{**defaults, **overrides})


def _oidc():
    from kimai_mcp.oidc import OIDCConfig

    return OIDCConfig(issuer="https://idp.test", client_id="cid")


def _build(args, oidc_config):
    from kimai_mcp.streamable_http_server import _build_provisioning_config

    return _build_provisioning_config(args, oidc_config)


def test_provisioning_config_is_none_when_the_feature_is_off(monkeypatch):
    monkeypatch.delenv("KIMAI_MCP_AUTO_PROVISION", raising=False)
    assert _build(_args(), _oidc()) is None


def test_provisioning_requires_the_oidc_backend(monkeypatch):
    monkeypatch.delenv("KIMAI_MCP_AUTO_PROVISION", raising=False)
    with pytest.raises(ValueError, match="--auth-backend oidc"):
        _build(_args(auto_provision=True), None)


def test_provisioning_names_the_flags_it_is_missing(monkeypatch):
    monkeypatch.delenv("KIMAI_MCP_PROVISION_KIMAI_URL", raising=False)
    monkeypatch.delenv("KIMAI_MCP_PROVISION_ADMIN_TOKEN", raising=False)
    with pytest.raises(ValueError, match="--provision-") as excinfo:
        _build(_args(auto_provision=True), _oidc())
    assert "--provision-kimai-url" in str(excinfo.value)
    assert "--provision-admin-token" in str(excinfo.value)


def test_provisioning_config_from_env(monkeypatch):
    monkeypatch.setenv("KIMAI_MCP_AUTO_PROVISION", "true")
    monkeypatch.setenv("KIMAI_MCP_PROVISION_KIMAI_URL", KIMAI_URL + "/")
    monkeypatch.setenv("KIMAI_MCP_PROVISION_ADMIN_TOKEN", "from-env")
    monkeypatch.setenv("KIMAI_MCP_PROVISION_MATCH", "fuzzy")

    config = _build(_args(), _oidc())

    assert config.kimai_url == KIMAI_URL
    assert config.admin_token == "from-env"
    assert config.match_mode == "fuzzy"
    assert config.token_name == provisioning.DEFAULT_TOKEN_NAME
    assert config.store_path is None


def test_cli_flags_win_over_the_environment(monkeypatch):
    monkeypatch.setenv("KIMAI_MCP_PROVISION_ADMIN_TOKEN", "from-env")
    config = _build(
        _args(
            auto_provision=True,
            provision_kimai_url=KIMAI_URL,
            provision_admin_token="from-cli",
        ),
        _oidc(),
    )
    assert config.admin_token == "from-cli"

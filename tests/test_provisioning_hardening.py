"""Regression tests for the auto-provisioning hardening pass.

Each test here fails without its fix. They are kept apart from
``test_provisioning.py`` because they document specific defects rather than the
feature's intended behaviour, and every one of them names the failure it guards
against.

The security-relevant theme is the same throughout: a wrong match, or a leaked
store, hands one employee another employee's Kimai API token.
"""

import json
import stat
import sys
import unicodedata

import pytest

from kimai_mcp import provisioning
from kimai_mcp.models import User
from kimai_mcp.provisioning import (
    ProvisionedUserStore,
    ProvisioningConfig,
    normalize,
    resolve_kimai_user,
)
from kimai_mcp.user_config import UserConfig, UsersConfig, atomic_write_json

KIMAI_URL = "https://kimai.example.com"


def user(
    user_id: int,
    username: str,
    alias: str | None = None,
    email: str | None = None,
    enabled: bool = True,
) -> User:
    return User(id=user_id, username=username, alias=alias, email=email, enabled=enabled)


def _config(token: str = "tok") -> UserConfig:
    return UserConfig(kimai_url=KIMAI_URL, kimai_token=token)


# ---------------------------------------------------------------------------
# Domain allow-list
#
# Every rule below the two exact ones compares the address *local part*, so it
# says nothing about which domain asserted the identity. With an issuer that can
# assert more than one, that alone is enough to be onboarded as somebody else.
# ---------------------------------------------------------------------------


def test_foreign_domain_is_refused_when_domains_are_restricted():
    users = [user(5, "anna.vondorf", alias="Anna von Dorf")]

    result = resolve_kimai_user(
        users, "anna.vondorf@attacker.example", allowed_domains=["corp.example"]
    )

    assert result.user is None
    assert result.reason == "domain_not_allowed"


def test_allowed_domain_still_matches():
    users = [user(5, "anna.vondorf", alias="Anna von Dorf")]

    result = resolve_kimai_user(
        users, "anna.vondorf@corp.example", allowed_domains=["corp.example"]
    )

    assert result.user is not None
    assert result.user.id == 5


def test_domain_check_is_case_insensitive():
    users = [user(5, "anna.vondorf")]

    result = resolve_kimai_user(
        users, "Anna.VonDorf@CORP.example", allowed_domains=["corp.example"]
    )

    assert result.matched


def test_without_the_list_any_domain_is_accepted():
    """The documented default, and the reason the startup warning exists."""
    users = [user(5, "anna.vondorf")]

    result = resolve_kimai_user(users, "anna.vondorf@somewhere-else.example")

    assert result.matched


def test_allowed_domains_parses_a_comma_separated_string():
    """CLI flags and environment variables arrive as one string."""
    config = ProvisioningConfig(
        kimai_url=KIMAI_URL,
        admin_token="t",
        allowed_domains=" Corp.Example , @corp.de ,, ",
    )

    assert config.allowed_domains == ["corp.example", "corp.de"]


# ---------------------------------------------------------------------------
# The evidence guard on the weaker rules
# ---------------------------------------------------------------------------


def test_short_given_name_no_longer_disables_the_normalized_rule():
    """The guard counted parts *after* the four-character floor had dropped some.

    ``max.mustermann`` reduced to ``{mustermann}``, so "at least two name parts"
    was false and the rule switched itself off, although the folded forms are
    equal. Hits every short given name: max., tim., jan., eva., uwe., ben., leo.
    """
    users = [user(5, "mmustermann", alias="Max Mustermann")]

    result = resolve_kimai_user(users, "max.mustermann@corp.example")

    assert result.user is not None
    assert result.user.id == 5


def test_a_bare_given_name_is_still_not_evidence():
    """The guard's actual purpose has to survive the fix above."""
    users = [user(5, "k.lehmann", alias="Max"), user(6, "m.mustermann")]

    result = resolve_kimai_user(users, "max@corp.example")

    assert result.user is None


def test_fuzzy_display_name_needs_more_than_a_given_name():
    """An IdP-editable display name equal to a colleague's alias must not match.

    A missing ``family_name`` collapses the full name to the given name, and the
    display-name rule carried no evidence guard at all, so this produced exactly
    one candidate and minted Kai Lehmann's token for Max Mustermann.
    """
    users = [user(5, "k.lehmann", alias="Max")]

    result = resolve_kimai_user(
        users, "max.mustermann@corp.example", given_name="Max", match_mode="fuzzy"
    )

    assert result.user is None


def test_fuzzy_display_name_still_matches_a_full_name():
    users = [user(5, "k.lehmann", alias="Anna von Dorf")]

    result = resolve_kimai_user(
        users,
        "a.vondorf@corp.example",
        given_name="Anna",
        family_name="von Dorf",
        match_mode="fuzzy",
    )

    assert result.user is not None
    assert result.user.id == 5


def test_normalize_folds_decomposed_and_composed_alike():
    """NFD input (macOS, some AD/LDAP exports) folded to 'muller', NFC to 'mueller'."""
    composed = "Müller"
    decomposed = unicodedata.normalize("NFD", composed)

    assert normalize(composed) == normalize(decomposed) == "mueller"


# ---------------------------------------------------------------------------
# ssl_verify agreeing across the two models that carry it
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    ("raw", "expected"),
    [("true", True), ("false", False), ("True", True), ("/etc/ca.pem", "/etc/ca.pem")],
)
def test_ssl_verify_is_coerced_like_user_config(raw, expected):
    """ProvisioningConfig copied the field's type but not its validator.

    The smart union kept "false" as a string, which httpx reads as a CA bundle
    path and rejects in its own constructor, during startup.
    """
    provisioning_value = ProvisioningConfig(
        kimai_url=KIMAI_URL, admin_token="t", ssl_verify=raw
    ).ssl_verify
    user_value = UserConfig(kimai_url=KIMAI_URL, kimai_token="t", ssl_verify=raw).ssl_verify

    assert provisioning_value == user_value == expected


# ---------------------------------------------------------------------------
# Store robustness
# ---------------------------------------------------------------------------


@pytest.mark.parametrize(
    "payload",
    ["[]", "null", '"a string"', '{"a@b.c": "not an object"}', '{"a@b.c": 42}'],
)
def test_a_store_of_the_wrong_shape_does_not_stop_the_server(tmp_path, payload):
    """Valid JSON of the wrong shape used to raise AttributeError.

    ``load_into`` runs synchronously from the server's ``__init__``, so this took
    the whole multi-user process down and every hand-configured user with it.
    """
    path = tmp_path / "provisioned.json"
    path.write_text(payload, encoding="utf-8")
    users = UsersConfig()

    assert ProvisionedUserStore(path).load_into(users) == 0
    assert users.users == {}


def test_add_replaces_a_store_of_the_wrong_shape_instead_of_crashing(tmp_path):
    path = tmp_path / "provisioned.json"
    path.write_text("[]", encoding="utf-8")

    ProvisionedUserStore(path).add("anna@example.com", "slug1", _config())

    assert json.loads(path.read_text(encoding="utf-8"))["anna@example.com"]["slug"] == "slug1"


def test_add_merges_instead_of_overwriting(tmp_path):
    """Read-modify-write across identities; the existing tests all use one."""
    path = tmp_path / "provisioned.json"
    store = ProvisionedUserStore(path)

    store.add("anna@example.com", "slug1", _config("tok-a"))
    store.add("bob@example.com", "slug2", _config("tok-b"))

    data = json.loads(path.read_text(encoding="utf-8"))
    assert data["anna@example.com"]["kimai_token"] == "tok-a"
    assert data["bob@example.com"]["kimai_token"] == "tok-b"


def test_remove_forgets_one_identity(tmp_path):
    """Without this, a token Kimai no longer accepts survived every restart."""
    path = tmp_path / "provisioned.json"
    store = ProvisionedUserStore(path)
    store.add("anna@example.com", "slug1", _config())
    store.add("bob@example.com", "slug2", _config())

    store.remove("Anna@Example.com")  # folded, the way add() stores it

    data = json.loads(path.read_text(encoding="utf-8"))
    assert "anna@example.com" not in data
    assert "bob@example.com" in data


def test_remove_is_a_no_op_for_an_unknown_identity(tmp_path):
    path = tmp_path / "provisioned.json"
    store = ProvisionedUserStore(path)
    store.add("anna@example.com", "slug1", _config())

    store.remove("nobody@example.com")

    assert "anna@example.com" in json.loads(path.read_text(encoding="utf-8"))


@pytest.mark.skipif(sys.platform == "win32", reason="POSIX file modes only")
def test_the_temp_file_is_never_world_readable(tmp_path, monkeypatch):
    """The mode has to be right *while* the tokens are being written.

    The final file's mode was already asserted, and passed: chmod ran after the
    write had closed, so the temp file spent the whole write, plus an fsync, at
    the process umask with plaintext tokens inside it.
    """
    path = tmp_path / "provisioned.json"
    seen = {}
    real_dump = json.dump

    def spy(obj, fp, **kwargs):
        tmp = path.with_suffix(path.suffix + ".tmp")
        seen["mode"] = stat.S_IMODE(tmp.stat().st_mode)
        return real_dump(obj, fp, **kwargs)

    monkeypatch.setattr(json, "dump", spy)
    ProvisionedUserStore(path).add("anna@example.com", "slug1", _config())

    assert seen["mode"] == 0o600
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.glob("*.tmp")) == []


def test_atomic_write_replaces_a_stale_temp_file(tmp_path):
    """A SIGKILL mid-write used to strand a temp file full of tokens forever."""
    path = tmp_path / "provisioned.json"
    stale = path.with_suffix(path.suffix + ".tmp")
    stale.write_text('{"leftover": "from a crash"}', encoding="utf-8")

    atomic_write_json(path, {"anna@example.com": {"kimai_token": "tok"}})

    assert json.loads(path.read_text(encoding="utf-8"))["anna@example.com"]["kimai_token"] == "tok"
    assert not stale.exists()


# ---------------------------------------------------------------------------
# Provisioned vs. declared users
# ---------------------------------------------------------------------------


def test_only_provisioned_users_can_be_forgotten():
    """A hand-written token is what the operator put there; it is never dropped."""
    users = UsersConfig(users={"declared": _config("from-users-json")})
    users.add_user("auto", _config("minted"))

    assert users.remove_provisioned_user("declared") is None
    assert "declared" in users.users

    removed = users.remove_provisioned_user("auto")
    assert removed is not None
    assert removed.kimai_token == "minted"
    assert "auto" not in users.users


def test_loading_a_store_marks_its_users_as_provisioned(tmp_path):
    """Otherwise a restart would turn them into undroppable entries."""
    path = tmp_path / "provisioned.json"
    ProvisionedUserStore(path).add("anna@example.com", "slug1", _config())
    users = UsersConfig()

    ProvisionedUserStore(path).load_into(users)

    assert "slug1" in users.provisioned_slugs
    assert users.remove_provisioned_user("slug1") is not None


def test_provisioned_slugs_are_not_serialized():
    """It is runtime bookkeeping, not configuration."""
    users = UsersConfig()
    users.add_user("auto", _config())

    assert "provisioned_slugs" not in users.model_dump()


# ---------------------------------------------------------------------------
# Per-identity locking
# ---------------------------------------------------------------------------


@pytest.mark.asyncio
async def test_distinct_identities_do_not_block_each_other():
    """One process-wide lock serialized every sign-in across all Kimai calls.

    On a rollout day the queue outlived the five-minute TTL of the OIDC login
    state, so queued users got "Invalid or expired sign-in state" and retried.
    """
    import asyncio

    provisioner = provisioning.KimaiProvisioner(
        ProvisioningConfig(kimai_url=KIMAI_URL, admin_token="t")
    )
    inside = []

    async def hold(identity):
        async with provisioner._identity_lock(identity):
            inside.append(identity)
            await asyncio.sleep(0.05)
            inside.remove(identity)

    await asyncio.gather(hold("a@x.example"), hold("b@x.example"))
    # Both were inside at once, or the gather would have taken twice as long;
    # the lock map is empty again either way.
    assert provisioner._locks == {}


@pytest.mark.asyncio
async def test_the_same_identity_is_still_serialized():
    """The invariant the lock exists for: never mint two tokens for one user."""
    import asyncio

    provisioner = provisioning.KimaiProvisioner(
        ProvisioningConfig(kimai_url=KIMAI_URL, admin_token="t")
    )
    events = []

    async def hold(identity):
        async with provisioner._identity_lock(identity):
            events.append("enter")
            await asyncio.sleep(0.02)
            events.append("exit")

    # Same identity, different spellings: add() folds it, so the lock must too.
    await asyncio.gather(hold("anna@example.com"), hold("Anna@Example.com"))

    assert events == ["enter", "exit", "enter", "exit"]
    assert provisioner._locks == {}


# ---------------------------------------------------------------------------
# Server-side lifecycle
# ---------------------------------------------------------------------------


def _server(users_config, monkeypatch, *, provisioning=True, store_path=None, failing=False):
    """A server instance without a running lifespan, for unit-level checks."""
    from kimai_mcp.streamable_http_server import StreamableHTTPMCPServer

    class FakeVersion:
        version = "2.65.0"

    class FakeKimaiClient:
        def __init__(self, **kwargs):
            pass

        async def get_version(self):
            if failing:
                raise RuntimeError("Kimai unreachable")
            return FakeVersion()

        async def close(self):
            pass

    monkeypatch.setattr("kimai_mcp.streamable_http_server.KimaiClient", FakeKimaiClient)
    kwargs = {"users_config": users_config, "public_url": "http://localhost:8000"}
    if provisioning:
        kwargs["provisioning_config"] = ProvisioningConfig(
            kimai_url=KIMAI_URL, admin_token="t", store_path=store_path
        )
    return StreamableHTTPMCPServer(**kwargs)


@pytest.mark.asyncio
async def test_declared_users_still_fail_fast_when_none_can_start(monkeypatch):
    """The guard keyed on the provisioner instead of on whether anyone was declared.

    A deployment with users in users.json and an unreachable Kimai started
    anyway and served /health 200 with user_count 0, so no orchestrator restart
    and no alert ever fired.
    """
    users = UsersConfig(users={"declaredUserSlug16": _config()})
    server = _server(users, monkeypatch, failing=True)

    with pytest.raises(RuntimeError, match="No user sessions"):
        await server.initialize_users()


@pytest.mark.asyncio
async def test_a_provisioning_only_deployment_still_boots_empty(monkeypatch):
    """The case the softened guard exists for must keep working."""
    server = _server(UsersConfig(), monkeypatch, failing=True)

    await server.initialize_users()  # must not raise

    assert server.user_sessions == {}


@pytest.mark.asyncio
async def test_a_rejected_token_forgets_a_provisioned_user(monkeypatch, tmp_path):
    """Kimai answering 401 has to be recoverable, not permanent.

    provision() short-circuits on a stored entry before contacting Kimai, and
    the OIDC callback only calls it when nothing matches, so a revoked token
    used to survive every restart and every fresh sign-in: 503 forever.
    """
    store_path = tmp_path / "provisioned.json"
    ProvisionedUserStore(store_path).add("anna@example.com", "autoSlug12345678", _config())
    users = UsersConfig()
    ProvisionedUserStore(store_path).load_into(users)
    server = _server(users, monkeypatch, store_path=str(store_path))

    await server._handle_auth_failure("autoSlug12345678")

    assert "autoSlug12345678" not in users.users
    assert json.loads(store_path.read_text(encoding="utf-8")) == {}


@pytest.mark.asyncio
async def test_a_rejected_token_never_deletes_a_declared_user(monkeypatch):
    """Its token is what the operator wrote down; only the session is dropped."""
    users = UsersConfig(users={"declaredUserSlug16": _config()})
    server = _server(users, monkeypatch)

    await server._handle_auth_failure("declaredUserSlug16")

    assert "declaredUserSlug16" in users.users


@pytest.mark.asyncio
async def test_idle_provisioned_sessions_are_released(monkeypatch):
    """Otherwise every directory member who signed in once cost a connection pool."""
    import time as _time

    from kimai_mcp.streamable_http_server import UserMCPSession

    users = UsersConfig(users={"declaredUserSlug16": _config()})
    users.add_user("autoSlug12345678", _config())
    server = _server(users, monkeypatch)

    for slug in ("declaredUserSlug16", "autoSlug12345678"):
        server.user_sessions[slug] = UserMCPSession(slug, users.users[slug])
        server._session_last_used[slug] = _time.time() - 10_000  # long idle

    await server._sweep_idle_sessions()

    # The provisioned one is released; the declared one is left alone.
    assert "autoSlug12345678" not in server.user_sessions
    assert "declaredUserSlug16" in server.user_sessions
    # Its configuration survives, so the next request rebuilds the session.
    assert "autoSlug12345678" in users.users


@pytest.mark.asyncio
async def test_a_recently_used_provisioned_session_is_kept(monkeypatch):
    from kimai_mcp.streamable_http_server import UserMCPSession

    users = UsersConfig()
    users.add_user("autoSlug12345678", _config())
    server = _server(users, monkeypatch)
    server.user_sessions["autoSlug12345678"] = UserMCPSession(
        "autoSlug12345678", users.users["autoSlug12345678"]
    )
    server._session_last_used["autoSlug12345678"] = __import__("time").time()

    await server._sweep_idle_sessions()

    assert "autoSlug12345678" in server.user_sessions

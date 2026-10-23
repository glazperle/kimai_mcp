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

    await server._forget_credentials("autoSlug12345678")

    assert "autoSlug12345678" not in users.users
    assert json.loads(store_path.read_text(encoding="utf-8")) == {}


@pytest.mark.asyncio
async def test_a_rejected_token_never_deletes_a_declared_user(monkeypatch):
    """Its token is what the operator wrote down; only the session is dropped."""
    users = UsersConfig(users={"declaredUserSlug16": _config()})
    server = _server(users, monkeypatch)

    await server._forget_credentials("declaredUserSlug16")

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


class _Kimai:
    """A fake KimaiClient whose GET /version yields, so concurrent requests interleave."""

    inits: list  # set per test (_serving_server)
    answer: object = None  # an exception to raise, or None for success

    def __init__(self, base_url, api_token, **kwargs):
        self.token = api_token

    async def get_version(self):
        import asyncio

        type(self).inits.append(self.token)
        await asyncio.sleep(0)
        if type(self).answer is not None:
            raise type(self).answer

        class Version:
            version = "2.70.2"

        return Version()

    async def close(self):
        pass


def _serving_server(users, monkeypatch, *, answer=None, store_path=None):
    """A server whose on-demand inits run, with a manager start that yields."""
    import asyncio

    from kimai_mcp.streamable_http_server import StreamableHTTPMCPServer

    kimai = type("Kimai", (_Kimai,), {"inits": [], "answer": answer})
    monkeypatch.setattr("kimai_mcp.streamable_http_server.KimaiClient", kimai)
    provisioning_config = ProvisioningConfig(kimai_url=KIMAI_URL, admin_token="t", store_path=store_path)
    server = StreamableHTTPMCPServer(
        users_config=users, public_url="http://localhost:8000", provisioning_config=provisioning_config
    )
    server._serving = True

    async def start(session):
        await asyncio.sleep(0)
        server._session_manager_tasks[session.user_slug] = asyncio.create_task(asyncio.Event().wait())

    server._start_session_manager = start
    return server, kimai


def _rejected_session(server, slug):
    from kimai_mcp.streamable_http_server import UserMCPSession

    old = UserMCPSession(slug, server.users_config.users[slug])
    old.session_manager = object()
    old.token_rejected = True
    server.user_sessions[slug] = old
    return old


@pytest.mark.asyncio
async def test_a_rejected_session_is_rebuilt_once_on_the_next_request(monkeypatch):
    """The call that saw the 401 only marks the session; tearing it down inside
    that call cancelled the call itself. Concurrent requests rebuild it once
    (every step yields here, so without the lock each would rebuild)."""
    import asyncio

    users = UsersConfig(users={"declaredUserSlug16": _config()})
    server, kimai = _serving_server(users, monkeypatch)
    old = _rejected_session(server, "declaredUserSlug16")

    first, second, third = await asyncio.gather(*(server._ensure_session("declaredUserSlug16") for _ in range(3)))

    assert first is second is third
    assert first is not old
    assert first.token_rejected is False
    assert kimai.inits == ["tok"]
    await server._stop_session_managers()


@pytest.mark.asyncio
async def test_a_failed_rebuild_is_not_repeated_by_the_requests_that_waited(monkeypatch):
    """Each queued request re-ran the init behind the failed one, one after another."""
    import asyncio

    from kimai_mcp.client import KimaiAPIError
    from kimai_mcp.streamable_http_server import INIT_RETRY_SECONDS

    users = UsersConfig(users={"declaredUserSlug16": _config()})
    server, kimai = _serving_server(users, monkeypatch, answer=KimaiAPIError("Unauthorized", 401))
    _rejected_session(server, "declaredUserSlug16")

    results = await asyncio.gather(*(server._ensure_session("declaredUserSlug16") for _ in range(3)))

    assert results == [None, None, None]
    assert kimai.inits == ["tok"]
    assert "declaredUserSlug16" in users.users  # a declared user is never forgotten
    # The next request too: a revoked token fails the same way every time.
    assert await server._ensure_session("declaredUserSlug16") is None
    assert kimai.inits == ["tok"]
    # A later one tries again: Kimai may accept the token by now.
    server._init_failed_at["declaredUserSlug16"] -= INIT_RETRY_SECONDS
    assert await server._ensure_session("declaredUserSlug16") is None
    assert kimai.inits == ["tok", "tok"]
    await server._stop_session_managers()


@pytest.mark.asyncio
async def test_one_users_slow_init_does_not_hold_up_another(monkeypatch):
    import asyncio

    users = UsersConfig(users={"slowUserSlug12345": _config("slow"), "fastUserSlug12345": _config("fast")})
    gate = asyncio.Event()
    server, kimai = _serving_server(users, monkeypatch)

    async def get_version(self):
        if self.token == "slow":
            await gate.wait()

        class Version:
            version = "2.70.2"

        return Version()

    monkeypatch.setattr(kimai, "get_version", get_version)
    slow = asyncio.create_task(server._ensure_session("slowUserSlug12345"))
    await asyncio.sleep(0)

    fast = await asyncio.wait_for(server._ensure_session("fastUserSlug12345"), 1)

    assert fast is not None
    gate.set()
    assert await slow is not None
    await server._stop_session_managers()


@pytest.mark.asyncio
async def test_a_request_waiting_while_the_user_is_forgotten_gets_no_session(monkeypatch):
    """It read users_config[slug] after the slug was removed: KeyError, HTTP 500."""
    import asyncio

    from kimai_mcp.client import KimaiAPIError

    users = UsersConfig()
    users.add_user("autoSlug12345678", _config())
    server, kimai = _serving_server(users, monkeypatch, answer=KimaiAPIError("Unauthorized", 401))

    results = await asyncio.gather(*(server._ensure_session("autoSlug12345678") for _ in range(2)))

    assert results == [None, None]
    assert "autoSlug12345678" not in users.users
    assert kimai.inits == ["tok"]


@pytest.mark.asyncio
async def test_a_401_in_a_call_forgets_a_provisioned_user_at_once(monkeypatch, tmp_path):
    """Forgotten only on the next request, a sign-in made right after the 401
    matched the dead entry, and the idle sweep or a restart lost the mark."""
    from types import SimpleNamespace

    from mcp.types import TextContent

    store_path = tmp_path / "provisioned.json"
    ProvisionedUserStore(store_path).add("anna@example.com", "autoSlug12345678", _config())
    users = UsersConfig()
    ProvisionedUserStore(store_path).load_into(users)
    server, _ = _serving_server(users, monkeypatch, store_path=str(store_path))
    session = server._new_session("autoSlug12345678", users.users["autoSlug12345678"])
    session.kimai_client = SimpleNamespace(unauthorized=False)

    async def dispatch(client, name, arguments):
        client.unauthorized = True
        return [TextContent(type="text", text="Deleted: 0, Failed: 1")]

    monkeypatch.setattr("kimai_mcp.streamable_http_server.dispatch_tool", dispatch)

    result = await session._call_tool(None, SimpleNamespace(name="timesheet", arguments={}))

    assert result.is_error is not True
    assert session.token_rejected is True
    assert "autoSlug12345678" not in users.users
    assert json.loads(store_path.read_text(encoding="utf-8")) == {}
    assert users.get_user_by_oidc_identity("anna@example.com") is None


@pytest.mark.asyncio
async def test_a_session_start_answered_with_401_forgets_a_provisioned_user(monkeypatch):
    """After a restart (or the idle sweep) no session carries the mark any more:
    the user's next request starts one, and Kimai's 401 there forgets them."""
    from kimai_mcp.client import KimaiAPIError

    users = UsersConfig()
    users.add_user("autoSlug12345678", _config())
    server, _ = _serving_server(users, monkeypatch, answer=KimaiAPIError("Unauthorized", 401))

    assert await server._ensure_session("autoSlug12345678") is None

    assert "autoSlug12345678" not in users.users


@pytest.mark.asyncio
async def test_an_init_answered_with_401_forgets_a_provisioned_user(monkeypatch):
    """A token revoked while the server was down: kept, the user's first
    sign-in matched the dead entry and only a second one provisioned."""
    from kimai_mcp.client import KimaiAPIError

    users = UsersConfig()
    users.add_user("autoSlug12345678", _config())
    server, _ = _serving_server(users, monkeypatch, answer=KimaiAPIError("Unauthorized", 401))

    await server.initialize_users()

    assert "autoSlug12345678" not in users.users


@pytest.mark.asyncio
async def test_an_outage_at_boot_does_not_stop_a_store_only_deployment(monkeypatch):
    """Users reloaded from the store counted as declared: the server refused to
    start until Kimai was back, although their sessions are built on demand."""
    from kimai_mcp.client import KimaiAPIError

    users = UsersConfig()
    users.add_user("autoSlug12345678", _config())
    server, _ = _serving_server(users, monkeypatch, answer=KimaiAPIError("Service Unavailable", 503))

    await server.initialize_users()

    assert "autoSlug12345678" in users.users


@pytest.mark.asyncio
async def test_an_outage_at_init_forgets_nobody(monkeypatch):
    from kimai_mcp.client import KimaiAPIError

    users = UsersConfig()
    users.add_user("autoSlug12345678", _config())
    server, _ = _serving_server(users, monkeypatch, answer=KimaiAPIError("Gateway Timeout", 504))

    assert await server._ensure_session("autoSlug12345678") is None
    assert "autoSlug12345678" in users.users


@pytest.mark.asyncio
async def test_the_sweep_releases_a_rejected_session_of_a_forgotten_user(monkeypatch):
    """Its user signs in under a new slug, so no request ever replaced it."""
    import time

    users = UsersConfig()
    users.add_user("autoSlug12345678", _config())
    server, _ = _serving_server(users, monkeypatch)
    _rejected_session(server, "autoSlug12345678")
    await server._forget_credentials("autoSlug12345678")
    server._session_last_used["autoSlug12345678"] = time.time()  # recently used

    await server._sweep_idle_sessions()

    assert "autoSlug12345678" not in server.user_sessions
    await server._stop_session_managers()


@pytest.mark.asyncio
async def test_a_replaced_session_answers_its_running_requests_first(monkeypatch):
    """One manager serves all MCP sessions of a user; stopping it at once
    cancelled the user's other calls in flight. Stopping it when their tool
    handlers returned still lost the answers: the SDK writes a result after
    its handler returned, from the manager's task group."""
    import asyncio
    from types import SimpleNamespace

    from mcp.types import TextContent

    users = UsersConfig(users={"declaredUserSlug16": _config()})
    server, _ = _serving_server(users, monkeypatch)
    old = _rejected_session(server, "declaredUserSlug16")
    old.token_rejected = False
    old.kimai_client = SimpleNamespace(unauthorized=False)
    manager = asyncio.create_task(asyncio.Event().wait())
    server._session_manager_tasks["declaredUserSlug16"] = manager
    release = asyncio.Event()
    written = []

    async def dispatch(client, name, arguments):
        await release.wait()
        return [TextContent(type="text", text="done")]

    class SessionManager:
        async def handle_request(self, scope, receive, send):
            result = await old._call_tool(None, SimpleNamespace(name="timesheet", arguments={}))
            for _ in range(10):  # the SDK sends the result on
                await asyncio.sleep(0)
            written.append((result.content[0].text, manager.done()))

    monkeypatch.setattr("kimai_mcp.streamable_http_server.dispatch_tool", dispatch)
    old.session_manager = SessionManager()
    request = asyncio.create_task(old.handle_request({"type": "http", "method": "POST"}, None, None))
    await asyncio.sleep(0)
    old.token_rejected = True  # another call saw a 401

    rebuilt = await server._ensure_session("declaredUserSlug16")
    await asyncio.sleep(0)

    assert rebuilt is not old
    assert not manager.done()  # the old manager waits for the running request
    release.set()
    await request
    assert written == [("done", False)]  # answered while the manager still ran
    await asyncio.wait_for(asyncio.gather(*server._retiring), 1)
    assert manager.cancelled()
    await server._stop_session_managers()


@pytest.mark.asyncio
async def test_a_request_starting_as_the_last_one_ends_holds_the_drain():
    """The waiter woke with a new request already running: its manager was
    stopped under it."""
    import asyncio

    from kimai_mcp.streamable_http_server import UserMCPSession

    session = UserMCPSession("declaredUserSlug16", _config())
    session._enter()
    waiter = asyncio.create_task(session.wait_idle())
    await asyncio.sleep(0)

    session._leave()
    session._enter()  # in the same turn
    for _ in range(3):
        await asyncio.sleep(0)

    assert not waiter.done()
    session._leave()
    await asyncio.wait_for(waiter, 1)


@pytest.mark.asyncio
async def test_the_notification_stream_does_not_hold_the_drain():
    import asyncio
    from types import SimpleNamespace

    from kimai_mcp.streamable_http_server import UserMCPSession

    session = UserMCPSession("declaredUserSlug16", _config())
    stream_open = asyncio.Event()

    async def handle_request(scope, receive, send):
        stream_open.set()
        await asyncio.Event().wait()

    session.session_manager = SimpleNamespace(handle_request=handle_request)
    stream = asyncio.create_task(session.handle_request({"type": "http", "method": "GET"}, None, None))
    await stream_open.wait()

    await asyncio.wait_for(session.wait_idle(), 1)
    stream.cancel()


@pytest.mark.asyncio
async def test_the_legacy_route_keeps_a_used_provisioned_session(monkeypatch):
    """Only a missing or rejected session went through _ensure_session, so a
    healthy one was never marked as used and the sweep released it hourly."""
    import time
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from kimai_mcp.streamable_http_server import PROVISIONED_SESSION_IDLE_SECONDS, UserMCPSession

    users = UsersConfig()
    users.add_user("autoSlug12345678", _config())
    server, _ = _serving_server(users, monkeypatch)
    server.create_app()
    session = UserMCPSession("autoSlug12345678", _config())
    session.session_manager = SimpleNamespace(handle_request=AsyncMock())
    server.user_sessions["autoSlug12345678"] = session
    monkeypatch.setattr(time, "time", lambda: 1_000_000.0)

    await server._routing_middleware._handle_mcp_request(
        {"type": "http", "method": "POST", "client": ("10.0.0.1", 1)}, AsyncMock(), AsyncMock(), "autoSlug12345678"
    )
    monkeypatch.setattr(time, "time", lambda: 1_000_000.0 + PROVISIONED_SESSION_IDLE_SECONDS / 2)
    await server._sweep_idle_sessions()

    session.session_manager.handle_request.assert_awaited_once()
    assert server.user_sessions["autoSlug12345678"] is session
    await server._stop_session_managers()


@pytest.mark.asyncio
async def test_a_user_forgotten_while_starting_is_sent_to_sign_in(monkeypatch):
    """The request whose session start Kimai refused with 401 was answered
    503: only the next one got the 401 that makes a client sign in again."""
    from types import SimpleNamespace

    from kimai_mcp.client import KimaiAPIError

    users = UsersConfig()
    users.add_user("autoSlug12345678", _config())
    server, _ = _serving_server(users, monkeypatch, answer=KimaiAPIError("Unauthorized", 401))
    sent = []

    async def send(message):
        sent.append(message)

    token = SimpleNamespace(subject="autoSlug12345678")
    scope = {"type": "http", "method": "POST", "user": SimpleNamespace(access_token=token)}
    await server._handle_oauth_mcp_request(scope, None, send)

    assert "autoSlug12345678" not in users.users
    assert sent[0]["status"] == 401
    challenge = dict(sent[0]["headers"])[b"www-authenticate"]
    assert b'error="invalid_token"' in challenge
    assert b"resource_metadata=" in challenge
    await server._stop_session_managers()


@pytest.mark.asyncio
async def test_the_legacy_route_rebuilds_a_rejected_session():
    """It served from the session table only: a dropped session answered 404,
    and ten of those blocked the client's IP for five minutes."""
    from types import SimpleNamespace
    from unittest.mock import AsyncMock

    from kimai_mcp.streamable_http_server import MCPRoutingMiddleware

    rebuilt = SimpleNamespace(token_rejected=False, session_manager=object(), handle_request=AsyncMock())
    stale = SimpleNamespace(token_rejected=True, session_manager=object())
    ensure = AsyncMock(return_value=rebuilt)
    middleware = MCPRoutingMiddleware(AsyncMock(), {"legacySlug": stale}, ensure_session=ensure)

    await middleware._handle_mcp_request({"type": "http", "client": ("10.0.0.1", 1)}, AsyncMock(), AsyncMock(), "legacySlug")

    ensure.assert_awaited_once_with("legacySlug")
    rebuilt.handle_request.assert_awaited_once()


@pytest.mark.asyncio
async def test_the_legacy_route_counts_a_configured_slug_like_any_other(monkeypatch):
    """Not counting a configured slug whose session cannot be built told a
    guesser which slug, a credential on this route, was right."""
    from unittest.mock import AsyncMock

    from kimai_mcp.client import KimaiAPIError

    monkeypatch.setattr("kimai_mcp.streamable_http_server.random_delay", AsyncMock())
    users = UsersConfig(users={"declaredUserSlug16": _config()})
    server, _ = _serving_server(users, monkeypatch, answer=KimaiAPIError("Service Unavailable", 503))
    server.create_app()
    middleware = server._routing_middleware

    for slug in ["guessedSlug12345"] * 10 + ["declaredUserSlug16"]:
        await middleware._handle_mcp_request(
            {"type": "http", "method": "POST", "client": ("10.0.0.1", 1)}, AsyncMock(), AsyncMock(), slug
        )

    assert await middleware.enumeration_protection.is_blocked("10.0.0.1")
    await server._stop_session_managers()


def test_oauth_tokens_of_a_forgotten_user_stop_verifying():
    """/mcp answered 503 and a refresh issued new tokens for the dead subject,
    so the client never got the 401 that starts a new sign-in."""
    import asyncio

    from kimai_mcp.oauth import KimaiOAuthProvider

    users = UsersConfig()
    users.add_user("autoSlug12345678", _config())
    provider = KimaiOAuthProvider(users_config=users, public_url="https://mcp.example.com")
    pair = provider._issue_token_pair(client_id="c1", scopes=["mcp"], subject="autoSlug12345678", resource=None)
    assert asyncio.run(provider.load_access_token(pair.access_token)) is not None

    users.remove_provisioned_user("autoSlug12345678")

    assert asyncio.run(provider.load_access_token(pair.access_token)) is None
    assert asyncio.run(provider.load_refresh_token(None, pair.refresh_token)) is None

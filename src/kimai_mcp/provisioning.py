"""Automatic Kimai onboarding for federated (OIDC) logins.

Without this, every user has to be declared in ``users.json`` before they can
sign in, together with a Kimai API token that an administrator first had to
create by hand in Kimai's web UI. With ``--auto-provision`` the server instead

1. resolves the verified OIDC identity to an existing Kimai user
   (:func:`resolve_kimai_user`), and
2. has Kimai mint that user's personal API token (:func:`provision_token`),

both using the configured provisioning admin token. Step 2 needs the
``ApiTokenBundle`` plugin (see ``kimai-plugin/``), because core Kimai can only
create access tokens through its web UI.

Matching is deliberately strict: a wrong match would hand one employee another
employee's token. Every rule must produce **exactly one** candidate; as soon as
a rule matches more than one user, resolution stops and reports ambiguity
instead of falling through to an even weaker rule. Note that the token
verification in :func:`provision_token` does *not* protect against a wrong
match - it only proves the minted token belongs to the user we already decided
on. That is why the two weakest, name-based rules are opt-in
(``match_mode="fuzzy"``): they were designed against a directory whose shape
was known, which is not something this server can assume about yours.

If any step fails the caller keeps its existing behaviour - the sign-in is
answered with the same generic "not authorized" page as before - so enabling
the feature cannot regress a working deployment.
"""

import asyncio
import json
import logging
import re
import secrets
import time
import unicodedata
from collections.abc import AsyncIterator, Mapping
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .client import KimaiAPIError, KimaiClient
from .models import User
from .user_config import (
    SLUG_PATTERN,
    UserConfig,
    UsersConfig,
    atomic_write_json,
    parse_ssl_verify,
)

logger = logging.getLogger(__name__)

DEFAULT_TOKEN_NAME = "Kimai MCP (auto)"

# Below this length a name part stops being evidence ("jo" would match "johanna",
# "jonas" and "joachim" alike), so the name-part rule ignores shorter fragments.
# A heuristic, not a law - it is tuned for Latin-script given/family names.
MIN_NAME_PART_LENGTH = 4

# Separators between the parts of a login or display name.
_NAME_PART_SEPARATORS = re.compile(r"[.\-_+\s]+")

# Folding for scripts where a diacritic is conventionally *expanded* rather than
# dropped; German and Nordic spellings are the cases this was built for. Every
# other diacritic is handled by the NFKD pass in normalize().
_TRANSLITERATIONS = {
    "ä": "ae",
    "ö": "oe",
    "ü": "ue",
    "ß": "ss",
    "å": "a",
    "ø": "o",
    "æ": "ae",
}

# Rule names in descending order of strength; see resolve_kimai_user().
RULES_EXACT = ("email", "username==identity")
RULES_NORMALIZED = RULES_EXACT + ("username==local-part", "normalized")
RULES_FUZZY = RULES_NORMALIZED + ("display-name", "name-part")

_MATCH_MODES: dict[str, tuple[str, ...]] = {
    "exact": RULES_EXACT,
    "normalized": RULES_NORMALIZED,
    "fuzzy": RULES_FUZZY,
}


class ProvisioningConfig(BaseModel):
    """Configuration for automatic Kimai onboarding."""

    kimai_url: str = Field(..., description="Kimai server URL used for provisioned users")
    admin_token: str = Field(
        ...,
        description=(
            "Kimai API token of an account holding 'api-token_other_profile' "
            "(ROLE_SUPER_ADMIN by default)."
        ),
    )
    token_name: str = Field(
        DEFAULT_TOKEN_NAME,
        description=(
            "Name given to provisioned tokens. Tokens are replaced by name, so "
            "keeping this stable means re-provisioning does not pile up dead "
            "tokens in a user's profile."
        ),
    )
    ssl_verify: bool | str = Field(True, description="SSL verification setting")
    match_mode: Literal["exact", "normalized", "fuzzy"] = Field(
        "normalized", description="How far to go when matching an identity to a Kimai user"
    )
    store_path: str | None = Field(
        None,
        description=(
            "Optional JSON file persisting provisioned users across restarts. "
            "Unset means in-memory only; users are re-provisioned on their next "
            "sign-in, which is idempotent."
        ),
    )
    allowed_domains: list[str] | None = Field(
        None,
        description=(
            "Mail domains an identity must come from to be provisioned. Unset "
            "means every identity the IdP asserts is accepted, which is only "
            "safe for a single-tenant issuer."
        ),
    )

    @field_validator("allowed_domains", mode="before")
    @classmethod
    def parse_allowed_domains(cls, v: Any) -> list[str] | None:
        """Accept a comma-separated string (env var / CLI) or a list."""
        if v is None:
            return None
        items = v.split(",") if isinstance(v, str) else list(v)
        domains = [d.strip().lower().lstrip("@") for d in items]
        domains = [d for d in domains if d]
        return domains or None

    # Same coercion UserConfig applies. This field mirrors that one, and copying
    # the type without the validator let the two models disagree about one
    # setting: the documented "false" survived as a string here and httpx read
    # it as a CA bundle path, raising in its constructor during startup.
    _parse_ssl_verify = field_validator("ssl_verify", mode="before")(parse_ssl_verify)

    @field_validator("kimai_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        v = v.strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError("Kimai URL must start with http:// or https://")
        return v

    @field_validator("token_name")
    @classmethod
    def validate_token_name(cls, v: str) -> str:
        # Kimai's AccessToken form requires a name; the plugin enforces 2-50.
        v = v.strip()
        if not 2 <= len(v) <= 50:
            raise ValueError("token_name must be between 2 and 50 characters")
        return v


def normalize(value: str | None) -> str:
    """Fold a name/login to a comparable form.

    Lowercases, expands the transliterated characters above, strips remaining
    diacritics and drops everything that is not a letter or digit. That makes
    ``anna.vondorf``, ``Anna von Dorf`` and ``A.von-Dorf`` comparable, which is
    exactly where Kimai logins and IdP addresses tend to differ.
    """
    if not value:
        return ""
    # NFC first, so the transliteration below sees composed characters. Without
    # it the table never matches decomposed input (NFD, as produced by macOS
    # and some AD/LDAP exports): "Müller" kept its "u" and the combining
    # diaeresis was then dropped by NFKD, folding to "muller", while the NFC
    # spelling of the same name folds to "mueller". Two normalized forms for one
    # person means a silent 403 depending on how the directory stored it.
    text = unicodedata.normalize("NFC", value.strip().lower())
    for src, dst in _TRANSLITERATIONS.items():
        text = text.replace(src, dst)
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c for c in stripped if c.isalnum())


def local_part(email: str) -> str:
    """The part before the ``@`` (the whole string if there is none)."""
    return email.split("@", 1)[0]


def name_parts(value: str | None, *, min_length: int = MIN_NAME_PART_LENGTH) -> set[str]:
    """Normalized name parts of a login or display name.

    ``anna.von-dorf`` -> ``{anna, dorf}`` (``von`` is below the length floor).

    ``min_length=1`` keeps every part. Callers that ask "does this look like
    more than a bare given name?" want that: the floor exists to stop a short
    *fragment* from being treated as evidence of identity, not to stop a short
    part from being counted as a part. Counting after the floor made the
    question "are there two parts of at least four characters", which silently
    answers "no" for ``max.mustermann`` - see :func:`is_multi_part_name`.
    """
    if not value:
        return set()
    parts = (normalize(part) for part in _NAME_PART_SEPARATORS.split(value))
    return {part for part in parts if len(part) >= min_length}


def is_multi_part_name(value: str | None) -> bool:
    """Whether ``value`` carries more than a single given name.

    The guard on the weaker rules: a lone first name is not an identifier, so
    "max@corp.example" must not match a colleague whose Kimai alias is "Max".
    Counts *all* parts, including short ones. The earlier version counted the
    output of :func:`name_parts`, i.e. after the four-character floor had
    already dropped things, so any address with a short given name
    (max., tim., jan., eva., uwe., ben., kim., leo., amy., ida.) failed the
    guard and switched off a rule that would have matched correctly.
    """
    return len(name_parts(value, min_length=1)) >= 2


@dataclass
class ResolveResult:
    """Outcome of matching an OIDC identity against Kimai's user list."""

    user: User | None = None
    # "matched" | "ambiguous" | "not_found" | "unsupported_identity"
    # | "domain_not_allowed"
    reason: str = "not_found"
    # Name of the rule that matched, for logs and support questions.
    rule: str | None = None
    # Usernames of the competing candidates when reason == "ambiguous".
    candidates: list[str] = field(default_factory=list)

    @property
    def matched(self) -> bool:
        return self.user is not None


def resolve_kimai_user(
    users: list[User],
    identity: str,
    *,
    display_name: str | None = None,
    given_name: str | None = None,
    family_name: str | None = None,
    match_mode: str = "normalized",
    allowed_domains: list[str] | None = None,
) -> ResolveResult:
    """Find the one Kimai user belonging to an OIDC identity.

    Args:
        users: All users visible to the provisioning admin token.
        identity: Verified identity from the id_token, an email address.
        display_name: ``name`` claim, e.g. "Anna von Dorf".
        given_name / family_name: ``given_name`` / ``family_name`` claims.
        match_mode: ``exact``, ``normalized`` (default) or ``fuzzy`` - see the
            module docstring for why the last two rules are not on by default.
        allowed_domains: If given, the identity's mail domain must be one of
            these. See the domain check below for why that matters.

    The rules run from strongest to weakest and stop at the first one that
    matches anything. Rules that hit several users abort with
    ``reason="ambiguous"`` rather than guessing.
    """
    # An identity that is not an address cannot be reasoned about here: with
    # --oidc-identity-claim sub it is an opaque provider GUID, and running that
    # through the name rules would compare a random string against usernames.
    # extract_identity() applies the same test to username-shaped claims.
    if "@" not in identity:
        logger.warning(
            "Automatic provisioning needs an email-shaped identity; "
            f"'{identity}' is not one. Configure --oidc-identity-claim accordingly."
        )
        return ResolveResult(reason="unsupported_identity")

    idp_email = identity.strip().lower()
    idp_local = local_part(idp_email)

    # Every rule below the two exact ones compares the *local part* against
    # Kimai usernames and aliases, so it says nothing about which domain the
    # identity came from. With an issuer that asserts more than one domain
    # (Entra's common/organizations endpoints, B2B guests, Google without an hd
    # check, Auth0 social connections), "anna.vondorf@somewhere-else.example"
    # therefore matches the Kimai user "anna.vondorf" as the *single* candidate,
    # so the ambiguity guard never fires and that employee's personal API token
    # is handed over. The /api/users/me probe in provision_token cannot catch it
    # either: it proves the token belongs to the user we already picked wrongly.
    #
    # Unset keeps the previous behaviour, which is only safe when the issuer is
    # single-tenant; check_prerequisites warns about exactly that at startup.
    if allowed_domains:
        idp_domain = idp_email.split("@", 1)[1]
        if idp_domain not in allowed_domains:
            logger.warning(
                f"Refusing to provision '{identity}': domain '{idp_domain}' is not in "
                f"--provision-allowed-domains ({', '.join(allowed_domains)})"
            )
            return ResolveResult(reason="domain_not_allowed")

    candidates = [u for u in users if u.enabled]
    if not candidates:
        return ResolveResult(reason="not_found")

    norm_local = normalize(idp_local)
    norm_display = normalize(display_name)
    norm_full_name = normalize(f"{given_name or ''}{family_name or ''}")

    def user_keys(user: User) -> set[str]:
        """Normalized identifiers a Kimai user can be recognized by."""
        keys = {normalize(user.username), normalize(user.alias)}
        if user.email:
            keys.add(normalize(local_part(user.email)))
        return {k for k in keys if k}

    # A single given name is not an identifier. The normalized rule compares an
    # address local part against usernames, *display names* and the local part of
    # a possibly different mail domain, so "max@corp.example" would match a
    # colleague whose Kimai alias is "Max" or whose address is
    # "max@partner.example" - one candidate each, so the ambiguity guard never
    # fires and the wrong person's token gets minted. Requiring at least two name
    # parts keeps the case this rule exists for (anna.vondorf@ vs. the alias
    # "Anna von Dorf") and drops the class that collides. Single-token addresses
    # still reach the exact rules above, and the fuzzy tier below.
    norm_local_is_evidence = is_multi_part_name(idp_local)

    # The same reasoning for the fuzzy display-name rule, which was missing it.
    # Its inputs are worse than the address: `name`, `given_name` and
    # `family_name` are IdP-side profile fields a user can usually edit, and a
    # missing family_name collapses norm_full_name to a bare given name. Without
    # the guard, setting a display name to a colleague's Kimai alias (aliases are
    # visible in every exported timesheet) produced exactly one candidate and
    # minted that colleague's token.
    display_is_evidence = is_multi_part_name(display_name)
    full_name_is_evidence = is_multi_part_name(f"{given_name or ''} {family_name or ''}")

    all_rules: dict[str, list[User]] = {
        "email": [u for u in candidates if u.email and u.email.strip().lower() == idp_email],
        "username==identity": [
            u for u in candidates if u.username.strip().lower() == idp_email
        ],
        "username==local-part": [
            u for u in candidates if u.username.strip().lower() == idp_local
        ],
        "normalized": [
            u for u in candidates if norm_local_is_evidence and norm_local in user_keys(u)
        ],
        "display-name": [
            u
            for u in candidates
            if normalize(u.alias)
            and normalize(u.alias)
            in {
                k
                for k, is_evidence in (
                    (norm_display, display_is_evidence),
                    (norm_full_name, full_name_is_evidence),
                )
                if k and is_evidence
            }
        ],
        "name-part": [u for u in candidates if _name_part_match(idp_local, u)],
    }

    enabled_rules = _MATCH_MODES.get(match_mode, RULES_NORMALIZED)

    for rule in enabled_rules:
        matches = all_rules[rule]
        if not matches:
            continue
        if len(matches) > 1:
            names = sorted(u.username for u in matches)
            logger.warning(
                f"Kimai user resolution for '{identity}' is ambiguous via rule '{rule}': {names}"
            )
            return ResolveResult(reason="ambiguous", rule=rule, candidates=names)
        logger.info(
            f"Resolved '{identity}' to Kimai user '{matches[0].username}' "
            f"(ID {matches[0].id}) via rule '{rule}'"
        )
        return ResolveResult(user=matches[0], reason="matched", rule=rule)

    logger.warning(
        f"No Kimai user found for '{identity}' among {len(candidates)} enabled users "
        f"(match mode '{match_mode}')"
    )
    return ResolveResult(reason="not_found")


def _name_part_match(idp_local: str, user: User) -> bool:
    """Whether a short address alias refers to the same person as a full login.

    Covers ``anna@`` vs. ``anna.vondorf@``: the address is exactly one *name
    part* of the Kimai login (or the other way round for a Kimai login that is
    only a first name).

    Deliberately not a character prefix: ``maria`` is a prefix of ``mariana``
    but a different person, and this rule runs last, i.e. for exactly the users
    who have no account of their own yet - the ones who would silently be handed
    a colleague's token. Only whole parts count, and only when the rule leaves a
    single candidate.
    """
    idp_parts = name_parts(idp_local)
    if not idp_parts:
        return False

    user_values = [user.username, user.alias]
    if user.email:
        user_values.append(local_part(user.email))

    for value in user_values:
        parts = name_parts(value)
        if not parts:
            continue
        # The address is one part of the login, or the login is one part of the
        # address ("vondorf@" vs. login "dorf" never matches - parts must be
        # equal, not contained).
        if idp_parts & parts:
            whole = normalize(value)
            if normalize(idp_local) in parts or (whole and whole in idp_parts):
                return True
    return False


async def provision_token(
    admin_client: KimaiClient,
    kimai_url: str,
    user: User,
    token_name: str = DEFAULT_TOKEN_NAME,
    ssl_verify: bool | str = True,
) -> str | None:
    """Create a personal API token for ``user`` and verify it before returning it.

    Returns the token, or ``None`` if provisioning is unavailable (plugin
    missing, admin token lacks ``api-token_other_profile``, Kimai unreachable).

    The freshly minted token is checked against ``/api/users/me`` before it is
    handed out: a token that resolves to a different user than the one we
    matched would give somebody else's data to this session, so it is discarded
    instead.
    """
    try:
        created = await admin_client.create_api_token(
            user_id=user.id, name=token_name, replace_existing=True
        )
    except KimaiAPIError as e:
        if e.status_code == 404:
            logger.warning(
                "Automatic token provisioning unavailable: Kimai has no "
                "POST /api/users/{id}/api-token endpoint. Install the ApiTokenBundle "
                "plugin (kimai-plugin/ApiTokenBundle) to enable it."
            )
        elif e.status_code == 403:
            logger.warning(
                "Automatic token provisioning refused: the configured provisioning "
                "admin token lacks the 'api-token_other_profile' permission "
                "(ROLE_SUPER_ADMIN by default)."
            )
        else:
            logger.error(
                f"Token provisioning failed for Kimai user {user.id}: "
                f"{e.message} (status {e.status_code})"
            )
        return None

    # Verify the token really belongs to the user we resolved.
    probe = KimaiClient(kimai_url, created.token, ssl_verify=ssl_verify)
    try:
        actual = await probe.get_current_user()
    except KimaiAPIError as e:
        logger.error(f"Provisioned token for user {user.id} could not be verified: {e.message}")
        return None
    finally:
        await probe.close()

    if actual.id != user.id:
        logger.error(
            f"Provisioned token belongs to Kimai user {actual.id} "
            f"('{actual.username}'), expected {user.id} ('{user.username}') - discarding it"
        )
        return None

    logger.info(
        f"Provisioned Kimai API token '{token_name}' for user '{user.username}' (ID {user.id})"
    )
    return created.token


class ProvisionedUserStore:
    """Optional JSON file remembering which Kimai account belongs to an identity.

    Holds plaintext Kimai API tokens, so the file is written with mode 0600.
    Persistence is a convenience: without it a restart simply re-provisions
    every user on their next sign-in.
    """

    def __init__(self, path: str | Path):
        self.path = Path(path)

    def load_into(self, users: UsersConfig) -> int:
        """Insert persisted users into ``users``, skipping anything already there.

        A hand-written configuration always wins: neither a slug nor an identity
        that is already declared is overwritten.
        """
        if not self.path.exists():
            return 0
        try:
            with self.path.open(encoding="utf-8") as f:
                data = json.load(f)
        # A corrupt store must not stop the server from booting; the affected
        # users are simply provisioned again on their next sign-in.
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to load provisioned users from {self.path}: {e}")
            return 0

        # Valid JSON of the wrong shape is not a corrupt file to json.load, so
        # it used to get past the guard above and then raise AttributeError on
        # .items() or .get(). load_into runs synchronously from the server's
        # __init__, so that took down the whole multi-user process and every
        # hand-configured user with it - the blast radius this guard exists to
        # prevent. A hand-edit, a truncated restore or a config-management
        # template that rendered a list all produce it.
        if not isinstance(data, dict):
            logger.error(
                f"Ignoring {self.path}: expected a JSON object of identities, "
                f"got {type(data).__name__}"
            )
            return 0

        loaded = 0
        for identity, entry in data.items():
            if not isinstance(entry, dict):
                logger.error(
                    f"Skipping provisioned user '{identity}' from {self.path}: "
                    f"expected an object, got {type(entry).__name__}"
                )
                continue
            if users.get_user_by_oidc_identity(identity) is not None:
                continue
            slug = entry.get("slug")
            if not slug or slug in users.users:
                continue
            try:
                users.add_user(
                    slug,
                    UserConfig(
                        kimai_url=entry["kimai_url"],
                        kimai_token=entry["kimai_token"],
                        ssl_verify=entry.get("ssl_verify", True),
                        auth_secret=None,
                        oidc_identity=identity,
                    ),
                )
            except Exception as e:  # noqa: BLE001
                logger.error(f"Skipping provisioned user '{identity}' from {self.path}: {e}")
                continue
            loaded += 1

        logger.info(f"Loaded {loaded} provisioned user(s) from {self.path}")
        return loaded

    def add(self, identity: str, slug: str, config: UserConfig) -> None:
        """Append one provisioned user and rewrite the file atomically."""
        try:
            data: dict[str, Any] = {}
            if self.path.exists():
                with self.path.open(encoding="utf-8") as f:
                    data = json.load(f)
            # Read-modify-write, so a store whose shape is wrong would drop
            # every existing entry rather than merge into it.
            if not isinstance(data, dict):
                logger.error(
                    f"Replacing {self.path}: expected a JSON object of identities, "
                    f"got {type(data).__name__}"
                )
                data = {}
            data[identity.strip().lower()] = {
                "slug": slug,
                "kimai_url": config.kimai_url,
                "kimai_token": config.kimai_token,
                "ssl_verify": config.ssl_verify,
                "created_at": int(time.time()),
            }
            atomic_write_json(self.path, data)
        # Persistence is a convenience; a failing write must not invalidate the
        # in-memory provisioning that just succeeded.
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to persist provisioned user to {self.path}: {e}")

    def remove(self, identity: str) -> None:
        """Forget one identity, so the next sign-in provisions it from scratch.

        Needed because ``provision()`` short-circuits on a stored entry before
        it ever contacts Kimai. Without this, a token Kimai no longer accepts
        (an admin deleted it, or another replica replaced it by name) stayed in
        the file forever: the user's every request answered 503 and signing in
        again did not help, because the stale entry still matched.
        """
        if not self.path.exists():
            return
        try:
            with self.path.open(encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                return
            if data.pop(identity.strip().lower(), None) is None:
                return
            atomic_write_json(self.path, data)
            logger.info(f"Removed stale provisioned user '{identity}' from {self.path}")
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to remove provisioned user from {self.path}: {e}")


class KimaiProvisioner:
    """Turns a verified OIDC identity into a usable Kimai user configuration."""

    def __init__(self, config: ProvisioningConfig, store: ProvisionedUserStore | None = None):
        self.config = config
        self.store = store
        # Two parallel sign-ins of the same identity would otherwise mint two
        # tokens, the second silently invalidating the first (tokens are
        # replaced by name). That invariant is per identity, so the lock is too:
        # a single process-wide one also serialized *unrelated* identities
        # across a TLS handshake, a full directory listing, the matching pass,
        # the mint, the verification probe and an fsynced write. On a rollout
        # day the queue outlived the five-minute TTL of the OIDC login state,
        # so users waiting in it got "Invalid or expired sign-in state" and
        # retried, adding more work to the same queue.
        self._locks: dict[str, asyncio.Lock] = {}
        self._waiters: dict[str, int] = {}
        self._locks_guard = asyncio.Lock()

    @asynccontextmanager
    async def _identity_lock(self, identity: str) -> AsyncIterator[None]:
        """Hold the lock belonging to one identity, and only that one."""
        key = identity.strip().lower()
        async with self._locks_guard:
            lock = self._locks.setdefault(key, asyncio.Lock())
            # Waiters counted while the map is guarded, so the entry cannot be
            # dropped between a waiter arriving and acquiring.
            self._waiters[key] = self._waiters.get(key, 0) + 1
        try:
            async with lock:
                yield
        finally:
            async with self._locks_guard:
                self._waiters[key] -= 1
                if self._waiters[key] == 0:
                    del self._waiters[key]
                    self._locks.pop(key, None)

    def _client(self) -> KimaiClient:
        return KimaiClient(
            self.config.kimai_url, self.config.admin_token, ssl_verify=self.config.ssl_verify
        )

    @staticmethod
    def generate_slug(taken: Mapping[str, Any] | None = None) -> str:
        """A slug with the entropy of the ones users.example.json tells users to generate."""
        taken = taken or {}
        for _ in range(10):
            slug = secrets.token_urlsafe(12)
            if SLUG_PATTERN.match(slug) and slug not in taken:
                return slug
        raise RuntimeError("Could not generate a free user slug")

    async def check_prerequisites(self) -> None:
        """Log at startup whether provisioning can actually work.

        Never raises: a Kimai that is briefly unreachable at boot must not stop
        the server, and provisioning failures are already handled per request.
        This runs inside the lifespan before the yield, where an exception is
        not a logged warning but "Application startup failed", so the client
        construction belongs inside the try as much as the calls do - httpx
        raises there for a bad CA path or a malformed proxy setting.
        """
        client = None
        try:
            if not self.config.allowed_domains:
                logger.warning(
                    "Automatic provisioning accepts identities from any domain the identity "
                    "provider asserts. That is only safe for a single-tenant issuer: with a "
                    "multi-tenant one (Entra common/organizations, B2B guests, Google without "
                    "an hd claim, social connections) an outside account whose address local "
                    "part equals a Kimai username is provisioned as that user. Set "
                    "--provision-allowed-domains to restrict it."
                )

            client = self._client()
            version = await client.get_version()
            me = await client.get_current_user()
            logger.info(
                f"Provisioning admin token belongs to '{me.username}' on Kimai "
                f"{version.version} at {self.config.kimai_url}"
            )
            plugins = await client.get_plugins()
            if not any(p.name == "ApiTokenBundle" for p in plugins):
                logger.error(
                    "Automatic provisioning is enabled but the ApiTokenBundle plugin is not "
                    "installed on this Kimai instance. POST /api/users/{id}/api-token will "
                    "return 404 and every first-time sign-in will be rejected. "
                    "See kimai-plugin/ApiTokenBundle/README.md."
                )

            # The permission the runtime path needs, which the probes above do
            # not cover: GET /api/users carries IsGranted('view_user'), on top
            # of the api-token_other_profile that minting needs. Without this
            # probe an admin token missing it passes startup with a reassuring
            # log line and then fails on every single callback instead.
            try:
                await client.get_users()
            except KimaiAPIError as e:
                if e.status_code == 403:
                    logger.error(
                        "The provisioning admin token cannot list Kimai users: "
                        "GET /api/users requires the 'view_user' permission. Every "
                        "first-time sign-in will be rejected until the token's role "
                        "has it."
                    )
                else:
                    raise
        except Exception as e:  # noqa: BLE001
            logger.error(f"Could not verify the provisioning prerequisites: {e}")
        finally:
            if client is not None:
                await client.close()

    async def provision(
        self, identity: str, claims: Mapping[str, Any], users: UsersConfig
    ) -> tuple[str, UserConfig] | None:
        """Resolve ``identity`` to a Kimai user and give it a token and a slug.

        Returns ``(slug, UserConfig)`` - the same shape as
        :meth:`UsersConfig.get_user_by_oidc_identity`, so a caller can treat a
        provisioned and a configured user identically - or ``None`` when the
        identity cannot be onboarded. The reason is logged, never returned: the
        sign-in response must not reveal whether an identity matched a Kimai
        account.
        """
        async with self._identity_lock(identity):
            # Another request may have provisioned this identity while we waited.
            existing = users.get_user_by_oidc_identity(identity)
            if existing is not None:
                return existing

            client = None
            try:
                client = self._client()
                kimai_users = await client.get_users()
                result = resolve_kimai_user(
                    kimai_users,
                    identity,
                    display_name=claims.get("name"),
                    given_name=claims.get("given_name"),
                    family_name=claims.get("family_name"),
                    match_mode=self.config.match_mode,
                    allowed_domains=self.config.allowed_domains,
                )
                if result.user is None:
                    return None

                token = await provision_token(
                    client,
                    self.config.kimai_url,
                    result.user,
                    token_name=self.config.token_name,
                    ssl_verify=self.config.ssl_verify,
                )
            except KimaiAPIError as e:
                # get_users() is the one call here whose permission the startup
                # probe cannot vouch for at the moment of use. Naming it beats
                # the stack trace oauth.py's blanket handler would otherwise log
                # while the operator sees only the generic 403 page.
                if e.status_code == 403:
                    logger.error(
                        f"Cannot provision '{identity}': the provisioning admin token was "
                        "refused by Kimai (403). GET /api/users needs 'view_user' and "
                        "minting needs 'api-token_other_profile'."
                    )
                else:
                    logger.error(
                        f"Cannot provision '{identity}': Kimai returned "
                        f"{e.status_code} ({e.message})"
                    )
                return None
            finally:
                # A super-admin token has no business sitting in a long-lived
                # idle connection, so the client lives for one callback only.
                if client is not None:
                    await client.close()

            if token is None:
                return None

            config = UserConfig(
                kimai_url=self.config.kimai_url,
                kimai_token=token,
                ssl_verify=self.config.ssl_verify,
                # Provisioned users authenticate through the IdP only; without a
                # secret the built-in login form cannot be used for them.
                auth_secret=None,
                oidc_identity=identity,
            )
            slug = self.generate_slug(users.users)
            users.add_user(slug, config)

            if self.store is not None:
                await asyncio.to_thread(self.store.add, identity, slug, config)

            logger.info(
                f"Provisioned '{identity}' -> Kimai user '{result.user.username}' (slug '{slug}')"
            )
            return slug, config

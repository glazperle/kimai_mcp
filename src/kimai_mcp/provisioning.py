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
import os
import re
import secrets
import time
import unicodedata
from collections.abc import Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Literal

from pydantic import BaseModel, Field, field_validator

from .client import KimaiAPIError, KimaiClient
from .models import User
from .user_config import SLUG_PATTERN, UserConfig, UsersConfig

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
    text = value.strip().lower()
    for src, dst in _TRANSLITERATIONS.items():
        text = text.replace(src, dst)
    decomposed = unicodedata.normalize("NFKD", text)
    stripped = "".join(c for c in decomposed if not unicodedata.combining(c))
    return "".join(c for c in stripped if c.isalnum())


def local_part(email: str) -> str:
    """The part before the ``@`` (the whole string if there is none)."""
    return email.split("@", 1)[0]


def name_parts(value: str | None) -> set[str]:
    """Normalized name parts of a login or display name.

    ``anna.von-dorf`` -> ``{anna, dorf}`` (``von`` is below the length floor).
    """
    if not value:
        return set()
    parts = (normalize(part) for part in _NAME_PART_SEPARATORS.split(value))
    return {part for part in parts if len(part) >= MIN_NAME_PART_LENGTH}


@dataclass
class ResolveResult:
    """Outcome of matching an OIDC identity against Kimai's user list."""

    user: User | None = None
    # "matched" | "ambiguous" | "not_found" | "unsupported_identity"
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
) -> ResolveResult:
    """Find the one Kimai user belonging to an OIDC identity.

    Args:
        users: All users visible to the provisioning admin token.
        identity: Verified identity from the id_token, an email address.
        display_name: ``name`` claim, e.g. "Anna von Dorf".
        given_name / family_name: ``given_name`` / ``family_name`` claims.
        match_mode: ``exact``, ``normalized`` (default) or ``fuzzy`` - see the
            module docstring for why the last two rules are not on by default.

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

    candidates = [u for u in users if u.enabled]
    if not candidates:
        return ResolveResult(reason="not_found")

    idp_email = identity.strip().lower()
    idp_local = local_part(idp_email)
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
    norm_local_is_evidence = len(name_parts(idp_local)) >= 2

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
            and normalize(u.alias) in {k for k in (norm_display, norm_full_name) if k}
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

        loaded = 0
        for identity, entry in data.items():
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
            data[identity.strip().lower()] = {
                "slug": slug,
                "kimai_url": config.kimai_url,
                "kimai_token": config.kimai_token,
                "ssl_verify": config.ssl_verify,
                "created_at": int(time.time()),
            }
            self.path.parent.mkdir(parents=True, exist_ok=True)
            tmp_path = self.path.with_suffix(self.path.suffix + ".tmp")
            with tmp_path.open("w", encoding="utf-8") as f:
                json.dump(data, f, indent=2)
                # Without the fsync the rename can reach the disk before the
                # data does, so a host crash leaves a correctly named but
                # truncated file - the outcome the temp file exists to prevent.
                f.flush()
                os.fsync(f.fileno())
            # Set the mode before the rename so the file is never briefly
            # world-readable while it already holds tokens.
            tmp_path.chmod(0o600)
            tmp_path.replace(self.path)
        # Persistence is a convenience; a failing write must not invalidate the
        # in-memory provisioning that just succeeded.
        except Exception as e:  # noqa: BLE001
            logger.error(f"Failed to persist provisioned user to {self.path}: {e}")


class KimaiProvisioner:
    """Turns a verified OIDC identity into a usable Kimai user configuration."""

    def __init__(self, config: ProvisioningConfig, store: ProvisionedUserStore | None = None):
        self.config = config
        self.store = store
        # Two parallel sign-ins of the same identity would otherwise mint two
        # tokens, the second silently invalidating the first (tokens are
        # replaced by name).
        self._lock = asyncio.Lock()

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
        """
        client = self._client()
        try:
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
        except Exception as e:  # noqa: BLE001
            logger.error(f"Could not verify the provisioning prerequisites: {e}")
        finally:
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
        async with self._lock:
            # Another request may have provisioned this identity while we waited.
            existing = users.get_user_by_oidc_identity(identity)
            if existing is not None:
                return existing

            client = self._client()
            try:
                kimai_users = await client.get_users()
                result = resolve_kimai_user(
                    kimai_users,
                    identity,
                    display_name=claims.get("name"),
                    given_name=claims.get("given_name"),
                    family_name=claims.get("family_name"),
                    match_mode=self.config.match_mode,
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
            finally:
                # A super-admin token has no business sitting in a long-lived
                # idle connection, so the client lives for one callback only.
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

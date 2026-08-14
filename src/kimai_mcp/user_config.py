"""User configuration management for multi-user MCP server."""

import json
import logging
import os
import re
from pathlib import Path

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# User slugs are used in URL paths and env var names - restrict to a safe charset.
SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def _env_key_for_slug(slug: str, suffix: str) -> str:
    """Build the environment variable name for a user slug.

    '-' is mapped to '_' because '-' is not portable in env var names.
    """
    return f"KIMAI_USER_{slug.upper().replace('-', '_')}_{suffix}"


def atomic_write_json(path: Path, data: object, *, mode: int = 0o600) -> None:
    """Write ``data`` as JSON so the file is never readable by anyone else.

    Every caller of this persists secrets (Kimai API tokens, OAuth client
    secrets), which drives all four properties:

    * ``os.open`` with ``mode`` creates the temp file **already** restricted.
      Creating it via ``open()`` and calling ``chmod`` afterwards leaves it at
      the process umask (usually 0644) for the whole write, and an fsync
      deliberately widens that window. A SIGKILL in between used to strand a
      world-readable ``.tmp`` full of plaintext tokens forever.
    * ``fsync`` on the file, so a crash cannot leave the rename pointing at
      truncated content.
    * ``fsync`` on the *directory*, so the rename itself survives a host crash.
      Without it the store can revert to its previous contents, which then
      re-provisions users and invalidates tokens live sessions still hold.
    * A stale ``.tmp`` from an earlier crash is removed rather than reused.

    ``mode`` is advisory on Windows, where the ACL rather than the mode bits
    decides; the atomicity and the fsyncs still apply.
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp_path = path.with_suffix(path.suffix + ".tmp")
    tmp_path.unlink(missing_ok=True)

    fd = os.open(tmp_path, os.O_CREAT | os.O_WRONLY | os.O_TRUNC, mode)
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2)
            f.flush()
            os.fsync(f.fileno())
    except BaseException:
        tmp_path.unlink(missing_ok=True)
        raise

    tmp_path.replace(path)

    # Directory fsync is POSIX-only; Windows has no handle for it.
    if hasattr(os, "O_DIRECTORY"):
        dir_fd = os.open(path.parent, os.O_DIRECTORY)
        try:
            os.fsync(dir_fd)
        finally:
            os.close(dir_fd)


def parse_ssl_verify(v: bool | str) -> bool | str:
    """Coerce an ssl_verify setting from a string, or pass a CA path through.

    Free-standing rather than a method, because every model carrying this field
    needs the same coercion: the value almost always arrives from an env var or
    a CLI argument, so the documented ``"false"`` reaches Pydantic as a string.
    A ``bool | str`` field accepts it as-is under the smart union, and httpx
    then treats ``"false"`` as a path to a CA bundle and raises in its own
    constructor. ProvisioningConfig once declared the field without this and
    the two models disagreed about the same setting.
    """
    if isinstance(v, bool):
        return v
    if isinstance(v, str):
        lower_v = v.lower()
        if lower_v == "true":
            return True
        elif lower_v == "false":
            return False
        # Treat as path to certificate
        return v
    return True


class UserConfig(BaseModel):
    """Configuration for a single user's Kimai connection."""

    kimai_url: str = Field(..., description="Kimai server URL")
    kimai_token: str = Field(..., description="Kimai API token")
    ssl_verify: bool | str = Field(True, description="SSL verification setting")
    auth_secret: str | None = Field(
        None,
        description=(
            "Per-user secret for the OAuth login form. Users without an "
            "auth_secret cannot authenticate via OAuth."
        ),
    )
    oidc_identity: str | None = Field(
        None,
        description=(
            "Identity value from the OIDC provider (e.g. the user's email) that "
            "maps to this user when --auth-backend=oidc. Matched case-insensitively "
            "against the configured --oidc-identity-claim."
        ),
    )

    @field_validator("kimai_url")
    @classmethod
    def validate_url(cls, v: str) -> str:
        """Validate and normalize the Kimai URL."""
        v = v.strip().rstrip("/")
        if not v.startswith(("http://", "https://")):
            raise ValueError("Kimai URL must start with http:// or https://")
        return v

    _parse_ssl_verify = field_validator("ssl_verify", mode="before")(parse_ssl_verify)


class UsersConfig(BaseModel):
    """Configuration for all users."""

    users: dict[str, UserConfig] = Field(
        default_factory=dict,
        description="Map of user slug to user configuration"
    )
    provisioned_slugs: set[str] = Field(
        default_factory=set,
        exclude=True,
        description=(
            "Slugs that were added at runtime by automatic provisioning rather "
            "than declared in users.json. Their credentials are disposable: a "
            "token Kimai no longer accepts can be dropped and re-minted on the "
            "next sign-in, which must never happen to a hand-written entry."
        ),
    )

    @field_validator("users")
    @classmethod
    def validate_slugs(cls, v: dict[str, UserConfig]) -> dict[str, UserConfig]:
        """Validate that all user slugs only contain safe characters."""
        for slug in v:
            if not SLUG_PATTERN.match(slug):
                raise ValueError(
                    f"Invalid user slug '{slug}': only letters, digits, "
                    f"'-' and '_' are allowed (pattern: ^[a-zA-Z0-9_-]+$)"
                )
        return v

    @staticmethod
    def _apply_env_overrides(users: dict[str, UserConfig]) -> None:
        """Apply per-user env-var overrides (KIMAI_USER_<NAME>_AUTH_SECRET /
        KIMAI_USER_<NAME>_OIDC_IDENTITY).

        Environment variables take precedence over values from the config file.
        """
        for slug, config in users.items():
            env_secret = os.getenv(_env_key_for_slug(slug, "AUTH_SECRET"))
            if env_secret:
                config.auth_secret = env_secret
                logger.info(f"Loaded auth_secret for user '{slug}' from environment")
            env_identity = os.getenv(_env_key_for_slug(slug, "OIDC_IDENTITY"))
            if env_identity:
                config.oidc_identity = env_identity
                logger.info(f"Loaded oidc_identity for user '{slug}' from environment")

    @classmethod
    def from_file(cls, path: str | Path, *, allow_empty: bool = False) -> "UsersConfig":
        """Load users configuration from a JSON file.

        Expected format:
        {
          "x7Kp2mQ9wL4r": {
            "kimai_url": "https://kimai.example.com",
            "kimai_token": "api_token_for_max",
            "auth_secret": "long-random-oauth-login-secret"
          },
          "bN3hT8rY5jF6": {
            "kimai_url": "https://kimai.example.com",
            "kimai_token": "api_token_for_anna"
          }
        }

        Args:
            path: Path to the JSON file.
            allow_empty: Accept a file that declares no users. Only meaningful
                with automatic provisioning enabled, where the user set is
                filled in at login time rather than declared up front.
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Users config file not found: {path}")

        with path.open(encoding="utf-8") as f:
            data = json.load(f)

        # Parse each user config
        users = {}
        for slug, user_data in data.items():
            if slug.startswith("_"):
                # Allow comment entries like "_SECURITY_WARNING"
                continue
            if not SLUG_PATTERN.match(slug):
                # Skip (don't abort the whole load): an invalid slug is unreachable
                # via routing anyway, and failing hard would take the whole server
                # down for every other (valid) user on upgrade.
                logger.warning(
                    f"Skipping user '{slug}' in {path}: slug contains characters outside "
                    f"^[a-zA-Z0-9_-]+$ and cannot be used in a URL. Rename it to enable this user."
                )
                continue
            try:
                users[slug] = UserConfig(**user_data)
                logger.info(f"Loaded config for user '{slug}' -> {user_data.get('kimai_url', 'N/A')}")
            except Exception as e:
                logger.error(f"Error parsing config for user '{slug}': {e}")
                raise ValueError(f"Invalid config for user '{slug}': {e}") from e

        if not users and not allow_empty:
            raise ValueError("No users configured in config file")

        cls._apply_env_overrides(users)
        return cls(users=users)

    @classmethod
    def from_env(cls, *, allow_empty: bool = False) -> "UsersConfig":
        """Load users configuration from environment variables.

        Supports two formats:

        1. JSON in USERS_CONFIG env var:
           USERS_CONFIG='{"max": {"kimai_url": "...", "kimai_token": "..."}}'

        2. Individual env vars per user:
           KIMAI_USER_MAX_URL=https://kimai.example.com
           KIMAI_USER_MAX_TOKEN=xxx
           KIMAI_USER_MAX_SSL_VERIFY=true (optional)
           KIMAI_USER_MAX_AUTH_SECRET=oauth-login-secret (optional)

        Args:
            allow_empty: Accept an environment that declares no users. Only
                meaningful with automatic provisioning enabled.
        """
        users = {}

        # Try JSON format first
        json_config = os.getenv("USERS_CONFIG")
        if json_config:
            try:
                data = json.loads(json_config)
                for slug, user_data in data.items():
                    if slug.startswith("_"):
                        continue
                    if not SLUG_PATTERN.match(slug):
                        logger.warning(
                            f"Skipping user '{slug}' from USERS_CONFIG: slug outside ^[a-zA-Z0-9_-]+$."
                        )
                        continue
                    users[slug] = UserConfig(**user_data)
                    logger.info(f"Loaded config for user '{slug}' from USERS_CONFIG")
                if not users and not allow_empty:
                    raise ValueError("No valid users configured in USERS_CONFIG")
                cls._apply_env_overrides(users)
                return cls(users=users)
            except json.JSONDecodeError as e:
                raise ValueError(f"Invalid JSON in USERS_CONFIG: {e}") from e

        # Try individual env vars
        # Look for KIMAI_USER_*_URL patterns
        prefix = "KIMAI_USER_"
        url_suffix = "_URL"

        for key, value in os.environ.items():
            if key.startswith(prefix) and key.endswith(url_suffix):
                # Extract user slug from KIMAI_USER_MAX_URL -> max
                slug = key[len(prefix) : -len(url_suffix)].lower()

                token_key = f"{prefix}{slug.upper()}_TOKEN"
                token = os.getenv(token_key)

                if not token:
                    logger.warning(f"Skipping user '{slug}': missing {token_key}")
                    continue

                ssl_key = f"{prefix}{slug.upper()}_SSL_VERIFY"
                auth_secret_key = f"{prefix}{slug.upper()}_AUTH_SECRET"
                oidc_identity_key = f"{prefix}{slug.upper()}_OIDC_IDENTITY"

                users[slug] = UserConfig(
                    kimai_url=value,
                    kimai_token=token,
                    ssl_verify=os.getenv(ssl_key, "true"),
                    auth_secret=os.getenv(auth_secret_key),
                    oidc_identity=os.getenv(oidc_identity_key),
                )
                logger.info(f"Loaded config for user '{slug}' from env vars")

        if not users and not allow_empty:
            raise ValueError(
                "No users configured. Set USERS_CONFIG or KIMAI_USER_*_URL/TOKEN env vars, "
                "or use --users-config to specify a config file."
            )

        return cls(users=users)

    @classmethod
    def load(
        cls, config_path: str | Path | None = None, *, allow_empty: bool = False
    ) -> "UsersConfig":
        """Load users configuration from file or environment.

        Priority:
        1. Explicit config_path argument
        2. USERS_CONFIG_FILE env var
        3. USERS_CONFIG env var (JSON)
        4. Individual KIMAI_USER_* env vars

        Args:
            config_path: Explicit path to a users config file.
            allow_empty: Tolerate a configuration that declares no users at all.
                Set when automatic provisioning is on: there the user set is
                discovered at login time, so demanding one up front would make
                the "sign in and nothing else" deployment impossible to boot.
        """
        # Check for explicit path
        if config_path:
            logger.info(f"Loading users config from: {config_path}")
            return cls.from_file(config_path, allow_empty=allow_empty)

        # Check for config file env var
        config_file_env = os.getenv("USERS_CONFIG_FILE")
        if config_file_env:
            logger.info(f"Loading users config from USERS_CONFIG_FILE: {config_file_env}")
            return cls.from_file(config_file_env, allow_empty=allow_empty)

        # Fall back to environment variables
        logger.info("Loading users config from environment variables")
        return cls.from_env(allow_empty=allow_empty)

    def get_user(self, slug: str) -> UserConfig | None:
        """Get configuration for a specific user."""
        return self.users.get(slug)

    def get_user_by_oidc_identity(self, value: str) -> tuple[str, UserConfig] | None:
        """Return (slug, UserConfig) whose oidc_identity matches value (case-insensitive)."""
        if not value:
            return None
        norm = value.strip().lower()
        for slug, config in self.users.items():
            if config.oidc_identity and config.oidc_identity.strip().lower() == norm:
                return slug, config
        return None

    def add_user(self, slug: str, config: UserConfig, *, provisioned: bool = True) -> None:
        """Register a user at runtime (used by automatic provisioning).

        Args:
            provisioned: Whether this entry may be dropped and re-created
                automatically. True for everything added at runtime, which is
                every current caller; see :attr:`provisioned_slugs`.

        Raises:
            ValueError: if the slug is unusable in a URL, or already taken.
                Overwriting is refused rather than silently replacing a
                hand-written configuration.
        """
        if not SLUG_PATTERN.match(slug):
            raise ValueError(
                f"Invalid user slug '{slug}': only letters, digits, '-' and '_' are allowed"
            )
        if slug in self.users:
            raise ValueError(f"User slug '{slug}' is already configured")
        self.users[slug] = config
        if provisioned:
            self.provisioned_slugs.add(slug)

    def remove_provisioned_user(self, slug: str) -> UserConfig | None:
        """Forget a provisioned user, so the next sign-in provisions it again.

        Refuses hand-written entries: their token is what the operator put
        there, and dropping it would turn an outage into a silent config
        change. Returns the removed config, or None if there was nothing to
        remove.
        """
        if slug not in self.provisioned_slugs:
            return None
        self.provisioned_slugs.discard(slug)
        return self.users.pop(slug, None)

    def list_users(self) -> list[str]:
        """List all configured user slugs."""
        return list(self.users.keys())

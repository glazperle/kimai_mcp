"""User configuration management for multi-user MCP server."""

import json
import logging
import os
import re
from pathlib import Path
from typing import Dict, Optional, Union

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)

# User slugs are used in URL paths and env var names - restrict to a safe charset.
SLUG_PATTERN = re.compile(r"^[a-zA-Z0-9_-]+$")


def _env_key_for_slug(slug: str, suffix: str) -> str:
    """Build the environment variable name for a user slug.

    '-' is mapped to '_' because '-' is not portable in env var names.
    """
    return f"KIMAI_USER_{slug.upper().replace('-', '_')}_{suffix}"


class UserConfig(BaseModel):
    """Configuration for a single user's Kimai connection."""

    kimai_url: str = Field(..., description="Kimai server URL")
    kimai_token: str = Field(..., description="Kimai API token")
    ssl_verify: Union[bool, str] = Field(True, description="SSL verification setting")
    auth_secret: Optional[str] = Field(
        None,
        description=(
            "Per-user secret for the OAuth login form. Users without an "
            "auth_secret cannot authenticate via OAuth."
        ),
    )
    oidc_identity: Optional[str] = Field(
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

    @field_validator("ssl_verify", mode="before")
    @classmethod
    def parse_ssl_verify(cls, v: Union[bool, str]) -> Union[bool, str]:
        """Parse SSL verify value from string or bool."""
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


class UsersConfig(BaseModel):
    """Configuration for all users."""

    users: Dict[str, UserConfig] = Field(
        default_factory=dict,
        description="Map of user slug to user configuration"
    )

    @field_validator("users")
    @classmethod
    def validate_slugs(cls, v: Dict[str, UserConfig]) -> Dict[str, UserConfig]:
        """Validate that all user slugs only contain safe characters."""
        for slug in v:
            if not SLUG_PATTERN.match(slug):
                raise ValueError(
                    f"Invalid user slug '{slug}': only letters, digits, "
                    f"'-' and '_' are allowed (pattern: ^[a-zA-Z0-9_-]+$)"
                )
        return v

    @staticmethod
    def _apply_env_overrides(users: Dict[str, UserConfig]) -> None:
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
    def from_file(cls, path: Union[str, Path]) -> "UsersConfig":
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
        """
        path = Path(path)
        if not path.exists():
            raise FileNotFoundError(f"Users config file not found: {path}")

        with open(path, "r", encoding="utf-8") as f:
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

        if not users:
            raise ValueError("No users configured in config file")

        cls._apply_env_overrides(users)
        return cls(users=users)

    @classmethod
    def from_env(cls) -> "UsersConfig":
        """Load users configuration from environment variables.

        Supports two formats:

        1. JSON in USERS_CONFIG env var:
           USERS_CONFIG='{"max": {"kimai_url": "...", "kimai_token": "..."}}'

        2. Individual env vars per user:
           KIMAI_USER_MAX_URL=https://kimai.example.com
           KIMAI_USER_MAX_TOKEN=xxx
           KIMAI_USER_MAX_SSL_VERIFY=true (optional)
           KIMAI_USER_MAX_AUTH_SECRET=oauth-login-secret (optional)
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
                if not users:
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

        if not users:
            raise ValueError(
                "No users configured. Set USERS_CONFIG or KIMAI_USER_*_URL/TOKEN env vars, "
                "or use --users-config to specify a config file."
            )

        return cls(users=users)

    @classmethod
    def load(cls, config_path: Optional[Union[str, Path]] = None) -> "UsersConfig":
        """Load users configuration from file or environment.

        Priority:
        1. Explicit config_path argument
        2. USERS_CONFIG_FILE env var
        3. USERS_CONFIG env var (JSON)
        4. Individual KIMAI_USER_* env vars
        """
        # Check for explicit path
        if config_path:
            logger.info(f"Loading users config from: {config_path}")
            return cls.from_file(config_path)

        # Check for config file env var
        config_file_env = os.getenv("USERS_CONFIG_FILE")
        if config_file_env:
            logger.info(f"Loading users config from USERS_CONFIG_FILE: {config_file_env}")
            return cls.from_file(config_file_env)

        # Fall back to environment variables
        logger.info("Loading users config from environment variables")
        return cls.from_env()

    def get_user(self, slug: str) -> Optional[UserConfig]:
        """Get configuration for a specific user."""
        return self.users.get(slug)

    def get_user_by_oidc_identity(self, value: str) -> Optional[tuple[str, UserConfig]]:
        """Return (slug, UserConfig) whose oidc_identity matches value (case-insensitive)."""
        if not value:
            return None
        norm = value.strip().lower()
        for slug, config in self.users.items():
            if config.oidc_identity and config.oidc_identity.strip().lower() == norm:
                return slug, config
        return None

    def list_users(self) -> list[str]:
        """List all configured user slugs."""
        return list(self.users.keys())

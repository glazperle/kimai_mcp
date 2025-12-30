"""User configuration management for multi-user MCP server."""

import json
import logging
import os
from pathlib import Path
from typing import Dict, Optional, Union

from pydantic import BaseModel, Field, field_validator

logger = logging.getLogger(__name__)


class UserConfig(BaseModel):
    """Configuration for a single user's Kimai connection."""

    kimai_url: str = Field(..., description="Kimai server URL")
    kimai_token: str = Field(..., description="Kimai API token")
    kimai_user_id: Optional[str] = Field(None, description="Default user ID for operations")
    ssl_verify: Union[bool, str] = Field(True, description="SSL verification setting")

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

    @classmethod
    def from_file(cls, path: Union[str, Path]) -> "UsersConfig":
        """Load users configuration from a JSON file.

        Expected format:
        {
          "max": {
            "kimai_url": "https://kimai.example.com",
            "kimai_token": "api_token_for_max",
            "kimai_user_id": "1"
          },
          "anna": {
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
            try:
                users[slug] = UserConfig(**user_data)
                logger.info(f"Loaded config for user '{slug}' -> {user_data.get('kimai_url', 'N/A')}")
            except Exception as e:
                logger.error(f"Error parsing config for user '{slug}': {e}")
                raise ValueError(f"Invalid config for user '{slug}': {e}") from e

        if not users:
            raise ValueError("No users configured in config file")

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
           KIMAI_USER_MAX_USER_ID=1 (optional)
           KIMAI_USER_MAX_SSL_VERIFY=true (optional)
        """
        users = {}

        # Try JSON format first
        json_config = os.getenv("USERS_CONFIG")
        if json_config:
            try:
                data = json.loads(json_config)
                for slug, user_data in data.items():
                    users[slug] = UserConfig(**user_data)
                    logger.info(f"Loaded config for user '{slug}' from USERS_CONFIG")
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

                user_id_key = f"{prefix}{slug.upper()}_USER_ID"
                ssl_key = f"{prefix}{slug.upper()}_SSL_VERIFY"

                users[slug] = UserConfig(
                    kimai_url=value,
                    kimai_token=token,
                    kimai_user_id=os.getenv(user_id_key),
                    ssl_verify=os.getenv(ssl_key, "true"),
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

    def list_users(self) -> list[str]:
        """List all configured user slugs."""
        return list(self.users.keys())

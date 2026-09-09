"""Configuration for bonfire_lib reservation lifecycle operations.

Can be constructed explicitly (for MCP server / testing) or
loaded from environment variables via Settings.from_env().
"""

import os
from dataclasses import dataclass

# GitHub API config for fetching templates from GitHub repos.
GH_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com")
GH_TOKEN = os.getenv("GITHUB_TOKEN")

# Override path for the GitLab CA bundle used to verify TLS to
# gitlab.cee.redhat.com. When unset, the cert bundled with the package is used.
GL_CA_CERT_ENV = "BONFIRE_GL_CA_CERT"
GL_CA_CERT = os.getenv(GL_CA_CERT_ENV)


@dataclass
class Settings:
    """Configuration for bonfire_lib reservation lifecycle operations.

    Can be constructed explicitly (for MCP server / testing) or
    loaded from environment variables via Settings.from_env().
    """

    default_namespace_pool: str = "default"
    default_reservation_duration: str = "1h"
    default_requester: str = ""
    ephemeral_env_name: str = "insights-ephemeral"
    default_base_namespace: str = "ephemeral-base"
    is_bot: bool = False

    @classmethod
    def from_env(cls) -> "Settings":
        """Load settings from environment variables (matching bonfire's existing env var names)."""
        return cls(
            default_namespace_pool=os.getenv("BONFIRE_DEFAULT_NAMESPACE_POOL", "default"),
            default_reservation_duration=os.getenv("BONFIRE_DEFAULT_DURATION", "1h"),
            default_requester=os.getenv("BONFIRE_NS_REQUESTER", ""),
            ephemeral_env_name=os.getenv("EPHEMERAL_ENV_NAME", "insights-ephemeral"),
            default_base_namespace=os.getenv("DEFAULT_BASE_NAMESPACE", "ephemeral-base"),
            is_bot=os.getenv("BONFIRE_BOT", "false").lower() == "true",
        )

"""Shared fixtures for bonfire_mcp tests."""

from unittest.mock import MagicMock

import pytest

from bonfire_lib.config import Settings
from bonfire_lib.k8s_client import EphemeralK8sClient


@pytest.fixture
def mock_client():
    """A mock EphemeralK8sClient for MCP server unit testing."""
    client = MagicMock(spec=EphemeralK8sClient)
    client.whoami.return_value = "test-user"
    client.list_pools.return_value = []
    client.list_reservations.return_value = []
    return client


@pytest.fixture
def settings():
    """Default settings for testing."""
    return Settings()

import pytest
from unittest.mock import MagicMock
from bonfire_lib.k8s_client import EphemeralK8sClient
from bonfire_lib.config import Settings


@pytest.fixture
def mock_client():
    """A mock EphemeralK8sClient for unit testing."""
    client = MagicMock(spec=EphemeralK8sClient)
    client.whoami.return_value = "test_at_user.com"
    return client


@pytest.fixture
def settings():
    """Default settings for testing."""
    return Settings()


@pytest.fixture
def sample_reservation():
    return {
        "apiVersion": "cloud.redhat.com/v1alpha1",
        "kind": "NamespaceReservation",
        "metadata": {"name": "test-reservation", "labels": {"requester": "test-user"}},
        "spec": {
            "duration": "1h",
            "requester": "test-user",
            "pool": "default",
        },
        "status": {
            "state": "active",
            "namespace": "ephemeral-abc123",
            "expiration": "2026-04-09T12:00:00Z",
            "pool": "default",
        },
    }


@pytest.fixture
def sample_pool():
    return {
        "apiVersion": "cloud.redhat.com/v1alpha1",
        "kind": "NamespacePool",
        "metadata": {"name": "default"},
        "spec": {
            "size": 5,
            "sizeLimit": 10,
            "description": "Default pool",
        },
        "status": {
            "ready": 3,
            "creating": 1,
            "reserved": 2,
        },
    }

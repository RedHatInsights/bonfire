import pytest
from unittest.mock import MagicMock


@pytest.fixture
def mock_lib_client(mocker):
    """Patch _get_lib_client in bonfire.namespaces so CLI tests don't hit a real cluster.

    Returns the mock EphemeralK8sClient instance for further configuration.
    """
    from bonfire_lib.k8s_client import EphemeralK8sClient

    mock_client = MagicMock(spec=EphemeralK8sClient)
    mock_client.whoami.return_value = "test_at_user.com"
    mocker.patch("bonfire.namespaces._get_lib_client", return_value=mock_client)
    return mock_client

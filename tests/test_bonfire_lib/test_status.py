import base64
from unittest.mock import patch

import pytest

from bonfire_lib.status import (
    get_reservation,
    list_reservations,
    wait_on_reservation,
    check_for_existing_reservation,
    get_console_url,
    describe_namespace,
)
from bonfire_lib.utils import FatalError


class TestGetReservation:
    def test_by_name(self, mock_client, sample_reservation):
        mock_client.get_reservation.return_value = sample_reservation
        result = get_reservation(mock_client, name="test-reservation")
        assert result["metadata"]["name"] == "test-reservation"

    def test_by_name_not_found(self, mock_client):
        mock_client.get_reservation.return_value = None
        result = get_reservation(mock_client, name="nonexistent")
        assert result is None

    def test_by_namespace(self, mock_client, sample_reservation):
        mock_client.list_reservations.return_value = [sample_reservation]
        result = get_reservation(mock_client, namespace="ephemeral-abc123")
        assert result["metadata"]["name"] == "test-reservation"

    def test_by_namespace_not_found(self, mock_client):
        mock_client.list_reservations.return_value = []
        result = get_reservation(mock_client, namespace="nonexistent")
        assert result is None

    def test_by_requester_single(self, mock_client, sample_reservation):
        mock_client.list_reservations.return_value = [sample_reservation]
        result = get_reservation(mock_client, requester="test-user")
        assert result is not None

    def test_by_requester_multiple(self, mock_client, sample_reservation):
        mock_client.list_reservations.return_value = [sample_reservation, sample_reservation]
        result = get_reservation(mock_client, requester="test-user")
        assert result is None

    def test_by_requester_none(self, mock_client):
        mock_client.list_reservations.return_value = []
        result = get_reservation(mock_client, requester="test-user")
        assert result is None

    def test_no_args(self, mock_client):
        result = get_reservation(mock_client)
        assert result is None


class TestListReservations:
    def test_all_reservations(self, mock_client, sample_reservation):
        mock_client.list_reservations.return_value = [sample_reservation]
        result = list_reservations(mock_client)
        assert len(result) == 1
        assert result[0]["name"] == "test-reservation"
        assert result[0]["namespace"] == "ephemeral-abc123"
        assert result[0]["state"] == "active"
        assert result[0]["requester"] == "test-user"
        assert result[0]["pool"] == "default"
        assert result[0]["duration"] == "1h"

    def test_filtered_by_requester(self, mock_client, sample_reservation):
        mock_client.list_reservations.return_value = [sample_reservation]
        result = list_reservations(mock_client, requester="test-user")
        assert len(result) == 1
        mock_client.list_reservations.assert_called_with(label_selector="requester=test-user")

    def test_empty_list(self, mock_client):
        mock_client.list_reservations.return_value = []
        result = list_reservations(mock_client)
        assert result == []


class TestWaitOnReservation:
    def test_returns_when_namespace_set(self, mock_client):
        mock_client.get_reservation.side_effect = [
            {"status": {}},
            {"status": {"namespace": "ephemeral-xyz"}},
        ]
        result = wait_on_reservation(mock_client, "test-res", timeout=600)
        assert result == "ephemeral-xyz"

    @patch("bonfire_lib.status.time")
    def test_timeout_raises(self, mock_time, mock_client):
        mock_client.get_reservation.return_value = {"status": {}}
        mock_time.time.side_effect = [0, 0, 100, 200]
        mock_time.sleep = lambda x: None

        with pytest.raises(TimeoutError, match="timed out"):
            wait_on_reservation(mock_client, "test-res", timeout=1)


class TestCheckForExistingReservation:
    def test_has_active_reservation(self, mock_client, sample_reservation):
        mock_client.list_reservations.return_value = [sample_reservation]
        mock_client.get_namespace.return_value = {"metadata": {"name": "ephemeral-abc123"}}

        assert check_for_existing_reservation(mock_client, "test-user") is True

    def test_no_active_reservation(self, mock_client):
        mock_client.list_reservations.return_value = []
        assert check_for_existing_reservation(mock_client, "test-user") is False

    def test_reservation_but_ns_gone(self, mock_client, sample_reservation):
        mock_client.list_reservations.return_value = [sample_reservation]
        mock_client.get_namespace.return_value = None

        assert check_for_existing_reservation(mock_client, "test-user") is False


class TestGetConsoleUrl:
    def test_returns_url(self, mock_client):
        mock_client.get_configmap.return_value = {
            "data": {"consoleURL": "https://console.example.com"}
        }
        result = get_console_url(mock_client)
        assert result == "https://console.example.com"

    def test_configmap_not_found(self, mock_client):
        mock_client.get_configmap.return_value = None
        result = get_console_url(mock_client)
        assert result is None

    def test_exception_returns_none(self, mock_client):
        mock_client.get_configmap.side_effect = Exception("connection error")
        result = get_console_url(mock_client)
        assert result is None


class TestDescribeNamespace:
    def test_comprehensive_output(self, mock_client):
        mock_client.get_namespace.return_value = {
            "metadata": {"name": "ephemeral-test", "labels": {"operator-ns": "true"}}
        }
        mock_client.list_crds.side_effect = [
            [{"metadata": {"name": "app1"}}, {"metadata": {"name": "app2"}}],  # ClowdApps
            [{"metadata": {"name": "fe1"}}],  # Frontends
        ]
        mock_client.get_crd.return_value = {
            "spec": {"hostname": "test.example.com", "sso": "https://keycloak.example.com"}
        }
        mock_client.get_secret.return_value = {
            "data": {
                "username": base64.b64encode(b"admin").decode(),
                "password": base64.b64encode(b"secret").decode(),
                "defaultUsername": base64.b64encode(b"user1").decode(),
                "defaultPassword": base64.b64encode(b"pass1").decode(),
            }
        }
        mock_client.get_configmap.return_value = {
            "data": {"consoleURL": "https://console.example.com"}
        }

        result = describe_namespace(mock_client, "ephemeral-test")

        assert result["namespace"] == "ephemeral-test"
        assert result["clowdapps_deployed"] == 2
        assert result["frontends_deployed"] == 1
        assert result["keycloak_admin_username"] == "admin"
        assert result["keycloak_admin_password"] == "secret"
        assert result["default_username"] == "user1"
        assert result["default_password"] == "pass1"
        assert result["gateway_route"] == "https://test.example.com"
        assert result["keycloak_admin_route"] == "https://keycloak.example.com"
        assert "console.example.com" in result["console_namespace_route"]

    def test_namespace_not_found(self, mock_client):
        mock_client.get_namespace.return_value = None
        with pytest.raises(FatalError, match="not found"):
            describe_namespace(mock_client, "nonexistent")

    def test_not_operator_ns(self, mock_client):
        mock_client.get_namespace.return_value = {"metadata": {"name": "regular-ns", "labels": {}}}
        with pytest.raises(FatalError, match="was not reserved"):
            describe_namespace(mock_client, "regular-ns")

    def test_no_keycloak_secret(self, mock_client):
        mock_client.get_namespace.return_value = {
            "metadata": {"name": "ephemeral-test", "labels": {"operator-ns": "true"}}
        }
        mock_client.list_crds.return_value = []
        mock_client.get_crd.return_value = None
        mock_client.get_secret.return_value = None
        mock_client.get_configmap.return_value = None

        result = describe_namespace(mock_client, "ephemeral-test")
        assert result["keycloak_admin_username"] == "N/A"
        assert result["keycloak_admin_password"] == "N/A"
        assert result["gateway_route"] == ""
        assert result["console_namespace_route"] == ""

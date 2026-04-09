from unittest.mock import patch

import pytest

from bonfire_lib.reservations import reserve, release, extend, _find_reservation
from bonfire_lib.utils import FatalError


class TestReserve:
    def test_happy_path(self, mock_client, sample_reservation):
        mock_client.get_reservation.side_effect = [
            None,  # check for existing
            sample_reservation,  # poll returns namespace
            sample_reservation,  # final get for return dict
        ]
        mock_client.create_reservation.return_value = sample_reservation

        result = reserve(
            mock_client,
            name="test-reservation",
            duration="1h",
            requester="test-user",
            pool="default",
        )

        assert result["name"] == "test-reservation"
        assert result["namespace"] == "ephemeral-abc123"
        assert result["requester"] == "test-user"
        assert result["pool"] == "default"
        mock_client.create_reservation.assert_called_once()

    def test_duplicate_name_raises(self, mock_client, sample_reservation):
        mock_client.get_reservation.return_value = sample_reservation

        with pytest.raises(FatalError, match="already exists"):
            reserve(mock_client, name="test-reservation")

    @patch("bonfire_lib.reservations.time")
    def test_timeout_auto_releases(self, mock_time, mock_client):
        mock_client.get_reservation.side_effect = [
            None,  # check existing
            {"status": {}},  # poll - no namespace yet (then timeout)
            {"metadata": {"name": "test-res"}, "spec": {}},  # release._find_reservation
        ]
        mock_time.time.side_effect = [0, 0, 100]
        mock_time.sleep = lambda x: None

        with pytest.raises(TimeoutError, match="timed out"):
            reserve(mock_client, name="test-res", timeout=1)

        mock_client.patch_reservation.assert_called_once_with(
            "test-res", {"spec": {"duration": "0s"}}
        )

    def test_auto_generated_name(self, mock_client, sample_reservation):
        mock_client.get_reservation.side_effect = [
            None,
            sample_reservation,
            sample_reservation,
        ]
        mock_client.create_reservation.return_value = sample_reservation

        result = reserve(mock_client, duration="1h", requester="test-user")
        assert result["name"].startswith("bonfire-reservation-")

    def test_default_requester_from_whoami(self, mock_client, sample_reservation):
        mock_client.get_reservation.side_effect = [
            None,
            sample_reservation,
            sample_reservation,
        ]
        mock_client.create_reservation.return_value = sample_reservation

        result = reserve(mock_client, name="test-res")
        assert result["requester"] == "test_at_user.com"


class TestRelease:
    def test_by_name(self, mock_client, sample_reservation):
        mock_client.get_reservation.return_value = sample_reservation

        result = release(mock_client, name="test-reservation")

        assert result["name"] == "test-reservation"
        assert result["released"] is True
        mock_client.patch_reservation.assert_called_once_with(
            "test-reservation", {"spec": {"duration": "0s"}}
        )

    def test_by_namespace(self, mock_client, sample_reservation):
        mock_client.list_reservations.return_value = [sample_reservation]

        result = release(mock_client, namespace="ephemeral-abc123")

        assert result["name"] == "test-reservation"
        assert result["released"] is True

    def test_unknown_name_raises(self, mock_client):
        mock_client.get_reservation.return_value = None

        with pytest.raises(FatalError, match="not found"):
            release(mock_client, name="nonexistent")

    def test_no_args_raises(self, mock_client):
        with pytest.raises(FatalError, match="Must provide"):
            release(mock_client)


class TestExtend:
    def test_happy_path(self, mock_client, sample_reservation):
        mock_client.list_reservations.return_value = [sample_reservation]

        result = extend(mock_client, namespace="ephemeral-abc123", duration="30m")

        assert result["name"] == "test-reservation"
        assert result["new_duration"] == "1h30m0s"
        mock_client.patch_reservation.assert_called_once_with(
            "test-reservation", {"spec": {"duration": "1h30m0s"}}
        )

    def test_expired_raises(self, mock_client):
        expired_res = {
            "metadata": {"name": "expired-res"},
            "spec": {"duration": "1h", "requester": "user", "pool": "default"},
            "status": {"state": "expired", "namespace": "ephemeral-expired"},
        }
        mock_client.list_reservations.return_value = [expired_res]

        with pytest.raises(FatalError, match="has expired"):
            extend(mock_client, namespace="ephemeral-expired", duration="1h")

    def test_not_found_raises(self, mock_client):
        mock_client.list_reservations.return_value = []

        with pytest.raises(FatalError, match="No reservation found"):
            extend(mock_client, namespace="nonexistent", duration="1h")


class TestFindReservation:
    def test_by_name_found(self, mock_client, sample_reservation):
        mock_client.get_reservation.return_value = sample_reservation
        result = _find_reservation(mock_client, name="test-reservation")
        assert result["metadata"]["name"] == "test-reservation"

    def test_by_name_not_found(self, mock_client):
        mock_client.get_reservation.return_value = None
        with pytest.raises(FatalError, match="not found"):
            _find_reservation(mock_client, name="nonexistent")

    def test_by_namespace_found(self, mock_client, sample_reservation):
        mock_client.list_reservations.return_value = [sample_reservation]
        result = _find_reservation(mock_client, namespace="ephemeral-abc123")
        assert result["metadata"]["name"] == "test-reservation"

    def test_by_namespace_not_found(self, mock_client):
        mock_client.list_reservations.return_value = []
        with pytest.raises(FatalError, match="No reservation found"):
            _find_reservation(mock_client, namespace="nonexistent")

    def test_neither_raises(self, mock_client):
        with pytest.raises(FatalError, match="Must provide"):
            _find_reservation(mock_client)

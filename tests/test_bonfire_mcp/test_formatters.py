"""Tests for bonfire_mcp.formatters module."""

from bonfire_mcp.formatters import (
    format_cluster_pool_list,
    format_cluster_reservation,
    format_cluster_reservation_list,
    format_describe,
    format_extend,
    format_kubeconfig,
    format_pool_list,
    format_release,
    format_reservation,
    format_reservation_list,
)


class TestFormatReservation:
    def test_basic(self):
        result = format_reservation({
            "name": "test-res",
            "namespace": "ephemeral-abc",
            "state": "active",
            "expiration": "2026-04-09T12:00:00Z",
            "requester": "user",
            "pool": "default",
        })
        assert "test-res" in result
        assert "active" in result
        assert "ephemeral-abc" in result
        assert "user" in result

    def test_pending_namespace(self):
        result = format_reservation({
            "name": "test-res",
            "state": "waiting",
        })
        assert "pending" in result
        assert "waiting" in result


class TestFormatPoolList:
    def test_empty(self):
        assert "No namespace pools" in format_pool_list([])

    def test_with_pools(self):
        result = format_pool_list([
            {
                "name": "default",
                "ready": 3,
                "creating": 1,
                "reserved": 2,
                "size": 5,
                "size_limit": 10,
            },
            {
                "name": "minimal",
                "ready": 1,
                "creating": 0,
                "reserved": 0,
                "size": 2,
                "size_limit": None,
            },
        ])
        assert "default" in result
        assert "minimal" in result
        assert "3" in result


class TestFormatReservationList:
    def test_empty(self):
        assert "No active reservations" in format_reservation_list([])

    def test_with_reservations(self):
        result = format_reservation_list([
            {
                "name": "res-1",
                "namespace": "ns-1",
                "state": "active",
                "requester": "user1",
                "pool": "default",
                "duration": "1h",
            },
        ])
        assert "res-1" in result
        assert "ns-1" in result
        assert "user1" in result


class TestFormatDescribe:
    def test_full_info(self):
        result = format_describe({
            "namespace": "ephemeral-abc",
            "console_namespace_route": "https://console.example.com/k8s/cluster/projects/ephemeral-abc",
            "gateway_route": "https://front.example.com",
            "clowdapps_deployed": 3,
            "frontends_deployed": 2,
            "keycloak_admin_route": "https://keycloak.example.com",
            "keycloak_admin_username": "admin",
            "keycloak_admin_password": "secret",
            "default_username": "user",
            "default_password": "pass",
        })
        assert "ephemeral-abc" in result
        assert "3" in result
        assert "admin" in result
        assert "https://front.example.com" in result

    def test_minimal_info(self):
        result = format_describe({
            "namespace": "test-ns",
            "clowdapps_deployed": 0,
            "frontends_deployed": 0,
        })
        assert "test-ns" in result
        assert "0" in result


class TestFormatRelease:
    def test_release(self):
        result = format_release({"name": "my-res"})
        assert "my-res" in result
        assert "released" in result


class TestFormatExtend:
    def test_extend(self):
        result = format_extend({"name": "my-res", "new_duration": "2h0m0s"})
        assert "my-res" in result
        assert "2h0m0s" in result


class TestFormatClusterReservation:
    def test_waiting(self):
        result = format_cluster_reservation({
            "name": "my-rosa",
            "state": "waiting",
            "requester": "user",
            "pool": "rosa-default",
        })
        assert "my-rosa" in result
        assert "waiting" in result
        assert "Poll with" in result

    def test_provisioning(self):
        result = format_cluster_reservation({
            "name": "my-rosa",
            "state": "provisioning",
            "requester": "user",
            "pool": "rosa-default",
        })
        assert "provisioning" in result
        assert "Poll with" in result

    def test_active(self):
        result = format_cluster_reservation({
            "name": "my-rosa",
            "state": "active",
            "cluster_name": "rosa-abc123",
            "console_url": "https://console.apps.rosa-abc123.example.com",
            "requester": "user",
            "pool": "rosa-default",
            "expiration": "2026-04-09T16:00:00Z",
        })
        assert "active" in result
        assert "rosa-abc123" in result
        assert "https://console" in result
        assert "Poll with" not in result


class TestFormatClusterPoolList:
    def test_empty(self):
        assert "No cluster pools" in format_cluster_pool_list([])

    def test_with_pools(self):
        result = format_cluster_pool_list([
            {
                "name": "rosa-default",
                "ready": 2,
                "provisioning": 1,
                "reserved": 1,
                "size": 3,
                "size_limit": 5,
            },
        ])
        assert "rosa-default" in result
        assert "Cluster Pools" in result


class TestFormatKubeconfig:
    def test_kubeconfig(self):
        result = format_kubeconfig("my-rosa", "apiVersion: v1\nclusters: []")
        assert "my-rosa" in result
        assert "apiVersion: v1" in result


class TestFormatClusterReservationList:
    def test_empty(self):
        assert "No active cluster reservations" in format_cluster_reservation_list([])

    def test_with_reservations(self):
        result = format_cluster_reservation_list([
            {
                "name": "rosa-res-1",
                "cluster_name": "rosa-abc123",
                "state": "active",
                "requester": "user1",
                "pool": "rosa-default",
                "duration": "4h",
            },
        ])
        assert "rosa-res-1" in result
        assert "rosa-abc123" in result
        assert "Active Cluster Reservations" in result

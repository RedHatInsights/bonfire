"""Tests for bonfire_mcp.formatters module."""

from bonfire_mcp.formatters import (
    format_deploy_rosa,
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
        result = format_reservation(
            {
                "name": "test-res",
                "namespace": "ephemeral-abc",
                "state": "active",
                "expiration": "2026-04-09T12:00:00Z",
                "requester": "user",
                "pool": "default",
            }
        )
        assert "test-res" in result
        assert "active" in result
        assert "ephemeral-abc" in result
        assert "user" in result

    def test_pending_namespace(self):
        result = format_reservation(
            {
                "name": "test-res",
                "state": "waiting",
            }
        )
        assert "pending" in result
        assert "waiting" in result


class TestFormatPoolList:
    def test_empty(self):
        assert "No namespace pools" in format_pool_list([])

    def test_with_pools(self):
        result = format_pool_list(
            [
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
            ]
        )
        assert "default" in result
        assert "minimal" in result
        assert "3" in result


class TestFormatReservationList:
    def test_empty(self):
        assert "No active reservations" in format_reservation_list([])

    def test_with_reservations(self):
        result = format_reservation_list(
            [
                {
                    "name": "res-1",
                    "namespace": "ns-1",
                    "state": "active",
                    "requester": "user1",
                    "pool": "default",
                    "duration": "1h",
                },
            ]
        )
        assert "res-1" in result
        assert "ns-1" in result
        assert "user1" in result


class TestFormatDescribe:
    def test_full_info(self):
        result = format_describe(
            {
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
            }
        )
        assert "ephemeral-abc" in result
        assert "3" in result
        assert "admin" in result
        assert "https://front.example.com" in result

    def test_minimal_info(self):
        result = format_describe(
            {
                "namespace": "test-ns",
                "clowdapps_deployed": 0,
                "frontends_deployed": 0,
            }
        )
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


class TestFormatKubeconfig:
    def test_kubeconfig(self):
        result = format_kubeconfig("my-rosa", "apiVersion: v1\nclusters: []")
        assert "my-rosa" in result
        assert "apiVersion: v1" in result


class TestFormatDeployRosa:
    def test_full_result(self):
        result = format_deploy_rosa(
            {
                "namespace": "ephemeral-rosa-abc",
                "describe": {
                    "namespace": "ephemeral-rosa-abc",
                    "console_namespace_route": "https://console.example.com/k8s/cluster/projects/ephemeral-rosa-abc",
                    "gateway_route": "https://my-gateway.example.com",
                    "clowdapps_deployed": 3,
                    "frontends_deployed": 2,
                    "keycloak_admin_route": "https://keycloak.example.com",
                    "keycloak_admin_username": "admin",
                    "keycloak_admin_password": "secret",
                    "default_username": "user@example.com",
                    "default_password": "userpass",
                },
                "deploy_output": "Deploying...\nephemeral-rosa-abc\n",
            }
        )
        assert "ROSA Cluster Deployed" in result
        assert "ephemeral-rosa-abc" in result
        assert "https://console.example.com" in result
        assert "https://my-gateway.example.com" in result
        assert "3" in result
        assert "admin" in result

    def test_minimal_result(self):
        result = format_deploy_rosa(
            {
                "namespace": "ephemeral-rosa-xyz",
                "describe": {
                    "namespace": "ephemeral-rosa-xyz",
                    "clowdapps_deployed": 0,
                    "frontends_deployed": 0,
                },
                "deploy_output": "ephemeral-rosa-xyz\n",
            }
        )
        assert "ROSA Cluster Deployed" in result
        assert "ephemeral-rosa-xyz" in result

"""Tests for bonfire_mcp.auth module."""

import os
from unittest.mock import MagicMock, patch

import pytest

from bonfire_mcp.auth import load_k8s_client, _preflight_check


class TestLoadK8sClient:
    @patch("bonfire_mcp.auth._preflight_check")
    @patch("bonfire_mcp.auth.EphemeralK8sClient")
    def test_server_token_auth(self, mock_cls, mock_preflight, monkeypatch):
        monkeypatch.setenv("K8S_SERVER", "https://api.example.com:6443")
        monkeypatch.setenv("K8S_TOKEN", "sha256~abc123")
        monkeypatch.delenv("K8S_CA_DATA", raising=False)
        monkeypatch.delenv("K8S_SKIP_TLS_VERIFY", raising=False)

        load_k8s_client()
        mock_cls.assert_called_once_with(
            server="https://api.example.com:6443",
            token="sha256~abc123",
            ca_data=None,
            skip_tls=False,
        )

    @patch("bonfire_mcp.auth._preflight_check")
    @patch("bonfire_mcp.auth.EphemeralK8sClient")
    def test_server_token_with_ca_data(self, mock_cls, mock_preflight, monkeypatch):
        monkeypatch.setenv("K8S_SERVER", "https://api.example.com:6443")
        monkeypatch.setenv("K8S_TOKEN", "sha256~abc123")
        monkeypatch.setenv("K8S_CA_DATA", "LS0tLS1CRUdJTi...")
        monkeypatch.setenv("K8S_SKIP_TLS_VERIFY", "false")

        load_k8s_client()
        mock_cls.assert_called_once_with(
            server="https://api.example.com:6443",
            token="sha256~abc123",
            ca_data="LS0tLS1CRUdJTi...",
            skip_tls=False,
        )

    @patch("bonfire_mcp.auth._preflight_check")
    @patch("bonfire_mcp.auth.EphemeralK8sClient")
    def test_server_token_skip_tls(self, mock_cls, mock_preflight, monkeypatch):
        monkeypatch.setenv("K8S_SERVER", "https://api.example.com:6443")
        monkeypatch.setenv("K8S_TOKEN", "sha256~abc123")
        monkeypatch.setenv("K8S_SKIP_TLS_VERIFY", "true")

        load_k8s_client()
        mock_cls.assert_called_once_with(
            server="https://api.example.com:6443",
            token="sha256~abc123",
            ca_data=None,
            skip_tls=True,
        )

    @patch("bonfire_mcp.auth._preflight_check")
    @patch("bonfire_mcp.auth.EphemeralK8sClient")
    def test_in_cluster_auth(self, mock_cls, mock_preflight, monkeypatch):
        monkeypatch.delenv("K8S_SERVER", raising=False)
        monkeypatch.delenv("K8S_TOKEN", raising=False)
        mock_cls._is_in_cluster.return_value = True

        load_k8s_client()
        mock_cls.assert_called_once_with()

    @patch("bonfire_mcp.auth._preflight_check")
    @patch("bonfire_mcp.auth.EphemeralK8sClient")
    def test_kubeconfig_auth(self, mock_cls, mock_preflight, monkeypatch):
        monkeypatch.delenv("K8S_SERVER", raising=False)
        monkeypatch.delenv("K8S_TOKEN", raising=False)
        mock_cls._is_in_cluster.return_value = False
        monkeypatch.setenv("KUBECONFIG", "/home/user/.kube/config")
        monkeypatch.setenv("K8S_CONTEXT", "my-context")

        load_k8s_client()
        mock_cls.assert_called_once_with(
            kubeconfig_path="/home/user/.kube/config", context="my-context"
        )

    @patch("bonfire_mcp.auth._preflight_check")
    @patch("bonfire_mcp.auth.EphemeralK8sClient")
    def test_kubeconfig_default(self, mock_cls, mock_preflight, monkeypatch):
        monkeypatch.delenv("K8S_SERVER", raising=False)
        monkeypatch.delenv("K8S_TOKEN", raising=False)
        monkeypatch.delenv("KUBECONFIG", raising=False)
        monkeypatch.delenv("K8S_CONTEXT", raising=False)
        mock_cls._is_in_cluster.return_value = False

        load_k8s_client()
        mock_cls.assert_called_once_with(kubeconfig_path=None, context=None)


class TestPreflightCheck:
    def test_success(self):
        client = MagicMock()
        client.list_pools.return_value = []
        _preflight_check(client)

    def test_crd_not_found(self):
        client = MagicMock()
        client.list_pools.side_effect = Exception("404 not found")
        with pytest.raises(RuntimeError, match="NamespacePool CRD not found"):
            _preflight_check(client)

    def test_auth_failure(self):
        client = MagicMock()
        client.list_pools.side_effect = Exception("401 Unauthorized")
        with pytest.raises(RuntimeError, match="authentication failed"):
            _preflight_check(client)

    def test_connection_failure(self):
        client = MagicMock()
        client.list_pools.side_effect = Exception("Connection refused")
        with pytest.raises(RuntimeError, match="Failed to connect"):
            _preflight_check(client)

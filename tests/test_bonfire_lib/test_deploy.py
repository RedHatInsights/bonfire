"""Tests for bonfire_lib.deploy module."""

import pytest
from unittest.mock import MagicMock, patch, call

from bonfire_lib.deploy import (
    deploy_rosa,
    wait_for_resources,
    _collect_components,
    _build_parameters,
    _is_capi_cluster_ready,
    _is_clowdapp_ready,
    _is_deployment_ready,
)
from bonfire_lib.utils import FatalError


class TestCollectComponents:
    def test_filters_components(self):
        apps_config = {
            "ephemeral": {
                "name": "ephemeral",
                "components": [
                    {"name": "rosa-ephemeral-cluster", "ref": "abc"},
                    {"name": "other-component", "ref": "def"},
                ],
            }
        }
        result = _collect_components(apps_config, ["rosa-ephemeral-cluster"])
        assert len(result) == 1
        assert result[0]["name"] == "rosa-ephemeral-cluster"

    def test_empty_filter_returns_all(self):
        apps_config = {
            "app": {
                "components": [
                    {"name": "a"},
                    {"name": "b"},
                ],
            }
        }
        result = _collect_components(apps_config, [])
        assert len(result) == 2

    def test_no_match(self):
        apps_config = {"app": {"components": [{"name": "a"}]}}
        result = _collect_components(apps_config, ["nonexistent"])
        assert result == []


class TestBuildParameters:
    def test_default_image_tag(self):
        component = {"parameters": {}, "hash_length": 7}
        params = _build_parameters(
            component, "abc1234567890", "my-ns", "env-my-ns"
        )
        assert params["IMAGE_TAG"] == "abc1234"
        assert params["NAMESPACE"] == "my-ns"
        assert params["ENV_NAME"] == "env-my-ns"

    def test_existing_image_tag_preserved(self):
        component = {"parameters": {"IMAGE_TAG": "custom"}}
        params = _build_parameters(component, "abc1234", "ns", "env-ns")
        assert params["IMAGE_TAG"] == "custom"

    def test_existing_namespace_preserved(self):
        component = {"parameters": {"NAMESPACE": "fixed-ns"}}
        params = _build_parameters(component, "abc", "ns", "env-ns")
        assert params["NAMESPACE"] == "fixed-ns"

    def test_custom_hash_length(self):
        component = {"parameters": {}, "hash_length": 10}
        params = _build_parameters(
            component, "abc1234567890abcdef", "ns", "env-ns"
        )
        assert params["IMAGE_TAG"] == "abc1234567"


class TestIsCapiClusterReady:
    def test_ready_condition(self):
        cluster = {
            "status": {
                "conditions": [
                    {"type": "Ready", "status": "True"}
                ]
            }
        }
        assert _is_capi_cluster_ready(cluster) is True

    def test_available_condition(self):
        cluster = {
            "status": {
                "conditions": [
                    {"type": "Available", "status": "True"}
                ]
            }
        }
        assert _is_capi_cluster_ready(cluster) is True

    def test_not_ready(self):
        cluster = {
            "status": {
                "conditions": [
                    {"type": "Ready", "status": "False"}
                ]
            }
        }
        assert _is_capi_cluster_ready(cluster) is False

    def test_no_conditions(self):
        assert _is_capi_cluster_ready({}) is False

    def test_provisioning(self):
        cluster = {
            "status": {
                "conditions": [
                    {"type": "InfrastructureReady", "status": "True"},
                    {"type": "Ready", "status": "False"},
                ]
            }
        }
        assert _is_capi_cluster_ready(cluster) is False


class TestIsClowdappReady:
    def test_ready_via_condition(self):
        app = {
            "status": {
                "conditions": [
                    {"type": "ReconciliationSuccessful", "status": "True"}
                ]
            }
        }
        assert _is_clowdapp_ready(app) is True

    def test_not_ready_via_condition(self):
        app = {
            "status": {
                "conditions": [
                    {"type": "ReconciliationSuccessful", "status": "False"}
                ]
            }
        }
        assert _is_clowdapp_ready(app) is False

    def test_ready_via_deployments(self):
        app = {
            "status": {
                "deployments": {
                    "readyDeployments": 3,
                    "managedDeployments": 3,
                }
            }
        }
        assert _is_clowdapp_ready(app) is True

    def test_not_ready_via_deployments(self):
        app = {
            "status": {
                "deployments": {
                    "readyDeployments": 1,
                    "managedDeployments": 3,
                }
            }
        }
        assert _is_clowdapp_ready(app) is False

    def test_empty_status(self):
        assert _is_clowdapp_ready({}) is False


class TestIsDeploymentReady:
    def test_ready(self):
        dep = {"spec": {"replicas": 2}, "status": {"readyReplicas": 2}}
        assert _is_deployment_ready(dep) is True

    def test_not_ready(self):
        dep = {"spec": {"replicas": 2}, "status": {"readyReplicas": 1}}
        assert _is_deployment_ready(dep) is False

    def test_zero_replicas_is_ready(self):
        dep = {"spec": {"replicas": 0}, "status": {}}
        assert _is_deployment_ready(dep) is True

    def test_no_ready_replicas(self):
        dep = {"spec": {"replicas": 1}, "status": {}}
        assert _is_deployment_ready(dep) is False


class TestWaitForResources:
    @patch("bonfire_lib.deploy.time.sleep")
    @patch("bonfire_lib.deploy.time.time")
    def test_capi_cluster_ready(self, mock_time, mock_sleep):
        mock_time.side_effect = [0, 1]
        mock_client = MagicMock()
        mock_client.list_dynamic_resources.side_effect = [
            # CAPI Clusters — one ready cluster
            [{"status": {"conditions": [{"type": "Ready", "status": "True"}]}}],
            # ClowdApps — none
            [],
            # Deployments — none
            [],
        ]
        wait_for_resources(mock_client, "test-ns", timeout=60)

    @patch("bonfire_lib.deploy.time.sleep")
    @patch("bonfire_lib.deploy.time.time")
    def test_clowdapp_and_deployment_ready(self, mock_time, mock_sleep):
        mock_time.side_effect = [0, 1]
        mock_client = MagicMock()
        mock_client.list_dynamic_resources.side_effect = [
            # CAPI Clusters — none
            [],
            # ClowdApps — one ready
            [{"status": {"conditions": [{"type": "ReconciliationSuccessful", "status": "True"}]}}],
            # Deployments — one ready
            [{"spec": {"replicas": 1}, "status": {"readyReplicas": 1}}],
        ]
        wait_for_resources(mock_client, "test-ns", timeout=60)

    @patch("bonfire_lib.deploy.time.sleep")
    @patch("bonfire_lib.deploy.time.time")
    def test_no_resources_waits_until_timeout(self, mock_time, mock_sleep):
        mock_time.return_value = 1000
        mock_client = MagicMock()
        mock_client.list_dynamic_resources.return_value = []

        with pytest.raises(TimeoutError, match="timed out"):
            wait_for_resources(mock_client, "test-ns", timeout=0)

    @patch("bonfire_lib.deploy.time.sleep")
    @patch("bonfire_lib.deploy.time.time")
    def test_capi_cluster_not_ready_keeps_polling(self, mock_time, mock_sleep):
        mock_time.side_effect = [0, 1, 2, 3]
        mock_client = MagicMock()
        mock_client.list_dynamic_resources.side_effect = [
            # Poll 1: cluster not ready
            [{"status": {"conditions": [{"type": "Ready", "status": "False"}]}}],
            # Poll 2: cluster ready
            [{"status": {"conditions": [{"type": "Ready", "status": "True"}]}}],
            [],
            [],
        ]
        wait_for_resources(mock_client, "test-ns", timeout=60)
        mock_sleep.assert_called_once()


class TestDeployRosa:
    @patch("bonfire_lib.deploy.wait_for_resources")
    @patch("bonfire_lib.deploy.RepoFile")
    @patch("bonfire_lib.deploy.get_apps_for_env")
    def test_end_to_end(self, mock_get_apps, mock_repo_cls, mock_wait):
        mock_get_apps.return_value = {
            "ephemeral": {
                "name": "ephemeral",
                "components": [
                    {
                        "name": "rosa-ephemeral-cluster",
                        "host": "github",
                        "repo": "org/repo",
                        "path": "/template.yaml",
                        "ref": "a" * 40,
                        "hash_length": 7,
                        "parameters": {},
                    }
                ],
            }
        }

        template_yaml = b"""\
apiVersion: template.openshift.io/v1
kind: Template
parameters:
  - name: IMAGE_TAG
  - name: NAMESPACE
  - name: ENV_NAME
objects:
  - apiVersion: apps/v1
    kind: Deployment
    metadata:
      name: test-deploy
"""

        mock_rf = MagicMock()
        mock_rf.fetch.return_value = ("a" * 40, template_yaml)
        mock_rf.org = "org"
        mock_rf.repo = "repo"
        mock_rf.ref = "a" * 40
        mock_rf.path = "/template.yaml"
        mock_repo_cls.from_component.return_value = mock_rf

        mock_client = MagicMock()
        mock_client.process_template.return_value = [
            {
                "apiVersion": "apps/v1",
                "kind": "Deployment",
                "metadata": {"name": "test-deploy"},
            }
        ]
        mock_client.apply_resource.return_value = {"metadata": {"name": "test-deploy"}}

        result = deploy_rosa(
            mock_client,
            namespace="ephemeral-test",
            timeout=1800,
        )

        assert result["namespace"] == "ephemeral-test"
        assert result["components_deployed"] == ["rosa-ephemeral-cluster"]
        assert result["resources_applied"] == 1

        mock_client.process_template.assert_called_once()
        mock_client.apply_resource.assert_called_once()
        mock_wait.assert_called_once()

    @patch("bonfire_lib.deploy.get_apps_for_env")
    def test_no_apps_raises(self, mock_get_apps):
        mock_get_apps.return_value = {}
        mock_client = MagicMock()

        with pytest.raises(FatalError, match="no app configs"):
            deploy_rosa(mock_client, namespace="ns")

    @patch("bonfire_lib.deploy.get_apps_for_env")
    def test_no_matching_components_raises(self, mock_get_apps):
        mock_get_apps.return_value = {
            "app": {
                "name": "app",
                "components": [{"name": "wrong-component"}],
            }
        }
        mock_client = MagicMock()

        with pytest.raises(FatalError, match="no components matching"):
            deploy_rosa(mock_client, namespace="ns")

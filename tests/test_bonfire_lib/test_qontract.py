"""Tests for bonfire_lib.qontract module."""

import pytest
from unittest.mock import MagicMock, patch

from bonfire_lib.qontract import (
    QontractClient,
    get_apps_for_env,
    _to_dict,
    _process_env_parameters,
    _check_replace_other,
)


class TestToDict:
    def test_none(self):
        assert _to_dict(None) == {}

    def test_empty_string(self):
        assert _to_dict("") == {}

    def test_valid_json(self):
        assert _to_dict('{"key": "val"}') == {"key": "val"}


class TestProcessEnvParameters:
    def test_variable_substitution(self):
        params = {"HOST": "kafka.svc", "URL": "${HOST}:9092"}
        _process_env_parameters(params)
        assert params["URL"] == "kafka.svc:9092"

    def test_no_substitution_needed(self):
        params = {"HOST": "kafka.svc", "PORT": "9092"}
        _process_env_parameters(params)
        assert params == {"HOST": "kafka.svc", "PORT": "9092"}

    def test_missing_variable_left_alone(self):
        params = {"URL": "${MISSING_VAR}:9092"}
        _process_env_parameters(params)
        assert params["URL"] == "${MISSING_VAR}:9092"


class TestCheckReplaceOther:
    def test_higher_preferred_weight_wins(self):
        other = {"CLOWDER_ENABLED": "false"}
        this = {"CLOWDER_ENABLED": "true"}
        assert _check_replace_other(other, this, {}) is True

    def test_equal_weight_does_not_replace(self):
        other = {"CLOWDER_ENABLED": "true"}
        this = {"CLOWDER_ENABLED": "true"}
        assert _check_replace_other(other, this, {}) is False

    def test_replicas_weight(self):
        other = {"REPLICAS": "0"}
        this = {"REPLICAS": "1"}
        assert _check_replace_other(other, this, {}) is True


class TestQontractClient:
    @patch("bonfire_lib.qontract.RequestsHTTPTransport")
    @patch("bonfire_lib.qontract.GQLClient")
    def test_init_with_token(self, mock_gql, mock_transport):
        client = QontractClient(
            base_url="https://example.com/graphql",
            token="Bearer mytoken",
        )
        mock_transport.assert_called_once()
        call_kwargs = mock_transport.call_args
        assert call_kwargs[1]["headers"] == {"Authorization": "Bearer mytoken"}

    @patch("bonfire_lib.qontract.RequestsHTTPTransport")
    @patch("bonfire_lib.qontract.GQLClient")
    def test_init_with_basic_auth(self, mock_gql, mock_transport):
        client = QontractClient(
            base_url="https://example.com/graphql",
            username="user",
            password="pass",
        )
        call_kwargs = mock_transport.call_args
        assert "auth" in call_kwargs[1]

    @patch("bonfire_lib.qontract.RequestsHTTPTransport")
    @patch("bonfire_lib.qontract.GQLClient")
    def test_init_from_env_vars(self, mock_gql, mock_transport):
        with patch.dict(
            "os.environ",
            {"QONTRACT_BASE_URL": "https://env.example.com/graphql"},
        ):
            client = QontractClient()
        call_kwargs = mock_transport.call_args
        assert call_kwargs[1]["url"] == "https://env.example.com/graphql"


class TestGetAppsForEnv:
    def _make_mock_client(self, env_data, apps_data):
        mock = MagicMock(spec=QontractClient)
        mock.get_env.return_value = env_data
        mock.get_apps.return_value = apps_data
        return mock

    def test_empty_env(self):
        assert get_apps_for_env("") == {}

    def test_basic_component_found(self):
        env = {
            "name": "rosa-ephemeral",
            "parameters": "{}",
            "namespaces": {"/path/to/ns.yml": "ephemeral-base"},
            "namespace_labels": {"/path/to/ns.yml": {}},
        }
        apps = [
            {
                "name": "ephemeral",
                "parentApp": {"name": "insights"},
                "saasFiles": [
                    {
                        "path": "/saas.yml",
                        "name": "ephemeral-saas",
                        "parameters": None,
                        "resourceTemplates": [
                            {
                                "name": "rosa-ephemeral-cluster",
                                "path": "/template.yaml",
                                "url": "https://github.com/org/repo",
                                "hash_length": 7,
                                "parameters": None,
                                "targets": [
                                    {
                                        "namespace": {
                                            "name": "ephemeral-base",
                                            "path": "/path/to/ns.yml",
                                            "cluster": {"name": "cluster1"},
                                        },
                                        "ref": "abc1234567890abcdef1234567890abcdef123456",
                                        "parameters": None,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]

        mock_client = self._make_mock_client(env, apps)
        result = get_apps_for_env("rosa-ephemeral", client=mock_client)

        assert "ephemeral" in result
        components = result["ephemeral"]["components"]
        assert len(components) == 1
        assert components[0]["name"] == "rosa-ephemeral-cluster"
        assert components[0]["host"] == "github"
        assert components[0]["repo"] == "org/repo"

    def test_non_consoledot_apps_ignored(self):
        env = {
            "name": "test-env",
            "parameters": "{}",
            "namespaces": {"/ns.yml": "ns"},
            "namespace_labels": {},
        }
        apps = [
            {
                "name": "other-app",
                "parentApp": {"name": "not-insights"},
                "saasFiles": [],
            }
        ]

        mock_client = self._make_mock_client(env, apps)
        result = get_apps_for_env("test-env", client=mock_client)
        assert result == {}

    def test_target_not_in_env_namespaces_skipped(self):
        env = {
            "name": "test-env",
            "parameters": "{}",
            "namespaces": {"/ns.yml": "ns"},
            "namespace_labels": {},
        }
        apps = [
            {
                "name": "myapp",
                "parentApp": {"name": "insights"},
                "saasFiles": [
                    {
                        "path": "/saas.yml",
                        "name": "saas",
                        "parameters": None,
                        "resourceTemplates": [
                            {
                                "name": "comp",
                                "path": "/t.yaml",
                                "url": "https://github.com/o/r",
                                "hash_length": 7,
                                "parameters": None,
                                "targets": [
                                    {
                                        "namespace": {
                                            "name": "other-ns",
                                            "path": "/other/ns.yml",
                                            "cluster": {"name": "c"},
                                        },
                                        "ref": "master",
                                        "parameters": None,
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]

        mock_client = self._make_mock_client(env, apps)
        result = get_apps_for_env("test-env", client=mock_client)
        assert result == {}

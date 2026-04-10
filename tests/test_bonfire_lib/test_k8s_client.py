from unittest.mock import patch, MagicMock

from bonfire_lib.k8s_client import EphemeralK8sClient, _sanitize_username, _extract_username


class TestSanitizeUsername:
    def test_at_sign(self):
        assert _sanitize_username("user@redhat.com") == "user_at_redhat.com"

    def test_colon(self):
        assert _sanitize_username("system:admin") == "system_admin"

    def test_both(self):
        assert _sanitize_username("u@r:c") == "u_at_r_c"

    def test_no_change(self):
        assert _sanitize_username("plainuser") == "plainuser"


class TestExtractUsername:
    def test_with_cluster_url(self):
        assert _extract_username("gbuchana/api-crc-eph-r9lp-p1-openshiftapps-com:6443") == "gbuchana"

    def test_with_simple_url(self):
        assert _extract_username("admin/api.example.com:6443") == "admin"

    def test_plain_username(self):
        assert _extract_username("gbuchana") == "gbuchana"

    def test_email_style(self):
        assert _extract_username("user@redhat.com") == "user@redhat.com"

    def test_multiple_slashes(self):
        assert _extract_username("user/host/extra") == "user"


class TestAuthModeSelection:
    @patch("bonfire_lib.k8s_client.DynamicClient")
    @patch("bonfire_lib.k8s_client.client")
    def test_server_token_mode(self, mock_client_module, mock_dynamic):
        mock_api_client = MagicMock()
        mock_client_module.Configuration.return_value = MagicMock()
        mock_client_module.ApiClient.return_value = mock_api_client
        mock_client_module.CoreV1Api.return_value = MagicMock()

        k8s = EphemeralK8sClient(server="https://api.example.com", token="mytoken")
        assert k8s._api_client is mock_api_client

    @patch("bonfire_lib.k8s_client.DynamicClient")
    @patch("bonfire_lib.k8s_client.client")
    @patch("bonfire_lib.k8s_client.config")
    @patch.object(EphemeralK8sClient, "_is_in_cluster", return_value=True)
    def test_in_cluster_mode(self, mock_in_cluster, mock_config, mock_client_module, mock_dynamic):
        mock_api_client = MagicMock()
        mock_client_module.ApiClient.return_value = mock_api_client
        mock_client_module.CoreV1Api.return_value = MagicMock()

        EphemeralK8sClient()
        mock_config.load_incluster_config.assert_called_once()

    @patch("bonfire_lib.k8s_client.DynamicClient")
    @patch("bonfire_lib.k8s_client.client")
    @patch("bonfire_lib.k8s_client.config")
    @patch.object(EphemeralK8sClient, "_is_in_cluster", return_value=False)
    def test_kubeconfig_mode(self, mock_in_cluster, mock_config, mock_client_module, mock_dynamic):
        mock_api_client = MagicMock()
        mock_client_module.ApiClient.return_value = mock_api_client
        mock_client_module.CoreV1Api.return_value = MagicMock()

        EphemeralK8sClient(kubeconfig_path="/tmp/kubeconfig", context="mycontext")
        mock_config.load_kube_config.assert_called_once_with(
            config_file="/tmp/kubeconfig",
            context="mycontext",
        )

    @patch("bonfire_lib.k8s_client.DynamicClient")
    @patch("bonfire_lib.k8s_client.client")
    def test_server_token_skip_tls(self, mock_client_module, mock_dynamic):
        mock_config = MagicMock()
        mock_client_module.Configuration.return_value = mock_config
        mock_client_module.ApiClient.return_value = MagicMock()
        mock_client_module.CoreV1Api.return_value = MagicMock()

        EphemeralK8sClient(server="https://api.example.com", token="mytoken", skip_tls=True)
        assert mock_config.verify_ssl is False

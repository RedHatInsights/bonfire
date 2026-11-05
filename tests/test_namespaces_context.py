from unittest.mock import patch

import bonfire.config as conf
import bonfire.namespaces as namespaces


def test_get_lib_client_uses_configured_context(monkeypatch):
    monkeypatch.setattr(conf, "K8S_CONTEXT", "eph")

    with patch("bonfire.namespaces.EphemeralK8sClient") as client:
        namespaces._get_lib_client()

    client.assert_called_once_with(context="eph")

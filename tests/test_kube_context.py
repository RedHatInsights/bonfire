import os
import stat
import subprocess
from unittest.mock import Mock, patch

import ocviapy

import bonfire.kube_context as kube_context


def test_configure_kube_context_uses_context_minified_kubeconfig(monkeypatch):
    monkeypatch.delattr(ocviapy, "set_default_context", raising=False)

    with patch(
        "bonfire.kube_context.subprocess.run",
        return_value=subprocess.CompletedProcess(
            args=[], returncode=0, stdout="apiVersion: v1\n", stderr=""
        ),
    ) as run:
        try:
            kube_context.configure_kube_context("eph")
            path = os.environ["KUBECONFIG"]

            assert os.path.exists(path)
            assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
            run.assert_called_once_with(
                ["oc", "config", "view", "--raw", "--minify", "--context", "eph"],
                check=True,
                capture_output=True,
                text=True,
            )
        finally:
            kube_context._cleanup_temp_kubeconfig()


def test_configure_kube_context_uses_ocviapy_default(monkeypatch):
    set_default_context = Mock()
    monkeypatch.setattr(ocviapy, "set_default_context", set_default_context, raising=False)

    with patch("bonfire.kube_context.subprocess.run") as run:
        kube_context.configure_kube_context("eph")

    set_default_context.assert_called_once_with("eph")
    run.assert_not_called()

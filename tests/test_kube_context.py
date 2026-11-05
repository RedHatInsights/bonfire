import os
import stat
import subprocess
import tempfile
from pathlib import Path
from unittest.mock import Mock, patch

import ocviapy
import pytest

import bonfire.kube_context as kube_context
from bonfire.utils import FatalError


def test_configure_kube_context_uses_context_minified_kubeconfig(monkeypatch):
    monkeypatch.delenv("KUBECONFIG", raising=False)
    monkeypatch.delattr(ocviapy, "set_default_context", raising=False)

    with (
        patch(
            "bonfire.kube_context.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="apiVersion: v1\n", stderr=""
            ),
        ) as run,
        kube_context.configure_kube_context("eph"),
    ):
        path = os.environ["KUBECONFIG"]
        assert os.path.exists(path)
        assert stat.S_IMODE(os.stat(path).st_mode) == 0o600
        run.assert_called_once_with(
            ["oc", "config", "view", "--raw", "--minify", "--context", "eph"],
            check=True,
            capture_output=True,
            text=True,
        )

    assert "KUBECONFIG" not in os.environ
    assert not os.path.exists(path)


def test_configure_kube_context_removes_directory_when_write_fails(monkeypatch, tmp_path):
    monkeypatch.delenv("KUBECONFIG", raising=False)
    monkeypatch.delattr(ocviapy, "set_default_context", raising=False)
    temp_directory = tempfile.TemporaryDirectory(dir=tmp_path)
    temp_directory_path = Path(temp_directory.name)

    with (
        patch(
            "bonfire.kube_context.subprocess.run",
            return_value=subprocess.CompletedProcess(
                args=[], returncode=0, stdout="apiVersion: v1\n", stderr=""
            ),
        ),
        patch(
            "bonfire.kube_context.tempfile.TemporaryDirectory",
            return_value=temp_directory,
        ),
        patch.object(Path, "write_text", side_effect=OSError("write failed")),
    ):
        with pytest.raises(FatalError, match="unable to create a temporary kubeconfig"):
            with kube_context.configure_kube_context("eph"):
                pass

    assert not temp_directory_path.exists()


def test_configure_kube_context_uses_ocviapy_default(monkeypatch):
    set_default_context = Mock()
    monkeypatch.setattr(ocviapy, "set_default_context", set_default_context, raising=False)

    with patch("bonfire.kube_context.subprocess.run") as run:
        with kube_context.configure_kube_context("eph"):
            pass

    set_default_context.assert_called_once_with("eph")
    run.assert_not_called()

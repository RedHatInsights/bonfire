"""Helpers for selecting the kubeconfig context used by the CLI."""

import atexit
import os
import subprocess
import tempfile

import ocviapy

from bonfire.utils import FatalError


_TEMP_KUBECONFIG_PATH: str | None = None
_ORIGINAL_KUBECONFIG: str | None = None
_KUBECONFIG_CAPTURED = False


def _cleanup_temp_kubeconfig() -> None:
    global _KUBECONFIG_CAPTURED, _ORIGINAL_KUBECONFIG, _TEMP_KUBECONFIG_PATH

    if _TEMP_KUBECONFIG_PATH is None:
        return

    try:
        os.unlink(_TEMP_KUBECONFIG_PATH)
    except FileNotFoundError:
        pass
    _TEMP_KUBECONFIG_PATH = None

    if _KUBECONFIG_CAPTURED:
        if _ORIGINAL_KUBECONFIG is None:
            os.environ.pop("KUBECONFIG", None)
        else:
            os.environ["KUBECONFIG"] = _ORIGINAL_KUBECONFIG
        _ORIGINAL_KUBECONFIG = None
        _KUBECONFIG_CAPTURED = False


def _minify_kubeconfig(context: str) -> str:
    try:
        result = subprocess.run(
            ["oc", "config", "view", "--raw", "--minify", "--context", context],
            check=True,
            capture_output=True,
            text=True,
        )
    except FileNotFoundError as exc:
        raise FatalError("unable to select a kube context: the 'oc' command was not found") from exc
    except subprocess.CalledProcessError as exc:
        raise FatalError(f"unable to select kube context '{context}'") from exc

    if not result.stdout.strip():
        raise FatalError(f"unable to select kube context '{context}': empty kubeconfig")

    try:
        with tempfile.NamedTemporaryFile(
            mode="w", prefix="bonfire-kubeconfig-", delete=False
        ) as kubeconfig:
            kubeconfig.write(result.stdout)
            path = kubeconfig.name
        os.chmod(path, 0o600)
    except OSError as exc:
        raise FatalError("unable to create a temporary kubeconfig") from exc

    return path


def configure_kube_context(context: str | None) -> None:
    """Configure all CLI Kubernetes access to use *context*.

    Newer ocviapy versions may expose ``set_default_context``. Older versions
    only use the kubeconfig's current context, so provide them with a
    short-lived, context-minified kubeconfig instead.
    """
    global _KUBECONFIG_CAPTURED, _ORIGINAL_KUBECONFIG, _TEMP_KUBECONFIG_PATH

    if not context:
        return

    set_default_context = getattr(ocviapy, "set_default_context", None)
    if set_default_context is not None:
        _cleanup_temp_kubeconfig()
        set_default_context(context)
        return

    _cleanup_temp_kubeconfig()
    _TEMP_KUBECONFIG_PATH = _minify_kubeconfig(context)
    _ORIGINAL_KUBECONFIG = os.environ.get("KUBECONFIG")
    _KUBECONFIG_CAPTURED = True
    os.environ["KUBECONFIG"] = _TEMP_KUBECONFIG_PATH
    atexit.register(_cleanup_temp_kubeconfig)

"""Helpers for selecting the kubeconfig context used by the CLI."""

from collections.abc import Iterator
from contextlib import contextmanager
import os
from pathlib import Path
import subprocess
import tempfile

import ocviapy

from bonfire.utils import FatalError


def _get_minified_kubeconfig(context: str) -> str:
    """Return the selected context as a minified kubeconfig document."""
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

    return result.stdout


@contextmanager
def configure_kube_context(context: str | None) -> Iterator[None]:
    """Scope CLI Kubernetes access to *context* for one command invocation."""
    if not context:
        yield
        return

    set_default_context = getattr(ocviapy, "set_default_context", None)
    if set_default_context is not None:
        set_default_context(context)
        yield
        return

    kubeconfig_data = _get_minified_kubeconfig(context)
    original_kubeconfig = os.environ.get("KUBECONFIG")

    with tempfile.TemporaryDirectory(prefix="bonfire-kubeconfig-") as temp_dir:
        path = Path(temp_dir) / "config"
        try:
            path.write_text(kubeconfig_data)
            path.chmod(0o600)
        except OSError as exc:
            raise FatalError("unable to create a temporary kubeconfig") from exc

        os.environ["KUBECONFIG"] = str(path)
        try:
            yield
        finally:
            if original_kubeconfig is None:
                os.environ.pop("KUBECONFIG", None)
            else:
                os.environ["KUBECONFIG"] = original_kubeconfig

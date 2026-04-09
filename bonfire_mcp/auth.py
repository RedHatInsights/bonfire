"""K8s authentication for the MCP server.

Mirrors the auth model of containers/kubernetes-mcp-server:
1. Explicit server + token (K8S_SERVER + K8S_TOKEN env vars)
2. In-cluster service account auto-detection
3. Kubeconfig file (KUBECONFIG env var or ~/.kube/config)
"""

import logging
import os

from bonfire_lib.k8s_client import EphemeralK8sClient

log = logging.getLogger(__name__)


def load_k8s_client() -> EphemeralK8sClient:
    """Load a K8s client with auth auto-detection.

    Priority order:
    1. K8S_SERVER + K8S_TOKEN env vars (explicit token auth)
    2. In-cluster detection (pod service account)
    3. KUBECONFIG env var or ~/.kube/config (kubeconfig file)

    Returns:
        EphemeralK8sClient configured with detected auth.

    Raises:
        RuntimeError: If no valid auth method is found or connection fails.
    """
    server = os.getenv("K8S_SERVER")
    token = os.getenv("K8S_TOKEN")

    if server and token:
        log.info("using K8S_SERVER + K8S_TOKEN auth (server: %s)", server)
        ca_data = os.getenv("K8S_CA_DATA")
        skip_tls = os.getenv("K8S_SKIP_TLS_VERIFY", "false").lower() == "true"
        client = EphemeralK8sClient(
            server=server, token=token, ca_data=ca_data, skip_tls=skip_tls
        )
    elif EphemeralK8sClient._is_in_cluster():
        log.info("using in-cluster service account auth")
        client = EphemeralK8sClient()
    else:
        kubeconfig = os.getenv("KUBECONFIG")
        context = os.getenv("K8S_CONTEXT")
        log.info(
            "using kubeconfig auth (file: %s, context: %s)",
            kubeconfig or "~/.kube/config",
            context or "current-context",
        )
        client = EphemeralK8sClient(kubeconfig_path=kubeconfig, context=context)

    _preflight_check(client)
    return client


def _preflight_check(client: EphemeralK8sClient) -> None:
    """Verify the client can reach the cluster and CRDs exist.

    Raises:
        RuntimeError: If the cluster is unreachable or CRDs are missing.
    """
    try:
        client.list_pools()
        log.info("preflight check passed: NamespacePool CRD accessible")
    except Exception as e:
        error_msg = str(e)
        if "404" in error_msg or "not found" in error_msg.lower():
            raise RuntimeError(
                "NamespacePool CRD not found on cluster. "
                "Is the Ephemeral Namespace Operator installed?"
            ) from e
        if "401" in error_msg or "unauthorized" in error_msg.lower():
            raise RuntimeError(
                "K8s authentication failed (401 Unauthorized). "
                "Check your K8S_TOKEN, kubeconfig, or service account credentials."
            ) from e
        raise RuntimeError(
            f"Failed to connect to the management cluster: {e}. "
            "Check network connectivity, K8S_SERVER, or KUBECONFIG."
        ) from e

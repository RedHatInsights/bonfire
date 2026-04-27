"""Pool listing and capacity query functions.

Replaces bonfire/openshift.py get_namespace_pools(), get_pool_size_limit()
— using EphemeralK8sClient instead of ocviapy.
"""

import logging

from bonfire_lib.k8s_client import EphemeralK8sClient

log = logging.getLogger(__name__)


def list_pools(client: EphemeralK8sClient) -> list[dict]:
    """List all namespace pools with capacity stats.

    Returns:
        List of dicts, each containing:
        - name: pool name
        - description: pool description
        - size: configured pool size
        - size_limit: max namespaces (None if unlimited)
        - ready: number of ready namespaces
        - creating: number of namespaces being created
        - reserved: number of reserved namespaces
    """
    pools = client.list_pools()
    result = []
    for pool in pools:
        spec = pool.get("spec", {})
        status = pool.get("status", {})
        result.append(
            {
                "name": pool["metadata"]["name"],
                "description": spec.get("description", ""),
                "size": spec.get("size", 0),
                "size_limit": spec.get("sizeLimit"),
                "ready": status.get("ready", 0),
                "creating": status.get("creating", 0),
                "reserved": status.get("reserved", 0),
            }
        )
    return result


def get_pool_capacity(client: EphemeralK8sClient, pool_name: str) -> dict | None:
    """Get capacity details for a specific pool.

    Returns:
        dict with pool capacity info, or None if pool not found
    """
    pool = client.get_pool(pool_name)
    if not pool:
        return None

    spec = pool.get("spec", {})
    status = pool.get("status", {})
    return {
        "name": pool_name,
        "description": spec.get("description", ""),
        "size": spec.get("size", 0),
        "size_limit": spec.get("sizeLimit"),
        "ready": status.get("ready", 0),
        "creating": status.get("creating", 0),
        "reserved": status.get("reserved", 0),
    }


def list_cluster_pools(client: EphemeralK8sClient) -> list[dict]:
    """List all cluster pools with capacity stats.

    Returns:
        List of dicts with cluster pool info. Returns empty list
        if ClusterPool CRD is not installed on the cluster.
    """
    try:
        pools = client.list_cluster_pools()
    except Exception:
        log.debug("ClusterPool CRD not available, skipping cluster pools")
        return []

    result = []
    for pool in pools:
        spec = pool.get("spec", {})
        status = pool.get("status", {})
        result.append(
            {
                "name": pool["metadata"]["name"],
                "type": "cluster",
                "description": spec.get("description", ""),
                "size": spec.get("size", 0),
                "size_limit": spec.get("sizeLimit", 0),
                "ready": status.get("ready", 0),
                "provisioning": status.get("provisioning", 0),
                "reserved": status.get("reserved", 0),
            }
        )
    return result


def list_all_pools(client: EphemeralK8sClient) -> dict:
    """List both namespace pools and cluster pools.

    Returns:
        dict with "namespace_pools" and "cluster_pools" keys.
    """
    return {
        "namespace_pools": list_pools(client),
        "cluster_pools": list_cluster_pools(client),
    }

"""Cluster reservation operations: reserve, release, extend, get_kubeconfig.

Handles ROSA HCP cluster reservations via ClusterReservation CRDs.
Unlike namespace reservations, cluster provisioning is async (20-40 min),
so reserve returns immediately and the caller polls status.
"""

import base64
import logging
import uuid

from bonfire_lib.core_resources import render_cluster_reservation
from bonfire_lib.k8s_client import EphemeralK8sClient
from bonfire_lib.utils import FatalError, hms_to_seconds, duration_fmt

log = logging.getLogger(__name__)

DEFAULT_CLUSTER_DURATION = "4h"
DEFAULT_CLUSTER_POOL = "rosa-default"
KUBECONFIG_SECRET_SUFFIX = "-kubeconfig"
KUBECONFIG_SECRET_NAMESPACE = "ephemeral-cluster-operator"


def reserve_cluster(
    client: EphemeralK8sClient,
    name: str | None = None,
    duration: str = DEFAULT_CLUSTER_DURATION,
    requester: str | None = None,
    pool: str = DEFAULT_CLUSTER_POOL,
    team: str | None = None,
) -> dict:
    """Reserve a ROSA HCP cluster. Returns immediately (async provisioning).

    Unlike namespace reservations, this does NOT poll for assignment.
    The caller should use get_cluster_status() to poll.

    Args:
        client: K8s API client
        name: Reservation name (auto-generated if None)
        duration: Duration string (default: "4h")
        requester: Requester identity (defaults to client.whoami())
        pool: Cluster pool to reserve from (default: "rosa-default")
        team: Team for cost attribution

    Returns:
        dict with keys: name, state ("waiting"), requester, pool, type ("cluster")
    """
    if name is None:
        name = f"cluster-reservation-{str(uuid.uuid4()).split('-')[0]}"

    if requester is None:
        try:
            requester = client.whoami()
        except Exception:
            requester = "bonfire"

    existing = client.get_cluster_reservation(name)
    if existing:
        raise FatalError(f"Cluster reservation with name {name} already exists")

    body = render_cluster_reservation(
        name=name,
        duration=duration,
        requester=requester,
        pool=pool,
        team=team,
    )
    client.create_cluster_reservation(body)

    log.info(
        "cluster reservation '%s' created by '%s' for '%s' from pool '%s'",
        name, requester, duration, pool,
    )

    return {
        "name": name,
        "state": "waiting",
        "requester": requester,
        "pool": pool,
        "type": "cluster",
    }


def release_cluster(
    client: EphemeralK8sClient,
    name: str,
) -> dict:
    """Release a cluster reservation by setting duration to 0s."""
    res = client.get_cluster_reservation(name)
    if not res:
        raise FatalError(f"Cluster reservation '{name}' not found")

    client.patch_cluster_reservation(name, {"spec": {"duration": "0s"}})
    log.info("releasing cluster reservation '%s'", name)
    return {"name": name, "released": True}


def extend_cluster(
    client: EphemeralK8sClient,
    name: str,
    duration: str,
) -> dict:
    """Extend a cluster reservation's duration."""
    res = client.get_cluster_reservation(name)
    if not res:
        raise FatalError(f"Cluster reservation '{name}' not found")

    state = res.get("status", {}).get("state", "")
    if state == "expired":
        raise FatalError(
            f"Cluster reservation '{name}' has expired. Reserve a new cluster."
        )

    prev_seconds = hms_to_seconds(res["spec"]["duration"])
    add_seconds = hms_to_seconds(duration)
    new_duration = duration_fmt(prev_seconds + add_seconds)

    client.patch_cluster_reservation(name, {"spec": {"duration": new_duration}})
    log.info("cluster reservation '%s' extended by '%s' (new total: %s)", name, duration, new_duration)
    return {"name": name, "new_duration": new_duration}


def get_cluster_status(
    client: EphemeralK8sClient,
    name: str,
) -> dict | None:
    """Get the status of a cluster reservation.

    Returns:
        dict with reservation details including state
        ("waiting", "provisioning", "active"), cluster_name, console_url.
        None if not found.
    """
    res = client.get_cluster_reservation(name)
    if not res:
        return None

    status = res.get("status", {})
    spec = res.get("spec", {})
    creation = res.get("metadata", {}).get("creationTimestamp", "")

    return {
        "name": res["metadata"]["name"],
        "type": "cluster",
        "state": status.get("state", ""),
        "cluster_name": status.get("clusterName", ""),
        "console_url": status.get("consoleURL", ""),
        "expiration": status.get("expiration", ""),
        "requester": spec.get("requester", ""),
        "pool": spec.get("pool", DEFAULT_CLUSTER_POOL),
        "duration": spec.get("duration", ""),
        "created": creation,
    }


def get_kubeconfig(
    client: EphemeralK8sClient,
    name: str,
) -> str:
    """Fetch kubeconfig YAML for a provisioned cluster reservation.

    The kubeconfig is stored in a Secret named <clusterName>-kubeconfig
    on the management cluster.

    Args:
        client: K8s API client
        name: Cluster reservation name

    Returns:
        Kubeconfig YAML string

    Raises:
        FatalError: If reservation not found, cluster not assigned,
                    or kubeconfig Secret not yet available
    """
    res = client.get_cluster_reservation(name)
    if not res:
        raise FatalError(f"Cluster reservation '{name}' not found")

    cluster_name = res.get("status", {}).get("clusterName", "")
    if not cluster_name:
        state = res.get("status", {}).get("state", "unknown")
        raise FatalError(
            f"Cluster not yet assigned to reservation '{name}' (state: {state}). "
            "Poll with ephemeral_status() until state is 'active'."
        )

    secret_name = f"{cluster_name}{KUBECONFIG_SECRET_SUFFIX}"
    secret = client.get_secret(secret_name, KUBECONFIG_SECRET_NAMESPACE)
    if not secret:
        raise FatalError(
            f"Kubeconfig Secret '{secret_name}' not found in namespace "
            f"'{KUBECONFIG_SECRET_NAMESPACE}'. The cluster may still be bootstrapping."
        )

    kubeconfig_data = secret.get("data", {}).get("kubeconfig", "")
    if not kubeconfig_data:
        kubeconfig_data = secret.get("data", {}).get("value", "")

    if not kubeconfig_data:
        raise FatalError(
            f"Kubeconfig Secret '{secret_name}' exists but contains no kubeconfig data."
        )

    return base64.b64decode(kubeconfig_data).decode("utf-8")

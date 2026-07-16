"""Reservation lifecycle operations: reserve, release, extend.

Replaces bonfire/namespaces.py reserve_namespace(), release_reservation(),
extend_namespace() — using EphemeralK8sClient instead of ocviapy.
"""

import base64
import logging
import uuid

from bonfire_lib.core_resources import render_reservation
from bonfire_lib.k8s_client import EphemeralK8sClient
from bonfire_lib.status import wait_on_reservation
from bonfire_lib.utils import FatalError, hms_to_seconds, duration_fmt

KUBECONFIG_SECRET_SUFFIX = "-kubeconfig"
KUBECONFIG_SECRET_NAMESPACE = "ephemeral-cluster-operator"

log = logging.getLogger(__name__)

DEFAULT_TIMEOUT = 600  # 10 minutes


def reserve(
    client: EphemeralK8sClient,
    name: str | None = None,
    duration: str = "1h",
    requester: str | None = None,
    pool: str = "default",
    team: str | None = None,
    secrets_src_namespace: str | None = None,
    timeout: int = DEFAULT_TIMEOUT,
) -> dict:
    """Reserve an ephemeral namespace.

    Creates a NamespaceReservation CR and polls until a namespace is assigned.

    Args:
        client: K8s API client
        name: Reservation name (auto-generated if None)
        duration: Duration string (e.g., "1h", "2h30m")
        requester: Requester identity (defaults to client.whoami())
        pool: Pool to reserve from
        team: Team for cost attribution
        secrets_src_namespace: Override secret source namespace
        timeout: Max seconds to wait for namespace assignment

    Returns:
        dict with keys: name (reservation name), namespace (assigned namespace name),
        state, expiration, requester, pool

    Raises:
        FatalError: If reservation already exists or creation fails
        TimeoutError: If namespace not assigned within timeout
    """
    if name is None:
        name = f"bonfire-reservation-{str(uuid.uuid4()).split('-')[0]}"

    if requester is None:
        try:
            requester = client.whoami()
        except Exception:
            requester = "bonfire"

    existing = client.get_reservation(name)
    if existing:
        raise FatalError(f"Reservation with name {name} already exists")

    body = render_reservation(
        name=name,
        duration=duration,
        requester=requester,
        pool=pool,
        team=team,
        secrets_src_namespace=secrets_src_namespace,
    )
    client.create_reservation(body)

    try:
        ns_name = wait_on_reservation(client, name, timeout)
    except TimeoutError:
        log.info("timeout waiting for namespace, cancelling reservation")
        release(client, name=name)
        raise

    log.info(
        "namespace '%s' reserved by '%s' for '%s' from pool '%s'",
        ns_name,
        requester,
        duration,
        pool,
    )

    res = client.get_reservation(name)
    return {
        "name": name,
        "namespace": ns_name,
        "state": res.get("status", {}).get("state", ""),
        "expiration": res.get("status", {}).get("expiration", ""),
        "requester": requester,
        "pool": pool,
    }


def release(
    client: EphemeralK8sClient,
    name: str | None = None,
    namespace: str | None = None,
) -> dict:
    """Release a reservation by setting duration to 0s.

    The ENO poller picks up reservations with duration=0s within 10 seconds
    and deletes them, which cascades to namespace deletion via OwnerRef.

    Args:
        client: K8s API client
        name: Reservation name (mutually exclusive with namespace)
        namespace: Namespace name to find reservation for

    Returns:
        dict with reservation name and release status
    """
    res = _find_reservation(client, name=name, namespace=namespace)

    res_name = res["metadata"]["name"]
    client.patch_reservation(res_name, {"spec": {"duration": "0s"}})

    log.info("releasing reservation '%s'", res_name)
    return {"name": res_name, "released": True}


def extend(
    client: EphemeralK8sClient,
    namespace: str,
    duration: str,
) -> dict:
    """Extend a reservation's duration.

    Adds the specified duration to the reservation's current duration.

    Args:
        client: K8s API client
        namespace: Namespace to extend reservation for
        duration: Additional duration to add (e.g., "1h", "30m")

    Returns:
        dict with reservation name and new duration
    """
    res = _find_reservation(client, namespace=namespace)

    state = res.get("status", {}).get("state", "")
    if state == "expired":
        raise FatalError(
            f"Reservation for namespace {namespace} has expired. Reserve a new namespace."
        )

    prev_seconds = hms_to_seconds(res["spec"]["duration"])
    add_seconds = hms_to_seconds(duration)
    new_duration = duration_fmt(prev_seconds + add_seconds)

    res_name = res["metadata"]["name"]
    client.patch_reservation(res_name, {"spec": {"duration": new_duration}})

    log.info(
        "reservation for ns '%s' extended by '%s' (new total: %s)",
        namespace,
        duration,
        new_duration,
    )
    return {"name": res_name, "new_duration": new_duration}


def _find_reservation(
    client: EphemeralK8sClient,
    name: str | None = None,
    namespace: str | None = None,
) -> dict:
    """Find a reservation by name or namespace."""
    if name:
        res = client.get_reservation(name)
        if not res:
            raise FatalError(f"Reservation '{name}' not found")
        return res
    elif namespace:
        all_res = client.list_reservations()
        for res in all_res:
            if res.get("status", {}).get("namespace") == namespace:
                return res
        raise FatalError(f"No reservation found for namespace '{namespace}'")
    else:
        raise FatalError("Must provide either name or namespace")


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

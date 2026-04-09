"""Reservation lifecycle operations: reserve, release, extend.

Replaces bonfire/namespaces.py reserve_namespace(), release_reservation(),
extend_namespace() — using EphemeralK8sClient instead of ocviapy.
"""

import logging
import time
import uuid

from bonfire_lib.core_resources import render_reservation
from bonfire_lib.k8s_client import EphemeralK8sClient
from bonfire_lib.utils import FatalError, hms_to_seconds, duration_fmt

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
        ns_name = _wait_for_namespace(client, name, timeout)
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


def _wait_for_namespace(client: EphemeralK8sClient, res_name: str, timeout: int) -> str:
    """Poll reservation status until namespace is assigned."""
    log.info("waiting for reservation '%s' to get picked up by operator", res_name)
    start = time.time()
    while time.time() - start < timeout:
        res = client.get_reservation(res_name)
        if res:
            ns = res.get("status", {}).get("namespace")
            if ns:
                return ns
        time.sleep(2)
    raise TimeoutError(
        f"timed out after {timeout}s waiting for namespace on reservation '{res_name}'"
    )


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

"""Reservation status queries, polling, and namespace description.

Replaces bonfire/openshift.py get_reservation(), get_all_reservations(),
wait_on_reservation(), get_console_url(), check_for_existing_reservation()
and bonfire/namespaces.py describe_namespace()
— using EphemeralK8sClient instead of ocviapy.
"""

import base64
import logging
import time

from bonfire_lib.k8s_client import EphemeralK8sClient
from bonfire_lib.utils import FatalError

log = logging.getLogger(__name__)


def get_reservation(
    client: EphemeralK8sClient,
    name: str | None = None,
    namespace: str | None = None,
    requester: str | None = None,
) -> dict | None:
    """Look up a reservation by name, namespace, or requester.

    Matches the lookup semantics of bonfire/openshift.py:get_reservation().
    """
    if name:
        return client.get_reservation(name)
    elif namespace:
        for res in client.list_reservations():
            if res.get("status", {}).get("namespace") == namespace:
                return res
    elif requester:
        reservations = client.list_reservations(label_selector=f"requester={requester}")
        if len(reservations) == 0:
            return None
        elif len(reservations) == 1:
            return reservations[0]
        else:
            log.info("Multiple reservations found for requester '%s'", requester)
            return None
    return None


def list_reservations(
    client: EphemeralK8sClient,
    requester: str | None = None,
) -> list[dict]:
    """List all reservations, optionally filtered by requester.

    Returns:
        List of reservation summary dicts.
    """
    if requester:
        reservations = client.list_reservations(label_selector=f"requester={requester}")
    else:
        reservations = client.list_reservations()

    result = []
    for res in reservations:
        status = res.get("status", {})
        spec = res.get("spec", {})
        result.append(
            {
                "name": res["metadata"]["name"],
                "namespace": status.get("namespace", ""),
                "state": status.get("state", ""),
                "expiration": status.get("expiration", ""),
                "requester": spec.get("requester", ""),
                "pool": spec.get("pool", "default"),
                "duration": spec.get("duration", ""),
            }
        )
    return result


def get_reservation_summary(res: dict) -> dict:
    """Extract a structured summary from a raw reservation dict.

    Avoids duplicating extraction logic across callers.
    """
    status = res.get("status", {})
    spec = res.get("spec", {})
    return {
        "name": res["metadata"]["name"],
        "namespace": status.get("namespace", ""),
        "state": status.get("state", ""),
        "expiration": status.get("expiration", ""),
        "requester": spec.get("requester", ""),
        "pool": spec.get("pool", "default"),
        "duration": spec.get("duration", ""),
    }


def wait_on_reservation(
    client: EphemeralK8sClient,
    name: str,
    timeout: int = 600,
) -> str:
    """Poll reservation until namespace is assigned.

    Returns:
        The assigned namespace name.

    Raises:
        TimeoutError if namespace not assigned within timeout.
    """
    log.info("waiting for reservation '%s' to get picked up by operator", name)
    start = time.time()
    while time.time() - start < timeout:
        res = client.get_reservation(name)
        if res:
            ns = res.get("status", {}).get("namespace")
            if ns:
                return ns
        time.sleep(2)
    raise TimeoutError(f"timed out after {timeout}s waiting for namespace on reservation '{name}'")


def check_for_existing_reservation(
    client: EphemeralK8sClient,
    requester: str,
) -> bool:
    """Check if requester already has an active reservation."""
    for res in client.list_reservations():
        if (
            res.get("spec", {}).get("requester") == requester
            and res.get("status", {}).get("state") == "active"
        ):
            ns = res["status"].get("namespace", "")
            if ns and client.get_namespace(ns):
                return True
    return False


def get_console_url(client: EphemeralK8sClient) -> str | None:
    """Get the OpenShift console URL from the cluster's console-public configmap."""
    try:
        cm = client.get_configmap("console-public", "openshift-config-managed")
        if cm:
            return cm.get("data", {}).get("consoleURL")
    except Exception as err:
        log.debug("unable to obtain console url: %s: %s", err.__class__.__name__, err)
    return None


def describe_namespace(client: EphemeralK8sClient, namespace: str) -> dict:
    """Get detailed information about an ephemeral namespace.

    Returns a dict with namespace details including:
    - namespace name, console URL
    - ClowdApp count and status
    - Frontend count
    - Gateway route, keycloak credentials
    """
    ns = client.get_namespace(namespace)
    if not ns:
        raise FatalError(f"namespace '{namespace}' not found")

    labels = ns.get("metadata", {}).get("labels", {})
    if labels.get("operator-ns") != "true":
        raise FatalError(f"namespace '{namespace}' was not reserved with namespace operator")

    try:
        clowdapps = client.list_crds("ClowdApp", namespace=namespace)
    except Exception as exc:
        log.warning("failed to list ClowdApps in namespace '%s': %s", namespace, exc)
        clowdapps = []

    try:
        frontends = client.list_crds("Frontend", namespace=namespace)
    except Exception as exc:
        log.warning("failed to list Frontends in namespace '%s': %s", namespace, exc)
        frontends = []

    fe_host = ""
    keycloak_url = ""
    try:
        fe_env = client.get_crd("FrontendEnvironment", f"env-{namespace}")
        if fe_env:
            fe_host = fe_env.get("spec", {}).get("hostname", "")
            keycloak_url = fe_env.get("spec", {}).get("sso", "")
    except Exception as exc:
        log.warning("failed to get FrontendEnvironment for namespace '%s': %s", namespace, exc)

    kc_creds = _get_keycloak_creds(client, namespace)

    console_url = get_console_url(client)
    ns_url = f"{console_url}/k8s/cluster/projects/{namespace}" if console_url else ""

    return {
        "namespace": namespace,
        "console_namespace_route": ns_url,
        "keycloak_admin_route": keycloak_url,
        "keycloak_admin_username": kc_creds.get("username", "N/A"),
        "keycloak_admin_password": kc_creds.get("password", "N/A"),
        "clowdapps_deployed": len(clowdapps),
        "frontends_deployed": len(frontends),
        "default_username": kc_creds.get("defaultUsername", "N/A"),
        "default_password": kc_creds.get("defaultPassword", "N/A"),
        "gateway_route": f"https://{fe_host}" if fe_host else "",
    }


def _get_keycloak_creds(client: EphemeralK8sClient, namespace: str) -> dict:
    """Get keycloak credentials from the namespace's keycloak secret."""
    secret = client.get_secret(f"env-{namespace}-keycloak", namespace)
    creds = {}
    if secret and "data" in secret:
        for key in ("username", "password", "defaultUsername", "defaultPassword"):
            raw = secret["data"].get(key, "")
            creds[key] = base64.b64decode(raw).decode("utf-8") if raw else "N/A"
    else:
        for key in ("username", "password", "defaultUsername", "defaultPassword"):
            creds[key] = "N/A"
    return creds

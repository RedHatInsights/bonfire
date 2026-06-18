"""Deploy orchestration — fetch, process, apply, and wait.

Ties together qontract, repo_fetch, and k8s_client to deploy
components to an ephemeral namespace without shelling out to
the bonfire CLI or requiring the oc binary.
"""

import logging
import time

import yaml

from bonfire_lib.k8s_client import EphemeralK8sClient
from bonfire_lib.qontract import QontractClient, get_apps_for_env
from bonfire_lib.repo_fetch import RepoFile
from bonfire_lib.utils import FatalError

log = logging.getLogger(__name__)

DEFAULT_COMPONENT_FILTER = ["rosa-ephemeral-cluster"]
DEFAULT_TARGET_ENV = "rosa-ephemeral"


def deploy_rosa(
    client: EphemeralK8sClient,
    namespace: str,
    target_env: str = DEFAULT_TARGET_ENV,
    component_filter: list[str] | None = None,
    env_name: str | None = None,
    timeout: int = 1800,
    qontract_client: QontractClient | None = None,
) -> dict:
    """Deploy ROSA components to a reserved namespace.

    Fetches app configs from app-interface, downloads templates from git,
    processes them via the OpenShift Template API, applies the resulting
    resources, and waits for readiness.

    Args:
        client: K8s client for the management cluster
        namespace: Target namespace (must already be reserved)
        target_env: App-interface environment name
        component_filter: Component names to deploy (default: rosa-ephemeral-cluster)
        env_name: ClowdEnvironment name (default: env-{namespace})
        timeout: Max seconds to wait for resource readiness
        qontract_client: Optional pre-configured QontractClient

    Returns:
        dict with keys: namespace, components_deployed, resources_applied
    """
    if component_filter is None:
        component_filter = list(DEFAULT_COMPONENT_FILTER)

    if env_name is None:
        env_name = f"env-{namespace}"

    log.info(
        "deploying to namespace '%s' (env=%s, components=%s)",
        namespace, target_env, component_filter,
    )

    apps_config = get_apps_for_env(
        target_env, client=qontract_client,
    )

    if not apps_config:
        raise FatalError(
            f"no app configs found for env '{target_env}' in app-interface"
        )

    components = _collect_components(apps_config, component_filter)
    if not components:
        raise FatalError(
            f"no components matching filter {component_filter} "
            f"found in env '{target_env}'"
        )

    all_resources = []
    components_deployed = []

    for component in components:
        log.info("processing component '%s'", component["name"])

        commit, template_content = _fetch_template(component)
        template = _parse_template(component["name"], template_content)
        params = _build_parameters(component, commit, namespace, env_name)

        processed_items = client.process_template(template, params)
        log.info(
            "component '%s' produced %d resources",
            component["name"], len(processed_items),
        )

        all_resources.extend(processed_items)
        components_deployed.append(component["name"])

    applied = _apply_resources(client, namespace, all_resources)

    log.info(
        "applied %d resources to namespace '%s', waiting for readiness (timeout=%ds)",
        len(applied), namespace, timeout,
    )
    wait_for_resources(client, namespace, timeout)

    return {
        "namespace": namespace,
        "components_deployed": components_deployed,
        "resources_applied": len(applied),
    }


def _collect_components(
    apps_config: dict, component_filter: list[str]
) -> list[dict]:
    """Flatten apps_config and filter to requested components."""
    components = []
    filter_set = set(component_filter) if component_filter else None

    for app_name, app in apps_config.items():
        for component in app.get("components", []):
            if filter_set and component["name"] not in filter_set:
                continue
            components.append(component)

    return components


def _fetch_template(component: dict) -> tuple[str, bytes]:
    """Fetch the template file from git for a component."""
    rf = RepoFile.from_component(component)
    log.debug(
        "component '%s': fetching template from %s/%s ref=%s path=%s",
        component["name"], rf.org, rf.repo, rf.ref, rf.path,
    )
    return rf.fetch()


def _parse_template(component_name: str, content: bytes) -> dict:
    """Parse template YAML content."""
    try:
        return yaml.safe_load(content)
    except Exception as err:
        raise FatalError(
            f"failed to parse template YAML for component '{component_name}': {err}"
        )


def _build_parameters(
    component: dict,
    commit: str,
    namespace: str,
    env_name: str,
) -> dict:
    """Build the parameter dict for template processing."""
    params = dict(component.get("parameters") or {})

    if "IMAGE_TAG" not in params:
        hash_length = int(component.get("hash_length") or 7)
        params["IMAGE_TAG"] = commit[:hash_length]

    if "NAMESPACE" not in params:
        params["NAMESPACE"] = namespace

    params["ENV_NAME"] = env_name
    params["FRONTEND_CONTEXT_NAME"] = env_name

    return params


def _apply_resources(
    client: EphemeralK8sClient,
    namespace: str,
    resources: list[dict],
) -> list[dict]:
    """Apply a list of K8s resources to a namespace."""
    applied = []
    for resource in resources:
        kind = resource.get("kind", "?")
        name = resource.get("metadata", {}).get("name", "?")
        log.debug("applying %s/%s to namespace '%s'", kind, name, namespace)
        try:
            result = client.apply_resource(resource, namespace=namespace)
            applied.append(result)
        except Exception as err:
            raise FatalError(
                f"failed to apply {kind}/{name} to namespace '{namespace}': {err}"
            )
    return applied


def wait_for_resources(
    client: EphemeralK8sClient,
    namespace: str,
    timeout: int = 600,
) -> None:
    """Wait for all resources in a namespace to become ready.

    Polls CAPI Clusters, ClowdApps, and Deployments for readiness.
    The ROSA template creates cluster.x-k8s.io Cluster resources whose
    status.conditions[type=Ready] aggregates readiness from the
    ROSACluster and ROSAControlPlane children.

    Raises:
        TimeoutError: If resources not ready within timeout
    """
    start = time.time()
    poll_interval = 10
    found_resources = False

    while True:
        elapsed = time.time() - start
        if elapsed >= timeout:
            raise TimeoutError(
                f"timed out after {timeout}s waiting for resources "
                f"in namespace '{namespace}'"
            )

        all_ready = True

        # CAPI Clusters (ROSA deploys)
        try:
            clusters = client.list_dynamic_resources(
                "cluster.x-k8s.io/v1beta1", "Cluster", namespace=namespace
            )
            if clusters:
                found_resources = True
            for cluster in clusters:
                if not _is_capi_cluster_ready(cluster):
                    all_ready = False
                    break
        except Exception as err:
            log.debug("error listing CAPI Clusters: %s", err)

        # ClowdApps
        if all_ready:
            try:
                clowdapps = client.list_dynamic_resources(
                    "cloud.redhat.com/v1alpha1", "ClowdApp", namespace=namespace
                )
                if clowdapps:
                    found_resources = True
                for app in clowdapps:
                    if not _is_clowdapp_ready(app):
                        all_ready = False
                        break
            except Exception as err:
                log.debug("error listing ClowdApps: %s", err)

        # Deployments
        if all_ready:
            try:
                deployments = client.list_dynamic_resources(
                    "apps/v1", "Deployment", namespace=namespace
                )
                if deployments:
                    found_resources = True
                for dep in deployments:
                    if not _is_deployment_ready(dep):
                        all_ready = False
                        break
            except Exception as err:
                log.debug("error listing Deployments: %s", err)

        if all_ready and found_resources:
            log.info("all resources in namespace '%s' are ready", namespace)
            return

        if not found_resources:
            log.debug(
                "no resources found yet in namespace '%s' (%.0fs elapsed)",
                namespace, elapsed,
            )

        time.sleep(poll_interval)


def _is_capi_cluster_ready(cluster: dict) -> bool:
    """Check if a CAPI Cluster is ready via status.conditions."""
    conditions = cluster.get("status", {}).get("conditions", [])
    for cond in conditions:
        if cond.get("type") in ("Ready", "Available") and cond.get("status") == "True":
            return True
    return False


def _is_clowdapp_ready(app: dict) -> bool:
    """Check if a ClowdApp is ready."""
    status = app.get("status", {})

    conditions = status.get("conditions", [])
    for cond in conditions:
        cond_type = cond.get("type", "")
        if cond_type in ("ReconciliationSuccessful", "DeploymentsReady", "Ready"):
            if cond.get("status") == "True":
                return True

    deployments = status.get("deployments", {})
    if deployments:
        ready = deployments.get("readyDeployments", 0)
        managed = deployments.get("managedDeployments", 0)
        if managed > 0 and ready >= managed:
            return True

    return False


def _is_deployment_ready(dep: dict) -> bool:
    """Check if a Deployment has all replicas ready."""
    spec_replicas = dep.get("spec", {}).get("replicas", 1)
    if spec_replicas == 0:
        return True
    ready_replicas = dep.get("status", {}).get("readyReplicas") or 0
    return ready_replicas >= spec_replicas

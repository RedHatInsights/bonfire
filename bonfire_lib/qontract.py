"""App-interface GraphQL client for fetching app/component deployment configs.

Simplified extraction of bonfire/qontract.py — keeps only what's needed
for the ROSA ephemeral deploy flow (get_apps_for_env). No dependency on
the bonfire CLI package, bonfire.config, or bonfire.utils.
"""

import copy
import json
import logging
import os
import re
from urllib.parse import urlparse

from gql import Client as GQLClient
from gql import gql
from gql.transport.requests import RequestsHTTPTransport
from requests.auth import HTTPBasicAuth

log = logging.getLogger(__name__)


DEFAULT_GRAPHQL_URL = (
    "https://app-interface.apps.rosa.appsrep09ue1.03r5.p3.openshiftapps.com/graphql"
)

CONSOLEDOT_PARENT_APPS = ("insights", "image-builder")

ENVS_QUERY = gql(
    """
    {
      envs: environments_v1 {
        name
        parameters
        namespaces {
          name
          path
          labels
        }
      }
    }
    """
)

APPS_QUERY = gql(
    """
    {
      apps: apps_v1 {
        name
        parentApp {
          name
        }
        saasFiles {
          path
          name
          parameters
          resourceTemplates {
            name
            path
            url
            hash_length
            parameters
            targets {
              namespace {
                name
                path
                cluster {
                  name
                }
              }
              ref
              parameters
            }
          }
        }
      }
    }
    """
)


class QontractClient:
    """GraphQL client for querying app-interface."""

    def __init__(
        self,
        base_url: str | None = None,
        token: str | None = None,
        username: str | None = None,
        password: str | None = None,
    ):
        app_interface_base = os.getenv("APP_INTERFACE_BASE_URL")
        if base_url is None:
            base_url = os.getenv("QONTRACT_BASE_URL")
            if not base_url and app_interface_base:
                base_url = f"https://{app_interface_base}/graphql"
            if not base_url:
                base_url = DEFAULT_GRAPHQL_URL

        if token is None:
            token = os.getenv("QONTRACT_TOKEN")
        if username is None:
            username = os.getenv(
                "QONTRACT_USERNAME", os.getenv("APP_INTERFACE_USERNAME")
            )
        if password is None:
            password = os.getenv(
                "QONTRACT_PASSWORD", os.getenv("APP_INTERFACE_PASSWORD")
            )

        log.debug("qontract url: %s", base_url)

        transport_kwargs = {"url": base_url}

        if token:
            log.debug("using token authentication")
            transport_kwargs["headers"] = {"Authorization": token}
        elif username and password:
            log.debug("using basic authentication")
            transport_kwargs["auth"] = HTTPBasicAuth(username, password)

        transport = RequestsHTTPTransport(**transport_kwargs)
        self._client = GQLClient(
            transport=transport, fetch_schema_from_transport=False
        )

        logging.getLogger("gql").setLevel(logging.ERROR)

    def get_env(self, env_name: str) -> dict:
        """Get environment configuration by name."""
        for env_data in self._client.execute(ENVS_QUERY)["envs"]:
            if env_data["name"] == env_name:
                raw_namespaces = env_data.get("namespaces") or []
                env_data["namespaces"] = {
                    ns["path"]: ns["name"] for ns in raw_namespaces
                }
                env_data["namespace_labels"] = {
                    ns["path"]: _to_dict(ns.get("labels"))
                    for ns in raw_namespaces
                }
                return env_data
        raise ValueError(f"cannot find env '{env_name}'")

    def get_apps(self) -> list[dict]:
        """Get all app definitions from app-interface."""
        return self._client.execute(APPS_QUERY)["apps"]


def _to_dict(nullable_json_str):
    return json.loads(nullable_json_str or "{}")


def _process_env_parameters(parameters):
    """Resolve variable references in place, e.g. KAFKA_URL='${KAFKA_HOST}:9092'."""
    for key, val in parameters.items():
        if isinstance(val, str):
            found = re.findall(r"\$\{([^$]+)\}", val)
            for var in found:
                if var in parameters:
                    parameters[key] = parameters[key].replace(
                        "${" + var + "}", parameters[var]
                    )


def _check_replace_other(other_params, this_params, preferred_params):
    """Compare parameter weights to decide which duplicate component wins."""
    this_weight = 0
    other_weight = 0

    preferred_params["CLOWDER_ENABLED"] = preferred_params.get(
        "CLOWDER_ENABLED", "true"
    )

    for param_name, param_value in preferred_params.items():
        if str(this_params.get(param_name)).lower() == str(param_value).lower():
            this_weight += 1
        if str(other_params.get(param_name)).lower() == str(param_value).lower():
            other_weight += 1

    for param_name in ("REPLICAS", "MIN_REPLICAS"):
        if int(this_params.get(param_name, 0)) >= 1:
            this_weight += 1
        if int(other_params.get(param_name, 0)) >= 1:
            other_weight += 1

    return this_weight > other_weight


def _find_matching_component(apps, app_name, component_name):
    for component in apps.get(app_name, {}).get("components", []):
        if component["name"] == component_name:
            return component
    return None


def _add_component_if_priority_higher(
    apps, app_name, component_name, component, defined_multiple, preferred_params
):
    existing = _find_matching_component(apps, app_name, component_name)
    if not existing:
        apps[app_name]["name"] = app_name
        apps[app_name]["components"].append(component)
    else:
        defined_multiple.add((app_name, component_name))
        if _check_replace_other(
            existing["parameters"], component["parameters"], preferred_params
        ):
            apps[app_name]["components"].remove(existing)
            apps[app_name]["components"].append(component)


def _add_component(
    apps, env, app_name, saas_file, resource_template, target,
    defined_multiple, preferred_params,
):
    component_name = resource_template["name"]

    if app_name not in apps:
        apps[app_name] = {"name": app_name, "components": []}

    url = resource_template["url"]
    if "github" not in url and "gitlab" not in url:
        raise ValueError(
            f"unknown host for resourceTemplate url '{url}' "
            f"found in saas file '{saas_file['path']}'"
        )
    host = "github" if "github" in url else "gitlab"

    try:
        repo_path = urlparse(url).path.strip("/")
        last_slash_pos = repo_path.rindex("/")
        org = repo_path[:last_slash_pos]
        repo = repo_path[last_slash_pos + 1:]
    except (ValueError, IndexError) as err:
        raise ValueError(f"invalid repo url '{url}': {err}")

    p = copy.deepcopy(_to_dict(env["parameters"]))
    p.update(_to_dict(saas_file["parameters"]))
    p.update(_to_dict(resource_template["parameters"]))
    p.update(_to_dict(target["parameters"]))
    _process_env_parameters(p)

    component = {
        "name": component_name,
        "path": resource_template["path"],
        "host": host,
        "repo": f"{org}/{repo}",
        "ref": target["ref"],
        "hash_length": resource_template.get("hash_length"),
        "parameters": p,
    }

    _add_component_if_priority_higher(
        apps, app_name, component_name, component,
        defined_multiple, preferred_params,
    )


def get_apps_for_env(
    target_env: str,
    preferred_params: dict | None = None,
    client: QontractClient | None = None,
) -> dict:
    """Fetch app/component deployment configs for a target environment.

    Args:
        target_env: Environment name (e.g. "rosa-ephemeral")
        preferred_params: Parameter preferences for duplicate resolution
        client: Optional pre-configured QontractClient

    Returns:
        Dict mapping app_name -> {"name": str, "components": [...]}.
        Each component has: name, path, host, repo, ref, hash_length, parameters.
    """
    if not target_env:
        return {}

    if preferred_params is None:
        preferred_params = {}

    if client is None:
        client = QontractClient()

    log.info("fetching app deployment configs for env '%s'", target_env)

    all_apps = client.get_apps()
    env = client.get_env(target_env)

    apps = {}
    ignored_apps = set()
    defined_multiple = set()

    for app in all_apps:
        if app["parentApp"] and app["parentApp"].get("name") not in CONSOLEDOT_PARENT_APPS:
            ignored_apps.add(app["name"])
            continue
        for saas_file in app.get("saasFiles") or []:
            for resource_template in saas_file.get("resourceTemplates") or []:
                for target in resource_template.get("targets") or []:
                    ns = target.get("namespace") or {}
                    ns_path = ns.get("path")
                    if ns_path not in env.get("namespaces", {}):
                        continue
                    _add_component(
                        apps, env, app["name"], saas_file,
                        resource_template, target,
                        defined_multiple, preferred_params,
                    )

    if ignored_apps:
        log.debug(
            "ignored apps not under %s: %s",
            CONSOLEDOT_PARENT_APPS,
            ", ".join(ignored_apps),
        )

    return apps

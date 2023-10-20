import copy
import json
import logging
import re
from urllib.parse import urlparse

from gql import Client as GQLClient
from gql import gql
from gql.transport.requests import RequestsHTTPTransport
from requests.auth import HTTPBasicAuth

import bonfire.config as conf
from bonfire.utils import check_url_connection

log = logging.getLogger(__name__)


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


class Client:
    def __init__(self):
        log.debug("using url: %s", conf.QONTRACT_BASE_URL)

        transport_kwargs = {"url": conf.QONTRACT_BASE_URL}

        if conf.QONTRACT_TOKEN:
            log.debug("using token authentication")
            transport_kwargs["headers"] = {"Authorization": conf.QONTRACT_TOKEN}
        elif conf.QONTRACT_USERNAME and conf.QONTRACT_PASSWORD:
            log.debug("using basic authentication")
            transport_kwargs["auth"] = HTTPBasicAuth(conf.QONTRACT_USERNAME, conf.QONTRACT_PASSWORD)

        check_url_connection(transport_kwargs["url"])

        transport = RequestsHTTPTransport(**transport_kwargs)
        self.client = GQLClient(transport=transport, fetch_schema_from_transport=True)

        # info level is way too noisy for the gql client
        logging.getLogger("gql").setLevel(logging.ERROR)

    def get_env(self, env):
        """Get insights env configuration."""
        for env_data in self.client.execute(ENVS_QUERY)["envs"]:
            if env_data["name"] == env:
                env_data["namespaces"] = {
                    ns["path"]: ns["name"] for ns in env_data.get("namespaces", [])
                }
                break
        else:
            raise ValueError(f"cannot find env '{env}'")

        return env_data

    def get_apps(self):
        return self.client.execute(APPS_QUERY)["apps"]


_client = None


def get_client():
    global _client
    if not _client:
        _client = Client()

    return _client


def _to_dict(nullable_json_str):
    return json.loads(nullable_json_str or "{}")


def _find_matching_component(apps, app_name, component_name):
    for component in apps.get(app_name, {}).get("components", []):
        if component["name"] == component_name:
            return component


def _check_replace_other(other_params, this_params, preferred_params):
    """
    Compare parameters of "this" component with parameters of the "other" component.
    Assign points to the component if it is using a preferred parameter value. The component
    with the higher number of points will be selected.
    """
    this_weight = 0
    other_weight = 0

    # prefer deployment targets that have CLOWDER_ENABLED=true
    # TODO: a relic of the past and at this point probably no longer needed, remove in a follow-up
    preferred_params["CLOWDER_ENABLED"] = preferred_params.get("CLOWDER_ENABLED", "true")

    # check if target is configured with preferred parameters
    for param_name, param_value in preferred_params.items():
        if str(this_params.get(param_name)).lower() == str(param_value).lower():
            log.debug("    `-- 'this' weight +1 for %s=%s", param_name, param_value)
            this_weight += 1
        if str(other_params.get(param_name)).lower() == str(param_value).lower():
            log.debug("    `-- 'other' weight +1 for %s=%s", param_name, param_value)
            other_weight += 1

    # prefer deployment targets that have REPLICAS >= 1
    for param_name in ("REPLICAS", "MIN_REPLICAS"):
        this_replicas = int(this_params.get(param_name, 0))
        other_replicas = int(other_params.get(param_name, 0))
        if this_replicas >= 1:
            log.debug("    `-- 'this' weight +1 for %s>=1", param_name)
            this_weight += 1
        if other_replicas >= 1:
            log.debug("    `-- 'other' weight +1 for %s>=1", param_name)
            other_weight += 1

    log.debug("    `-- final: 'this' weight: %d, 'other' weight: %d", this_weight, other_weight)

    if this_weight > other_weight:
        return True

    return False


def _add_component_if_priority_higher(
    apps,
    app_name,
    component_name,
    component,
    defined_multiple,
    preferred_params,
):
    existing_match = _find_matching_component(apps, app_name, component_name)
    if not existing_match:
        apps[app_name]["name"] = app_name
        apps[app_name]["components"].append(component)
    else:
        # this app/component is defined multiple times in the environment
        # look at the parameters set on it to decide which definition to prioritize
        defined_multiple.add((app_name, component_name))
        other_params = existing_match["parameters"]
        this_params = component["parameters"]
        log.debug("  `-- this is a duplicate target, checking if this replaces existing other")

        replace = _check_replace_other(other_params, this_params, preferred_params)

        if replace:
            log.debug("  `-- this is weighted higher, replaces other")
            apps[app_name]["components"].remove(existing_match)
            apps[app_name]["components"].append(component)
        else:
            log.debug("  `-- this is weighted equal/lower, not replacing")


def _process_env_parameters(parameters):
    """Process variable reference in place, e.g. KAFKA_URL='${KAFKA_HOST}:9092'"""
    for key, val in parameters.items():
        if isinstance(val, str):
            found = re.findall(r"\$\{([^$]+)\}", val)
            for var in found:
                if var in parameters:
                    parameters[key] = parameters[key].replace("${" + var + "}", parameters[var])
                    log.debug(
                        "parameter %s found and replaced with %s",
                        var,
                        parameters[var],
                    )


def _add_component(
    apps,
    env,
    app_name,
    saas_file,
    resource_template,
    target,
    defined_multiple,
    preferred_params,
):
    component_name = resource_template["name"]
    saas_file_path = saas_file["path"]

    if app_name not in apps:
        apps[app_name] = {"name": app_name, "components": []}

    url = resource_template["url"]
    if "github" not in url and "gitlab" not in url:
        raise ValueError(
            f"unknown host for resourceTemplate url '{url}' found in saas file '{saas_file_path}'"
        )
    host = "github" if "github" in url else "gitlab"

    try:
        parsed_url = urlparse(url)
        org, repo = parsed_url.path.rstrip("/").split("/")[-2:]
    except (ValueError, IndexError) as err:
        raise ValueError(f"invalid repo url '{url}': {err}")

    # merge the various layers of parameters
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
        "parameters": p,
    }

    _add_component_if_priority_higher(
        apps,
        app_name,
        component_name,
        component,
        defined_multiple,
        preferred_params,
    )


def get_apps_for_env(env_name, preferred_params):
    if not env_name:
        return {}

    log.info("fetching app deployment configs for env '%s'", env_name)

    client = get_client()
    all_apps = client.get_apps()
    env = client.get_env(env_name)

    # work-around to only show apps with an ephemeral deploy target
    if env_name == conf.EPHEMERAL_ENV_NAME:
        env["namespaces"] = [conf.BASE_NAMESPACE_PATH]

    apps = {}
    ignored_apps = set()
    defined_multiple = set()

    for app in all_apps:
        if app["parentApp"] and app["parentApp"].get("name") not in CONSOLEDOT_PARENT_APPS:
            ignored_apps.add(app["name"])
            continue
        saas_files = app.get("saasFiles", [])
        for saas_file in saas_files:
            for rt_idx, resource_template in enumerate(saas_file.get("resourceTemplates", [])):
                for target_idx, target in enumerate(resource_template.get("targets", [])):
                    ns = target.get("namespace") or {}
                    ns_name = ns.get("name")
                    ns_path = ns.get("path")
                    if ns_path not in env.get("namespaces", []):
                        # this deploy target ns is not in the environment
                        continue
                    # this target ns belongs to the environment
                    log.debug(
                        "app '%s' component '%s' found in saas file '%s'",
                        app["name"],
                        resource_template["name"],
                        saas_file["path"],
                    )
                    log.debug(
                        "  position: .resourceTemplates[%d].targets[%d] (env '%s', ns '%s')",
                        rt_idx,
                        target_idx,
                        env_name,
                        ns_name,
                    )
                    _add_component(
                        apps,
                        env,
                        app["name"],
                        saas_file,
                        resource_template,
                        target,
                        defined_multiple,
                        preferred_params,
                    )

    if ignored_apps:
        log.debug(
            "ignored apps in env '%s' that do not have parentApp of %s: %s",
            CONSOLEDOT_PARENT_APPS,
            env_name,
            ", ".join(ignored_apps),
        )

    if defined_multiple:
        log.debug(
            "the following components in env '%s' are defined multiple times: %s",
            env_name,
            ", ".join([f"{app}/{component}" for app, component in defined_multiple]),
        )

    return apps


def _find_ref_target_and_update_component(
    final_apps,
    ref_env_apps,
    fallback_ref_env_apps,
    ref_env,
    fallback_ref_env,
    app_name,
    component_idx,
    component_name,
):
    log_prefix = f"app: '{app_name}' component: '{component_name}' --"

    ref_component = _find_matching_component(ref_env_apps, app_name, component_name)

    if not ref_component and fallback_ref_env:
        log.debug(
            "%s no deploy cfg found in ref env '%s', trying fallback ref '%s'",
            log_prefix,
            ref_env,
            fallback_ref_env,
        )
        ref_component = _find_matching_component(fallback_ref_env_apps, app_name, component_name)

    if not ref_component:
        log.debug(
            "%s no deploy cfg found in ref env '%s' nor fallback '%s', using git ref 'master'",
            log_prefix,
            ref_env,
            fallback_ref_env or "(none)",
        )
        final_apps[app_name]["components"][component_idx]["ref"] = "master"

    else:
        # use git ref from reference deployment config
        final_component = final_apps[app_name]["components"][component_idx]
        final_component["ref"] = ref_component["ref"]

        # fetch any param starting with 'IMAGE_TAG' from the reference deployment config
        # and update the component's parameters with the new parameter values.
        image_tags = {}
        parameters = ref_component.get("parameters", {})
        for param, val in parameters.items():
            if param.startswith("IMAGE_TAG"):
                image_tags[param] = val
        if image_tags:
            if "parameters" not in final_component:
                final_component["parameters"] = {}
            final_component["parameters"].update(image_tags)

        log.debug(
            "%s using git ref/image tag from env '%s': %s%s",
            log_prefix,
            ref_env,
            final_component["ref"],
            f", {image_tags}" if image_tags else "",
        )


def sub_refs(apps, ref_env, fallback_ref_env=None, preferred_params=None):
    if not preferred_params:
        preferred_params = {}

    if fallback_ref_env == ref_env:
        # it would be a waste of time to try to fall back to the same env
        log.debug("ref env and fallback ref env are the same, setting fallback to 'None'")
        fallback_ref_env = None

    final_apps = copy.deepcopy(apps)
    log.info(
        "setting git refs/image tags to match deploy config found in env: %s, fallback env: %s",
        ref_env,
        fallback_ref_env or "(none)",
    )
    ref_env_apps = get_apps_for_env(ref_env, preferred_params)
    fallback_ref_env_apps = get_apps_for_env(fallback_ref_env, preferred_params)

    for app_name, app in apps.items():
        for component_idx, component in enumerate(app["components"]):
            _find_ref_target_and_update_component(
                final_apps,
                ref_env_apps,
                fallback_ref_env_apps,
                ref_env,
                fallback_ref_env,
                app_name,
                component_idx,
                component["name"],
            )

    return final_apps

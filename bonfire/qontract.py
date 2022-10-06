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

NAMESPACE_QUERY = gql(
    """
    {
      namespaces: namespaces_v1 {
        name
        openshiftResources {
          ... on NamespaceOpenshiftResourceVaultSecret_v1 {
            name
            path
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

        transport = RequestsHTTPTransport(**transport_kwargs)
        self.client = GQLClient(transport=transport, fetch_schema_from_transport=True)

        # info level is way too noisy for the gql client
        logging.getLogger("gql").setLevel(logging.ERROR)

    def get_env(self, env):
        """Get insights env configuration."""
        for env_data in self.client.execute(ENVS_QUERY)["envs"]:
            if env_data["name"] == env:
                env_data["namespaces"] = set(n["name"] for n in env_data["namespaces"])
                break
        else:
            raise ValueError(f"cannot find env '{env}'")

        return env_data

    def get_apps(self):
        return self.client.execute(APPS_QUERY)["apps"]

    def get_namespace(self, name):
        for ns in self.client.execute(NAMESPACE_QUERY)["namespaces"]:
            if ns["name"] == name:
                return ns


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


def _check_replace_other(other_params, this_params):
    this_clowder_enabled = bool(this_params.get("CLOWDER_ENABLED"))
    other_clowder_enabled = bool(other_params.get("CLOWDER_ENABLED"))
    if this_clowder_enabled and not other_clowder_enabled:
        return True

    this_replicas = int(this_params.get("REPLICAS", 1))
    other_replicas = int(other_params.get("REPLICAS", 1))
    if other_replicas < 1 and this_replicas > 1:
        return True

    this_replicas = int(this_params.get("MIN_REPLICAS", 1))
    other_replicas = int(other_params.get("MIN_REPLICAS", 1))
    if other_replicas < 1 and this_replicas > 1:
        return True

    return False


def _add_component_if_priority_higher(
    apps, app_name, component_name, env_name, saas_file, component, defined_multiple
):
    add_component = True
    existing_match = _find_matching_component(apps, app_name, component_name)

    if existing_match:
        # this app/component is defined multiple times in the environment
        # look at the parameters set on it to decide which definition to prioritize
        defined_multiple.add((app_name, component_name))
        other_params = existing_match["parameters"]
        this_params = component["parameters"]
        add_component = _check_replace_other(other_params, this_params)
        if add_component:
            log.debug(
                "app: '%s' component: '%s' defined in saas file '%s' takes priority",
                app_name,
                component_name,
                saas_file["path"],
            )
        else:
            log.debug(
                "app: '%s' component: '%s' defined in saas file '%s' has lower priority, skipped",
                app_name,
                component_name,
                saas_file["path"],
            )

    if add_component:
        apps[app_name]["name"] = app_name
        apps[app_name]["components"].append(component)
        log.debug(
            "app: '%s' component: '%s' added for env '%s' using saas file: %s",
            app_name,
            component_name,
            env_name,
            saas_file["name"],
        )


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


def _add_component(apps, env, app_name, saas_file, resource_template, target, defined_multiple):
    component_name = resource_template["name"]
    env_name = env["name"]
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
        apps, app_name, component_name, env_name, saas_file, component, defined_multiple
    )


def get_apps_for_env(env_name):
    client = get_client()
    all_apps = client.get_apps()
    env = client.get_env(env_name)

    # work-around to only show apps with an ephemeral deploy target
    if env_name == conf.EPHEMERAL_ENV_NAME:
        env["namespaces"] = [conf.BASE_NAMESPACE_NAME]

    apps = {}
    ignored_apps = set()
    defined_multiple = set()

    for app in all_apps:
        if app["parentApp"] and app["parentApp"].get("name") not in CONSOLEDOT_PARENT_APPS:
            ignored_apps.add(app["name"])
            continue
        saas_files = app.get("saasFiles", [])
        for saas_file in saas_files:
            for resource_template in saas_file.get("resourceTemplates", []):
                for target in resource_template.get("targets", []):
                    if target["namespace"]["name"] in env["namespaces"]:
                        # this target belongs to the environment
                        _add_component(
                            apps,
                            env,
                            app["name"],
                            saas_file,
                            resource_template,
                            target,
                            defined_multiple,
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


def sub_refs(apps, ref_env_name):
    ref_env_apps = get_apps_for_env(ref_env_name)

    final_apps = copy.deepcopy(apps)
    for app_name, app in apps.items():
        for idx, component in enumerate(app["components"]):
            component_name = component["name"]
            ref_component = _find_matching_component(ref_env_apps, app_name, component_name)

            if ref_component:
                final_component = final_apps[app_name]["components"][idx]
                final_component["ref"] = ref_component["ref"]
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
                    "app: '%s' component: '%s' -- using ref from env '%s': %s%s",
                    app_name,
                    component_name,
                    ref_env_name,
                    final_component["ref"],
                    f", {image_tags}" if image_tags else "",
                )
            else:
                log.debug(
                    "app: '%s' component: '%s' -- no deploy cfg for env '%s', using ref 'master'",
                    app_name,
                    component_name,
                    ref_env_name,
                )
                final_apps[app_name]["components"][idx]["ref"] = "master"

    return final_apps


def get_namespaces_for_env(environment_name):
    client = get_client()

    namespaces = client.get_env(environment_name)["namespaces"]
    results = list(namespaces)
    log.debug("namespaces listed in qontract for environment '%s': %s", environment_name, results)
    return results


def get_secret_names_in_namespace(namespace_name):
    client = get_client()

    secret_names = []
    namespace = client.get_namespace(namespace_name)
    for resource in namespace["openshiftResources"]:
        if not resource:
            # query returns {} if resource is not 'NamespaceOpenshiftResourceVaultSecret_v1'
            continue
        name = resource["name"] or resource["path"].split("/")[-1]
        secret_names.append(name)
    return secret_names

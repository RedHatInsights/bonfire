import json
import copy
import logging

from gql import gql
from gql import Client as GQLClient
from gql.transport.requests import RequestsHTTPTransport
from requests.auth import HTTPBasicAuth

import bonfire.config as conf

log = logging.getLogger(__name__)


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

    return False


def _add_component(apps, env, app_name, saas_file, resource_template, target, defined_multiple):
    component_name = resource_template["name"]
    env_name = env["name"]
    sp = saas_file["path"]

    if app_name not in apps:
        apps[app_name] = {"name": app_name, "components": []}

    url = resource_template["url"]
    if "github" not in url and "gitlab" not in url:
        raise ValueError(f"unknown host for resourceTemplate url '{url}' found in saas file '{sp}'")
    host = "github" if "github" in url else "gitlab"

    org, repo = url.split("/")[-2:]

    # merge the various layers of parameters
    p = copy.deepcopy(_to_dict(env["parameters"]))
    p.update(_to_dict(saas_file["parameters"]))
    p.update(_to_dict(resource_template["parameters"]))
    p.update(_to_dict(target["parameters"]))

    component = {
        "name": component_name,
        "path": resource_template["path"],
        "host": host,
        "repo": f"{org}/{repo}",
        "ref": target["ref"],
        "parameters": p,
    }

    add_component = True
    existing_match = _find_matching_component(apps, app_name, component_name)
    if existing_match:
        # this app/component is defined multiple times in the environment
        # look at the parameters set on it to decide which definition to prioritize
        defined_multiple.add((app_name, component_name))
        other_params = existing_match["parameters"]
        this_params = p
        add_component = _check_replace_other(other_params, this_params)
        if add_component:
            log.debug(
                "app: '%s' component: '%s' defined in saas file '%s' takes priority",
                app_name,
                component_name,
                sp,
            )
        else:
            log.debug(
                "app: '%s' component: '%s' defined in saas file '%s' has lower priority, skipped",
                app_name,
                component_name,
                sp,
            )

    if add_component:
        apps[app_name]["components"].append(component)
        log.debug(
            "app: '%s' component: '%s' added for env '%s' using saas file: %s",
            app_name,
            component_name,
            env_name,
            saas_file["name"],
        )


def get_apps_for_env(env_name):
    client = get_client()
    all_apps = client.get_apps()
    env = client.get_env(env_name)

    apps = {}
    ignored_apps = set()
    defined_multiple = set()

    for app in all_apps:
        if app["parentApp"] and app["parentApp"].get("name") != "insights":
            ignored_apps.add(app["name"])
            continue
        for saas_file in app.get("saasFiles", []):
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
            "ignored apps in env '%s' that do not have parentApp 'insights': %s",
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
                ref_image_tag = ref_component["parameters"].get("IMAGE_TAG")
                if ref_image_tag:
                    final_component["parameters"]["IMAGE_TAG"] = ref_image_tag
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
    return list(namespaces)


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

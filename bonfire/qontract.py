import json
import copy
import logging
import yaml
import re

from gql import gql
from gql import Client as GQLClient
from gql import RequestsHTTPTransport
import requests
from requests.auth import HTTPBasicAuth

import bonfire.config as conf
from bonfire.openshift import process_template

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

SAAS_QUERY = gql(
    """
    {
      saas_files: saas_files_v1 {
        name
        app {
          name
          parentApp {
            name
          }
        }
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
            log.info("using token authentication")
            transport_kwargs["headers"] = {"Authorization": conf.QONTRACT_TOKEN}
        elif conf.QONTRACT_USERNAME and conf.QONTRACT_PASSWORD:
            log.info("using basic authentication")
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

    def get_saas_files(self, app):
        """Get app's saas file data."""
        saas_files = []

        for saas_file in self.client.execute(SAAS_QUERY)["saas_files"]:
            if saas_file["app"]["name"] != app:
                continue

            if saas_file["app"].get("parentApp", {}).get("name") != "insights":
                log.warning("ignoring app named '%s' that does not have parentApp 'insights'")
                continue

            # load the parameters as a dict to save us some trouble later on...
            saas_file["parameters"] = json.loads(saas_file["parameters"] or "{}")
            saas_files.append(saas_file)

        if not saas_files:
            raise ValueError(f"no saas files found for app '{app}'")
        return saas_files

    def get_namespace(self, name):
        for ns in self.client.execute(NAMESPACE_QUERY)["namespaces"]:
            if ns["name"] == name:
                return ns


def _format_namespace(namespace):
    return f"[cluster: {namespace['cluster']['name']}, ns: {namespace['name']}]"


def _format_app_resource(app, resource_name):
    return f"app '{app}' resource '{resource_name}'"


def _parse_targets(src_targets, ref_targets, app, resource_name, src_env, ref_env):
    if not src_targets:
        log.warning(
            "%s: no targets found using src env '%s'",
            _format_app_resource(app, resource_name),
            src_env,
        )
        src_targets = [None]

    if not ref_targets:
        log.warning(
            "%s: no targets found using ref env '%s'",
            _format_app_resource(app, resource_name),
            ref_env,
        )
        ref_targets = src_targets

    if len(ref_targets) > 1:
        # find a target with >0 replicas if possible
        namespaces = [_format_namespace(t["namespace"]) for t in ref_targets]
        log.warning(
            "%s: multiple targets defined for ref env '%s' (target namespaces: %s)",
            _format_app_resource(app, resource_name),
            ref_env,
            ", ".join(namespaces),
        )
        for t in ref_targets:
            if t["parameters"].get("REPLICAS") != 0:
                log.info(
                    "%s: selected ref target with >0 replicas (target namespace is '%s')",
                    _format_app_resource(app, resource_name),
                    _format_namespace(t["namespace"]),
                )
                ref_targets = [t]
                break

    src_target = src_targets[0]  # TODO: handle cases where more than 1 src target was found?
    ref_target = ref_targets[0]

    return src_target, ref_target


def _download_raw_template(resource, ref):
    org, repo = resource["url"].split("/")[-2:]
    path = resource["path"]
    raw_template = conf.RAW_GITHUB_URL if "github" in resource["url"] else conf.RAW_GITLAB_URL
    template_url = raw_template.format(org=org, repo=repo, ref=ref, path=path)

    log.info("downloading template: '%s'", template_url)
    response = requests.get(template_url, verify=False)
    response.raise_for_status()
    template = response.text

    # just in case response.raise_for_status() doesn't take care of it ...
    if "Page Not Found" in template or "404: Not Found" in template:
        raise Exception(f"invalid template URL: {template_url}")

    template_yaml = yaml.safe_load(template)

    return template_yaml


def _get_resources_for_env(saas_file_data, env_data):
    """Return resourceTemplates with targets filtered only to those mapped to 'env_name'."""
    resources = {}

    for resource in saas_file_data["resourceTemplates"]:
        name = resource["name"]
        targets = []
        for t in resource["targets"]:
            if t["namespace"]["name"] in env_data["namespaces"]:
                targets.append(t)

        resources[name] = copy.deepcopy(resource)
        resources[name]["targets"] = targets
        # load the parameters as a dict to save us some trouble later on...
        resources[name]["parameters"] = json.loads(resource["parameters"] or "{}")
        for target in resources[name]["targets"]:
            target["parameters"] = json.loads(target["parameters"] or "{}")

    return resources


def _get_processed_config_items(
    client, app, saas_file, src_env, ref_env, template_ref_overrides, namespace
):
    src_env_data = client.get_env(src_env)
    ref_env_data = client.get_env(ref_env)

    src_resources = _get_resources_for_env(saas_file, src_env_data)
    ref_resources = _get_resources_for_env(saas_file, ref_env_data)

    items = []

    for resource_name, resource in src_resources.items():
        src_targets = resource.get("targets", [])
        ref_targets = ref_resources.get(resource_name, {}).get("targets", [])
        src_target, ref_target = _parse_targets(
            src_targets, ref_targets, app, resource_name, src_env, ref_env
        )
        if not src_target:
            # no target configuration exists for this resource in the desired source env
            continue

        if resource_name in template_ref_overrides:
            # if template ref has explicitly been overridden, use the override
            log.info("overriding template ref for resource '%s'", resource_name)
            template_ref = template_ref_overrides[resource_name]
        else:
            # otherwise use template ref configured in the "reference deploy target"
            template_ref = ref_target["ref"]

        raw_template = _download_raw_template(resource, template_ref)

        # merge the various layers of parameters to pass into the template
        p = copy.deepcopy(json.loads(src_env_data["parameters"]))
        p.update(saas_file["parameters"])
        p.update(resource["parameters"])
        p.update(src_target["parameters"])
        # set IMAGE_TAG to be the reference env's IMAGE_TAG
        p["IMAGE_TAG"] = ref_target["parameters"].get("IMAGE_TAG")
        if not p.get("IMAGE_TAG"):
            p.update({"IMAGE_TAG": "latest" if template_ref == "master" else template_ref[:7]})
            log.warning(
                "IMAGE_TAG not defined in reference target for resource '%s', using tag '%s'",
                resource_name,
                p["IMAGE_TAG"],
            )

        # set the env name based on the namespace you intend to deploy to
        p["ENV_NAME"] = conf.ENV_NAME_FORMAT.format(namespace=namespace)

        processed_template = process_template(raw_template, p)
        items.extend(processed_template.get("items", []))

    return items


_client = None


def get_client():
    global _client
    if not _client:
        _client = Client()

    return _client


def get_app_config(app, src_env, ref_env, template_ref_overrides, image_tag_overrides, namespace):
    """
    Load application's config:
    * Look up deploy config for any namespaces that are mapped to 'src_env'
    * Look up deploy config for any namespaces that are mapped to 'ref_env'

    A dict representing a k8s List resource for this app is returned. If any service has a target
    set up that maps to 'src_env' it will be included in the list, but using the IMAGE_TAG and
    template 'ref' defined in the deploy config for 'ref_env'
    """
    # we will output one large that contains all resources
    client = get_client()

    root_list = {
        "kind": "List",
        "apiVersion": "v1",
        "metadata": {},
        "items": [],
    }

    for saas_file in client.get_saas_files(app):
        root_list["items"].extend(
            _get_processed_config_items(
                client, app, saas_file, src_env, ref_env, template_ref_overrides, namespace
            )
        )

    # override any explicitly provided image tags, easier to just re.sub on a whole string
    if image_tag_overrides:
        content = json.dumps(root_list)
        for image, image_tag in image_tag_overrides.items():
            content, subs = re.subn(rf"{image}:\w+", rf"{image}:{image_tag}", content)
            if subs:
                log.info("replaced %d occurence(s) of image tag for image '%s'", subs, image)
        root_list = json.loads(content)

    return root_list


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

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


def _format_app_resource(app, resource_name, saas_file):
    return f"app: '{app}' resource: '{resource_name}' saas file: '{saas_file['name']}'"


def _parse_targets(src_targets, ref_targets, app, resource_name, src_env, ref_env, saas_file):
    if not src_targets:
        log.debug(
            "%s -- no targets found using src env '%s'",
            _format_app_resource(app, resource_name, saas_file),
            src_env,
        )

    if not ref_targets:
        log.debug(
            "%s -- no targets found using ref env '%s'",
            _format_app_resource(app, resource_name, saas_file),
            ref_env,
        )

    if src_targets and not ref_targets:
        log.warn(
            "%s -- src target found but not ref target",
            _format_app_resource(app, resource_name, saas_file),
        )

    src_targets = src_targets or [{}]
    ref_targets = ref_targets or [{}]

    if len(ref_targets) > 1:
        # find a target with >0 replicas if possible
        namespaces = [_format_namespace(t["namespace"]) for t in ref_targets]
        log.debug(
            "%s -- multiple targets defined for ref env '%s' (target namespaces: %s)",
            _format_app_resource(app, resource_name, saas_file),
            ref_env,
            ", ".join(namespaces),
        )
        for t in ref_targets:
            if t["parameters"].get("REPLICAS") != 0:
                log.debug(
                    "%s -- selected ref target with >0 replicas (target namespace is '%s')",
                    _format_app_resource(app, resource_name, saas_file),
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


def _get_processed_items(
    client,
    app,
    saas_file,
    src_env,
    ref_env,
    src_env_data,
    ref_env_data,
    template_ref_overrides,
    namespace,
):
    src_resources = _get_resources_for_env(saas_file, src_env_data)
    log.debug(
        "found resources for %s in saas file '%s': %s",
        src_env,
        saas_file["name"],
        json.dumps(src_resources, indent=2),
    )
    ref_resources = _get_resources_for_env(saas_file, ref_env_data)
    log.debug(
        "found resources for %s in saas file '%s': %s",
        ref_env,
        saas_file["name"],
        json.dumps(ref_resources, indent=2),
    )

    items = []

    for resource_name, resource in src_resources.items():
        src_targets = resource.get("targets", [])
        ref_targets = ref_resources.get(resource_name, {}).get("targets", [])
        log.debug("%s -- parsing targets", _format_app_resource(app, resource_name, saas_file))
        src_target, ref_target = _parse_targets(
            src_targets, ref_targets, app, resource_name, src_env, ref_env, saas_file
        )

        if not src_target:
            # this resource was not marked for deployment
            log.warn(
                "%s -- not marked for deploy in src env, skipping resource!",
                _format_app_resource(app, resource_name, saas_file),
            )
            continue

        if resource_name in template_ref_overrides:
            # if template ref has explicitly been overridden, use the override
            log.debug(
                "%s -- overriding template ref",
                _format_app_resource(app, resource_name, saas_file),
            )
            template_ref = template_ref_overrides[resource_name]
        elif not ref_target:
            # if template ref not overridden, and there's no ref target, we don't know what git ref
            # to use for template download
            log.warn(
                "%s -- no ref target found nor template ref override given, defaulting to 'master'",
                _format_app_resource(app, resource_name, saas_file),
            )
            template_ref = "master"
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
        p["IMAGE_TAG"] = ref_target.get("parameters", {}).get("IMAGE_TAG")
        if not p.get("IMAGE_TAG"):
            p.update({"IMAGE_TAG": "latest" if template_ref == "master" else template_ref[:7]})
            log.debug(
                "%s -- no IMAGE_TAG found on ref target, assuming tag '%s' based on template ref",
                _format_app_resource(app, resource_name, saas_file),
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


def _sub_image_tags(items, image_tag_overrides):
    if image_tag_overrides:
        content = json.dumps(items)
        for image, image_tag in image_tag_overrides.items():
            # easier to just re.sub on a whole string
            content, subs = re.subn(rf"{image}:\w+", rf"{image}:{image_tag}", content)
            if subs:
                log.info("replaced %d occurence(s) of image tag for image '%s'", subs, image)
        return json.loads(content)
    return items


def _add_dependencies_to_config(app_name, new_items, processed_apps, k8s_list, static_args):
    clowdapp_items = [item for item in new_items if item.get("kind").lower() == "clowdapp"]
    dependencies = {d for item in clowdapp_items for d in item["spec"].get("dependencies", [])}

    # also include optionalDependencies since we're interested in them for testing
    for item in clowdapp_items:
        for od in item["spec"].get("optionalDependencies", []):
            dependencies.add(od)

    if dependencies:
        log.debug("found dependencies for app '%s': %s", app_name, list(dependencies))

    dependencies = [d for d in dependencies if d not in processed_apps]
    if dependencies:
        # recursively get config for any dependencies, they will be stored in the
        # already-created 'k8s_list' dict
        log.info("app '%s' dependencies %s not previously processed", app_name, dependencies)
        get_apps_config(dependencies, *static_args, k8s_list, processed_apps)


def _process_app(
    client,
    app_name,
    src_env,
    ref_env,
    src_env_data,
    ref_env_data,
    template_ref_overrides,
    image_tag_overrides,
    get_dependencies,
    namespace,
    k8s_list,
    processed_apps,
):
    new_items = []
    saas_files = client.get_saas_files(app_name)
    log.debug("found %d saas files for app '%s'", len(saas_files), app_name)
    for saas_file in saas_files:
        found_items = _get_processed_items(
            client,
            app_name,
            saas_file,
            src_env,
            ref_env,
            src_env_data,
            ref_env_data,
            template_ref_overrides,
            namespace,
        )
        item_names = []
        for item in found_items:
            name = item.get("metadata", {}).get("name", "nameUnknown")
            kind = item.get("kind", "kindUnknown")
            item_names.append(f"{kind}/{name}".lower())
        log.info(
            "app: %s env: %s saas file: %s -- resource(s) marked for deploy: %s",
            app_name,
            src_env,
            saas_file["name"],
            ", ".join(item_names) if item_names else "none",
        )
        new_items.extend(found_items)

    # override any explicitly provided image tags
    new_items = _sub_image_tags(new_items, image_tag_overrides)

    k8s_list["items"].extend(new_items)
    processed_apps.add(app_name)

    if get_dependencies:
        # these args don't change when get_apps_config is called recursively
        static_args = (
            src_env,
            ref_env,
            template_ref_overrides,
            image_tag_overrides,
            get_dependencies,
            namespace,
            src_env_data,
            ref_env_data,
        )
        _add_dependencies_to_config(app_name, new_items, processed_apps, k8s_list, static_args)


def get_apps_config(
    app_names,
    src_env,
    ref_env,
    template_ref_overrides,
    image_tag_overrides,
    get_dependencies,
    namespace,
    src_env_data=None,
    ref_env_data=None,
    k8s_list=None,
    processed_apps=None,
):
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

    if not k8s_list:
        k8s_list = {
            "kind": "List",
            "apiVersion": "v1",
            "metadata": {},
            "items": [],
        }

    if not processed_apps:
        processed_apps = set()

    src_env_data = src_env_data or client.get_env(src_env)
    ref_env_data = ref_env_data or client.get_env(ref_env)

    for app_name in app_names:
        log.info("Getting configuration for app '%s'", app_name)
        _process_app(
            client,
            app_name,
            src_env,
            ref_env,
            src_env_data,
            ref_env_data,
            template_ref_overrides,
            image_tag_overrides,
            get_dependencies,
            namespace,
            k8s_list,
            processed_apps,
        )

    return k8s_list


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

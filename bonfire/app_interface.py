import json
import copy
import logging
import yaml

from gql import gql
from gql import Client as GQLClient
from gql import RequestsHTTPTransport
import requests
from requests.auth import HTTPBasicAuth
from subprocess import PIPE
from subprocess import Popen

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
        log.info("using url: %s", conf.APP_INTERFACE_BASE_URL)

        transport_kwargs = {"url": conf.APP_INTERFACE_BASE_URL}

        if conf.APP_INTERFACE_TOKEN:
            log.info("using token authentication")
            transport_kwargs["headers"] = {"Authorization": conf.APP_INTERFACE_TOKEN}
        elif conf.APP_INTERFACE_USERNAME and conf.APP_INTERFACE_PASSWORD:
            log.info("using basic authentication")
            transport_kwargs["auth"] = HTTPBasicAuth(
                conf.APP_INTERFACE_USERNAME, conf.APP_INTERFACE_PASSWORD
            )

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

    @staticmethod
    def get_filtered_resource_templates(saas_file_data, env_data):
        """Return resourceTemplates with targets filtered only to those mapped to 'env_name'."""
        resource_templates = {}

        for r in saas_file_data["resourceTemplates"]:
            name = r["name"]
            targets = []
            for t in r["targets"]:
                if t["namespace"]["name"] in env_data["namespaces"]:
                    targets.append(t)

            resource_templates[name] = copy.deepcopy(r)
            resource_templates[name]["targets"] = targets
            # load the parameters as a dict to save us some trouble later on...
            resource_templates[name]["parameters"] = json.loads(r["parameters"] or "{}")
            for t in resource_templates[name]["targets"]:
                t["parameters"] = json.loads(t["parameters"] or "{}")

        return resource_templates


def _format_namespace(namespace):
    return f"[cluster: {namespace['cluster']['name']}, ns: {namespace['name']}]"


def get_app_config(app, src_env, ref_env):
    """
    Load application's config:
    * Look up deploy config for any namespaces that are mapped to 'src_env'
    * Look up deploy config for any namespaces that are mapped to 'ref_env'

    A dict representing a k8s List resource for this app is returned. If any service has a target
    set up that maps to 'src_env' it will be included in the list, but using the IMAGE_TAG and
    template 'ref' defined in the deploy config for 'ref_env'
    """
    # TODO: break this function up

    client = Client()
    src_env_data = client.get_env(src_env)
    ref_env_data = client.get_env(ref_env)

    # we will output one large that contains all resources
    root_list = {
        "kind": "List",
        "apiVersion": "v1",
        "metadata": {},
        "items": [],
    }

    for saas_file in client.get_saas_files(app):
        src_resources = client.get_filtered_resource_templates(saas_file, src_env_data)
        ref_resources = client.get_filtered_resource_templates(saas_file, ref_env_data)

        for resource_name, r in src_resources.items():
            resource_name = r["name"]
            src_targets = r.get("targets", [])
            ref_targets = ref_resources.get(app, {}).get("targets", [])
            if not src_targets:
                log.warning(
                    "app '%s' resource '%s' no targets found using src env '%s'",
                    app,
                    resource_name,
                    src_env,
                )
                continue
            if not ref_targets:
                log.warning(
                    "app '%s' resource '%s' no targets found using ref env '%s'",
                    app,
                    resource_name,
                    ref_env,
                )
                ref_targets = src_targets

            if len(ref_targets) > 1:
                # find a target with >0 replicas if possible
                namespaces = [_format_namespace(t["namespace"]) for t in ref_targets]
                log.warning(
                    "app '%s' resource '%s' has multiple targets defined for ref env '%s' (target namespaces: %s)",
                    app,
                    resource_name,
                    ref_env,
                    ", ".join(namespaces),
                )
                for t in ref_targets:
                    if t["parameters"].get("REPLICAS") != 0:
                        log.info(
                            "app '%s' resource '%s' selected target with >0 replicas (target namespace is '%s')",
                            app,
                            resource_name,
                            _format_namespace(t["namespace"]),
                        )
                        ref_targets = [t]
                        break

            ref_target = ref_targets[0]

            ref_git_ref = ref_target["ref"]
            ref_image_tag = ref_target["parameters"].get("IMAGE_TAG")

            org, repo = r["url"].split("/")[-2:]
            path = r["path"]
            raw_template = conf.RAW_GITHUB_URL if "github" in r["url"] else conf.RAW_GITLAB_URL
            # override the target's parameters for 'ref' using the reference env
            t["ref"] = ref_git_ref
            template_url = raw_template.format(org=org, repo=repo, ref=t["ref"], path=path)

            for t in src_targets:
                p = copy.deepcopy(json.loads(src_env_data["parameters"]))
                p.update(saas_file["parameters"])
                p.update(r["parameters"])
                p.update(t["parameters"])
                # override the target's IMAGE_TAG using the reference env
                p["IMAGE_TAG"] = ref_image_tag
                if not p.get("IMAGE_TAG"):
                    p.update({"IMAGE_TAG": "latest" if t["ref"] == "master" else t["ref"][:7]})

                template = requests.get(template_url, verify=False).text
                y = yaml.safe_load(template)

                pnames = set(p["name"] for p in y["parameters"])
                param_str = " ".join(f"-p {k}={v}" for k, v in p.items() if k in pnames)

                proc = Popen(
                    f"oc process --local -o json -f - {param_str}",
                    shell=True,
                    stdin=PIPE,
                    stdout=PIPE,
                )
                stdout, stderr = proc.communicate(template.encode("utf-8"))
                output = json.loads(stdout.decode("utf-8"))
                if output.get("items"):
                    root_list["items"].extend(output["items"])

    return root_list


def get_namespaces_for_env(environment_name):
    client = Client()
    namespaces = client.get_env(environment_name)["namespaces"]
    return list(namespaces)


def get_secret_names_in_namespace(namespace_name):
    client = Client()
    secret_names = []
    namespace = client.get_namespace(namespace_name)
    for resource in namespace["openshiftResources"]:
        if not resource:
            # query returns {} if resource is not 'NamespaceOpenshiftResourceVaultSecret_v1'
            continue
        name = resource["name"] or resource["path"].split("/")[-1]
        secret_names.append(name)
    return secret_names

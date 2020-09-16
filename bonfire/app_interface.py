import json
import copy
import os
import logging
import yaml

from gql import gql
from gql import Client as GQLClient
from gql import RequestsHTTPTransport
import requests
from requests.auth import HTTPBasicAuth
from subprocess import PIPE
from subprocess import Popen


log = logging.getLogger(__name__)

APP_INTERFACE_BASE_URL = os.getenv("APP_INTERFACE_BASE_URL", "http://localhost:4000/graphql")
APP_INTERFACE_USERNAME = os.getenv("APP_INTERFACE_USERNAME")
APP_INTERFACE_PASSWORD = os.getenv("APP_INTERFACE_PASSWORD")
APP_INTERFACE_TOKEN = os.getenv("APP_INTERFACE_TOKEN")

RAW_GITHUB = "https://raw.githubusercontent.com/{org}/{repo}/{ref}{path}"
RAW_GITLAB = "https://gitlab.cee.redhat.com/{org}/{repo}/-/raw/{ref}{path}"

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
            }
            ref
            parameters
          }
        }
      }
    }
    """
)


class Client:
    def __init__(self):
        log.info("using url: %s", APP_INTERFACE_BASE_URL)

        transport_kwargs = {"url": APP_INTERFACE_BASE_URL}

        if APP_INTERFACE_TOKEN:
            log.info("using token authentication")
            transport_kwargs["headers"] = {"Authorization": APP_INTERFACE_TOKEN}
        elif APP_INTERFACE_USERNAME and APP_INTERFACE_PASSWORD:
            log.info("using basic authentication")
            transport_kwargs["auth"] = HTTPBasicAuth(APP_INTERFACE_USERNAME, APP_INTERFACE_PASSWORD)

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


def get_app_config(app, src_env, ref_env):
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

        for app_name, r in src_resources.items():
            src_targets = r.get("targets", [])
            ref_targets = ref_resources.get(app, {}).get("targets", [])
            if not src_targets:
                log.warning("app '%s' no targets found using src env '%s'", app_name, src_env)
                continue
            if not ref_targets:
                log.warning("app '%s' no targets found using ref env '%s'", app_name, ref_env)
                ref_targets = src_targets

            if len(ref_targets) > 1:
                # find a target with >0 replicas if possible
                log.warning("app '%s' has multiple targets defined for ref env '%s'", app, ref_env)
                for t in ref_targets:
                    if t["parameters"].get("REPLICAS") != 0:
                        ref_targets = [t]
                        break

            ref_target = ref_targets[0]

            ref_git_ref = ref_target["ref"]
            ref_image_tag = ref_target["parameters"].get("IMAGE_TAG")

            org, repo = r["url"].split("/")[-2:]
            path = r["path"]
            raw_template = RAW_GITHUB if "github" in r["url"] else RAW_GITLAB
            # override the target's parameters for 'ref' using the reference env
            t["ref"] = ref_git_ref
            template_url = raw_template.format(org=org, repo=repo, ref=t["ref"], path=path)

            for t in src_targets:
                p = copy.deepcopy(json.loads(src_env_data["parameters"]))
                p.update(saas_file["parameters"])
                p.update(r["parameters"])
                p.update(r["parameters"])
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


def get_ephemeral_namespaces():
    client = Client()
    namespaces = client.get_env("insights-ephemeral")["namespaces"]
    namespaces.remove("ephemeral-base")
    # TODO: figure out which of these are currently in use
    return namespaces

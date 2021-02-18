import logging
import os
import os.path
from pathlib import Path
import requests
import tempfile
import yaml
import subprocess
import shlex

import bonfire.config as conf
from bonfire.openshift import process_template
from bonfire.utils import split_equals

log = logging.getLogger(__name__)

GH_MASTER_REF = "https://api.github.com/repos/%s/git/refs/heads/master"
GH_CONTENT = "https://raw.githubusercontent.com/%s/%s/%s"
GL_PROJECTS = "https://gitlab.cee.redhat.com/api/v4/%s/%s/projects/?per_page=100"
GL_MASTER_REF = "https://gitlab.cee.redhat.com/api/v4/projects/%s/repository/branches/master"
GL_CONTENT = "https://gitlab.cee.redhat.com/%s/-/raw/%s/%s"
GL_CA_CERT = """
-----BEGIN CERTIFICATE-----
MIIENDCCAxygAwIBAgIJANunI0D662cnMA0GCSqGSIb3DQEBCwUAMIGlMQswCQYD
VQQGEwJVUzEXMBUGA1UECAwOTm9ydGggQ2Fyb2xpbmExEDAOBgNVBAcMB1JhbGVp
Z2gxFjAUBgNVBAoMDVJlZCBIYXQsIEluYy4xEzARBgNVBAsMClJlZCBIYXQgSVQx
GzAZBgNVBAMMElJlZCBIYXQgSVQgUm9vdCBDQTEhMB8GCSqGSIb3DQEJARYSaW5m
b3NlY0ByZWRoYXQuY29tMCAXDTE1MDcwNjE3MzgxMVoYDzIwNTUwNjI2MTczODEx
WjCBpTELMAkGA1UEBhMCVVMxFzAVBgNVBAgMDk5vcnRoIENhcm9saW5hMRAwDgYD
VQQHDAdSYWxlaWdoMRYwFAYDVQQKDA1SZWQgSGF0LCBJbmMuMRMwEQYDVQQLDApS
ZWQgSGF0IElUMRswGQYDVQQDDBJSZWQgSGF0IElUIFJvb3QgQ0ExITAfBgkqhkiG
9w0BCQEWEmluZm9zZWNAcmVkaGF0LmNvbTCCASIwDQYJKoZIhvcNAQEBBQADggEP
ADCCAQoCggEBALQt9OJQh6GC5LT1g80qNh0u50BQ4sZ/yZ8aETxt+5lnPVX6MHKz
bfwI6nO1aMG6j9bSw+6UUyPBHP796+FT/pTS+K0wsDV7c9XvHoxJBJJU38cdLkI2
c/i7lDqTfTcfLL2nyUBd2fQDk1B0fxrskhGIIZ3ifP1Ps4ltTkv8hRSob3VtNqSo
GxkKfvD2PKjTPxDPWYyruy9irLZioMffi3i/gCut0ZWtAyO3MVH5qWF/enKwgPES
X9po+TdCvRB/RUObBaM761EcrLSM1GqHNueSfqnho3AjLQ6dBnPWlo638Zm1VebK
BELyhkLWMSFkKwDmne0jQ02Y4g075vCKvCsCAwEAAaNjMGEwHQYDVR0OBBYEFH7R
4yC+UehIIPeuL8Zqw3PzbgcZMB8GA1UdIwQYMBaAFH7R4yC+UehIIPeuL8Zqw3Pz
bgcZMA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgGGMA0GCSqGSIb3DQEB
CwUAA4IBAQBDNvD2Vm9sA5A9AlOJR8+en5Xz9hXcxJB5phxcZQ8jFoG04Vshvd0e
LEnUrMcfFgIZ4njMKTQCM4ZFUPAieyLx4f52HuDopp3e5JyIMfW+KFcNIpKwCsak
oSoKtIUOsUJK7qBVZxcrIyeQV2qcYOeZhtS5wBqIwOAhFwlCET7Ze58QHmS48slj
S9K0JAcps2xdnGu0fkzhSQxY8GPQNFTlr6rYld5+ID/hHeS76gq0YG3q6RLWRkHf
4eTkRjivAlExrFzKcljC4axKQlnOvVAzz+Gm32U0xPBF4ByePVxCJUHw1TsyTmel
RxNEp7yHoXcwn+fXna+t5JWh1gxUZty3
-----END CERTIFICATE-----
"""


def process_gitlab(component):
    with tempfile.NamedTemporaryFile(delete=False) as fp:
        cert_fname = fp.name
        fp.write(GL_CA_CERT.encode("ascii"))

    group, project = component["repo"].split("/")
    response = requests.get(GL_PROJECTS % ("groups", group), verify=cert_fname)
    if response.status_code == 404:
        # Weird quirk in gitlab API. If it's a user instead of a group, need to
        # use a different path
        response = requests.get(GL_PROJECTS % ("users", group), verify=cert_fname)
    response.raise_for_status()
    projects = response.json()
    project_id = 0

    for p in projects:
        if p["path"] == project:
            project_id = p["id"]

    if not project_id:
        raise ValueError("project ID not found for %s" % component["repo"])

    response = requests.get(GL_MASTER_REF % project_id, verify=cert_fname)
    response.raise_for_status()
    commit = response.json()["commit"]["id"]

    url = GL_CONTENT % (component["repo"], commit, component["path"])
    response = requests.get(url, verify=cert_fname)
    if response.status_code != 200:
        msg = "Invalid response code %s fetching template for %s: %s"
        raise ValueError(msg % (response.status_code, component["name"], url))

    os.unlink(cert_fname)

    return commit, response.content


def process_github(component):
    response = requests.get(GH_MASTER_REF % component["repo"])
    response.raise_for_status()
    commit = response.json()["object"]["sha"]
    url = GH_CONTENT % (component["repo"], commit, component["path"])
    response = requests.get(url)
    if response.status_code != 200:
        msg = "Invalid response code %s fetching template for %s: %s"
        raise ValueError(msg % (response.status_code, component["name"], url))
    return commit, response.content


def process_local(component):
    cmd = "git -C %s rev-parse HEAD" % component["repo"]
    commit = subprocess.check_output(shlex.split(cmd)).decode("ascii")
    template_path = os.path.join(component["repo"], component["path"])
    with open(template_path) as fp:
        return commit, fp.read()


def _add_dependencies_to_config(app_name, new_items, processed_apps, config):
    clowdapp_items = [item for item in new_items if item.get("kind").lower() == "clowdapp"]
    dependencies = {d for item in clowdapp_items for d in item["spec"].get("dependencies", [])}

    # also include optionalDependencies since we're interested in them for testing
    for item in clowdapp_items:
        for od in item["spec"].get("optionalDependencies", []):
            dependencies.add(od)

    if dependencies:
        log.debug("found dependencies for app '%s': %s", app_name, list(dependencies))

    dep_items = []
    dependencies = [d for d in dependencies if d not in processed_apps]
    if dependencies:
        # recursively get config for any dependencies, they will be stored in the
        # already-created 'config' dict
        log.info("app '%s' dependencies %s not previously processed", app_name, dependencies)
        items = process_local_config(config, dependencies, True, processed_apps)["items"]
        dep_items.extend(items)

    return dep_items


def _remove_resource_config(items):
    # custom tweaks for ClowdApp resources
    for i in items:
        if i["kind"] != "ClowdApp":
            continue

        for d in i["spec"].get("deployments", []):
            if "resources" in d["podSpec"]:
                del d["podSpec"]["resources"]
        for p in i["spec"].get("pods", []):
            if "resources" in p:
                del p["resources"]


def _process_component(image_tag_overrides, config, component):
    required_keys = ["name", "host", "repo", "path"]
    missing_keys = [k for k in required_keys if k not in component]
    if missing_keys:
        raise ValueError("component is missing required keys: %s", ", ".join(missing_keys))

    component_name = component["name"]
    log.info("processing component %s", component_name)

    if component["host"] == "gitlab":
        commit, template_content = process_gitlab(component)
    elif component["host"] == "github":
        commit, template_content = process_github(component)
    elif component["host"] == "local":
        commit, template_content = process_local(component)
    else:
        raise ValueError(
            "invalid host %s for component %s" % (component["host"], component["name"])
        )

    template = yaml.safe_load(template_content)

    params = {
        "IMAGE_TAG": commit[:7],
        "ENV_NAME": config["envName"],
        "CLOWDER_ENABLED": "true",
        "MIN_REPLICAS": "1",
        "REPLICAS": "1",
    }

    params.update(component.get("parameters", {}))

    if component_name in image_tag_overrides:
        params["IMAGE_TAG"] = image_tag_overrides[component_name]

    new_items = process_template(template, params)["items"]
    _remove_resource_config(new_items)

    return new_items


def _process_app(app_cfg, config, k8s_list, get_dependencies, image_tag_overrides, processed_apps):
    required_keys = ["name", "components"]
    missing_keys = [k for k in required_keys if k not in app_cfg]
    if missing_keys:
        raise ValueError("app is missing required keys: %s", ", ".join(missing_keys))

    app_name = app_cfg["name"]

    for component in app_cfg["components"]:
        new_items = _process_component(image_tag_overrides, config, component)
        k8s_list["items"].extend(new_items)

    processed_apps.add(app_name)

    if get_dependencies:
        items = _add_dependencies_to_config(app_name, new_items, processed_apps, config)
        k8s_list["items"].extend(items)


def validate_local_config(config):
    if "envName" not in config:
        raise ValueError("Name of ClowdEnvironment must be set in local config using 'envName'")


def process_local_config(config, app_names, get_dependencies, set_image_tag, processed_apps=None):
    k8s_list = {
        "kind": "List",
        "apiVersion": "v1",
        "metadata": {},
        "items": [],
    }

    if not processed_apps:
        processed_apps = set()

    apps_cfg = {a["name"]: a for a in config["apps"]}

    image_tag_overrides = split_equals(set_image_tag)

    for app_name in set(app_names):
        if app_name not in apps_cfg:
            raise ValueError("app %s not found in local config" % app_name)
        log.info("processing app '%s'", app_name)
        _process_app(
            apps_cfg[app_name],
            config,
            k8s_list,
            get_dependencies,
            image_tag_overrides,
            processed_apps,
        )

    return k8s_list


def process_clowd_env(config):
    log.info("processing ClowdEnvironment")
    target_ns = config.get("targetNamespace")
    if not target_ns:
        raise ValueError(
            "ClowdEnvironment target namespace must be set in local config using 'targetNamespace'"
        )

    env_template_path = Path(
        config["envTemplate"] if "envTemplate" in config else conf.DEFAULT_CLOWDENV_TEMPLATE
    )

    if not env_template_path.exists():
        raise ValueError("ClowdEnvironment template file does not exist: %s", env_template_path)

    with env_template_path.open() as fp:
        template_data = yaml.safe_load(fp)

    processed_template = process_template(
        template_data,
        params={
            "ENV_NAME": config["envName"],
            "NAMESPACE": target_ns,
        },
    )

    if not processed_template.get("items"):
        raise ValueError("Processed ClowdEnvironment template has no items")

    return processed_template["items"]

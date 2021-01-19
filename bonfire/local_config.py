import logging
import os
import os.path
import requests
import tempfile
import yaml
import subprocess
import shlex


import bonfire.config as conf
from bonfire.openshift import process_template

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


def process_gitlab(app):

    with tempfile.NamedTemporaryFile(delete=False) as fp:
        cert_fname = fp.name
        fp.write(GL_CA_CERT.encode("ascii"))

    group, project = app["repo"].split("/")
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
        raise ValueError("project ID not found for %s" % app["repo"])

    response = requests.get(GL_MASTER_REF % project_id, verify=cert_fname)
    response.raise_for_status()
    commit = response.json()["commit"]["id"]

    url = GL_CONTENT % (app["repo"], commit, app["path"])
    response = requests.get(url, verify=cert_fname)
    if response.status_code != 200:
        msg = "Invalid response code %s fetching template for %s: %s"
        raise ValueError(msg % (response.status_code, app["name"], url))

    os.unlink(cert_fname)

    return commit, response.content


def process_github(app):
    response = requests.get(GH_MASTER_REF % app["repo"])
    response.raise_for_status()
    commit = response.json()["object"]["sha"]
    url = GH_CONTENT % (app["repo"], commit, app["path"])
    response = requests.get(url)
    if response.status_code != 200:
        msg = "Invalid response code %s fetching template for %s: %s"
        raise ValueError(msg % (response.status_code, app["name"], url))
    return commit, response.content


def process_local(app):
    cmd = "git -C %s rev-parse HEAD" % app["repo"]
    commit = subprocess.check_output(shlex.split(cmd)).decode("ascii")
    template_path = os.path.join(app["repo"], app["path"])
    with open(template_path) as fp:
        return commit, fp.read()


def _add_dependencies_to_config(namespace, app_name, new_items, processed_apps, config):
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
        items = process_local_config(namespace, config, dependencies, True, processed_apps)["items"]
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


def _process_app(namespace, app_name, apps_cfg, config, k8s_list, get_dependencies, processed_apps):
    app_cfg = apps_cfg[app_name]
    if app_cfg["host"] == "gitlab":
        commit, template_content = process_gitlab(app_cfg)
    elif app_cfg["host"] == "github":
        commit, template_content = process_github(app_cfg)
    elif app_cfg["host"] == "local":
        commit, template_content = process_local(app_cfg)
    else:
        raise ValueError("invalid host %s for app %s" % (app_cfg["host"], app_cfg["name"]))

    template = yaml.safe_load(template_content)

    params = {
        "IMAGE_TAG": commit[:7],
        "ENV_NAME": config.get("envName") or conf.ENV_NAME_FORMAT.format(namespace=namespace),
        "CLOWDER_ENABLED": "true",
        "MIN_REPLICAS": "1",
        "REPLICAS": "1",
    }

    params.update(app_cfg.get("parameters", {}))

    new_items = process_template(template, params)["items"]
    _remove_resource_config(new_items)

    k8s_list["items"].extend(new_items)

    processed_apps.add(app_name)

    if get_dependencies:
        items = _add_dependencies_to_config(namespace, app_name, new_items, processed_apps, config)
        k8s_list["items"].extend(items)


def process_local_config(namespace, config, app_names, get_dependencies, processed_apps=None):
    k8s_list = {
        "kind": "List",
        "apiVersion": "v1",
        "metadata": {},
        "items": [],
    }

    if not processed_apps:
        processed_apps = set()

    apps_cfg = {a["name"]: a for a in config["apps"]}

    for app_name in set(app_names):
        if app_name not in apps_cfg:
            raise ValueError("app %s not found in local config" % app_name)
        log.info("processing app '%s'", app_name)
        _process_app(
            namespace, app_name, apps_cfg, config, k8s_list, get_dependencies, processed_apps
        )

    return k8s_list

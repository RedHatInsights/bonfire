import os
import requests
import yaml
import sh
import json
import tempfile

GH_MASTER_REF = "https://api.github.com/repos/%s/git/refs/heads/master"
GH_CONTENT = "https://raw.githubusercontent.com/%s/%s/%s"
GL_PROJECTS = "https://gitlab.cee.redhat.com/api/v4/groups/%s/projects/?per_page=100"
GL_MASTER_REF = "https://gitlab.cee.redhat.com/api/v4/projects/%s/repository/branches/master"
GL_CONTENT = "https://gitlab.cee.redhat.com/%s/-/raw/%s/%s"
GL_TLS_CA = "2015-RH-IT-Root-CA.pem"

cert = """
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
        fp.write(cert.encode("ascii"))

    group, project = app["repo"].split("/")
    projects = requests.get(GL_PROJECTS % group, verify=cert_fname).json()
    project_id = 0

    for p in projects:
        if p["path"] == project:
            project_id = p["id"]

    if not project_id:
        raise ValueError("Project ID not found for %s" % app["repo"])

    commit = requests.get(GL_MASTER_REF % project_id, verify=cert_fname).json()["commit"]["id"]
    url = GL_CONTENT % (app["repo"], commit, app["path"])
    response = requests.get(url, verify=cert_fname)
    if response.status_code != 200:
        msg = "Invalid response code %s fetching template for %s: %s"
        raise ValueError(msg % (response.status_code, app["name"], url))

    os.unlink(cert_fname)

    return commit, response.content


def process_github(app):
    commit = requests.get(GH_MASTER_REF % app["repo"]).json()["object"]["sha"]
    url = GH_CONTENT % (app["repo"], commit, app["path"])
    response = requests.get(url)
    if response.status_code != 200:
        msg = "Invalid response code %s fetching template for %s: %s"
        raise ValueError(msg % (response.status_code, app["name"], url))
    return commit, response.content


def get_app_local_config(app_name, get_dependencies):
    config_list = {
        "kind": "List",
        "apiVersion": "v1",
        "metadata": {},
        "items": [],
    }

    with open("config.yaml") as fp:
        config = yaml.safe_load(fp)

    apps = {a["name"]: a for a in config["apps"]}

    if app_name not in apps:
        raise ValueError("App %s not found in local config.yaml" % app_name)

    app = apps[app_name]

    if app["host"] == "gitlab":
        commit, template = process_gitlab(app)
    elif app["host"] == "github":
        commit, template = process_github(app)
    else:
        raise ValueError("Invalid host %s for app %s" % (app["host"], app["name"]))

    oc_process_args = ["--local", "-f", "-", "--ignore-unknown-parameters"]

    params = {
        "IMAGE_TAG": commit[:7],
        "ENV_NAME": config["envName"],
        "CLOWDER_ENABLED": "true",
        "MIN_REPLICAS": "1",
        "REPLICAS": "1",
    }

    for k, v in params.items():
        oc_process_args.extend(["-p", "%s=%s" % (k, v)])

    template_json = json.loads(str(sh.oc.process(oc_process_args, _in=template)))

    if template_json["kind"] == "List":
        t_list = template_json
    else:
        t_list = {"items": template_json}

    for i in t_list["items"]:
        if i["kind"] != "ClowdApp":
            continue

        k = "deployments" if "deployments" in i["spec"] else "pods"
        for d in i["spec"].get("deployments", []):
            if "resources" in d["podSpec"]:
                del d["podSpec"]["resources"]
        for p in i["spec"].get("pods", []):
            if "resources" in p:
                del p["resources"]

        for dep in i.get("dependencies") or []:
            config_list["items"].extend(get_app_local_config(dep)["items"])

    config_list["items"].extend(t_list["items"])

    return config_list

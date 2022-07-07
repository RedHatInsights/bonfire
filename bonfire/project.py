from ocviapy import oc
import json
import base64


def get_project_info():
    output = ""
    project_name = oc("project", "-q", _silent=True).strip()
    if not project_name.startswith("ephemeral") or project_name == "default":
        output += "Can't get project info. Please use an ephemeral oc project\n"
        output += "Hint: run 'oc project <ephemeral-namespace>' and retry\n"
        output += "If you do not know your namespace, use 'bonfire namespace list'\n"
        return output
    host = get_hostname(oc("get", "route", "-o", "json", _silent=True).strip())

    kc_name = f"env-{project_name}-keycloak"
    fe_creds = get_fe_creds(oc("get", "secret", kc_name, "-o", "json", _silent=True).strip())
    output += f"Current project: {project_name}\n"
    output += f"Frontend route: https://{host}\n"
    output += f"Keycloak login: {fe_creds}\n"
    return output


def get_hostname(routes):
    json_routes = json.loads(routes)
    # Hostnames are all the same, so return the first one
    return json_routes['items'][0]['spec']['host']


def get_default_pass(keycloak_secret):
    json_secret = json.loads(keycloak_secret)
    default_pass = json_secret['data']['defaultPassword']
    return base64.b64decode(default_pass).decode("UTF-8")


def get_fe_creds(keycloak_secret):
    username = "jdoe"
    password = get_default_pass(keycloak_secret)
    return f"Username: {username} || Password: {password}"

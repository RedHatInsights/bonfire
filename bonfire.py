#!/usr/bin/env python3

import copy
import click
import os
import sys
import json
import requests
import yaml
from subprocess import PIPE
from subprocess import Popen

from graphqlclient import GraphQLClient

RAW_GITHUB = "https://raw.githubusercontent.com/{org}/{repo}/{ref}{path}"
RAW_GITLAB = "https://gitlab.cee.redhat.com/{org}/{repo}/-/raw/{ref}{path}"

ENVS_QUERY = """
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

SAAS_QUERY = """
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


@click.command()
@click.option("--target-app", "-a", required=True, type=str, help="Name of application")
@click.option(
    "--target-env",
    "-e",
    help="Name of environment (default: insights-production)",
    type=str,
    default="insights-production"
)
@click.option(
    "--url",
    "-u",
    help="qontract-server API url (default: 'http://localhost:4000/graphql')",
    type=str,
    default="http://localhost:4000/graphql"
)
def main(target_app, target_env, url):
    client = GraphQLClient(url)

    if "GRAPHQL_CREDS" in os.environ:
        client.inject_token(os.environ["GRAPHQL_CREDS"])

    for env in json.loads(client.execute(ENVS_QUERY))["data"]["envs"]:
        if env["name"] == target_env:
            env = env
            env["namespaces"] = set(n["name"] for n in env["namespaces"])
            break
    else:
        raise ValueError("cannot find env '{target_env}'")

    found_templates = True

    for saas_file in json.loads(client.execute(SAAS_QUERY))["data"]["saas_files"]:
        if saas_file["app"]["name"] != target_app:
            continue

        if saas_file["app"].get("parentApp", {}).get("name") != "insights":
            raise ValueError(f"specified app '{target_app}' is not part of cloud.redhat.com")

        for r in saas_file["resourceTemplates"]:
            found_templates = True

            org, repo = r["url"].split("/")[-2:]
            path = r["path"]
            for t in r["targets"]:
                if t["namespace"]["name"] not in env["namespaces"]:
                    continue

                raw_template = RAW_GITHUB if "github" in r["url"] else RAW_GITLAB
                template_url = raw_template.format(org=org, repo=repo, ref=t["ref"], path=path)

                p = copy.deepcopy(json.loads(env["parameters"]))
                p.update(json.loads(saas_file["parameters"] or "{}"))
                p.update(json.loads(r["parameters"] or "{}"))
                p.update(json.loads(t["parameters"] or "{}"))
                if "IMAGE_TAG" not in p:
                    p.update({"IMAGE_TAG": "latest" if t["ref"] == "master" else t["ref"][:7]})

                template = requests.get(template_url, verify=False).text
                y = yaml.safe_load(template)

                pnames = set(p["name"] for p in y["parameters"])
                param_str = " ".join(f"-p {k}={v}" for k, v in p.items() if k in pnames)

                proc = Popen(
                    f"oc process --local -o json -f - {param_str}",
                    shell=True, stdin=PIPE, stdout=PIPE
                )
                stdout, stderr = proc.communicate(template.encode("utf-8"))
                print(stdout.decode("utf-8"))

    if not found_templates:
        raise ValueError(f"templates for app '{target_app}' not found")


if __name__ == "__main__":
    main()




#!/usr/bin/env python3

import copy
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

if len(sys.argv) < 2:
    print("Please provide app name")
    sys.exit(1)

target_app = sys.argv[1]

client = GraphQLClient('http://localhost:4000/graphql')

if "GRAPHQL_CREDS" in os.environ:
    client.inject_token(os.environ["GRAPHQL_CREDS"])

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

prod_env = None

for env in json.loads(client.execute(ENVS_QUERY))["data"]["envs"]:
    if env["name"] == "insights-production":
        prod_env = env
        env["namespaces"] = set(n["name"] for n in env["namespaces"])
        break

if not prod_env:
    raise ValueError("Cannot find production env")

for saas_file in json.loads(client.execute(SAAS_QUERY))["data"]["saas_files"]:
    if saas_file["app"]["name"] != target_app:
        continue

    if saas_file["app"]["parentApp"]["name"] != "insights":
        raise ValueError("Specified app is not part of cloud.redhat.com")
    
    for r in saas_file["resourceTemplates"]:
        org, repo = r["url"].split("/")[-2:]
        path = r["path"]
        for t in r["targets"]:
            if t["namespace"]["name"] not in prod_env["namespaces"]:
                continue

            raw_template = RAW_GITHUB if "github" in r["url"] else RAW_GITLAB
            template_url = raw_template.format(org=org, repo=repo, ref=t["ref"], path=path)

            p = copy.deepcopy(json.loads(prod_env["parameters"]))
            p.update(json.loads(saas_file["parameters"] or "{}"))
            p.update(json.loads(r["parameters"] or "{}"))
            p.update(json.loads(t["parameters"] or "{}"))
            p.update({"IMAGE_TAG": t["ref"][:7]})

            template = requests.get(template_url, verify=False).text
            y = yaml.load(template)

            pnames = set(p["name"] for p in y["parameters"])
            param_str = " ".join("-p %s=%s" % (k, v) for k, v in p.items() if k in pnames)
            # print(param_str)

            proc = Popen("oc process --local -o json -f - %s" % param_str, shell=True, stdin=PIPE, stdout=PIPE)
            stdout, stderr = proc.communicate(template.encode("utf-8"))
            print(stdout.decode("utf-8"))

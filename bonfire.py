#!/usr/bin/env python3

import copy
import click
import os
import sys
import json
import requests
import yaml
import logging
from subprocess import PIPE
from subprocess import Popen

from client import Client

log = logging.getLogger('bonfire.main')

RAW_GITHUB = "https://raw.githubusercontent.com/{org}/{repo}/{ref}{path}"
RAW_GITLAB = "https://gitlab.cee.redhat.com/{org}/{repo}/-/raw/{ref}{path}"


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
def main():
    pass


@main.command('get-namespaces')
def get_namespaces():
    """Get list of namespaces available for ephemeral deployments"""
    client = Client()
    namespaces = client.get_env("insights-ephemeral")["namespaces"]
    namespaces.remove('ephemeral-base')
    # TODO: figure out which of these are currently in use
    click.echo("\n".join(namespaces))


@main.command('get-config')
@click.option("--app", "-a", required=True, type=str, help="Name of application")
@click.option(
    "--src-env",
    "-e",
    help="Name of environment to pull app config from (default: insights-ephemeral)",
    type=str,
    default="insights-ephemeral"
)
@click.option(
    "--ref-env",
    "-r",
    help="Name of environment to use for 'ref'/'IMAGE_TAG' (default: insights-production)",
    type=str,
    default="insights-production"
)
@click.pass_context
def get_config(ctx, app, src_env, ref_env):
    """Get kubernetes config for an app"""
    client = Client()

    src_env_data = client.get_env(src_env)
    ref_env_data = client.get_env(ref_env)

    for saas_file in client.get_saas_files(app):
        src_resources = client.get_filtered_resource_templates(saas_file, src_env_data)
        ref_resources = client.get_filtered_resource_templates(saas_file, ref_env_data)

        for app_name, r in src_resources.items():
            src_targets = r.get('targets', [])
            ref_targets = ref_resources.get(app, {}).get('targets', [])
            if not src_targets:
                log.warning("app '%s' no targets found using src env '%s'", app_name, src_env)
                continue
            if not ref_targets:
                log.warning("app '%s' no targets found using ref env '%s'", app_name, ref_env)
                ref_targets = src_targets

            if len(ref_targets) > 1:
                # find a target with 0 replicas if possible
                log.warning("app '%s' has multiple targets defined for ref env '%s'", app, ref_env)
                for t in ref_targets:
                    if t['parameters'].get("REPLICAS") != 0:
                        ref_targets = [t]
                        break

            ref_target = ref_targets[0]

            ref_git_ref = ref_target["ref"]
            ref_image_tag = ref_target['parameters'].get("IMAGE_TAG")

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
                    shell=True, stdin=PIPE, stdout=PIPE
                )
                stdout, stderr = proc.communicate(template.encode("utf-8"))
                print(stdout.decode("utf-8"))


if __name__ == "__main__":
    main()




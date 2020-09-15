#!/usr/bin/env python3

import copy
import click
import os
import sys
import json
import requests
import yaml
import logging

from bonfire.app_interface import get_ephemeral_namespaces, get_app_config
from bonfire.openshift import get_json, wait_for_all_resources

log = logging.getLogger(__name__)


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option(
    "--debug",
    "-d",
    help="Enable debug logging",
    is_flag=True,
    default=False
)
def main(debug):
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)


@main.command('get-namespaces')
def get_namespaces():
    """Get list of namespaces available for ephemeral deployments"""
    click.echo("\n".join(get_ephemeral_namespaces()))


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
def get_config(app, src_env, ref_env):
    """Get kubernetes config for an app"""
    print(json.dumps(get_app_config(app, src_env, ref_env), indent=2))


@main.command('wait')
@click.option(
    "--namespace", "-n", required=True, type=str, help="namespace"
)
@click.option(
    "--timeout", "-t", required=True, type=int, default=300, help="timeout in sec (default = 300)"
)
def wait(namespace, timeout):
    """Wait for all deployment(config)/(stateful|daemon)set resources to be ready in namespace"""
    wait_for_all_resources(namespace, timeout)


if __name__ == "__main__":
    main()




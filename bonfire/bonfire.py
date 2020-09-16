#!/usr/bin/env python3

import click
import json
import logging

import bonfire.config as conf
from bonfire.app_interface import (
    get_namespaces_for_env,
    get_app_config,
    get_secret_names_in_namespace,
)
from bonfire.openshift import wait_for_all_resources, copy_namespace_secrets

log = logging.getLogger(__name__)


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option("--debug", "-d", help="Enable debug logging", is_flag=True, default=False)
def main(debug):
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)


def _get_namespaces():
    namespaces = get_namespaces_for_env(conf.EPHEMERAL_ENV_NAME)
    namespaces.remove(conf.BASE_NAMESPACE_NAME)
    return namespaces


@main.command("list-namespaces")
def list_namespaces():
    """Get list of namespaces available for ephemeral deployments"""
    click.echo("\n".join(_get_namespaces))


@main.command("checkout-namespace")
@click.option(
    "--namespace",
    "-n",
    required=False,
    type=str,
    help="namespace name (if not specified, one is picked for you)",
)
def checkout_namespace(namespace):
    """Reserve an available ephemeral namespace"""
    # TODO: figure out how to determine which namespaces are in use and reserve it
    namespace = namespace or _get_namespaces()[0]
    click.echo(namespace)


@main.command("checkin-namespace")
@click.option("--namespace", "-n", required=True, type=str, help="namespace name")
def checkin_namespace(namespace):
    """Remove reservation from an ephemeral namespace"""
    # TODO: implement this
    pass


@main.command("get-config")
@click.option("--app", "-a", required=True, type=str, help="name of application")
@click.option(
    "--src-env",
    "-e",
    help=f"Name of environment to pull app config from (default: {conf.EPHEMERAL_ENV_NAME})",
    type=str,
    default=conf.EPHEMERAL_ENV_NAME,
)
@click.option(
    "--ref-env",
    "-r",
    help=f"Name of environment to use for 'ref'/'IMAGE_TAG' (default: {conf.PROD_ENV_NAME})",
    type=str,
    default=conf.PROD_ENV_NAME,
)
def get_config(app, src_env, ref_env):
    """Get kubernetes config for an app"""
    print(json.dumps(get_app_config(app, src_env, ref_env), indent=2))


@main.command("wait-on-resources")
@click.option("--namespace", "-n", required=True, type=str, help="namespace")
@click.option(
    "--timeout", "-t", required=True, type=int, default=300, help="timeout in sec (default = 300)"
)
def wait_on_resources(namespace, timeout):
    """Wait for rolled out resources to be ready in namespace"""
    wait_for_all_resources(namespace, timeout)


@main.command("copy-secrets")
@click.option("--namespace", "-n", required=True, type=str, help="namespace")
def copy_secrets(namespace):
    """Copy secrets from base namespace to specified namespace"""
    secret_names = get_secret_names_in_namespace(conf.BASE_NAMESPACE)
    copy_namespace_secrets(conf.BASE_NAMESPACE, namespace, secret_names)


if __name__ == "__main__":
    main()

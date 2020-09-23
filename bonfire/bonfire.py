#!/usr/bin/env python3

import click
import json
import logging
import re
import sys

import bonfire.config as conf
from bonfire.qontract import (
    get_namespaces_for_env,
    get_app_config,
    get_secret_names_in_namespace,
)
from bonfire.openshift import wait_for_all_resources, copy_namespace_secrets

log = logging.getLogger(__name__)
EQUALS_REGEX = re.compile(r"^\S+=\S+$")


def _error(msg):
    click.echo(f"ERROR: {msg}")
    sys.exit(1)


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option("--debug", "-d", help="Enable debug logging", is_flag=True, default=False)
def main(debug):
    logging.getLogger("sh").setLevel(logging.CRITICAL)  # silence the 'sh' library logger
    logging.basicConfig(level=logging.DEBUG if debug else logging.INFO)


def _get_namespaces():
    namespaces = get_namespaces_for_env(conf.EPHEMERAL_ENV_NAME)
    namespaces.remove(conf.BASE_NAMESPACE_NAME)
    return namespaces


@main.command("list-namespaces")
def list_namespaces():
    """Get list of namespaces available for ephemeral deployments"""
    click.echo("\n".join(_get_namespaces()))


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
    log.warning("not yet implemented")
    namespace = namespace or _get_namespaces()[0]
    click.echo(namespace)


@main.command("checkin-namespace")
@click.option("--namespace", "-n", required=True, type=str, help="namespace name")
def checkin_namespace(namespace):
    """Remove reservation from an ephemeral namespace"""
    # TODO: implement this
    log.warning("not yet implemented")


def _split_equals(list_of_str):
    if not list_of_str:
        return {}

    output = {}

    for item in list_of_str:
        item = str(item)
        if not EQUALS_REGEX.match(item):
            _error(f"invalid format for value '{item}', must match: r'{EQUALS_REGEX.pattern}'")
        key, val = item.split("=")
        output[key] = val

    return output


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
@click.option(
    "--set-template-ref",
    "-t",
    help=f"Name of environment to use for 'ref'/'IMAGE_TAG' (default: {conf.PROD_ENV_NAME})",
    multiple=True,
)
@click.option(
    "--set-image-tag",
    "-i",
    help=f"Name of environment to use for 'ref'/'IMAGE_TAG' (default: {conf.PROD_ENV_NAME})",
    multiple=True,
)
def get_config(app, src_env, ref_env, set_template_ref, set_image_tag):
    """Get kubernetes config for an app"""
    template_ref_overrides = _split_equals(set_template_ref)
    image_tag_overrides = _split_equals(set_image_tag)
    app_config = get_app_config(app, src_env, ref_env, template_ref_overrides, image_tag_overrides)
    print(json.dumps(app_config, indent=2))


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
    secret_names = get_secret_names_in_namespace(conf.BASE_NAMESPACE_NAME)
    copy_namespace_secrets(conf.BASE_NAMESPACE_NAME, namespace, secret_names)


if __name__ == "__main__":
    main()

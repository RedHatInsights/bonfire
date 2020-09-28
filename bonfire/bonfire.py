#!/usr/bin/env python3

import click
import json
import logging
import re
import sys

import bonfire.config as conf
from bonfire.qontract import get_app_config
from bonfire.openshift import wait_for_all_resources
from bonfire.namespaces import (
    get_namespaces,
    reserve_namespace,
    release_namespace,
    copy_base_resources,
    reconcile,
)

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


@main.group()
def namespace():
    """perform operations on OpenShift namespaces"""
    pass


@main.group()
def config():
    """perform operations related to app configurations"""
    pass


@namespace.command("list")
@click.option(
    "--available", "-a", is_flag=True, default=False, help="show only un-reserved/ready namespaces"
)
def _list_namespaces(available):
    """Get list of namespaces available for ephemeral deployments"""
    namespace_names = sorted([ns.name for ns in get_namespaces(available_only=available)])
    if not namespace_names:
        click.echo("no namespaces found")
    else:
        click.echo("\n".join(namespace_names))


@namespace.command("reserve")
@click.option(
    "--duration",
    "-d",
    required=False,
    type=int,
    default=60,
    help="duration of reservation in minutes (default: 60)",
)
@click.option(
    "--retries",
    "-r",
    required=False,
    type=int,
    default=0,
    help="how many times to retry before giving up (default: infinite)",
)
def _reserve_namespace(duration, retries):
    """Reserve an available ephemeral namespace"""
    ns = reserve_namespace(duration, retries)
    if not ns:
        _error("unable to reserve namespace")
    click.echo(ns.name)


@namespace.command("release")
@click.argument("namespace", required=True, type=str)
def _release_namespace(namespace):
    """Remove reservation from an ephemeral namespace"""
    release_namespace(namespace)


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


@namespace.command("wait-on-resources")
@click.option("--namespace", "-n", required=True, type=str, help="namespace")
@click.option(
    "--timeout", "-t", required=True, type=int, default=300, help="timeout in sec (default = 300)"
)
def wait_on_resources(namespace, timeout):
    """Wait for rolled out resources to be ready in namespace"""
    wait_for_all_resources(namespace, timeout)


@namespace.command("copy-base-resources")
@click.option("--namespace", "-n", required=True, type=str, help="namespace")
def _copy_base_resources(namespace):
    """Copy resources from base namespace to specified namespace"""
    copy_base_resources(namespace)


@namespace.command("reconcile")
def _reconcile():
    """Run reconciler for namespace reservations"""
    reconcile()


@config.command("get")
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


if __name__ == "__main__":
    main()

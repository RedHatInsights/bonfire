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
    reset_namespace,
    add_base_resources,
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
@click.argument("namespace", required=True, type=str)
@click.option(
    "--timeout", "-t", required=True, type=int, default=300, help="timeout in sec (default = 300)"
)
def wait_on_resources(namespace, timeout):
    """Wait for rolled out resources to be ready in namespace"""
    ready = wait_for_all_resources(namespace, timeout)
    if not ready:
        _error("Timed out waiting for resources")


@namespace.command("prepare")
@click.argument("namespace", required=True, type=str)
def _prepare(namespace):
    """Copy base resources into specified namespace"""
    add_base_resources(namespace)


@namespace.command("reconcile")
def _reconcile():
    """Run reconciler for namespace reservations"""
    reconcile()


@namespace.command("reset")
@click.argument("namespace", required=True, type=str)
def _reset(namespace):
    """Set namespace to not released/not ready"""
    reset_namespace(namespace)


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
    help="Override template ref for a component using format '<component name>=<ref>'",
    multiple=True,
)
@click.option(
    "--set-image-tag",
    "-i",
    help="Override image tag for an image using format '<image name>=<tag>'",
    multiple=True,
)
@click.option(
    "--get-dependencies",
    "-d",
    help="Get config for any listed 'dependencies' in this app's ClowdApps",
    is_flag=True,
    default=False,
)
@click.option(
    "--namespace",
    "-n",
    help="Namespace you intend to deploy these components into",
)
def get_config(app, src_env, ref_env, set_template_ref, set_image_tag, get_dependencies, namespace):
    """Get kubernetes config for an app"""
    template_ref_overrides = _split_equals(set_template_ref)
    image_tag_overrides = _split_equals(set_image_tag)
    app_config = get_app_config(
        app,
        src_env,
        ref_env,
        template_ref_overrides,
        image_tag_overrides,
        get_dependencies,
        namespace,
    )
    print(json.dumps(app_config, indent=2))


if __name__ == "__main__":
    main()

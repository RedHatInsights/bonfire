#!/usr/bin/env python3

import click
import json
import logging
import sys

from tabulate import tabulate

import bonfire.config as conf
from bonfire.qontract import get_apps_for_env, sub_refs
from bonfire.openshift import (
    apply_config,
    get_all_namespaces,
    oc_login,
    wait_for_all_resources,
    find_clowd_env_for_ns,
    wait_for_clowd_env_target_ns,
)
from bonfire.utils import split_equals
from bonfire.local import get_local_apps
from bonfire.processor import TemplateProcessor, process_clowd_env
from bonfire.namespaces import (
    Namespace,
    get_namespaces,
    reserve_namespace,
    release_namespace,
    reset_namespace,
    add_base_resources,
    reconcile,
)

log = logging.getLogger(__name__)

APP_SRE_SRC = "appsre"
LOCAL_SRC = "local"


def _error(msg):
    click.echo(f"ERROR: {msg}", err=True)
    sys.exit(1)


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option("--debug", "-d", help="Enable debug logging", is_flag=True, default=False)
def main(debug):
    logging.getLogger("sh").setLevel(logging.CRITICAL)  # silence the 'sh' library logger
    logging.basicConfig(
        format="%(asctime)s [%(levelname)8s] [%(threadName)20s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.DEBUG if debug else logging.INFO,
    )
    if conf.ENV_FILE:
        log.debug("using env file: %s", conf.ENV_FILE)


@main.group()
def namespace():
    """Perform operations related to namespace reservation"""
    pass


@main.group()
def config():
    """Commands related to bonfire configuration"""
    pass


def _reserve_namespace(duration, retries, namespace=None):
    if namespace:
        _warn_if_not_available(namespace)
    ns = reserve_namespace(duration, retries, namespace)
    if not ns:
        _error("unable to reserve namespace")
    return ns.name


def _wait_on_namespace_resources(namespace, timeout):
    time_taken = wait_for_all_resources(namespace, timeout)
    if time_taken >= timeout:
        _error("Timed out waiting for resources; exiting")


def _prepare_namespace(namespace):
    add_base_resources(namespace)


def _warn_if_not_available(namespace):
    ns = Namespace(name=namespace)
    if not ns.available:
        if not click.confirm(
            "Namespace currently not ready or reserved by someone else.  Continue anyway?"
        ):
            click.echo("Aborting")
            sys.exit(0)


_ns_reserve_options = [
    click.option(
        "--duration",
        "-d",
        required=False,
        type=int,
        default=1,
        help="duration of reservation in hrs (default: 1)",
    ),
    click.option(
        "--retries",
        "-r",
        required=False,
        type=int,
        default=0,
        help="how many times to retry namespace reserve before giving up (default: infinite)",
    ),
]

_timeout_option = [
    click.option(
        "--timeout",
        "-t",
        required=True,
        type=int,
        default=300,
        help="timeout in sec (default = 300) to wait for resources to be ready",
    )
]


def _validate_set_template_ref(ctx, param, value):
    try:
        split_value = split_equals(value)
        if split_value:
            # check that values unpack properly
            for app_component, value in split_value.items():
                app_name, component_name = app_component.split("/")
        return split_value
    except ValueError:
        raise click.BadParameter("format must be '<app>/<component>=<ref>'")


def _validate_set_parameter(ctx, param, value):
    try:
        split_value = split_equals(value)
        if split_value:
            # check that values unpack properly
            for param_path, value in split_value.items():
                app_name, component_name, param_name = param_path.split("/")
        return split_value
    except ValueError:
        raise click.BadParameter("format must be '<app>/<component>/<param>=<value>'")


def _validate_set_image_tag(ctx, param, value):
    try:
        return split_equals(value)
    except ValueError:
        raise click.BadParameter("format must be '<image uri>=<tag>'")


_process_options = [
    click.argument(
        "app_names",
        required=True,
        nargs=-1,
    ),
    click.option(
        "--source",
        "-s",
        help=f"Configuration source to use when fetching app templates (default: {LOCAL_SRC})",
        type=click.Choice([LOCAL_SRC, APP_SRE_SRC], case_sensitive=False),
        default=LOCAL_SRC,
    ),
    click.option(
        "--local-config-path",
        "-c",
        help=(
            "File to use for local config (default: first try ./config.yaml, then "
            "$XDG_CONFIG_HOME/bonfire/config.yaml)"
        ),
        default=None,
    ),
    click.option(
        "--set-image-tag",
        "-i",
        help=("Override image tag for an image using format '<image uri>=<tag>'"),
        multiple=True,
        callback=_validate_set_image_tag,
    ),
    click.option(
        "--set-template-ref",
        "-t",
        help="Override template ref for a component using format '<app>/<component>=<ref>'",
        multiple=True,
        callback=_validate_set_template_ref,
    ),
    click.option(
        "--set-parameter",
        "-p",
        help=(
            "Override parameter for a component using format "
            "'<app>/<component>/<parameter name>=<value>"
        ),
        multiple=True,
        callback=_validate_set_parameter,
    ),
    click.option(
        "--namespace",
        "-n",
        help="Namespace you intend to deploy to (default: none)",
        type=str,
    ),
    click.option(
        "--clowd-env",
        "-e",
        help=(
            f"Name of ClowdEnvironment (default: if --namespace provided, {conf.ENV_NAME_FORMAT})"
        ),
        type=str,
        default=None,
    ),
    click.option(
        "--target-env",
        help=(
            f"When using source={APP_SRE_SRC}, name of environment to fetch templates for"
            f" (default: {conf.EPHEMERAL_ENV_NAME})"
        ),
        type=str,
        default=conf.EPHEMERAL_ENV_NAME,
    ),
    click.option(
        "--ref-env",
        help=f"Query {APP_SRE_SRC} for apps in this environment and substitute 'ref'/'IMAGE_TAG'",
        type=str,
        default=None,
    ),
    click.option(
        "--get-dependencies/--no-get-dependencies",
        help="Get config for any listed 'dependencies' in ClowdApps (default: true)",
        default=True,
    ),
    click.option(
        "--remove-resources/--no-remove-resources",
        help="Remove resource limits and requests on ClowdApp configs (default: true)",
        default=True,
    ),
    click.option(
        "--single-replicas/--no-single-replicas",
        help="Set replicas to '1' on all on ClowdApp configs (default: true)",
        default=True,
    ),
]


_clowdenv_process_options = [
    click.option(
        "--namespace",
        "-n",
        help="Target namespace of the ClowdEnvironment (default: none)",
        type=str,
    ),
    click.option(
        "--clowd-env",
        "-e",
        help=(f"Name of ClowdEnvironment (default: if target ns provided, {conf.ENV_NAME_FORMAT})"),
        type=str,
        default=None,
    ),
    click.option(
        "--template-file",
        "-f",
        help=(
            "Path to ClowdEnvironment template file (default: use ephemeral template packaged with"
            " bonfire)"
        ),
        type=str,
        default=None,
    ),
]


def options(options_list):
    """Click decorator used to set a list of click options on a command."""

    def inner(func):
        for option in reversed(options_list):
            func = option(func)
        return func

    return inner


@namespace.command("list")
@click.option(
    "--available",
    "-a",
    is_flag=True,
    default=False,
    help="show only un-reserved/ready namespaces",
)
@click.option(
    "--mine",
    "-m",
    is_flag=True,
    default=False,
    help="show only namespaces reserved in your name",
)
def _list_namespaces(available, mine):
    """Get list of ephemeral namespaces"""
    namespaces = get_namespaces(available_only=available, mine=mine)
    if not namespaces:
        click.echo("no namespaces found")
    else:
        data = {
            "NAME": [ns.name for ns in namespaces],
            "RESERVED": [str(ns.reserved).lower() for ns in namespaces],
            "READY": [str(ns.ready).lower() for ns in namespaces],
            "REQUESTER": [ns.requester_name for ns in namespaces],
            "EXPIRES IN": [ns.expires_in for ns in namespaces],
        }
        tabulated = tabulate(data, headers="keys")
        click.echo(tabulated)


@namespace.command("reserve")
@options(_ns_reserve_options)
@click.argument("namespace", required=False, type=str)
def _cmd_namespace_reserve(duration, retries, namespace):
    """Reserve an ephemeral namespace (specific or random)"""
    click.echo(_reserve_namespace(duration, retries, namespace))


@namespace.command("release")
@click.argument("namespace", required=True, type=str)
def _cmd_namespace_release(namespace):
    """Remove reservation from an ephemeral namespace"""
    _warn_if_not_available(namespace)
    release_namespace(namespace)


@namespace.command("wait-on-resources")
@click.argument("namespace", required=True, type=str)
@options(_timeout_option)
def _cmd_namespace_wait_on_resources(namespace, timeout):
    """Wait for rolled out resources to be ready in namespace"""
    _wait_on_namespace_resources(namespace, timeout)


@namespace.command("prepare", hidden=True)
@click.argument("namespace", required=True, type=str)
def _cmd_namespace_prepare(namespace):
    """Copy base resources into specified namespace (for admin use only)"""
    _prepare_namespace(namespace)


@namespace.command("reconcile", hidden=True)
def _cmd_namespace_reconcile():
    """Run reconciler for namespace reservations (for admin use only)"""
    reconcile()


@namespace.command("reset", hidden=True)
@click.argument("namespace", required=True, type=str)
def _cmd_namespace_reset(namespace):
    """Set namespace to not released/not ready (for admin use only)"""
    reset_namespace(namespace)


def _get_apps_config(source, target_env, ref_env, local_config_path):
    config = conf.load_config(local_config_path)

    if source == APP_SRE_SRC:
        if not target_env:
            _error("target env must be supplied for source '{APP_SRE_SRC}'")
        apps_config = get_apps_for_env(target_env)

        if target_env == conf.EPHEMERAL_ENV_NAME and not ref_env:
            log.info("target env is 'ephemeral' with no ref env given, using 'master' for all apps")
            for _, app_cfg in apps_config.items():
                for component in app_cfg.get("components", []):
                    component["ref"] = "master"

        # override any apps that were defined in 'apps' setion of local config file
        apps_config.update(get_local_apps(config, fetch_remote=False))

    elif source == LOCAL_SRC:
        apps_config = get_local_apps(config, fetch_remote=True)

    if ref_env:
        sub_refs(apps_config, ref_env)

    return apps_config


def _get_env_name(target_namespace, env_name):
    if not env_name:
        if not target_namespace:
            _error(
                "unable to infer name of ClowdEnvironment if namespace not provided."
                "  Please run with one of: --clowd-env or --namespace"
            )
        env_name = conf.ENV_NAME_FORMAT.format(namespace=target_namespace)
    return env_name


def _process(
    app_names,
    source,
    get_dependencies,
    set_image_tag,
    ref_env,
    target_env,
    set_template_ref,
    set_parameter,
    clowd_env,
    local_config_path,
    remove_resources,
    single_replicas,
):
    apps_config = _get_apps_config(source, target_env, ref_env, local_config_path)

    processor = TemplateProcessor(
        apps_config,
        app_names,
        get_dependencies,
        set_image_tag,
        set_template_ref,
        set_parameter,
        clowd_env,
        remove_resources,
        single_replicas,
    )
    return processor.process()


@main.command("process")
@options(_process_options)
def _cmd_process(
    app_names,
    source,
    get_dependencies,
    set_image_tag,
    ref_env,
    target_env,
    set_template_ref,
    set_parameter,
    clowd_env,
    namespace,
    local_config_path,
    remove_resources,
    single_replicas,
):
    """Fetch and process application templates"""
    clowd_env = _get_env_name(namespace, clowd_env)

    processed_templates = _process(
        app_names,
        source,
        get_dependencies,
        set_image_tag,
        ref_env,
        target_env,
        set_template_ref,
        set_parameter,
        clowd_env,
        local_config_path,
        remove_resources,
        single_replicas,
    )
    print(json.dumps(processed_templates, indent=2))


@main.command("deploy")
@options(_process_options)
@click.option(
    "--namespace",
    "-n",
    help="Namespace to deploy to (if none given, bonfire will try to reserve one)",
    default=None,
)
@click.option(
    "--no-release-on-fail",
    "-f",
    is_flag=True,
    help="Do not release namespace reservation if deployment fails",
)
@options(_ns_reserve_options)
@options(_timeout_option)
def _cmd_config_deploy(
    app_names,
    source,
    get_dependencies,
    set_image_tag,
    ref_env,
    target_env,
    set_template_ref,
    set_parameter,
    clowd_env,
    local_config_path,
    remove_resources,
    single_replicas,
    namespace,
    duration,
    retries,
    timeout,
    no_release_on_fail,
):
    """Process app templates and deploy them to a cluster"""
    requested_ns = namespace
    ns = None

    oc_login()

    successfully_reserved_ns = False
    reservable_namespaces = get_namespaces()

    if reservable_namespaces:
        # check if we're on a cluster that has reservable namespaces
        log.info(
            "reserving ephemeral namespace%s...",
            f" '{requested_ns}'" if requested_ns else "",
        )
        ns = _reserve_namespace(duration, retries, requested_ns)
        successfully_reserved_ns = True

    else:
        # we're not, user will have to specify namespace to deploy to
        if not requested_ns:
            _error("no reservable namespaces found on this cluster.  '--namespace' is required")

        # make sure namespace exists on the cluster
        cluster_namespaces = get_all_namespaces()
        for cluster_ns in cluster_namespaces:
            if cluster_ns["metadata"]["name"] == requested_ns:
                ns = requested_ns
                break
        else:
            _error(f"namespace '{requested_ns}' not found on cluster")

    if not clowd_env:
        # if no ClowdEnvironment name provided, see if a ClowdEnvironment is associated with this ns
        match = find_clowd_env_for_ns(ns)
        if not match:
            _error(
                f"could not find a ClowdEnvironment tied to ns '{ns}'.  Specify one with "
                "'--clowd-env' or apply one with 'bonfire deploy-clowdenv'"
            )
        clowd_env = match["metadata"]["name"]
        log.debug("inferred clowd_env: '%s'", clowd_env)

    try:
        log.info("processing app templates...")
        apps_config = _process(
            app_names,
            source,
            get_dependencies,
            set_image_tag,
            ref_env,
            target_env,
            set_template_ref,
            set_parameter,
            clowd_env,
            local_config_path,
            remove_resources,
            single_replicas,
        )
        log.debug("app configs:\n%s", json.dumps(apps_config, indent=2))
        if not apps_config["items"]:
            log.warning("no configurations found to apply!")
        else:
            log.info("applying app configs...")
            apply_config(ns, apps_config)
            log.info("waiting on resources...")
            _wait_on_namespace_resources(ns, timeout)
    except (Exception, KeyboardInterrupt):
        log.exception("hit unexpected error!")
        try:
            if not no_release_on_fail and not requested_ns and successfully_reserved_ns:
                # if we auto-reserved this ns, auto-release it on failure unless
                # --no-release-on-fail was requested
                log.info("releasing namespace '%s'", ns)
                release_namespace(ns)
        finally:
            _error("deploy failed")
    else:
        log.info("successfully deployed to %s", ns)
        print(ns)


def _process_clowdenv(target_namespace, env_name, template_file):
    env_name = _get_env_name(target_namespace, env_name)

    try:
        clowd_env_config = process_clowd_env(target_namespace, env_name, template_file)
    except ValueError as err:
        _error(str(err))

    return clowd_env_config


@main.command("process-env")
@options(_clowdenv_process_options)
def _cmd_process_clowdenv(namespace, clowd_env, template_file):
    """Process ClowdEnv template and print output"""
    clowd_env_config = _process_clowdenv(namespace, clowd_env, template_file)
    print(json.dumps(clowd_env_config, indent=2))


@main.command("deploy-env")
@options(_clowdenv_process_options)
@options(_timeout_option)
def _cmd_deploy_clowdenv(namespace, clowd_env, template_file, timeout):
    """Process ClowdEnv template and deploy to a cluster"""
    oc_login()

    clowd_env_config = _process_clowdenv(namespace, clowd_env, template_file)

    log.debug("ClowdEnvironment config:\n%s", clowd_env_config)

    apply_config(None, clowd_env_config)

    if not namespace:
        # wait for Clowder to tell us what target namespace it created
        namespace = wait_for_clowd_env_target_ns(clowd_env)

    _wait_on_namespace_resources(namespace, timeout)

    clowd_env_name = find_clowd_env_for_ns(namespace)["metadata"]["name"]
    log.info("ClowdEnvironment '%s' using ns '%s' is ready", clowd_env_name, namespace)
    print(namespace)


@config.command("write-default")
@click.argument("path", required=False, type=str)
def _cmd_write_default_config(path):
    """Write default configuration file to PATH (default: $XDG_CONFIG_HOME/bonfire/config.yaml)"""
    conf.write_default_config(path)


if __name__ == "__main__":
    main()

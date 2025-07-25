#!/usr/bin/env python3

import json
import logging
import sys
import warnings
from functools import wraps

import click
from ocviapy import apply_config, get_current_namespace, StatusError
from tabulate import tabulate
from wait_for import TimedOutError

import bonfire.config as conf
from bonfire.elastic_logging import ElasticLogger
from bonfire.local import get_local_apps, get_appsfile_apps
from bonfire.utils import AppOrComponentSelector, RepoFile, SYNTAX_ERR
from bonfire.namespaces import (
    Namespace,
    extend_namespace,
    get_namespaces,
    release_reservation,
    reserve_namespace,
    describe_namespace,
)
from bonfire.openshift import (
    check_for_existing_reservation,
    find_clowd_env_for_ns,
    get_namespace_pools,
    get_reservation,
    has_clowder,
    has_ns_operator,
    wait_for_all_resources,
    wait_for_clowd_env_target_ns,
    wait_for_db_resources,
    wait_on_cji,
    whoami,
    get_console_url,
    get_pool_size_limit,
    get_reserved_namespace_quantity,
)
from bonfire.processor import TemplateProcessor, process_clowd_env, process_iqe_cji
from bonfire.qontract import get_apps_for_env, sub_refs
from bonfire.secrets import import_secrets_from_dir
from bonfire.configmaps import import_configmaps_from_dir
from bonfire.utils import (
    FatalError,
    check_pypi,
    find_what_depends_on,
    get_version,
    split_equals,
    validate_time_string,
    merge_app_configs,
)


log = logging.getLogger(__name__)
es_telemetry = ElasticLogger()

APP_SRE_SRC = "appsre"
FILE_SRC = "file"
NO_RESERVATION_SYS = "this cluster does not use a namespace reservation system"

_local_option = click.option(
    "--local",
    help="Whether 'oc process' uses --local=true or --local=false (default: true)",
    type=bool,
    default=True,
)


def _error(msg):
    es_telemetry.send_telemetry(msg, success=False)
    click.echo(f"\nERROR: {msg}", err=True)
    sys.exit(1)


def current_namespace_or_error():
    log.info("attempting to use current namespace from oc/kubectl context...")
    namespace = get_current_namespace()
    if not namespace:
        _error(
            "Namespace from current oc/kubectl context is not set."
            " Please specify namespace using options/arguments."
        )
    return namespace


def click_exception_wrapper(command):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            try:
                result = f(*args, **kwargs)
                return result
            except KeyboardInterrupt:
                _error(f"{command}: aborted by keyboard interrupt")
            except (TimedOutError, FatalError, StatusError) as err:
                _error(f"{command}: hit error: {err}")
            except Exception as err:
                log.exception("hit unexpected error")
                _error(f"{command}: hit unexpected error: {err}")

        return wrapper

    return decorator


@click.group(context_settings=dict(help_option_names=["-h", "--help"]))
@click.option("--debug", "-d", help="Enable debug logging", is_flag=True, default=False)
def main(debug):
    logging.getLogger("sh").setLevel(logging.CRITICAL)  # silence the 'sh' library logger
    logging.basicConfig(
        format="%(asctime)s [%(levelname)8s] [%(threadName)20s] %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
        level=logging.DEBUG if debug else logging.INFO,
    )

    def custom_formatwarning(msg, *args, **kwargs):
        # ignore everything except the message
        return str(msg)

    warnings.formatwarning = custom_formatwarning
    warnings.simplefilter("default")
    logging.captureWarnings(True)
    if conf.ENV_FILE:
        log.debug("using env file: %s", conf.ENV_FILE)

    check_pypi()


@main.group(hidden=True)
def test():
    """
    Used for unit testing
    """
    pass


@main.group()
def namespace():
    """Perform operations related to namespace reservation"""
    pass


@main.group()
def config():
    """Commands related to bonfire configuration"""
    pass


@main.group()
def apps():
    """Show information about deployable apps"""
    pass


@main.group()
def pool():
    """Perform operations related to pool types"""
    pass


def _confirm_or_abort(msg):
    if conf.BONFIRE_BOT:
        # these types of warnings shouldn't occur in automated runs, error out immediately
        _error(msg)
    else:
        # have end user confirm if they want to proceed anyway
        click.echo(f"\n{msg}")
        prompt = "Continue anyway?"
        if not sys.stdout.isatty():
            _error(
                f"Prompt cannot be answered:\n\n{msg}\n{prompt}\n\nOutput is not a TTY. Aborting."
            )
        if not click.confirm(prompt):
            click.echo("Aborting")
            sys.exit(0)


def _warn_if_not_owned_by_me():
    _confirm_or_abort("Namespace currently reserved by someone else")


def _warn_if_not_ready():
    _confirm_or_abort("Namespace's environment is not currently ready")


def _warn_before_delete():
    _confirm_or_abort("Deleting this reservation will also delete the associated namespace")


def _warn_of_existing(requester):
    _confirm_or_abort(
        f"Existing reservation(s) found for requester '{requester}', "
        "consider re-using the existing namespace."
    )


def _get_requester():
    if conf.BONFIRE_NS_REQUESTER:
        requester = conf.BONFIRE_NS_REQUESTER
    else:
        try:
            requester = whoami()
        except Exception:
            log.info("whoami returned an error - setting requester to 'bonfire'")  # minikube
            requester = "bonfire"
    return requester


def _wait_on_namespace_resources(namespace, timeout, db_only=False, defer_status_errors=False):
    if db_only:
        wait_for_db_resources(namespace, timeout, defer_status_errors)
    else:
        wait_for_all_resources(namespace, timeout, defer_status_errors)


def _validate_reservation_duration(ctx, param, value):
    try:
        return validate_time_string(value)
    except ValueError as err:
        raise click.BadParameter(err)


_ns_reserve_options = [
    click.option(
        "--name",
        type=str,
        default=None,
        help="Identifier for the reservation",
    ),
    click.option(
        "--requester",
        "-r",
        type=str,
        default=None,
        help="Name of the user requesting a reservation",
    ),
    click.option(
        "--duration",
        "-d",
        type=str,
        default="1h",
        help="Duration of the reservation",
        callback=_validate_reservation_duration,
    ),
    click.option(
        "--pool",
        type=str,
        default=conf.DEFAULT_NAMESPACE_POOL,
        show_default=True,
        help="Specifies the pool type name",
    ),
    click.option(
        "-f",
        "--force",
        is_flag=True,
        default=False,
        help="Don't prompt if reservations exist for user",
    ),
    _local_option,
]


_ns_list_options = [
    click.option(
        "--available",
        "-a",
        is_flag=True,
        default=False,
        help="show only un-reserved/ready namespaces",
    ),
    click.option(
        "--mine",
        "-m",
        is_flag=True,
        default=False,
        help="show only namespaces reserved in your name",
    ),
    click.option(
        "--output",
        "-o",
        default="cli",
        help="which output format to return the data in",
        type=click.Choice(["cli", "json"], case_sensitive=False),
    ),
]

_timeout_options = [
    click.option(
        "--timeout",
        "-t",
        required=True,
        type=int,
        default=600,
        help="timeout in sec (default = 600) to wait for resources to be ready",
    ),
    click.option(
        "--defer-status-errors",
        is_flag=True,
        default=False,
        help="do not exit immediately if status errors seen (e.g. ImagePullBackOff). Default: false",
    ),
]


def _validate_set_template_ref(ctx, param, value):
    try:
        split_value = split_equals(value)
        if split_value:
            # check that values unpack properly
            for app_component, value in split_value.items():
                # TODO: remove once app name syntax fully deprecated
                split = app_component.split("/")
                if len(split) == 2:
                    warnings.warn(
                        (
                            "--set-template-ref: <app>/<component>=<ref> syntax is deprecated, "
                            "use <component>=<ref>"
                        ),
                        DeprecationWarning,
                    )
                elif len(split) > 2:
                    raise ValueError
        return split_value
    except ValueError:
        raise click.BadParameter("format must be '<component>=<ref>'")


def _validate_set_parameter(ctx, param, value):
    try:
        split_value = split_equals(value)
        if split_value:
            # check that values unpack properly
            for param_path, value in split_value.items():
                # TODO: remove once app name syntax fully deprecated
                split = param_path.split("/")
                if len(split) == 3:
                    warnings.warn(
                        (
                            "--set-parameter: <app>/<component>/<param>=<value> syntax is "
                            "deprecated, use <component>/<param>=<value>"
                        ),
                        DeprecationWarning,
                    )
                elif len(split) < 2 or len(split) > 3:
                    raise ValueError
        return split_value
    except ValueError:
        raise click.BadParameter("format must be '<component>/<param>=<value>'")


def _validate_split_equals(ctx, param, value):
    try:
        return split_equals(value)
    except ValueError:
        msg = "format must be '<name>=<value>'"
        name = param.name
        if name == "set_image_tag":
            msg = "format must be '<image uri>=<tag>', example: 'quay.io/org/repo=latest'"
        elif name == "preferred_params":
            msg = "format must be 'PARAMETER_NAME=value'"
        elif name == "custom_env_vars":
            msg = "format must be 'ENV_VAR_NAME=value'"
        raise click.BadParameter(msg)


def _translate_to_obj(value_list):
    apps = []
    components = []
    select_all = False
    for value in value_list:
        if value == "all":
            # all is a special keyword
            select_all = True
        elif value.startswith("app:"):
            apps.append(value.split(":")[1])
        else:
            components.append(value)
    return AppOrComponentSelector(select_all, apps, components)


def _app_or_component_selector(ctx, param, this_value):
    if any([val.startswith("-") for val in this_value]):
        raise click.BadParameter("requires a component name or keyword 'all'")

    # check if 'app:' syntax has been used and translate input values to apps/components dictionary
    this_value = _translate_to_obj(this_value)

    opposite_option = {
        "remove_resources": "no_remove_resources",
        "no_remove_resources": "remove_resources",
        "remove_dependencies": "no_remove_dependencies",
        "no_remove_dependencies": "remove_dependencies",
    }

    this_param_name: str = param.name
    other_param_name: str = opposite_option[this_param_name]

    other_value = ctx.params.get(other_param_name, AppOrComponentSelector())

    # validate that opposing options are not both set to 'all'
    if this_value.select_all and other_value.select_all:
        raise click.BadParameter(
            f"'all' cannot be specified on both this option and its opposite '{other_param_name}'"
        )

    # validate that the same app was not used in opposing options
    for app in this_value.apps:
        if app in other_value.apps:
            raise click.BadParameter(
                f"app '{app}' cannot be specified on both this option"
                f" and its opposite '{other_param_name}'"
            )

    # validate that the same component was not used in opposing options
    for component in this_value.components:
        if component in other_value.components:
            raise click.BadParameter(
                f"component '{component}' cannot be specified on both this option"
                f" and its opposite '{other_param_name}'"
            )

    # set default value for --remove-resources to 'all' if option was unspecified
    # set default value for --no-remove-dependencies to 'all' if option was unspecified
    options_w_defaults = ("remove_resources", "no_remove_dependencies")
    if this_param_name in options_w_defaults and this_value.empty and other_value.empty:
        this_value.select_all = True

    return this_value


_app_source_options = [
    click.option(
        "--source",
        "-s",
        help=f"Configuration source to use when fetching app templates (default: {APP_SRE_SRC})",
        type=click.Choice([APP_SRE_SRC, FILE_SRC], case_sensitive=False),
        default=APP_SRE_SRC,
    ),
    click.option(
        "--local-config-path",
        "-c",
        help="File to use for local config (default: $XDG_CONFIG_HOME/bonfire/config.yaml)",
        default=None,
    ),
    click.option(
        "--local-config-method",
        help="Selects method used when combining apps in local config with remote app config",
        type=click.Choice(["merge", "override"], case_sensitive=False),
        show_default=True,
        default="merge",
    ),
    click.option(
        "--target-env",
        help=(
            f"Target environment name when using source={APP_SRE_SRC}. "
            f"Use to select which template parameters are fetched."
        ),
        type=str,
        default=conf.EPHEMERAL_ENV_NAME,
        show_default=True,
    ),
    click.option(
        "--prefer",
        "preferred_params",
        help=(
            f"When there are multiple deployment targets found in {APP_SRE_SRC}, prefer the ones "
            "that have '<parameter name>=<value>' set. Can be specified multiple times."
        ),
        multiple=True,
        default=conf.BONFIRE_DEFAULT_PREFER,
        callback=_validate_split_equals,
    ),
]

_process_options = _app_source_options + [
    click.argument(
        "app_names",
        required=True,
        nargs=-1,
    ),
    click.option(
        "--ref-env",
        help=(
            f"Reference environment name in {APP_SRE_SRC}. "
            "Use to set default 'ref'/'IMAGE_TAG' for apps."
        ),
        type=str,
        default=conf.BONFIRE_DEFAULT_REF_ENV,
    ),
    click.option(
        "--fallback-ref-env",
        help=(
            f"Reference environment name in {APP_SRE_SRC} to be used if deployment configuration"
            " not found in primary reference environment."
        ),
        type=str,
        default=conf.BONFIRE_DEFAULT_FALLBACK_REF_ENV,
    ),
    click.option(
        "--set-image-tag",
        "-i",
        help=("Override image tag for an image using format '<image uri>=<tag>'"),
        multiple=True,
        callback=_validate_split_equals,
    ),
    click.option(
        "--set-template-ref",
        help="Override template ref for a component using format '<component>=<ref>'",
        multiple=True,
        callback=_validate_set_template_ref,
    ),
    click.option(
        "--set-parameter",
        "-p",
        help=(
            "Override parameter for a component using format '<component>/<parameter name>=<value>'"
        ),
        multiple=True,
        callback=_validate_set_parameter,
    ),
    click.option(
        "--clowd-env",
        "-e",
        help=(
            "Name of ClowdEnvironment (default: if --namespace provided, will try to find match)"
        ),
        type=str,
        default=None,
    ),
    click.option(
        "--get-dependencies/--no-get-dependencies",
        help="Recursively fetch dependencies listed in ClowdApps (default: true)",
        default=True,
    ),
    click.option(
        "--optional-deps-method",
        help="Selects which method to use when fetching optionalDependencies",
        type=click.Choice(["hybrid", "all", "none"], case_sensitive=False),
        show_default=True,
        default="hybrid",
    ),
    click.option(
        "--remove-resources",
        help=(
            "Remove untrusted (defined in README) resource limits/requests on "
            "ClowdApp/ClowdJob/CJI objects for specific components or apps. Prefix the app name "
            "with 'app:', otherwise specify the component name. (default: 'all')"
        ),
        type=str,
        multiple=True,
        callback=_app_or_component_selector,
    ),
    click.option(
        "--no-remove-resources",
        help=(
            "Preserve resource limits/requests even if untrusted (defined in README) on "
            "ClowdApp/ClowdJob/CJI objects for specific components or apps. Prefix the app name "
            "with 'app:', otherwise specify the component name. (default: none)"
        ),
        type=str,
        multiple=True,
        callback=_app_or_component_selector,
    ),
    click.option(
        "--remove-dependencies",
        help=(
            "Remove dependencies/optionalDependencies on ClowdApp configs "
            "for specific components or apps. Prefix the app name with "
            "'app:', otherwise specify the component name. (default: none)"
        ),
        type=str,
        multiple=True,
        callback=_app_or_component_selector,
    ),
    click.option(
        "--no-remove-dependencies",
        help=(
            "Don't remove dependencies/optionalDependencies on ClowdApp configs "
            "for specific components or apps. Prefix the app name with "
            "'app:', otherwise specify the component name. (default: all)"
        ),
        type=str,
        multiple=True,
        callback=_app_or_component_selector,
    ),
    click.option(
        "--single-replicas/--no-single-replicas",
        help="Set replicas to '1' on all on ClowdApp configs (default: true)",
        default=True,
    ),
    click.option(
        "--component",
        "-C",
        "component_filter",
        help="Specific component(s) that should be processed (default: all)",
        type=str,
        multiple=True,
    ),
    click.option(
        "--exclude-components",
        type=str,
        help="Comma-separated list of components to exclude from deployment",
    ),
    click.option(
        "--frontends",
        "-F",
        help="Deploy frontends (default: false)",
        type=bool,
        default=False,
    ),
    _local_option,
]


_clowdenv_process_options = [
    click.option(
        "--namespace",
        "-n",
        help="Target namespace of the ClowdEnvironment",
        type=str,
        required=True,
    ),
    click.option(
        "--quay-user",
        "-u",
        help="Quay username for pullSecret provider",
        type=str,
    ),
    click.option(
        "--clowd-env",
        "-e",
        help=("Name of ClowdEnvironment (default: env-<namespace>)"),
        type=str,
        default=None,
    ),
    click.option(
        "--template-file",
        help=(
            "Path to ClowdEnvironment template file (default: use local cluster template packaged"
            " with bonfire)"
        ),
        type=str,
        default=None,
    ),
    _local_option,
]


_iqe_cji_process_options = [
    click.argument(
        "clowd_app_name",
        type=str,
        required=True,
    ),
    click.option(
        "--debug-pod",
        "debug",
        help="Set debug mode on IQE pod",
        default=False,
        is_flag=True,
    ),
    click.option(
        "--marker",
        "-m",
        help="pytest marker expression",
        type=str,
        default="",
    ),
    click.option(
        "--plugins",
        "-p",
        help="comma,separated,list of IQE plugins (default: determined by ClowdApp)",
        type=str,
        default="",
    ),
    click.option(
        "--filter",
        "-k",
        help="pytest filter expression",
        type=str,
        default="",
    ),
    click.option(
        "--env",
        "-e",
        help="dynaconf env name",
        type=str,
        default="clowder_smoke",
    ),
    click.option(
        "--image-tag",
        "-i",
        help="image tag to use for IQE pod",
        type=str,
        default="",
    ),
    click.option(
        "--selenium",
        "-s",
        help="deploy selenium container (default: false)",
        is_flag=True,
        default=False,
    ),
    click.option(
        "--cji-name",
        "-c",
        help="Name of ClowdJobInvocation (default: generate a random name)",
        type=str,
        default=None,
    ),
    click.option(
        "--template-file",
        help=(
            "Path to ClowdJobInvocation template file (default: use IQE CJI template packaged"
            " with bonfire)"
        ),
        type=str,
        default=None,
    ),
    click.option(
        "--requirements",
        help="iqe --requirements expression",
        type=str,
        default="",
    ),
    click.option(
        "--requirements-priority",
        help="iqe --requirements-priority expression",
        type=str,
        default="",
    ),
    click.option(
        "--test-importance",
        help="iqe --test-importance expression",
        type=str,
        default="",
    ),
    click.option(
        "--parallel-enabled",
        help="iqe --parallel-enabled expression",
        type=str,
        default="",
    ),
    click.option(
        "--parallel-worker-count",
        help="iqe --parallel-worker-count expression",
        type=str,
        default="",
    ),
    click.option(
        "--rp-args",
        help="iqe --rp-args expression",
        type=str,
        default="",
    ),
    click.option(
        "--ibutsu-source",
        help="iqe --ibutsu-source expression",
        type=str,
        default="",
    ),
    click.option(
        "--env-var",
        "custom_env_vars",
        help=(
            "Define a custom env var to set on the IQE pod in the format of ENV_VAR_NAME=value "
            "(can be specified multiple times)"
        ),
        multiple=True,
        callback=_validate_split_equals,
    ),
    _local_option,
]


def options(options_list):
    """Click decorator used to set a list of click options on a command."""

    def inner(func):
        for option in reversed(options_list):
            func = option(func)
        return func

    return inner


@namespace.command("list")
@options(_ns_list_options)
def _list_namespaces(available, mine, output):
    """Get list of ephemeral namespaces"""
    if not has_ns_operator():
        _error(NO_RESERVATION_SYS)

    namespaces = get_namespaces(available=available, mine=mine)

    if not namespaces:
        if output == "json":
            click.echo("{}")
        else:
            click.echo("no namespaces found")
    else:
        if output == "json":
            data = {}
            for ns in namespaces:
                data[ns.name] = {
                    "reserved": ns.reserved,
                    "status": ns.status,
                    "requester": ns.requester,
                    "expires_in": ns.expires_in,
                    "pool_type": ns.pool_type,
                }
            click.echo(json.dumps(data, indent=2))
        else:
            data = {
                "NAME": [ns.name for ns in namespaces],
                "RESERVED": [str(ns.reserved).lower() for ns in namespaces],
                "ENV STATUS": [str(ns.status).lower() for ns in namespaces],
                "APPS READY": [ns.clowdapps for ns in namespaces],
                "REQUESTER": [ns.requester for ns in namespaces],
                "POOL TYPE": [ns.pool_type for ns in namespaces],
                "EXPIRES IN": [ns.expires_in for ns in namespaces],
            }
            tabulated = tabulate(data, headers="keys")
            click.echo(tabulated)


@namespace.command("reserve")
@options(_ns_reserve_options)
@options(_timeout_options)
@click_exception_wrapper("namespace reserve")
def _cmd_namespace_reserve(
    name, requester, duration, pool, timeout, local, force, defer_status_errors
):
    """Reserve an ephemeral namespace"""
    ns = _check_and_reserve_namespace(name, requester, duration, pool, timeout, local, force)
    click.echo(ns.name)


@namespace.command("release")
@click.argument("namespace", required=False, type=str)
@click.option(
    "-f",
    "--force",
    is_flag=True,
    default=False,
    help="Do not ask for confirmation",
)
@options([_local_option])
@click_exception_wrapper("namespace release")
def _cmd_namespace_release(namespace, force, local):
    """Remove reservation from an ephemeral namespace"""
    if not has_ns_operator():
        _error(NO_RESERVATION_SYS)

    if not namespace:
        namespace = current_namespace_or_error()

    if not force:
        ns = Namespace(name=namespace)
        if not ns.owned_by_me:
            _warn_if_not_owned_by_me()
        _warn_before_delete()

    release_reservation(namespace=namespace, local=local)


@namespace.command("extend")
@click.argument("namespace", required=False, type=str)
@click.option(
    "--duration",
    "-d",
    type=str,
    default="1h",
    help="Amount of time to extend the reservation",
    callback=_validate_reservation_duration,
)
@options([_local_option])
@click_exception_wrapper("namespace extend")
def _cmd_namespace_extend(namespace, duration, local):
    """Extend a reservation of an ephemeral namespace"""
    if not has_ns_operator():
        _error(NO_RESERVATION_SYS)

    if not namespace:
        namespace = current_namespace_or_error()

    extend_namespace(namespace, duration, local)


@namespace.command("wait-on-resources")
@click.argument("namespace", required=False, type=str)
@click.option(
    "--db-only",
    is_flag=True,
    default=False,
    help="Only wait for DB resources owned by ClowdApps to be ready",
)
@options(_timeout_options)
def _cmd_namespace_wait_on_resources(namespace, timeout, db_only, defer_status_errors):
    """Wait for rolled out resources to be ready in namespace"""
    if not namespace:
        namespace = current_namespace_or_error()
    try:
        _wait_on_namespace_resources(namespace, timeout, db_only, defer_status_errors)
    except TimedOutError as err:
        log.error("hit timeout error: %s", err)
        _error("namespace wait timed out")
    except StatusError as err:
        log.error("hit status error: %s", err)
        _error("namespace resources have status errors")


@namespace.command("describe")
@click.argument("namespace", required=False, type=str)
@click.option(
    "--output",
    "-o",
    default="cli",
    help="which output format to return the data in",
    type=click.Choice(["cli", "json"], case_sensitive=False),
)
def _describe_namespace(namespace, output):
    """Get current namespace info"""
    if not namespace:
        namespace = current_namespace_or_error()

    click.echo(describe_namespace(namespace, output))


def _get_apps_config(
    source,
    target_env,
    ref_env,
    fallback_ref_env,
    local_config_path,
    local_config_method,
    preferred_params,
):
    config = conf.load_config(local_config_path)

    if source == APP_SRE_SRC:
        log.info("fetching target env apps config using source: %s", source)
        if not target_env:
            _error("target env must be supplied for source '{APP_SRE_SRC}'")
        apps_config = get_apps_for_env(target_env, preferred_params)

        if not ref_env and target_env == conf.EPHEMERAL_ENV_NAME:
            # set git target to 'master' because ephemeral targets have no git ref defined
            log.info(
                "target env is '%s' and no ref env given, using 'master' git ref for all apps",
                conf.EPHEMERAL_ENV_NAME,
            )
            for _, app_cfg in apps_config.items():
                for component in app_cfg.get("components", []):
                    component["ref"] = "master"

    elif source == FILE_SRC:
        log.info("fetching apps config using source: %s", source)
        apps_config = get_appsfile_apps(config)

    # handle git ref/image substitutions if reference environment was provided
    if ref_env:
        apps_config = sub_refs(apps_config, ref_env, fallback_ref_env, preferred_params)

    # merge remote apps config with local app config
    local_apps = get_local_apps(config)
    apps_config = merge_app_configs(apps_config, local_apps, local_config_method)

    # validate the components look ok after merging
    for app_name, app_config in apps_config.items():
        for component in app_config["components"]:
            # validate the config for a component
            if not component.get("name"):
                raise FatalError(f"{SYNTAX_ERR}, component is missing 'name'")
            try:
                RepoFile.from_config(component)
            except FatalError as err:
                # re-raise with a bit more context
                raise FatalError(f"{str(err)}, hit on app {app_name}")

    return apps_config


def _log_and_return(env_name):
    log.info("templates will be processed with parameter ENV_NAME='%s'", env_name)
    return env_name


def _get_env_name(ns=None, env_name=None):
    if env_name:
        return _log_and_return(env_name)

    if not ns:
        log.warning("neither '--clowd-env' nor '--namespace' provided")
        return _log_and_return(None)

    log.info("searching for ClowdEnvironment tied to ns '%s'...", ns)
    match = find_clowd_env_for_ns(ns)
    if not match:
        log.warning(
            "could not find a ClowdEnvironment with target ns '%s'.  "
            "Specify one with '--clowd-env' if needed.",
            ns,
        )
        return _log_and_return(None)

    return _log_and_return(match["metadata"]["name"])


def _process(
    app_names,
    source,
    get_dependencies,
    optional_deps_method,
    local_config_method,
    set_image_tag,
    ref_env,
    fallback_ref_env,
    target_env,
    set_template_ref,
    set_parameter,
    clowd_env,
    local_config_path,
    remove_resources,
    no_remove_resources,
    remove_dependencies,
    no_remove_dependencies,
    single_replicas,
    component_filter,
    local,
    frontends,
    preferred_params,
    namespace,
    exclude_components,
):
    apps_config = _get_apps_config(
        source,
        target_env,
        ref_env,
        fallback_ref_env,
        local_config_path,
        local_config_method,
        preferred_params,
    )

    processor = TemplateProcessor(
        apps_config,
        app_names,
        get_dependencies,
        optional_deps_method,
        set_image_tag,
        set_template_ref,
        set_parameter,
        clowd_env,
        remove_resources,
        no_remove_resources,
        remove_dependencies,
        no_remove_dependencies,
        single_replicas,
        component_filter,
        local,
        frontends,
        namespace,
        exclude_components,
    )
    return processor.process()


@pool.command("list")
def _cmd_pool_types():
    """List all pool types"""
    click.echo("\n".join(get_namespace_pools()))


def _get_return_args(*args, **kwargs):
    """Dummy function used for unit testing process options"""
    pass


@test.command("process", hidden=True)
@options(_process_options)
def _cmd_test_process(*args, **kwargs):
    """Dummy command used for unit testing process options"""
    _get_return_args(*args, **kwargs)


@main.command("process")
@options(_process_options)
@click.option(
    "--namespace",
    "-n",
    help="Namespace you intend to deploy to (default: none)",
    type=str,
)
def _cmd_process(
    app_names,
    source,
    get_dependencies,
    optional_deps_method,
    local_config_method,
    set_image_tag,
    ref_env,
    fallback_ref_env,
    target_env,
    set_template_ref,
    set_parameter,
    clowd_env,
    namespace,
    local_config_path,
    remove_resources,
    no_remove_resources,
    remove_dependencies,
    no_remove_dependencies,
    single_replicas,
    component_filter,
    local,
    frontends,
    preferred_params,
    exclude_components,
):
    """Fetch and process application templates"""
    clowd_env = _get_env_name(namespace, clowd_env)

    processed_templates = _process(
        app_names,
        source,
        get_dependencies,
        optional_deps_method,
        local_config_method,
        set_image_tag,
        ref_env,
        fallback_ref_env,
        target_env,
        set_template_ref,
        set_parameter,
        clowd_env,
        local_config_path,
        remove_resources,
        no_remove_resources,
        remove_dependencies,
        no_remove_dependencies,
        single_replicas,
        component_filter,
        local,
        frontends,
        preferred_params,
        namespace,
        exclude_components,
    )
    print(json.dumps(processed_templates, indent=2))


def _get_namespace(
    requested_ns_name, name, requester, duration, pool, timeout, local, force, using_current=False
):
    if not has_ns_operator():
        if requested_ns_name:
            ns = Namespace(name=requested_ns_name)
            return ns.name, False
        else:
            _error(f"{NO_RESERVATION_SYS}. Use '-n' to provide a specific target namespace")

    ns = None
    if requested_ns_name:
        ns = _check_and_use_namespace(requested_ns_name, using_current, requester)

    reserved_new_ns = False
    if not ns:
        if using_current:
            log.info(
                "current namespace could not be used (not reserved,"
                " expired, or not owned), reserving a new one",
            )
        ns = _check_and_reserve_namespace(name, requester, duration, pool, timeout, local, force)
        reserved_new_ns = True

    return ns.name, reserved_new_ns


def _check_and_use_namespace(requested_ns_name, using_current, requester):
    if using_current:
        log.info("attempting to use current namespace from oc/kubectl context...")

    if not has_ns_operator():
        _error(f"{NO_RESERVATION_SYS}")

    log.debug("checking if namespace '%s' has been reserved via ns operator...", requested_ns_name)
    operator_reservation = get_reservation(namespace=requested_ns_name)
    ns = None
    if operator_reservation:
        log.debug("found existing ns operator reservation")

        if operator_reservation.get("status", {}).get("state") == "expired":
            msg = f"reservation has expired for namespace '{requested_ns_name}'"
            if using_current:
                log.info(msg)
                return None
            else:
                _error(msg)

        ns = Namespace(name=requested_ns_name)

        if ns.owned_by_me or ns.requester == requester:
            log.info("namespace '%s' is owned by this user", ns.name)
        else:
            log.info("namespace '%s' is reserved by someone else", ns.name)
            if using_current:
                return None
            _warn_if_not_owned_by_me()

        if not ns.ready:
            _warn_if_not_ready()

    elif not using_current:
        _error(f"Namespace '{requested_ns_name}' has not been reserved yet")

    return ns


def _check_and_reserve_namespace(name, requester, duration, pool, timeout, local, force):
    if not has_ns_operator():
        _error(f"{NO_RESERVATION_SYS}")

    if pool not in get_namespace_pools():
        _error(f"namespace pool '{pool}' does not exist on this cluster")

    log.debug("checking if requester already has another namespace reserved...")
    requester = requester if requester else _get_requester()
    if not force and check_for_existing_reservation(requester):
        _warn_of_existing(requester)

    log.info("checking for available namespaces to reserve...")

    pool_size_limit = get_pool_size_limit(pool)
    log.info("pool size limit is defined as %d in '%s' pool", pool_size_limit, pool)
    if pool_size_limit > 0 and get_reserved_namespace_quantity(pool) >= pool_size_limit:
        _error(
            f"Maximum number of namespaces for pool `{pool}` (limit: {pool_size_limit})"
            " have been reserved"
        )

    return reserve_namespace(name, requester, duration, pool, timeout, local)


def _deploy_err_handler(err, no_release_on_fail, reserved_new_ns, reserve, ns):
    if isinstance(err, KeyboardInterrupt):
        msg = "keyboard interrupt"
    else:
        msg = "deploy failed"

    if str(err):
        msg += f": {str(err)}"

    if isinstance(err, (KeyboardInterrupt, TimedOutError, FatalError, StatusError)):
        log.error(msg)
    else:
        log.exception("hit unexpected error!")

    try:
        if not no_release_on_fail and reserved_new_ns and not reserve:
            # if we auto-reserved this ns, auto-release it on failure unless
            # --no-release-on-fail was requested
            log.info("releasing namespace '%s'", ns)
            release_reservation(namespace=ns)
    finally:
        _error(msg)


@main.command("deploy")
@options(_process_options)
@click.option(
    "--namespace",
    "-n",
    help=(
        "Namespace (defaults to namespace from current context; "
        "if not set, not reserved, or not owned, then bonfire will reserve a new one)"
    ),
    default=None,
)
@click.option(
    "--reserve",
    help=(
        "Do not use current context's namespace and force reserve a new one. (keeps"
        " the reservation on failure)"
    ),
    is_flag=True,
)
@click.option(
    "--import-secrets",
    is_flag=True,
    help="Import secrets from local directory at deploy time",
    default=False,
)
@click.option(
    "--import-configmaps",
    is_flag=True,
    help="Import configmaps from local directory at deploy time",
    default=False,
)
@click.option(
    "--secrets-dir",
    type=str,
    help="Directory to use for secrets import (default: $XDG_CONFIG_HOME/bonfire/secrets/)",
    default=conf.DEFAULT_SECRETS_DIR,
)
@click.option(
    "--configmaps-dir",
    type=str,
    help=("Directory to use for configmaps import (default: $XDG_CONFIG_HOME/bonfire/configmaps/)"),
    default=conf.DEFAULT_CONFIGMAPS_DIR,
)
@click.option(
    "--no-release-on-fail",
    is_flag=True,
    help="Do not release namespace reservation if deployment fails",
)
@options(_ns_reserve_options)
@options(_timeout_options)
def _cmd_config_deploy(
    app_names,
    source,
    get_dependencies,
    optional_deps_method,
    local_config_method,
    set_image_tag,
    ref_env,
    fallback_ref_env,
    target_env,
    set_template_ref,
    set_parameter,
    clowd_env,
    local_config_path,
    remove_resources,
    no_remove_resources,
    remove_dependencies,
    no_remove_dependencies,
    single_replicas,
    namespace,
    reserve,
    name,
    requester,
    duration,
    timeout,
    no_release_on_fail,
    exclude_components,
    component_filter,
    import_secrets,
    import_configmaps,
    secrets_dir,
    configmaps_dir,
    local,
    frontends,
    pool,
    force,
    preferred_params,
    defer_status_errors,
):
    """Process app templates and deploy them to a cluster"""
    if not has_clowder():
        _error("cluster does not have clowder operator installed")

    using_current = False
    if reserve:
        namespace = None
    elif not namespace and not conf.BONFIRE_BOT:
        using_current = True
        namespace = get_current_namespace()

    ns, reserved_new_ns = _get_namespace(
        namespace,
        name,
        requester,
        duration,
        pool,
        timeout,
        local,
        force,
        using_current=using_current,
    )

    if import_secrets:
        import_secrets_from_dir(secrets_dir)

    if import_configmaps:
        import_configmaps_from_dir(configmaps_dir)

    clowd_env = _get_env_name(ns, clowd_env)

    try:
        log.info("processing app templates...")
        apps_config = _process(
            app_names,
            source,
            get_dependencies,
            optional_deps_method,
            local_config_method,
            set_image_tag,
            ref_env,
            fallback_ref_env,
            target_env,
            set_template_ref,
            set_parameter,
            clowd_env,
            local_config_path,
            remove_resources,
            no_remove_resources,
            remove_dependencies,
            no_remove_dependencies,
            single_replicas,
            component_filter,
            local,
            frontends,
            preferred_params,
            namespace,
            exclude_components,
        )
        log.debug("app configs:\n%s", json.dumps(apps_config, indent=2))
        if not apps_config["items"]:
            log.warning("no configurations found to apply!")
        else:
            log.info("applying app configs...")
            apply_config(ns, apps_config)
            log.info("waiting on resources for max of %dsec...", timeout)
            _wait_on_namespace_resources(ns, timeout, False, defer_status_errors)
    except (KeyboardInterrupt, Exception) as err:
        _deploy_err_handler(err, no_release_on_fail, reserved_new_ns, reserve, ns)
    else:
        log.info("successfully deployed to namespace %s", ns)
        es_telemetry.send_telemetry("successful deployment")
        url = get_console_url()
        if url:
            ns_url = f"{url}/k8s/cluster/projects/{ns}"
            log.info("namespace url: %s", ns_url)
            log.info(
                "resource usage dashboard for namespace '%s': %s",
                ns,
                conf.RESOURCE_DASHBOARD_URL.format(namespace=ns),
            )
        click.echo(ns)


def _process_clowdenv(namespace, quay_user, clowd_env, template_file, local):
    if not clowd_env:
        clowd_env = f"env-{namespace}"
    return process_clowd_env(namespace, quay_user, clowd_env, template_file, local)


@main.command("process-env")
@options(_clowdenv_process_options)
def _cmd_process_clowdenv(namespace, quay_user, clowd_env, template_file, local):
    """Process ClowdEnv template and print output"""
    clowd_env_config = _process_clowdenv(namespace, quay_user, clowd_env, template_file, local)
    print(json.dumps(clowd_env_config, indent=2))


@main.command("deploy-env")
@options(_clowdenv_process_options)
@click.option(
    "--import-secrets",
    is_flag=True,
    help="Import secrets from local directory at deploy time",
    default=False,
)
@click.option(
    "--import-configmaps",
    is_flag=True,
    help="Import configmaps from local directory at deploy time",
    default=False,
)
@click.option(
    "--secrets-dir",
    type=str,
    help=("Import secrets from this directory (default: $XDG_CONFIG_HOME/bonfire/secrets/)"),
    default=conf.DEFAULT_SECRETS_DIR,
)
@click.option(
    "--configmaps-dir",
    type=str,
    help=(
        "Import configmaps from this directory \
           (default: "
        "$XDG_CONFIG_HOME/bonfire/configmaps/)"
    ),
    default=conf.DEFAULT_CONFIGMAPS_DIR,
)
@options(_ns_reserve_options)
@options(_timeout_options)
@click_exception_wrapper("deploy-env")
def _cmd_deploy_clowdenv(
    namespace,
    quay_user,
    clowd_env,
    template_file,
    timeout,
    import_secrets,
    import_configmaps,
    secrets_dir,
    configmaps_dir,
    name,
    requester,
    duration,
    local,
    pool,
    force,
    defer_status_errors,
):
    """Process ClowdEnv template and deploy to a cluster"""
    if not has_clowder():
        _error("cluster does not have clowder operator installed")

    namespace, _ = _get_namespace(namespace, name, requester, duration, pool, timeout, local, force)

    if import_secrets:
        import_secrets_from_dir(secrets_dir)

    if import_configmaps:
        import_configmaps_from_dir(configmaps_dir)

    clowd_env_config = _process_clowdenv(namespace, quay_user, clowd_env, template_file, local)

    log.debug("ClowdEnvironment config:\n%s", clowd_env_config)

    apply_config(None, clowd_env_config)

    if not namespace:
        # wait for Clowder to tell us what target namespace it created
        namespace = wait_for_clowd_env_target_ns(clowd_env)

    log.info("waiting on resources for max of %dsec...", timeout)
    _wait_on_namespace_resources(namespace, timeout, False, defer_status_errors)

    clowd_env_name = find_clowd_env_for_ns(namespace)["metadata"]["name"]

    log.info("ClowdEnvironment '%s' using ns '%s' is ready", clowd_env_name, namespace)
    click.echo(namespace)


@main.command("process-iqe-cji")
@options(_iqe_cji_process_options)
def _cmd_process_iqe_cji(
    clowd_app_name,
    debug,
    marker,
    filter,
    env,
    image_tag,
    cji_name,
    template_file,
    requirements,
    requirements_priority,
    test_importance,
    plugins,
    local,
    selenium,
    parallel_enabled,
    parallel_worker_count,
    rp_args,
    ibutsu_source,
    custom_env_vars,
):
    """Process IQE ClowdJobInvocation template and print output"""
    cji_config = process_iqe_cji(
        clowd_app_name,
        debug,
        marker,
        filter,
        env,
        image_tag,
        cji_name,
        template_file,
        requirements,
        requirements_priority,
        test_importance,
        plugins,
        local,
        selenium,
        parallel_enabled,
        parallel_worker_count,
        rp_args,
        ibutsu_source,
        custom_env_vars,
    )
    print(json.dumps(cji_config, indent=2))


@main.command("deploy-iqe-cji")
@click.option("--namespace", "-n", help="Namespace to deploy to", type=str, required=True)
@options(_iqe_cji_process_options)
@options(_ns_reserve_options)
@options(_timeout_options)
@click_exception_wrapper("deploy-iqe-cji")
def _cmd_deploy_iqe_cji(
    namespace,
    clowd_app_name,
    debug,
    marker,
    filter,
    env,
    image_tag,
    cji_name,
    template_file,
    timeout,
    requirements,
    requirements_priority,
    test_importance,
    plugins,
    name,
    requester,
    duration,
    local,
    selenium,
    parallel_enabled,
    parallel_worker_count,
    rp_args,
    ibutsu_source,
    custom_env_vars,
    pool,
    force,
    defer_status_errors,
):
    """Process IQE CJI template, apply it, and wait for it to start running."""
    if not has_clowder():
        _error("cluster does not have clowder operator installed")

    namespace, _ = _get_namespace(namespace, name, requester, duration, pool, timeout, local, force)

    cji_config = process_iqe_cji(
        clowd_app_name,
        debug,
        marker,
        filter,
        env,
        image_tag,
        cji_name,
        template_file,
        requirements,
        requirements_priority,
        test_importance,
        plugins,
        local,
        selenium,
        parallel_enabled,
        parallel_worker_count,
        rp_args,
        ibutsu_source,
        custom_env_vars,
    )

    log.debug("processed CJI config:\n%s", cji_config)

    try:
        cji_name = cji_config["items"][0]["metadata"]["name"]
    except (KeyError, IndexError):
        raise Exception("error parsing name of CJI from processed template, check CJI template")

    apply_config(namespace, cji_config)

    log.info("waiting on CJI '%s' for max of %dsec...", cji_name, timeout)
    pod_name = wait_on_cji(namespace, cji_name, timeout, defer_status_errors)
    log.info("pod '%s' related to CJI '%s' in ns '%s' is running", pod_name, cji_name, namespace)
    click.echo(pod_name)


@main.command("version")
def _cmd_version():
    """Print bonfire version"""
    click.echo("bonfire version " + get_version())


@config.command("write-default")
@click.argument("path", required=False, type=str)
def _cmd_write_default_config(path):
    """Write default configuration file to PATH (default: $XDG_CONFIG_HOME/bonfire/config.yaml)"""
    conf.write_default_config(path)


@config.command("edit")
@click.argument("path", required=False, type=str)
def _cmd_edit_default_config(path):
    """Edit configuration with $EDITOR (default path: $XDG_CONFIG_HOME/bonfire/config.yaml)"""
    conf.edit_default_config(path)


@options(_app_source_options)
@click.option(
    "--components/--no-components",
    "list_components",
    default=False,
    help="List components contained within each app group",
)
@apps.command("list")
def _cmd_apps_list(
    source,
    local_config_path,
    local_config_method,
    target_env,
    list_components,
    preferred_params,
):
    """List names of all apps that are marked for deployment in given 'target_env'"""
    apps = _get_apps_config(
        source, target_env, None, None, local_config_path, local_config_method, preferred_params
    )

    print("")
    sorted_keys = sorted(apps.keys())
    for app_name in sorted_keys:
        app_config = apps[app_name]
        print(app_name)
        if list_components:
            component_names = sorted([c["name"] for c in app_config["components"]])
            for component_name in component_names:
                print(f" `-- {component_name}")


@options(_app_source_options)
@click.argument(
    "component",
    type=str,
)
@apps.command("what-depends-on")
def _cmd_apps_what_depends_on(
    source,
    local_config_path,
    local_config_method,
    target_env,
    component,
    preferred_params,
):
    """Show any apps that depend on COMPONENT for deployments in given 'target_env'"""
    apps = _get_apps_config(
        source, target_env, None, None, local_config_path, local_config_method, preferred_params
    )
    found = find_what_depends_on(apps, component)
    print("\n".join(found) or f"no apps depending on {component} found")


def main_with_handler():
    try:
        main()
    except (StatusError, FatalError) as err:
        _error(str(err))


if __name__ == "__main__":
    main_with_handler()

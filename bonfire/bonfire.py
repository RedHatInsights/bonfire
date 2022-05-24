#!/usr/bin/env python3

import json
import logging
import sys
import warnings
from functools import wraps

import click
from ocviapy import apply_config
from tabulate import tabulate
from wait_for import TimedOutError

import bonfire.config as conf
from bonfire.local import get_local_apps
from bonfire.namespaces import (
    Namespace,
    extend_namespace,
    get_namespaces,
    release_reservation,
    reserve_namespace,
)
from bonfire.openshift import (
    check_for_existing_reservation,
    find_clowd_env_for_ns,
    get_reservation,
    has_clowder,
    has_ns_operator,
    wait_for_all_resources,
    wait_for_clowd_env_target_ns,
    wait_for_db_resources,
    wait_on_cji,
    whoami,
)
from bonfire.processor import TemplateProcessor, process_clowd_env, process_iqe_cji
from bonfire.qontract import get_apps_for_env, sub_refs
from bonfire.secrets import import_secrets_from_dir
from bonfire.utils import (
    FatalError,
    check_pypi,
    find_what_depends_on,
    get_version,
    split_equals,
    validate_time_string,
)

log = logging.getLogger(__name__)

APP_SRE_SRC = "appsre"
LOCAL_SRC = "local"
NO_RESERVATION_SYS = "this cluster does not use a namespace reservation system"

_local_option = click.option(
    "--local",
    help="Whether 'oc process' uses --local=true or --local=false (default: true)",
    type=bool,
    default=True,
)


def _error(msg):
    click.echo(f"ERROR: {msg}", err=True)
    sys.exit(1)


def click_exception_wrapper(command):
    def decorator(f):
        @wraps(f)
        def wrapper(*args, **kwargs):
            try:
                return f(*args, **kwargs)
            except KeyboardInterrupt:
                _error(f"{command}: aborted by keyboard interrupt")
            except TimedOutError as err:
                _error(f"{command}: hit timeout error: {err}")
            except FatalError as err:
                _error(f"{command}: hit fatal error: {err}")
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


def _confirm_or_abort(msg):
    if conf.BONFIRE_BOT:
        # these types of warnings shouldn't occur in automated runs, error out immediately
        _error(msg)
    else:
        # have end user confirm if they want to proceed anyway
        msg = f"{msg}.  Continue anyway?"
        if not click.confirm(msg):
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
        "consider re-using the existing namespace"
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


def _wait_on_namespace_resources(namespace, timeout, db_only=False):
    if db_only:
        wait_for_db_resources(namespace, timeout)
    else:
        wait_for_all_resources(namespace, timeout)


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
        type=click.Choice(["default", "minimal"], case_sensitive=False),
        default="default",
        show_default=True,
        help="Specifies the pool type name.",
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


_timeout_option = [
    click.option(
        "--timeout",
        "-t",
        required=True,
        type=int,
        default=600,
        help="timeout in sec (default = 600) to wait for resources to be ready",
    )
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


def _validate_set_image_tag(ctx, param, value):
    try:
        return split_equals(value)
    except ValueError:
        raise click.BadParameter("format must be '<image uri>=<tag>'")


def _validate_opposing_opts(ctx, param, value):
    opposite_option = {
        "remove_resources": "no_remove_resources",
        "no_remove_resources": "remove_resources",
        "remove_dependencies": "no_remove_dependencies",
        "no_remove_dependencies": "remove_dependencies",
    }
    opposite_option_value = ctx.params.get(opposite_option[param.name], "")

    if any([val.startswith("-") for val in value]):
        raise click.BadParameter("requires a component name or keyword 'all'")
    if "all" in value and "all" in opposite_option_value:
        raise click.BadParameter(
            f"'{param.opts[0]}' and its opposite option can't be both set to 'all'"
        )

    # default values
    if param.name == "remove_resources" and not value and not opposite_option_value:
        value = ("all",)
    if param.name == "no_remove_dependencies" and not value and not opposite_option_value:
        value = ("all",)

    return value


_app_source_options = [
    click.option(
        "--source",
        "-s",
        help=f"Configuration source to use when fetching app templates (default: {APP_SRE_SRC})",
        type=click.Choice([APP_SRE_SRC, LOCAL_SRC], case_sensitive=False),
        default=APP_SRE_SRC,
    ),
    click.option(
        "--local-config-path",
        "-c",
        help="File to use for local config (default: $XDG_CONFIG_HOME/bonfire/config.yaml)",
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
]

_process_options = [
    click.argument(
        "app_names",
        required=True,
        nargs=-1,
    ),
    _app_source_options[0],
    _app_source_options[1],
    click.option(
        "--set-image-tag",
        "-i",
        help=("Override image tag for an image using format '<image uri>=<tag>'"),
        multiple=True,
        callback=_validate_set_image_tag,
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
            "Override parameter for a component using format "
            "'<component>/<parameter name>=<value>'"
        ),
        multiple=True,
        callback=_validate_set_parameter,
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
    _app_source_options[2],
    click.option(
        "--ref-env",
        help=f"Query {APP_SRE_SRC} for apps in this environment and substitute 'ref'/'IMAGE_TAG'",
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
            "Remove resource limits and requests on ClowdApp configs "
            "for specific components (default: all)"
        ),
        type=str,
        multiple=True,
        callback=_validate_opposing_opts,
    ),
    click.option(
        "--no-remove-resources",
        help=(
            "Don't remove resource limits and requests on ClowdApp configs "
            "for specific components (default: none)"
        ),
        type=str,
        multiple=True,
        callback=_validate_opposing_opts,
    ),
    click.option(
        "--remove-dependencies",
        help=(
            "Remove dependencies/optionalDependencies on ClowdApp configs "
            "for specific components (default: none)"
        ),
        type=str,
        multiple=True,
        callback=_validate_opposing_opts,
    ),
    click.option(
        "--no-remove-dependencies",
        help=(
            "Don't remove dependencies/optionalDependencies on ClowdApp configs "
            "for specific components (default: all)"
        ),
        type=str,
        multiple=True,
        callback=_validate_opposing_opts,
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
        help="Target namespace of the ClowdEnvironment (default: none)",
        type=str,
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
        help=(f"Name of ClowdEnvironment (default: if target ns provided, {conf.ENV_NAME_FORMAT})"),
        type=str,
        default=None,
    ),
    click.option(
        "--template-file",
        "-f",
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
        "-f",
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
                }
            click.echo(json.dumps(data, indent=2))
        else:
            data = {
                "NAME": [ns.name for ns in namespaces],
                "RESERVED": [str(ns.reserved).lower() for ns in namespaces],
                "ENV STATUS": [str(ns.status).lower() for ns in namespaces],
                "APPS READY": [ns.clowdapps for ns in namespaces],
                "REQUESTER": [ns.requester for ns in namespaces],
                "EXPIRES IN": [ns.expires_in for ns in namespaces],
            }
            tabulated = tabulate(data, headers="keys")
            click.echo(tabulated)


@namespace.command("reserve")
@options(_ns_reserve_options)
@options(_timeout_option)
@click_exception_wrapper("namespace reserve")
def _cmd_namespace_reserve(name, requester, duration, pool, timeout, local):
    """Reserve an ephemeral namespace"""
    log.info("Attempting to reserve a namespace...")
    if not has_ns_operator():
        _error(NO_RESERVATION_SYS)

    if requester is None:
        requester = _get_requester()

    if check_for_existing_reservation(requester):
        _warn_of_existing(requester)

    ns = reserve_namespace(name, requester, duration, pool, timeout, local)

    click.echo(ns.name)


@namespace.command("release")
@click.argument("namespace", required=True, type=str)
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

    if not force:
        _warn_before_delete()
        ns = Namespace(name=namespace)
        if not ns.owned_by_me:
            _warn_if_not_owned_by_me()

    release_reservation(namespace=namespace, local=local)


@namespace.command("extend")
@click.argument("namespace", required=True, type=str)
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

    extend_namespace(namespace, duration, local)


@namespace.command("wait-on-resources")
@click.argument("namespace", required=True, type=str)
@click.option(
    "--db-only",
    is_flag=True,
    default=False,
    help="Only wait for DB resources owned by ClowdApps to be ready",
)
@options(_timeout_option)
def _cmd_namespace_wait_on_resources(namespace, timeout, db_only):
    """Wait for rolled out resources to be ready in namespace"""
    try:
        _wait_on_namespace_resources(namespace, timeout, db_only=db_only)
    except TimedOutError as err:
        log.error("Hit timeout error: %s", err)
        _error("namespace wait timed out")


def _get_apps_config(source, target_env, ref_env, local_config_path):
    config = conf.load_config(local_config_path)

    if source == APP_SRE_SRC:
        log.info("fetching apps config using source: %s, target env: %s", source, target_env)
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
        log.info("fetching apps config using source: %s", source)
        apps_config = get_local_apps(config, fetch_remote=True)

    if ref_env:
        log.info("subbing app template refs/image tags using environment: %s", ref_env)
        apps_config = sub_refs(apps_config, ref_env)

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
    optional_deps_method,
    set_image_tag,
    ref_env,
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
):
    apps_config = _get_apps_config(source, target_env, ref_env, local_config_path)

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
    )
    return processor.process()


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
    set_image_tag,
    ref_env,
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
):
    """Fetch and process application templates"""
    clowd_env = _get_env_name(namespace, clowd_env)

    processed_templates = _process(
        app_names,
        source,
        get_dependencies,
        optional_deps_method,
        set_image_tag,
        ref_env,
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
    )
    print(json.dumps(processed_templates, indent=2))


def _get_namespace(requested_ns_name, name, requester, duration, pool, timeout, local):
    reserved_new_ns = False

    if not has_ns_operator():
        if requested_ns_name:
            ns = Namespace(name=requested_ns_name)
        else:
            _error(f"{NO_RESERVATION_SYS}. Use '-n' to provide a specific target namespace")

    else:
        if requested_ns_name:
            log.debug(
                "checking if namespace '%s' has been reserved via ns operator...", requested_ns_name
            )
            operator_reservation = get_reservation(namespace=requested_ns_name)
            if not operator_reservation:
                _error(f"Namespace '{requested_ns_name}' has not been reserved yet")
            else:
                log.debug("found existing ns operator reservation")

                if operator_reservation.get("status", {}).get("state") == "expired":
                    _error(f"Reservation has expired for namespace '{requested_ns_name}'")

                ns = Namespace(name=requested_ns_name)
                if not ns.owned_by_me:
                    _warn_if_not_owned_by_me()
                if not ns.ready:
                    _warn_if_not_ready()

        else:
            log.debug("checking if requester already has another namespace reserved...")
            requester = requester if requester else _get_requester()
            if check_for_existing_reservation(requester):
                _warn_of_existing(requester)
            ns = reserve_namespace(name, requester, duration, pool, timeout, local)
            reserved_new_ns = True

    return ns.name, reserved_new_ns


@main.command("deploy")
@options(_process_options)
@click.option(
    "--namespace",
    "-n",
    help="Namespace to deploy to (if none given, bonfire will try to reserve one)",
    default=None,
)
@click.option(
    "--import-secrets",
    is_flag=True,
    help="Import secrets from local directory at deploy time",
    default=False,
)
@click.option(
    "--secrets-dir",
    type=str,
    help="Directory to use for secrets import (default: " "$XDG_CONFIG_HOME/bonfire/secrets/)",
    default=conf.DEFAULT_SECRETS_DIR,
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
    optional_deps_method,
    set_image_tag,
    ref_env,
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
    name,
    requester,
    duration,
    timeout,
    no_release_on_fail,
    component_filter,
    import_secrets,
    secrets_dir,
    local,
    frontends,
    pool,
):
    """Process app templates and deploy them to a cluster"""
    if not has_clowder():
        _error("cluster does not have clowder operator installed")

    ns, reserved_new_ns = _get_namespace(namespace, name, requester, duration, pool, timeout, local)

    if import_secrets:
        import_secrets_from_dir(secrets_dir)

    if not clowd_env:
        # if no ClowdEnvironment name provided, see if a ClowdEnvironment is associated with this ns
        match = find_clowd_env_for_ns(ns)
        if not match:
            _error(
                f"could not find a ClowdEnvironment tied to ns '{ns}'.  Specify which one "
                "if you have already deployed one with '--clowd-env' or deploy one with "
                "'bonfire deploy-env'"
            )
        clowd_env = match["metadata"]["name"]
        log.debug("inferred clowd_env: '%s'", clowd_env)

    def _err_handler(err):
        try:
            if not no_release_on_fail and reserved_new_ns:
                # if we auto-reserved this ns, auto-release it on failure unless
                # --no-release-on-fail was requested
                log.info("releasing namespace '%s'", ns)
                release_reservation(namespace=ns)
        finally:
            msg = "deploy failed"
            if str(err):
                msg += f": {str(err)}"
            _error(msg)

    try:
        log.info("processing app templates...")
        apps_config = _process(
            app_names,
            source,
            get_dependencies,
            optional_deps_method,
            set_image_tag,
            ref_env,
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
        )
        log.debug("app configs:\n%s", json.dumps(apps_config, indent=2))
        if not apps_config["items"]:
            log.warning("no configurations found to apply!")
        else:
            log.info("applying app configs...")
            apply_config(ns, apps_config)
            log.info("waiting on resources for max of %dsec...", timeout)
            _wait_on_namespace_resources(ns, timeout)
    except KeyboardInterrupt as err:
        log.error("aborted by keyboard interrupt!")
        _err_handler(err)
    except TimedOutError as err:
        log.error("hit timeout error: %s", err)
        _err_handler(err)
    except FatalError as err:
        log.error("hit fatal error: %s", err)
        _err_handler(err)
    except Exception as err:
        log.exception("hit unexpected error!")
        _err_handler(err)
    else:
        log.info("successfully deployed to namespace '%s'", ns)
        click.echo(ns)


def _process_clowdenv(target_namespace, quay_user, env_name, template_file, local):
    env_name = _get_env_name(target_namespace, env_name)
    return process_clowd_env(target_namespace, quay_user, env_name, template_file, local)


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
    "--secrets-dir",
    type=str,
    help=("Import secrets from this directory (default: " "$XDG_CONFIG_HOME/bonfire/secrets/)"),
    default=conf.DEFAULT_SECRETS_DIR,
)
@options(_ns_reserve_options)
@options(_timeout_option)
@click_exception_wrapper("deploy-env")
def _cmd_deploy_clowdenv(
    namespace,
    quay_user,
    clowd_env,
    template_file,
    timeout,
    import_secrets,
    secrets_dir,
    name,
    requester,
    duration,
    local,
    pool,
):
    """Process ClowdEnv template and deploy to a cluster"""
    if not has_clowder():
        _error("cluster does not have clowder operator installed")

    namespace, _ = _get_namespace(namespace, name, requester, duration, pool, timeout, local)

    if import_secrets:
        import_secrets_from_dir(secrets_dir)

    clowd_env_config = _process_clowdenv(namespace, quay_user, clowd_env, template_file, local)

    log.debug("ClowdEnvironment config:\n%s", clowd_env_config)

    apply_config(None, clowd_env_config)

    if not namespace:
        # wait for Clowder to tell us what target namespace it created
        namespace = wait_for_clowd_env_target_ns(clowd_env)

    log.info("waiting on resources for max of %dsec...", timeout)
    _wait_on_namespace_resources(namespace, timeout)

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
    )
    print(json.dumps(cji_config, indent=2))


@main.command("deploy-iqe-cji")
@click.option("--namespace", "-n", help="Namespace to deploy to", type=str, required=True)
@options(_iqe_cji_process_options)
@options(_ns_reserve_options)
@options(_timeout_option)
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
    pool,
):
    """Process IQE CJI template, apply it, and wait for it to start running."""
    if not has_clowder():
        _error("cluster does not have clowder operator installed")

    namespace, _ = _get_namespace(namespace, name, requester, duration, pool, timeout, local)

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
    )

    log.debug("processed CJI config:\n%s", cji_config)

    try:
        cji_name = cji_config["items"][0]["metadata"]["name"]
    except (KeyError, IndexError):
        raise Exception("error parsing name of CJI from processed template, check CJI template")

    apply_config(namespace, cji_config)

    log.info("waiting on CJI '%s' for max of %dsec...", cji_name, timeout)
    pod_name = wait_on_cji(namespace, cji_name, timeout)
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
    target_env,
    list_components,
):
    """List names of all apps that are marked for deployment in given 'target_env'"""
    apps = _get_apps_config(source, target_env, None, local_config_path)

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
    target_env,
    component,
):
    """Show any apps that depend on COMPONENT for deployments in given 'target_env'"""
    apps = _get_apps_config(source, target_env, None, local_config_path)
    found = find_what_depends_on(apps, component)
    print("\n".join(found) or f"no apps depending on {component} found")


def main_with_handler():
    try:
        main()
    except FatalError as err:
        _error(str(err))


if __name__ == "__main__":
    main_with_handler()

import functools
import json
import logging
import threading
import time

import sh
from sh import ErrorReturnCode, TimeoutException
from subprocess import PIPE
from subprocess import Popen

from ocviapy import export
from wait_for import wait_for, TimedOutError

import bonfire.config as conf

log = logging.getLogger(__name__)

# Resource types and their cli shortcuts
# Mostly listed here: https://docs.openshift.com/online/cli_reference/basic_cli_operations.html
SHORTCUTS = {
    "build": None,
    "buildconfig": "bc",
    "daemonset": "ds",
    "deployment": "deploy",
    "deploymentconfig": "dc",
    "event": "ev",
    "imagestream": "is",
    "imagestreamtag": "istag",
    "imagestreamimage": "isimage",
    "job": None,
    "limitrange": "limits",
    "namespace": "ns",
    "node": "no",
    "pod": "po",
    "project": "project",
    "resourcequota": "quota",
    "replicationcontroller": "rc",
    "secrets": "secret",
    "service": "svc",
    "serviceaccount": "sa",
    "statefulset": "sts",
    "persistentvolume": "pv",
    "persistentvolumeclaim": "pvc",
    "configmap": "cm",
    "replicaset": "rs",
    "route": None,
    "clowdenvironment": None,
    "clowdapp": None,
}


def parse_restype(string):
    """
    Given a resource type or its shortcut, return the full resource type name.
    """
    string_lower = string.lower()
    if string_lower in SHORTCUTS:
        return string_lower

    for resource_name, shortcut in SHORTCUTS.items():
        if string_lower == shortcut:
            return resource_name

    raise ValueError("Unknown resource type: {}".format(string))


def _only_immutable_errors(err_lines):
    return all("field is immutable after creation" in line.lower() for line in err_lines)


def _conflicts_found(err_lines):
    return any("error from server (conflict)" in line.lower() for line in err_lines)


def _get_logging_args(args, kwargs):
    # Format the cmd args/kwargs for log printing before the command is run
    cmd_args = " ".join([str(arg) for arg in args if arg is not None])

    cmd_kwargs = []
    for key, val in kwargs.items():
        if key.startswith("_"):
            continue
        if len(key) > 1:
            cmd_kwargs.append("--{} {}".format(key, val))
        else:
            cmd_kwargs.append("-{} {}".format(key, val))
    cmd_kwargs = " ".join(cmd_kwargs)

    return cmd_args, cmd_kwargs


def _exec_oc(*args, **kwargs):
    _silent = kwargs.pop("_silent", False)
    _hide_output = kwargs.pop("_hide_output", False)
    _ignore_immutable = kwargs.pop("_ignore_immutable", True)
    _retry_conflicts = kwargs.pop("_retry_conflicts", True)
    _stdout_log_prefix = kwargs.pop("_stdout_log_prefix", " |stdout| ")
    _stderr_log_prefix = kwargs.pop("_stderr_log_prefix", " |stderr| ")

    kwargs["_bg"] = True
    kwargs["_bg_exc"] = False

    err_lines = []
    out_lines = []

    def _err_line_handler(line, _, process):
        threading.current_thread().name = f"pid-{process.pid}"
        log.info("%s%s", _stderr_log_prefix, line.rstrip())
        err_lines.append(line)

    def _out_line_handler(line, _, process):
        threading.current_thread().name = f"pid-{process.pid}"
        if not _silent and not _hide_output:
            log.info("%s%s", _stdout_log_prefix, line.rstrip())
        out_lines.append(line)

    retries = 3
    last_err = None
    for count in range(1, retries + 1):
        cmd = sh.oc(*args, **kwargs, _tee=True, _out=_out_line_handler, _err=_err_line_handler)
        if not _silent:
            cmd_args, cmd_kwargs = _get_logging_args(args, kwargs)
            log.info("running (pid %d): oc %s %s", cmd.pid, cmd_args, cmd_kwargs)
        try:
            return cmd.wait()
        except ErrorReturnCode as err:
            # Sometimes stdout/stderr is empty in the exception even though we appended
            # data in the callback. Perhaps buffers are not being flushed ... so just
            # set the out lines/err lines we captured on the Exception before re-raising it by
            # re-init'ing the err and causing it to rebuild its message template.
            #
            # see https://github.com/amoffat/sh/blob/master/sh.py#L381
            err.__init__(
                full_cmd=err.full_cmd,
                stdout="\n".join(out_lines).encode(),
                stderr="\n".join(err_lines).encode(),
                truncate=err.truncate,
            )

            # Make these plain strings for easier exception handling
            err.stdout = "\n".join(out_lines)
            err.stderr = "\n".join(err_lines)

            last_err = err
            # Ignore warnings that are printed to stderr in our error analysis
            err_lines = [line for line in err_lines if not line.lstrip().startswith("Warning:")]

            # Check if these are errors we should handle
            if _ignore_immutable and _only_immutable_errors(err_lines):
                log.warning("Ignoring immutable field errors")
                break
            elif _retry_conflicts and _conflicts_found(err_lines):
                log.warning(
                    "Hit resource conflict, retrying in 1 sec (attempt %d/%d)",
                    count,
                    retries,
                )
                time.sleep(1)
                continue

            # Bail if not
            raise last_err
    else:
        log.error("Retried %d times, giving up", retries)
        raise last_err


def oc(*args, **kwargs):
    """
    Run 'sh.oc' and print the command, show output, catch errors, etc.

    Optional kwargs:
        _ignore_errors: if ErrorReturnCode is hit, don't re-raise it (default False)
        _silent: don't print command or resulting stdout (default False)
        _ignore_immutable: ignore errors related to immutable objects (default True)
        _retry_conflicts: retry commands if a conflict error is hit
        _stdout_log_prefix: prefix this string to stdout log output (default " |stdout| ")
        _stderr_log_prefix: prefix this string to stderr log output (default " |stderr| ")

    Returns:
        None if cmd fails and _exit_on_err is False
        command output (str) if command succeeds
    """
    _ignore_errors = kwargs.pop("_ignore_errors", False)
    # The _silent/_ignore_immutable/_retry_conflicts kwargs are passed on so don't pop them yet

    try:
        return _exec_oc(*args, **kwargs)
    except ErrorReturnCode:
        if not _ignore_errors:
            raise
        else:
            if not kwargs.get("_silent"):
                log.warning("Non-zero return code ignored")


def oc_login():
    if conf.OC_LOGIN_TOKEN and conf.OC_LOGIN_SERVER:
        # use _silent so token is not logged
        oc(
            "login",
            token=conf.OC_LOGIN_TOKEN,
            server=conf.OC_LOGIN_SERVER,
            _silent=True,
        )
    # run 'oc project' so we see what server we're logged into
    oc("project")


# we will assume that 'oc whoami' will not change during execution of a single 'bonfire' command
@functools.lru_cache(maxsize=None, typed=False)
def whoami():
    name = oc("whoami", _silent=True).strip()
    # a valid label must be an empty string or consist of alphanumeric characters,
    # '-', '_' or '.', and must start and end with an alphanumeric character, so let's just sanitize
    # the name at this point
    return name.replace("@", "_at_").replace(":", "_")


def apply_config(namespace, list_resource):
    """
    Apply a k8s List of items to a namespace
    """
    oc("apply", "-f", "-", "-n", namespace, _in=json.dumps(list_resource))


def get_json(restype, name=None, label=None, namespace=None):
    """
    Run 'oc get' for a given resource type/name/label and return the json output.

    If name is None all resources of this type are returned

    If label is not provided, then "oc get" will not be filtered on label
    """
    restype = parse_restype(restype)

    args = ["get", restype]
    if name:
        args.append(name)
    if label:
        args.extend(["-l", label])
    if namespace:
        args.extend(["-n", namespace])
    try:
        output = oc(*args, o="json", _silent=True)
    except ErrorReturnCode as err:
        if "NotFound" in err.stderr:
            return {}
        raise

    try:
        parsed_json = json.loads(str(output))
    except ValueError:
        return {}

    return parsed_json


def get_routes(namespace):
    """
    Get all routes in the project.

    Return dict with key of service name, value of http route
    """
    data = get_json("route", namespace=namespace)
    ret = {}
    for route in data.get("items", []):
        ret[route["metadata"]["name"]] = route["spec"]["host"]
    return ret


class StatusError(Exception):
    pass


_CHECKABLE_RESOURCES = ["deploymentconfig", "deployment", "statefulset", "daemonset"]


def _check_status_for_restype(restype, json_data):
    """
    Depending on the resource type, check that it is "ready" or "complete"

    Uses the status json from an 'oc get'

    Returns True if ready, False if not.
    """
    restype = parse_restype(restype)

    if restype != "pod" and restype not in _CHECKABLE_RESOURCES:
        raise ValueError(f"Checking status for resource type {restype} currently not supported")

    try:
        status = json_data["status"]
    except KeyError:
        status = None

    if not status:
        return False

    if restype == "deploymentconfig" or restype == "deployment":
        spec_replicas = json_data["spec"]["replicas"]
        available_replicas = status.get("availableReplicas", 0)
        updated_replicas = status.get("updatedReplicas", 0)
        unavailable_replicas = status.get("unavailableReplicas", 1)
        if unavailable_replicas == 0:
            if available_replicas == spec_replicas and updated_replicas == spec_replicas:
                return True

    elif restype == "statefulset":
        spec_replicas = json_data["spec"]["replicas"]
        ready_replicas = status.get("readyReplicas", 0)
        return ready_replicas == spec_replicas

    elif restype == "daemonset":
        desired = status.get("desiredNumberScheduled", 1)
        available = status.get("numberAvailable")
        return desired == available

    elif restype == "pod":
        if status.get("phase").lower() == "running":
            return True


def _wait_with_periodic_status_check(namespace, timeout, key, restype, name):
    """Check if resource is ready using _check_status_for_restype, periodically log an update."""
    time_last_logged = time.time()
    time_remaining = timeout

    def _ready():
        nonlocal time_last_logged, time_remaining

        j = get_json(restype, name, namespace=namespace)
        if _check_status_for_restype(restype, j):
            return True

        if time.time() > time_last_logged + 60:
            time_remaining -= 60
            if time_remaining:
                log.info("[%s] waiting %dsec longer", key, time_remaining)
                time_last_logged = time.time()
        return False

    wait_for(
        _ready,
        timeout=timeout,
        delay=5,
        message="wait for '{}' to be ready".format(key),
    )


def wait_for_ready(namespace, restype, name, timeout=300, _result_dict=None):
    """
    Wait {timeout} for resource to be complete/ready/active.

    Args:
        restype: type of resource, which can be "build", "dc", "deploymentconfig"
        name: name of resource
        timeout: time in secs to wait for resource to become ready

    Returns:
        True if ready,
        False if timed out

    '_result_dict' can be passed when running this in a threaded fashion
    to store the result of this wait as:
        _result_dict[resource_name] = True or False
    """
    restype = parse_restype(restype)
    key = "{}/{}".format(SHORTCUTS.get(restype) or restype, name)

    if _result_dict is None:
        _result_dict = dict()
    _result_dict[key] = False

    log.info("[%s] waiting up to %dsec for resource to be ready", key, timeout)

    try:
        # Do not use rollout status for statefulset/daemonset yet until we can handle
        # https://github.com/kubernetes/kubernetes/issues/64500
        if restype in ["deployment", "deploymentconfig"]:
            # use oc rollout status for the applicable resource types
            oc(
                "rollout",
                "status",
                key,
                namespace=namespace,
                _timeout=timeout,
                _stdout_log_prefix=f"[{key}] ",
                _stderr_log_prefix=f"[{key}]  ",
            )
        else:
            _wait_with_periodic_status_check(namespace, timeout, key, restype, name)

        log.info("[%s] is ready!", key)
        _result_dict[key] = True
        return True
    except (StatusError, ErrorReturnCode) as err:
        log.error("[%s] hit error waiting for resource to be ready: %s", key, str(err))
    except (TimeoutException, TimedOutError):
        log.error("[%s] timed out waiting for resource to be ready", key)
    return False


def wait_for_ready_threaded(namespace, restype_name_list, timeout=300):
    """
    Wait for multiple delpoyments in a threaded fashion.

    Args:
        restype_name_list: list of tuples with (resource_type, resource_name,)
        timeout: timeout for each thread

    Returns:
        True if all deployments are ready
        False if any failed
    """
    result_dict = dict()
    threads = [
        threading.Thread(
            target=wait_for_ready, args=(namespace, restype, name, timeout, result_dict)
        )
        for restype, name in restype_name_list
    ]
    for thread in threads:
        thread.daemon = True
        thread.name = thread.name.lower()  # because I'm picky
        thread.start()
    for thread in threads:
        thread.join()

    failed = [key for key, result in result_dict.items() if not result]

    if failed:
        log.info("Some resources failed to become ready: %s", ", ".join(failed))
        return False
    return True


def _wait_for_resources(namespace, timeout, skip=None):
    skip = skip or []
    wait_for_list = []
    for restype in _CHECKABLE_RESOURCES:
        resources = get_json(restype, namespace=namespace)
        for item in resources["items"]:
            entry = (restype, item["metadata"]["name"])
            if entry not in skip:
                wait_for_list.append((restype, item["metadata"]["name"]))

    result = wait_for_ready_threaded(namespace, wait_for_list, timeout=timeout)
    return result, wait_for_list


def _operator_resource_present(namespace, owner_kind):
    response = get_json("deployment", namespace=namespace)
    for item in response.get("items", []):
        if item.get("metadata", {}).get("ownerReferences"):
            if item["metadata"]["ownerReferences"][0]["kind"] == owner_kind:
                return True
    return False


def _operator_resources(namespace, timeout, wait_on_app=True):
    log.info("Waiting for resources owned by 'ClowdEnvironment' to appear")
    wait_for(
        _operator_resource_present,
        func_args=(namespace, "ClowdEnvironment"),
        message="wait for ClowdEnvironment-owned resources to appear",
        timeout=timeout,
    )
    # now wait for everything in ns to be 'ready'
    result, already_waited_on = _wait_for_resources(namespace, timeout)

    # the first wait failed, so just return 'False' now
    if not result:
        return result

    if wait_on_app:
        log.info("Waiting for resources owned by 'ClowdApp' to appear")
        wait_for(
            _operator_resource_present,
            func_args=(namespace, "ClowdApp"),
            message="wait for ClowdApp-owned resources to appear",
            timeout=timeout,
        )
        # now that ClowdApp resources showed up, again wait for everything new in ns to be 'ready'
        result, _ = _wait_for_resources(namespace, timeout, already_waited_on)

    return result


def wait_for_all_resources(namespace, timeout=300, wait_on_app=True):
    # wrap the other wait_fors in 1 wait_for so overall timeout is honored
    # wait_for returns a tuple of the return code and the time taken
    if len(get_json("clowdapp", namespace=namespace).get("items", [])) == 0:
        # only wait on ClowdApp if one was deployed
        wait_on_app = False

    return_val, time_taken = wait_for(
        _operator_resources,
        func_args=(namespace, timeout, wait_on_app),
        message="wait for all deployed resources to be ready",
        timeout=timeout,
    )
    return time_taken


def copy_namespace_secrets(src_namespace, dst_namespace, secret_names):
    for secret_name in secret_names:
        log.info(
            "copying secret '%s' from namespace '%s' to namespace '%s'",
            secret_name,
            src_namespace,
            dst_namespace,
        )
        secret_data = export("secret", secret_name, namespace=src_namespace)
        oc(
            "apply",
            f="-",
            n=dst_namespace,
            _in=json.dumps(secret_data),
            _silent=True,
        )


def process_template(template_data, params):
    valid_pnames = set(p["name"] for p in template_data.get("parameters", []))
    param_str = " ".join(f"-p {k}='{v}'" for k, v in params.items() if k in valid_pnames)

    proc = Popen(
        f"oc process --local --ignore-unknown-parameters -o json -f - {param_str}",
        shell=True,
        stdin=PIPE,
        stdout=PIPE,
    )
    stdout, stderr = proc.communicate(json.dumps(template_data).encode("utf-8"))
    return json.loads(stdout.decode("utf-8"))

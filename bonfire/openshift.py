import functools
import json
import logging
import re
import threading
import time

import sh
from sh import ErrorReturnCode, TimeoutException
from subprocess import PIPE
from subprocess import Popen

from ocviapy import export
from wait_for import wait_for, TimedOutError

log = logging.getLogger(__name__)


# assume that the result of this will not change during execution of our app
@functools.lru_cache(maxsize=None, typed=False)
def get_api_resources():
    output = oc("api-resources", verbs="list", _silent=True).strip()
    if not output:
        return []

    lines = output.split("\n")
    # lines[0] is the table header, use it to figure out length of each column
    groups = re.findall(r"(\w+\s+)", lines[0])

    name_start = 0
    name_end = len(groups[0])
    shortnames_start = name_end
    shortnames_end = name_end + len(groups[1])
    apigroup_start = shortnames_end
    apigroup_end = shortnames_end + len(groups[2])
    namespaced_start = apigroup_end
    namespaced_end = apigroup_end + len(groups[3])
    kind_start = namespaced_end

    resources = []
    for line in lines[1:]:
        shortnames = line[shortnames_start:shortnames_end].strip()
        resource = {
            "name": line[name_start:name_end].strip().rstrip("s") or None,
            "shortnames": shortnames.split(",") if shortnames else [],
            "apigroup": line[apigroup_start:apigroup_end].strip() or None,
            "namespaced": line[namespaced_start:namespaced_end].strip() == "true",
            "kind": line[kind_start:].strip() or None,
        }
        resources.append(resource)
    return resources


def parse_restype(string):
    """
    Given a resource type or its shortcut, return the full resource type name.
    """
    s = string.lower()
    for r in get_api_resources():
        if s in r["shortnames"] or s == r["name"]:
            return r["name"]

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
        if not _silent:
            log.info("%s%s", _stderr_log_prefix, line.rstrip())
        err_lines.append(line)

    def _out_line_handler(line, _, process):
        threading.current_thread().name = f"pid-{process.pid}"
        if not _silent:
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


# we will assume that 'oc whoami' will not change during execution
@functools.lru_cache(maxsize=None, typed=False)
def whoami():
    name = oc("whoami", _silent=True).strip()
    # a valid label must be an empty string or consist of alphanumeric characters,
    # '-', '_' or '.', and must start and end with an alphanumeric character, so let's just sanitize
    # the name at this point
    return name.replace("@", "_at_").replace(":", "_")


def apply_config(namespace, list_resource):
    """
    Apply a k8s List of items
    """
    if namespace is None:
        oc("apply", "-f", "-", _in=json.dumps(list_resource))
    else:
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


# resources we are able to parse the status of
_CHECKABLE_RESOURCES = [
    "deploymentconfig",
    "deployment",
    "statefulset",
    "daemonset",
    "clowdapp",
    "clowdenvironment",
    "clowdjobinvocation",
    "kafka",
    "kafkaconnect",
    "pod",
    "cyndipipeline",
    "xjoinpipeline",
]


def _is_checkable(kind):
    return kind.lower() in _CHECKABLE_RESOURCES


def _available_checkable_resources(namespaced=False):
    """Returns resources we are able to parse status of that are present on the cluster."""
    if namespaced:
        return [
            r["kind"].lower()
            for r in get_api_resources()
            if _is_checkable(r["kind"]) and r["namespaced"]
        ]

    return [r["kind"].lower() for r in get_api_resources() if _is_checkable(r["kind"])]


def _resources_for_ns_wait():
    """Only check "higher level" resource types when waiting on a namespace"""
    resources = _available_checkable_resources(namespaced=True)
    try:
        resources.remove("pod")
    except ValueError as err:
        if "not in list" in str(err):
            pass
        else:
            raise
    return resources


def _get_name_for_kind(kind):
    for r in get_api_resources():
        if r["kind"].lower() == kind.lower():
            return r["name"]
    raise ValueError(f"unable to find resource name for kind '{kind}'")


def _check_status_condition(status, expected_type, expected_value):
    conditions = status.get("conditions", [])
    expected_type = str(expected_type).lower()
    expected_value = str(expected_value).lower()

    for c in conditions:
        status_value = str(c.get("status")).lower()
        status_type = str(c.get("type")).lower()
        if status_value == expected_value and status_type == expected_type:
            return True
    return False


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

    generation = json_data["metadata"].get("generation")
    status_generation = status.get("observedGeneration") or status.get("generation")
    if generation and status_generation and generation != status_generation:
        return False

    if restype == "deploymentconfig" or restype == "deployment":
        spec_replicas = json_data["spec"]["replicas"]
        available_replicas = status.get("availableReplicas", 0)
        updated_replicas = status.get("updatedReplicas", 0)
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

    elif restype in ("clowdenvironment", "clowdapp"):
        return _check_status_condition(
            status, "DeploymentsReady", "true"
        ) and _check_status_condition(status, "ReconciliationSuccessful", "true")

    elif restype == "clowdjobinvocation":
        return _check_status_condition(
            status, "JobInvocationComplete", "true"
        ) and _check_status_condition(status, "ReconciliationSuccessful", "true")

    elif restype in ("kafka", "kafkaconnect"):
        return _check_status_condition(status, "ready", "true")

    elif restype == "cyndipipeline":
        return _check_status_condition(status, "valid", "true") and status.get("activeTableName")

    elif restype == "xjoinpipeline":
        return _check_status_condition(status, "valid", "true") and status.get("activeIndexName")


def _get_resource_info(item):
    kind = item["kind"].lower()
    restype = _get_name_for_kind(kind)
    name = item["metadata"]["name"]
    key = f"{restype}/{name}"
    return kind, restype, name, key


class ResourceWaiter:
    def __init__(self, namespace, restype, name):
        self.namespace = namespace
        self.restype = parse_restype(restype)
        self.name = name.lower()
        self.observed_resources = dict()
        self._uid = None
        self.key = f"{self.restype}/{self.name}"
        self._time_last_logged = None
        self._time_remaining = None

        if self.restype not in _available_checkable_resources():
            raise ValueError(
                f"unable to check status of '{self.restype}' resources on this cluster"
            )

    def _observe(self, item):
        _, restype, _, key = _get_resource_info(item)
        if key not in self.observed_resources:
            self.observed_resources[key] = {"ready": False}
        if not self.observed_resources[key]["ready"]:
            if _check_status_for_restype(restype, item):
                log.info("[%s] resource is ready!", key)
                self.observed_resources[key]["ready"] = True

    def check_ready(self):
        response = get_json(self.restype, name=self.name, namespace=self.namespace)
        if response:
            self._uid = response["metadata"]["uid"]
            self._observe(response)
            return all([r["ready"] is True for _, r in self.observed_resources.items()])
        return False

    def _check_with_periodic_log(self):
        if self.check_ready():
            return True

        if time.time() > self._time_last_logged + 60:
            self._time_remaining -= 60
            if self._time_remaining:
                log.info("[%s] waiting %dsec longer", self.key, self._time_remaining)
                self._time_last_logged = time.time()
        return False

    def wait_for_ready(self, timeout, reraise=False):
        self._time_last_logged = time.time()
        self._time_remaining = timeout

        try:
            # check for ready initially, only wait_for if we need to
            log.debug("[%s] checking if 'ready'", self.key)
            if not self.check_ready():
                log.info("[%s] waiting up to %dsec for resource to be 'ready'", self.key, timeout)
                wait_for(
                    self._check_with_periodic_log,
                    message=f"wait for {self.key} to be 'ready'",
                    delay=5,
                    timeout=timeout,
                )
            return True
        except (StatusError, ErrorReturnCode) as err:
            log.error("[%s] hit error waiting for resource to be ready: %s", self.key, str(err))
            if reraise:
                raise
        except (TimeoutException, TimedOutError):
            log.error("[%s] timed out waiting for resource to be ready", self.key)
            if reraise:
                raise
        return False


class ResourceOwnerWaiter(ResourceWaiter):
    def _update_observed_resources(self, item):
        for owner_ref in item["metadata"].get("ownerReferences", []):
            restype_matches = owner_ref["kind"].lower() == self.restype
            owner_uid_matches = owner_ref["uid"] == self._uid
            if restype_matches and owner_uid_matches:
                _, restype, _, resource_key = _get_resource_info(item)
                if resource_key not in self.observed_resources:
                    self.observed_resources[resource_key] = {"ready": False}
                    log.info(
                        "[%s] found owned resource %s",
                        self.key,
                        resource_key,
                    )

                # check if ready state has transitioned for this resource
                if not self.observed_resources[resource_key]["ready"]:
                    if _check_status_for_restype(restype, item):
                        log.info("[%s] owned resource %s is ready!", self.key, resource_key)
                        self.observed_resources[resource_key]["ready"] = True

    def _observe(self, item):
        super()._observe(item)
        for restype in _available_checkable_resources():
            response = get_json(restype, namespace=self.namespace)
            for item in response.get("items", []):
                self._update_observed_resources(item)


def wait_for_ready(namespace, restype, name, timeout=600):
    waiter = ResourceWaiter(namespace, restype, name)
    return waiter.wait_for_ready(timeout)


def wait_for_ready_threaded(waiters, timeout=600):
    threads = [
        threading.Thread(target=waiter.wait_for_ready, daemon=True, args=(timeout,))
        for waiter in waiters
    ]
    for thread in threads:
        thread.name = thread.name.lower()
        thread.start()
    for thread in threads:
        thread.join()

    all_failed_resources = set()
    for waiter in waiters:
        waiter_failed_resources = [
            key for key, val in waiter.observed_resources.items() if val["ready"] is False
        ]
        for failed_resource in waiter_failed_resources:
            all_failed_resources.add(failed_resource)

    if all_failed_resources:
        log.info("some resources failed to become ready: %s", ", ".join(all_failed_resources))
        return False
    return True


def _all_resources_ready(namespace, timeout):
    already_waited_on = set()

    # wait on ClowdEnvironment, if there's one using this ns as its targetNamespace
    start = time.time()

    clowd_env = find_clowd_env_for_ns(namespace)
    if clowd_env:
        waiter = ResourceOwnerWaiter(namespace, "clowdenvironment", clowd_env["metadata"]["name"])
        if not waiter.wait_for_ready(timeout):
            return False

        for key in waiter.observed_resources:
            already_waited_on.add(key)

    end = time.time()
    elapsed = end - start
    timeout = int(timeout - elapsed)

    # wait on all ClowdApps in this namespace
    start = time.time()

    waiters = []
    clowdapps = get_json("clowdapp", namespace=namespace)
    for clowdapp in clowdapps["items"]:
        waiter = ResourceOwnerWaiter(namespace, "clowdapp", clowdapp["metadata"]["name"])
        waiters.append(waiter)
    if not wait_for_ready_threaded(waiters, timeout):
        return False

    for waiter in waiters:
        for key in waiter.observed_resources:
            already_waited_on.add(key)

    end = time.time()
    elapsed = end - start
    timeout = int(timeout - elapsed)

    # wait on anything else not covered by the above
    waiters = []
    for restype in _resources_for_ns_wait():
        response = get_json(restype, namespace=namespace)
        for item in response.get("items", []):
            _, restype, name, resource_key = _get_resource_info(item)
            if resource_key not in already_waited_on:
                waiter = ResourceWaiter(namespace, restype, name)
                waiters.append(waiter)

    return wait_for_ready_threaded(waiters, timeout)


def wait_for_all_resources(namespace, timeout=600):
    # wrap the other wait_fors in 1 wait_for so overall timeout is honored
    # wait_for returns a tuple of the return code and the time taken
    wait_for(
        _all_resources_ready,
        func_args=(namespace, timeout),
        message="wait for all deployed resources to be ready",
        timeout=timeout,
    )


def wait_for_db_resources(namespace, timeout=600):
    clowdapps = get_json("clowdapp", namespace=namespace).get("items", [])
    if len(clowdapps) == 0:
        raise ValueError(f"no clowdapps found in ns '{namespace}', no DB's to wait for")

    waiters = []
    for clowdapp in clowdapps:
        clowdapp_name = clowdapp["metadata"]["name"]
        db_name = clowdapp["spec"].get("database", {}).get("name")
        if db_name:
            waiters.append(ResourceWaiter(namespace, "deployment", f"{clowdapp_name}-db"))
        shared_db_app_name = clowdapp["spec"].get("database", {}).get("sharedDbAppName")
        if shared_db_app_name:
            waiters.append(ResourceWaiter(namespace, "deployment", f"{shared_db_app_name}-db"))

    if not waiters:
        raise ValueError(
            f"no clowdapps with db configurations found in '{namespace}', no DB's to wait for"
        )

    wait_for_ready_threaded(waiters, timeout)


def copy_namespace_secrets(src_namespace, dst_namespace, secret_names):
    for secret_name in secret_names:
        secret_data = export("secret", secret_name, namespace=src_namespace)
        ignore = secret_data["metadata"].get("annotations", {}).get("bonfire.ignore")
        if str(ignore).lower() == "true":
            log.debug(
                "secret '%s' in namespace '%s' has bonfire.ignore==true, skipping",
                secret_name,
                src_namespace,
            )
            continue

        log.info(
            "copying secret '%s' from namespace '%s' to namespace '%s'",
            secret_name,
            src_namespace,
            dst_namespace,
        )
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


def find_clowd_env_for_ns(ns):
    try:
        clowd_envs = get_json("clowdenvironment")
    except ErrorReturnCode as err:
        log.debug("hit error running 'oc get clowdenvironment': %s", err)
        clowd_envs = {"items": []}

    for clowd_env in clowd_envs["items"]:
        target_ns = clowd_env["spec"].get("targetNamespace")
        # in case target ns was not defined in the spec, check the env's status...
        target_ns = target_ns or clowd_env.get("status", {}).get("targetNamespace")
        if target_ns == ns:
            return clowd_env


def get_clowd_env_target_ns(clowd_env_name):
    try:
        clowd_env = get_json("clowdenvironment", clowd_env_name)
    except ErrorReturnCode as err:
        log.debug("hit error running 'oc get clowdenvironment %s': %s", clowd_env_name, err)
        return None

    return clowd_env.get("status", {}).get("targetNamespace")


def wait_for_clowd_env_target_ns(clowd_env_name):
    log.info("waiting for Clowder to provision target namespace for env '%s'", clowd_env_name)
    return wait_for(
        get_clowd_env_target_ns,
        func_args=(clowd_env_name,),
        fail_condition=None,
        num_sec=60,
        message="wait for Clowder to provision target namespace",
    ).out


# assume that the result of this will not change during execution of a single 'bonfire' command
@functools.lru_cache(maxsize=None, typed=False)
def on_k8s():
    """Detect whether this is a k8s or openshift cluster based on existence of projects."""
    project_resource = [r for r in get_api_resources() if r["name"] == "project"]

    if project_resource:
        return False
    return True


def get_all_namespaces():
    if not on_k8s():
        all_namespaces = get_json("project")["items"]
    else:
        all_namespaces = get_json("namespace")["items"]

    return all_namespaces


def wait_on_cji(namespace, cji_name, timeout):
    # first wait for job associated with this CJI to appear
    log.info("waiting for Job to appear owned by CJI '%s'", cji_name)

    def _find_job():
        jobs = get_json("job", label=f"clowdjob={cji_name}", namespace=namespace)
        try:
            return jobs["items"][0]["metadata"]["name"]
        except (KeyError, IndexError):
            return False

    job_name, elapsed = wait_for(
        _find_job, num_sec=timeout, message=f"wait for Job to appear owned by CJI '{cji_name}'"
    )

    log.info(
        "found Job '%s' created by CJI '%s', now waiting for pod to appear", job_name, cji_name
    )

    def _pod_found():
        pods = get_json("pod", label=f"job-name={job_name}", namespace=namespace)
        try:
            return pods["items"][0]["metadata"]["name"]
        except (KeyError, IndexError):
            return False

    remaining_time = timeout - elapsed

    pod_name, elapsed = wait_for(
        _pod_found,
        num_sec=remaining_time,
        message=f"wait for Pod to appear owned by CJI '{cji_name}'",
    )

    log.info(
        "found pod '%s' associated with CJI '%s', now waiting for pod to be 'running'",
        pod_name,
        cji_name,
    )

    remaining_time = remaining_time - elapsed

    waiter = ResourceWaiter(namespace, "pod", pod_name)
    waiter.wait_for_ready(remaining_time, reraise=True)

    return pod_name


def wait_on_reservation(res_name, timeout):
    log.info("waiting for reservation '%s' to get picked up by operator", res_name)

    def _find_reservation():
        res = get_json("reservation", name=res_name)
        try:
            return res["status"]["namespace"]
        except (KeyError, IndexError):
            return False

    ns_name, elapsed = wait_for(
        _find_reservation,
        num_sec=timeout,
        message=f"waiting for namespace to be allocated to reservation '{res_name}'",
    )
    return ns_name


def check_for_existing_reservation(requester):
    if on_k8s():
        return False

    log.info("Checking for existing reservations for '%s'", requester)

    all_res = get_json("reservation")

    for res in all_res["items"]:
        if res["spec"]["requester"] == requester:
            return True

    return False


def get_reservation(name=None, namespace=None, requester=None):
    if on_k8s():
        return False

    if name:
        res = get_json("reservation", name=name)
        return res if res else False
    elif namespace:
        all_res = get_json("reservation")
        for res in all_res["items"]:
            if res["status"]["namespace"] == namespace:
                return res
    elif requester:
        all_res = get_json("reservation", label=f"requester={requester}")
        numRes = len(all_res["items"])
        if numRes == 0:
            return False
        elif numRes == 1:
            return all_res["items"][0]
        else:
            log.info("Multiple reservations found for requester '%s'. Aborting.", requester)
            return False

    return False

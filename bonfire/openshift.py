import functools
import logging
import time

from ocviapy import (
    Resource,
    ResourceWaiter,
    ResourceWatcher,
    available_checkable_resources,
    get_api_resources,
    get_json,
    oc,
    wait_for_ready_threaded,
    on_k8s,
    get_all_namespaces,
)
from sh import ErrorReturnCode
from wait_for import TimedOutError, wait_for

log = logging.getLogger(__name__)


@functools.lru_cache(maxsize=None, typed=False)
def has_ns_operator():
    for res in get_api_resources():
        name = res["name"]
        apigroup = res["apigroup"].split("/")[0]
        if name == "namespacereservation" and apigroup == "cloud.redhat.com":
            return True
    return False


@functools.lru_cache(maxsize=None, typed=False)
def get_console_url():
    if on_k8s():
        return None
    else:
        try:
            cfg_map = get_json("configmap", "console-public", namespace="openshift-config-managed")
            url = cfg_map["data"]["consoleURL"]
        except Exception as err:
            log.debug("unable to obtain console url: %s: %s", err.__class__.__name__, err)
            return None
        return url


@functools.lru_cache(maxsize=None, typed=False)
def get_namespace_pools():
    namespace_pools = get_json("namespacepool")
    return [pool["metadata"]["name"] for pool in namespace_pools.get("items", [])]


def has_clowder():
    for res in get_api_resources():
        name = res["name"]
        apigroup = res["apigroup"].split("/")[0]
        if name == "clowdapp" and apigroup == "cloud.redhat.com":
            return True
    return False


# we will assume that 'oc whoami' will not change during execution
@functools.lru_cache(maxsize=None, typed=False)
def whoami():
    name = oc("whoami", _silent=True).strip()
    # a valid label must be an empty string or consist of alphanumeric characters,
    # '-', '_' or '.', and must start and end with an alphanumeric character, so let's just sanitize
    # the name at this point
    return name.replace("@", "_at_").replace(":", "_")


def _resources_for_ns_wait():
    """Only check "higher level" resource types when waiting on a namespace"""
    resources = available_checkable_resources(namespaced=True)
    try:
        resources.remove("pod")
    except ValueError as err:
        if "not in list" in str(err):
            pass
        else:
            raise
    return resources


def _all_resources_ready(namespace, timeout, watcher):
    already_waited_on = set()

    # wait on ClowdEnvironment, if there's one using this ns as its targetNamespace
    start = time.time()

    clowd_env = find_clowd_env_for_ns(namespace)
    if clowd_env:
        waiter = ResourceWaiter(
            namespace,
            "clowdenvironment",
            clowd_env["metadata"]["name"],
            watch_owned=True,
            watcher=watcher,
        )
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
        waiter = ResourceWaiter(
            namespace, "clowdapp", clowdapp["metadata"]["name"], watch_owned=True, watcher=watcher
        )
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
    for k, r in watcher.resources.copy().items():
        if r.restype in _resources_for_ns_wait() and r.key not in already_waited_on:
            waiter = ResourceWaiter(
                r.namespace,
                r.restype,
                r.name,
                watch_owned=True,
                watcher=watcher,
            )
            waiters.append(waiter)

    return wait_for_ready_threaded(waiters, timeout)


def wait_for_all_resources(namespace, timeout=600):
    # wrap the other wait_fors in 1 wait_for so overall timeout is honored
    # wait_for returns a tuple of the return code and the time taken
    watcher = ResourceWatcher(namespace)
    watcher.start()

    try:
        wait_for(
            _all_resources_ready,
            func_args=(namespace, timeout, watcher),
            message="wait for all deployed resources to be ready",
            timeout=timeout,
        )
    finally:
        watcher.stop()


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


def wait_on_cji(namespace, cji_name, timeout):
    # wait for job associated with this CJI to appear
    log.info("waiting for Job to appear owned by CJI '%s'", cji_name)

    def _find_job():
        jobs = get_json("job", label=f"clowdjob={cji_name}", namespace=namespace)
        try:
            return jobs["items"][0]["metadata"]["name"]
        except (KeyError, IndexError):
            return False

    cji = Resource("clowdjobinvocation", cji_name, namespace)
    try:
        job_name, elapsed = wait_for(
            _find_job, num_sec=timeout, message=f"wait for Job to appear owned by CJI '{cji_name}'"
        )
    except TimedOutError:
        if not cji.ready:
            log.error("[%s] not ready, details: %s\n", cji.key, cji.details_str)
        raise

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
        return res.get("status", {}).get("namespace", False) or False

    ns_name, elapsed = wait_for(
        _find_reservation,
        num_sec=timeout,
        message=f"waiting for namespace to be allocated to reservation '{res_name}'",
    )
    return ns_name


def get_all_reservations():
    if not has_ns_operator():
        return []
    return get_json("reservation").get("items", [])


def check_for_existing_reservation(requester):
    if not has_ns_operator():
        return False

    log.info("Checking for existing reservations for '%s'", requester)

    for res in get_all_reservations():
        res_state = res.get("status", {}).get("state")
        if res["spec"]["requester"] == requester and res_state == "active":
            ns = res["status"]["namespace"]
            if get_json("namespace", ns):
                return True
            else:
                log.info("reservation found for namespace '%s' which no longer exists", ns)
    return False


def get_reservation(name=None, namespace=None, requester=None):
    if not has_ns_operator():
        return None

    if name:
        res = get_json("reservation", name=name)
        return res if res else False
    elif namespace:
        for res in get_all_reservations():
            if res.get("status", {}).get("namespace") == namespace:
                return res
    elif requester:
        requester_res = get_json("reservation", label=f"requester={requester}")
        numRes = len(requester_res.get("items", []))
        if numRes == 0:
            return None
        elif numRes == 1:
            return requester_res["items"][0]
        else:
            log.info("Multiple reservations found for requester '%s'. Aborting.", requester)
            return None

    return None


def get_pool_size_limit(pool):
    pool_data = get_json("namespacepool", name=pool)
    size_limit = pool_data["spec"].get("sizeLimit") if pool_data else 0
    return int(size_limit) if size_limit else 0


def get_reserved_namespace_quantity(pool):
    label = f"pool={pool}"
    pool_namespaces = get_all_namespaces(label=label)
    reserved_namespaces = [
        ns
        for ns in pool_namespaces
        if ns["metadata"].get("annotations", {}).get("reserved") == "true"
    ]

    return len(reserved_namespaces)

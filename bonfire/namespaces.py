import copy
import datetime
import logging

import bonfire.config as conf
from bonfire.openshift import (
    apply_config,
    on_k8s,
    get_all_namespaces,
    get_json,
    get_reservation,
    wait_on_reservation,
    whoami,
)
from bonfire.processor import process_reservation
from bonfire.utils import FatalError


log = logging.getLogger(__name__)
TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _utc_tz(dt):
    return dt.replace(tzinfo=datetime.timezone.utc)


def _parse_time(string):
    return _utc_tz(datetime.datetime.strptime(string, TIME_FMT)) if string else None


def _fmt_time(dt):
    return datetime.datetime.strftime(_utc_tz(dt), TIME_FMT) if dt else None


def _utcnow():
    return _utc_tz(datetime.datetime.utcnow())


def _pretty_time_delta(seconds):
    # https://gist.github.com/thatalextaylor/7408395
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days > 0:
        return "%dd%dh%dm%ds" % (days, hours, minutes, seconds)
    elif hours > 0:
        return "%dh%dm%ds" % (hours, minutes, seconds)
    elif minutes > 0:
        return "%dm%ds" % (minutes, seconds)
    else:
        return "%ds" % (seconds,)


class Namespace:
    @property
    def annotations(self):
        return self.data.get("metadata", "").get("annotations", {})

    @property
    def status(self):
        return self.annotations.get("status", "false")

    @property
    def reserved(self):
        return self.annotations.get("reserved", "false") == "true"

    @property
    def operator_ns(self):
        return self.annotations.get("operator-ns", "false") == "true"

    @property
    def is_reservable(self):
        """
        Check whether a namespace was created by the namespace operator.
        """
        return self.operator_ns

    @property
    def expires_in(self):
        if not self.expires:
            # reconciler needs to set the time ...
            return "TBD"
        utcnow = _utcnow()
        if self.expires < utcnow:
            return "expired"
        else:
            delta = self.expires - utcnow
            return _pretty_time_delta(delta.total_seconds())

    @property
    def owned_by_me(self):
        if on_k8s():
            return True
        elif conf.BONFIRE_NS_REQUESTER:
            return self.requester.lower() == conf.BONFIRE_NS_REQUESTER.lower()
        else:
            return self.requester == whoami()

    @property
    def ready(self):
        return self.status == "ready"

    @property
    def available(self):
        return not self.reserved and self.ready

    def refresh(self, data):
        self.data = data or get_json("namespace", self.name)
        self.name = self.data.get("metadata", {}).get("name")

        if "annotations" not in self.data["metadata"]:
            self.data["metadata"]["annotations"] = {}

        if self.reserved:
            res = get_reservation(namespace=self.name)
            if res:
                self.requester = res["spec"]["requester"]
                self.expires = _parse_time(res["status"]["expiration"])
            else:
                log.error("Could not retrieve reservation details for ns: %s", self.name)
        else:
            self.requester = None
            self.expires = None

    def __init__(self, name=None, namespace_data=None):
        self.data = copy.deepcopy(namespace_data) or {}
        self.name = name
        self.requester = None
        self.expires = None

        if not self.data and not self.name:
            raise ValueError('Namespace needs one of: "name", "namespace_data"')

        # if __init__ was called with only 'name', we will fetch the ns data,
        # otherwise we will use the data passed to __init__ to populated
        # this instance's properties
        self.refresh(data=self.data)

    def __str__(self):
        return (
            f"ns {self.name} (reservable: {self.is_reservable}, owned_by_me: {self.owned_by_me}, "
            f"available: {self.available})"
        )

    @property
    def clowdapps(self):
        if not self.reserved or not self.ready:
            return "none"
        else:
            clowd_apps = get_json("app", namespace=self.name)
            managed = len(clowd_apps["items"])
            ready = 0
            for app in clowd_apps["items"]:
                if "status" in app:
                    deployments = app["status"]["deployments"]
                    if deployments["managedDeployments"] == deployments["readyDeployments"]:
                        ready += 1

            return f"{ready}/{managed}"


def get_namespaces(available=False, mine=False):
    """
    Look up reservable namespaces in the cluster.

    available (bool) -- return only namespaces that are ready and not reserved
    mine (bool) -- return only namespaces owned by current user
    """
    log.debug("get_namespaces(available=%s, mine=%s)", available, mine)
    all_namespaces = [Namespace(namespace_data=ns) for ns in get_all_namespaces()]

    log.debug("namespaces found:\n%s", "\n".join([str(n) for n in all_namespaces]))

    ephemeral_namespaces = []
    for ns in all_namespaces:
        if not ns.is_reservable:
            continue
        get_all = not mine and not available
        if get_all or (mine and ns.owned_by_me) or (available and ns.available):
            ephemeral_namespaces.append(ns)

    return ephemeral_namespaces


def reserve_namespace(name, requester, duration, timeout):
    res = get_reservation(name)
    # Name should be unique on reservation creation.
    if res:
        raise FatalError(f"Reservation with name {name} already exists")

    res_config = process_reservation(name, requester, duration)

    log.debug("processed reservation:\n%s", res_config)

    try:
        res_name = res_config["items"][0]["metadata"]["name"]
    except (KeyError, IndexError):
        raise Exception(
            "error parsing name of Reservation from processed template, "
            "check Reservation template"
        )

    apply_config(None, list_resource=res_config)

    ns_name = wait_on_reservation(res_name, timeout)
    log.info(
        "namespace '%s' is reserved by '%s' for '%s'",
        ns_name,
        requester,
        duration,
    )

    return Namespace(name=ns_name)


def release_namespace(namespace):
    res = get_reservation(namespace=namespace)
    if res:
        res_config = process_reservation(
            res["metadata"]["name"],
            res["spec"]["requester"],
            "0s",  # on release set duration to 0s
        )

        apply_config(None, list_resource=res_config)
        log.info("releasing namespace '%s'", namespace)
    else:
        raise FatalError("Reservation lookup failed")


def extend_namespace(namespace, duration):
    res = get_reservation(namespace=namespace)
    if res:
        if res["status"]["state"] == "expired":
            log.error(
                "The reservation for namespace %s has expired. Please reserve a new namespace",
                res["status"]["namespace"],
            )
            return None
        res_config = process_reservation(
            res["metadata"]["name"],
            res["spec"]["requester"],
            duration,
        )

        log.debug("processed reservation:\n%s", res_config)

        apply_config(None, list_resource=res_config)
    else:
        raise FatalError("Reservation lookup failed")

    log.info("reservation for ns '%s' extended by '%s'", namespace, duration)

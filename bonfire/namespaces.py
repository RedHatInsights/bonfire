import copy
import datetime
import logging
import base64

from ocviapy import apply_config, get_all_namespaces, get_json, on_k8s, set_current_namespace
from wait_for import TimedOutError

import bonfire.config as conf
from bonfire.openshift import (
    get_all_reservations,
    get_reservation,
    get_console_url,
    wait_on_reservation,
    whoami,
)
from bonfire.processor import process_reservation
from bonfire.utils import FatalError, hms_to_seconds


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


def _duration_fmt(seconds):
    # https://gist.github.com/thatalextaylor/7408395
    seconds = int(seconds)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if hours > 0:
        return "%dh%dm%ds" % (hours, minutes, seconds)
    elif minutes > 0:
        return "%dm%ds" % (minutes, seconds)
    else:
        return "%ds" % (seconds,)


class Namespace:
    PHASE_ACTIVE = "Active"
    PHASE_TERMINATING = "Terminating"

    @property
    def annotations(self):
        return self._data.get("metadata", "").get("annotations", {})

    @property
    def labels(self):
        return self._data.get("metadata", "").get("labels", {})

    @property
    def status(self):
        return self.annotations.get("env-status", "false")

    @property
    def reserved(self):
        return self.annotations.get("reserved", "false") == "true"

    @property
    def operator_ns(self):
        return self.labels.get("operator-ns", "false") == "true"

    @property
    def is_reservable(self):
        """
        Check whether a namespace was created by the namespace operator.
        """
        return self.operator_ns

    @property
    def pool_type(self):
        return self.labels.get("pool", "false")

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

    def refresh(self, namespace_data=None, reservation_data=None, clowdapps_data=None):
        self._data = copy.deepcopy(namespace_data)
        self._reservation = copy.deepcopy(reservation_data)
        self._clowdapps = copy.deepcopy(clowdapps_data)

        if namespace_data is None:
            self._data = get_json("namespace", self.name)
            if not self._data:
                raise ValueError(f"namespace '{self.name}' not found")
        elif not namespace_data:
            raise ValueError(f"{self.__class__.__name__} initialized with empty namespace_data")
        else:
            self._data = namespace_data

        self.name = self._data.get("metadata", {}).get("name")

        if "annotations" not in self._data["metadata"]:
            self._data["metadata"]["annotations"] = {}

        if "labels" not in self._data["metadata"]:
            self._data["metadata"]["labels"] = {}

        if self.reserved and not self.is_terminating:
            res = self.reservation  # note: using 'reservation' property defined below
            if res:
                self.requester = res["spec"]["requester"]
                self.expires = _parse_time(res["status"]["expiration"])
        else:
            self.requester = None
            self.expires = None

    def __init__(self, name=None, namespace_data=None, reservation_data=None, clowdapps_data=None):
        self.name = name
        self._data = namespace_data  # if None, we will fetch data
        self._reservation = reservation_data  # if None, we will fetch data
        self._clowdapps = clowdapps_data  # if None, we will fetch data
        self.requester = None
        self.expires = None

        if not namespace_data and not name:
            raise ValueError('Namespace needs one of: "name", "namespace_data"')

        # if __init__ was called with only 'name', we will fetch the ns data,
        # otherwise we will use the data passed to __init__ to populate
        # this instance's properties
        self.refresh(namespace_data, reservation_data, clowdapps_data)

    def __str__(self):
        return (
            f"ns {self.name} (reservable: {self.is_reservable}, owned_by_me: {self.owned_by_me}, "
            f"available: {self.available})"
        )

    @property
    def reservation(self):
        if self._reservation is None:
            log.debug("fetching reservation for ns '%s'", self.name)
            self._reservation = get_reservation(namespace=self.name)

        if not self._reservation or not self._reservation.get("status"):
            self._reservation = None
            log.warning("could not retrieve reservation details for ns: %s", self.name)

        return self._reservation

    @property
    def clowdapps(self):
        if not self.reserved or not self.ready:
            return "none"
        if self._clowdapps is None:
            log.debug("fetching clowdapps for ns %s", self.name)
            self._clowdapps = get_json("app", namespace=self.name).get("items", [])

        managed = len(self._clowdapps)
        ready = 0
        for app in self._clowdapps:
            if "status" in app:
                deployments = app["status"]["deployments"]
                if deployments["managedDeployments"] == deployments["readyDeployments"]:
                    ready += 1

        return f"{ready}/{managed}"

    @property
    def phase(self):
        return self._data.get("status", {}).get("phase", "")

    @property
    def is_terminating(self):
        return self.phase == self.PHASE_TERMINATING

    @property
    def is_active(self):
        return self.phase == self.PHASE_ACTIVE


def get_namespaces(available=False, mine=False):
    """
    Look up reservable namespaces in the cluster.

    available (bool) -- return only namespaces that are ready and not reserved
    mine (bool) -- return only namespaces owned by current user
    """
    log.debug("get_namespaces(available=%s, mine=%s)", available, mine)
    all_namespaces = get_all_namespaces(label="operator-ns")
    all_clowdapps = get_json("clowdapp", "--all-namespaces").get("items", [])
    all_res = get_all_reservations()

    # build a list containing the ns data, reservation data, and clowdapp
    # data pertaining to each ns
    all_ns_kwargs = []

    for ns in all_namespaces:
        ns_name = ns["metadata"]["name"]
        clowdapps_data = [
            app for app in all_clowdapps if app.get("metadata", {}).get("namespace") == ns_name
        ]
        reservation_data = [
            res for res in all_res if res.get("status", {}).get("namespace") == ns_name
        ]
        # ensure a non-None value is passed in for these kwargs since we have already
        # pre-fetched the data
        kwargs = {
            "namespace_data": ns,
            "clowdapps_data": clowdapps_data,
            "reservation_data": reservation_data[0] if reservation_data else {},
        }
        all_ns_kwargs.append(kwargs)

    ephemeral_namespaces = []
    for ns_kwargs in all_ns_kwargs:
        ns = Namespace(**ns_kwargs)
        if ns.is_terminating:
            continue
        if not ns.is_reservable:
            continue
        get_all = not mine and not available
        if get_all or (mine and ns.owned_by_me) or (available and ns.available):
            ephemeral_namespaces.append(ns)

    return ephemeral_namespaces


def reserve_namespace(name, requester, duration, pool, timeout, local=True):
    res = get_reservation(name)
    # Name should be unique on reservation creation.
    if res:
        raise FatalError(f"Reservation with name {name} already exists")

    res_config = process_reservation(name, requester, duration, pool, local=local)

    log.debug("processed reservation:\n%s", res_config)

    try:
        res_name = res_config["items"][0]["metadata"]["name"]
    except (KeyError, IndexError):
        raise Exception(
            "error parsing name of Reservation from processed template, "
            "check Reservation template"
        )

    apply_config(None, list_resource=res_config)

    try:
        ns_name = wait_on_reservation(res_name, timeout)
    except TimedOutError:
        log.info("timeout waiting for namespace. Cancelling reservation.")
        release_reservation(name=res_name)
        raise

    log.info(
        "namespace '%s' is reserved by '%s' for '%s' from the %s pool",
        ns_name,
        requester,
        duration,
        pool,
    )

    if not conf.BONFIRE_BOT:
        # set reserved namespace as current
        set_current_namespace(ns_name)

    url = get_console_url()
    if url:
        ns_url = f"{url}/k8s/cluster/projects/{ns_name}"
        log.info("namespace console url: %s", ns_url)

    return Namespace(name=ns_name)


def release_reservation(name=None, namespace=None, local=True):
    res = get_reservation(name=name, namespace=namespace)
    if res:
        res_name = res["metadata"]["name"]
        res_config = process_reservation(
            res["metadata"]["name"],
            res["spec"]["requester"],
            "0s",  # on release set duration to 0s
            pool=res["spec"].get("pool"),
            local=local,
        )

        apply_config(None, list_resource=res_config)
        msg = f"releasing reservation '{res_name}'"
        if namespace:
            msg += f" namespace '{namespace}'"
        log.info(msg)
    else:
        raise FatalError("Reservation lookup failed")


def extend_namespace(namespace, duration, local=True):
    res = get_reservation(namespace=namespace)
    if res:
        if res.get("status", {}).get("state") == "expired":
            log.error(
                "The reservation for namespace %s has expired. Please reserve a new namespace",
                res["status"]["namespace"],
            )
            return None

        prev_duration = hms_to_seconds(res["spec"]["duration"])
        new_duration = prev_duration + hms_to_seconds(duration)

        res_config = process_reservation(
            res["metadata"]["name"],
            res["spec"]["requester"],
            _duration_fmt(new_duration),
            pool=res["spec"].get("pool"),
            local=local,
        )

        log.debug("processed reservation:\n%s", res_config)

        apply_config(None, list_resource=res_config)
    else:
        raise FatalError("Reservation lookup failed")

    log.info("reservation for ns '%s' extended by '%s'", namespace, duration)


def describe_namespace(project_name: str):
    ns_data = get_json("namespace", project_name)
    if not ns_data:
        raise FatalError(f"namespace '{project_name}' not found")
    ns = Namespace(namespace_data=ns_data)
    if not ns.operator_ns:
        raise FatalError(f"namespace '{project_name}' was not reserved with namespace operator")

    frontends = get_json("frontend", namespace=project_name)
    fe_host, keycloak_url = parse_fe_env(project_name)
    kc_creds = get_keycloak_creds(project_name)
    project_url = get_console_url()

    output = f"Current project: {project_name}\n"
    if project_url:
        ns_url = f"{project_url}/k8s/cluster/projects/{project_name}"
        output += f"Project URL: {ns_url}\n"
    output += f"Keycloak admin route: {keycloak_url}\n"
    output += f"Keycloak admin login: {kc_creds['username']} | {kc_creds['password']}\n"
    if frontends.get('items'):
        output += f"Frontend route: https://{fe_host}\n"
    else:
        output += "No frontends deployed\n"
    output += f"Default user login: {kc_creds['defaultUsername']} | {kc_creds['defaultPassword']}\n"

    return output


def parse_fe_env(project_name):
    fe_env = get_json("frontendenvironment", f"env-{project_name}")
    fe_host = fe_env.get("spec", {}).get("hostname", "")
    keycloak_url = fe_env.get("spec", {}).get("sso", "")
    return fe_host, keycloak_url


def get_keycloak_creds(project_name):
    secret = get_json("secret", name=f"env-{project_name}-keycloak", namespace=project_name)
    kc_creds = {}
    for key in ("username", "password", "defaultUsername", "defaultPassword"):
        kc_creds[key] = decode_b64(secret["data"][key])
    return kc_creds


def decode_b64(item: str):
    return base64.b64decode(item).decode("UTF-8")

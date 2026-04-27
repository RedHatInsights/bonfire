import base64
import copy
import datetime
import json
import logging

from ocviapy import get_all_namespaces, get_json, on_k8s, set_current_namespace
from wait_for import TimedOutError

import bonfire.config as conf
from bonfire.openshift import (
    get_all_reservations,
    get_console_url,
    get_reservation,
    whoami,
)
from bonfire.utils import FatalError

import bonfire_lib.reservations as _lib_reservations
import bonfire_lib.status as _lib_status
from bonfire_lib.k8s_client import EphemeralK8sClient

log = logging.getLogger(__name__)


def _get_lib_client() -> EphemeralK8sClient:
    """Create an EphemeralK8sClient from the current kubeconfig context."""
    return EphemeralK8sClient()


TIME_FMT = "%Y-%m-%dT%H:%M:%SZ"


def _utc_tz(dt):
    return dt.replace(tzinfo=datetime.timezone.utc)


def _parse_time(string):
    return _utc_tz(datetime.datetime.strptime(string, TIME_FMT)) if string else None


def _fmt_time(dt):
    return datetime.datetime.strftime(_utc_tz(dt), TIME_FMT) if dt else None


def _utcnow():
    return _utc_tz(datetime.datetime.now(datetime.timezone.utc))


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
        if namespace_data is None:
            self._data = get_json("namespace", self.name)
            if not self._data:
                raise ValueError(f"namespace '{self.name}' not found")
        elif not namespace_data:
            raise ValueError(f"{self.__class__.__name__} initialized with empty namespace_data")
        else:
            self._data = copy.deepcopy(namespace_data)

        self._reservation = copy.deepcopy(reservation_data) if reservation_data else None
        self._clowdapps = copy.deepcopy(clowdapps_data) if clowdapps_data else None

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
            try:
                self._clowdapps = get_json("clowdapp", namespace=self.name).get("items", [])
            except ValueError:
                return "none"

        if not self._clowdapps:
            return "none"

        managed = len(self._clowdapps)
        ready = 0
        for app in self._clowdapps:
            if "status" in app:
                deployments = app["status"]["deployments"]
                if deployments["managedDeployments"] == deployments["readyDeployments"]:
                    ready += 1

        return f"{ready}/{managed}"

    @property
    def clusters(self):
        if not self.reserved or not self.ready:
            return "none"

        try:
            cluster_data = get_json("cluster.cluster.x-k8s.io", namespace=self.name)
            items = cluster_data.get("items", [])
        except Exception:
            return "n/a"

        if not items:
            return "none"

        total = len(items)
        ready = 0
        for cluster in items:
            conditions = cluster.get("status", {}).get("conditions", [])
            for cond in conditions:
                if cond.get("type") == "Ready" and cond.get("status") == "True":
                    ready += 1
                    break

        return f"{ready}/{total}"

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
    try:
        all_clowdapps = get_json("clowdapp", "--all-namespaces").get("items", [])
    except ValueError:
        log.debug("clowdapp resource type not found, skipping")
        all_clowdapps = []
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


def reserve_namespace(
    name, requester, duration, pool, timeout, local=True, team=None, secrets_src_namespace=None
):
    client = _get_lib_client()

    try:
        result = _lib_reservations.reserve(
            client,
            name=name,
            duration=duration,
            requester=requester,
            pool=pool,
            team=team,
            secrets_src_namespace=secrets_src_namespace,
            timeout=timeout,
        )
    except _lib_reservations.FatalError as exc:
        raise FatalError(str(exc))
    except TimeoutError:
        raise TimedOutError("timed out waiting for namespace")

    ns_name = result["namespace"]

    if not conf.BONFIRE_BOT:
        set_current_namespace(ns_name)

    url = get_console_url()
    if url:
        ns_url = f"{url}/k8s/cluster/projects/{ns_name}"
        log.info("namespace console url: %s", ns_url)

    return Namespace(name=ns_name)


def release_reservation(name=None, namespace=None, local=True):
    client = _get_lib_client()
    try:
        _lib_reservations.release(client, name=name, namespace=namespace)
    except _lib_reservations.FatalError as exc:
        raise FatalError(str(exc))


def extend_namespace(namespace, duration, local=True):
    client = _get_lib_client()
    try:
        result = _lib_reservations.extend(client, namespace=namespace, duration=duration)
    except _lib_reservations.FatalError as exc:
        raise FatalError(str(exc))
    if result is None:
        return None
    log.info("reservation for ns '%s' extended by '%s'", namespace, duration)


def describe_namespace(project_name: str, output: str):
    client = _get_lib_client()
    try:
        info = _lib_status.describe_namespace(client, project_name)
    except _lib_status.FatalError as exc:
        raise FatalError(str(exc))

    if output == "json":
        return json.dumps(info, indent=2)

    data = f"\nCurrent project: {project_name}\n"
    if info.get("console_namespace_route"):
        data += f"Project URL: {info['console_namespace_route']}\n"
    data += f"Keycloak admin route: {info['keycloak_admin_route']}\n"
    data += f"Keycloak admin login: {info['keycloak_admin_username']} | {info['keycloak_admin_password']}\n"
    data += f"{info['clowdapps_deployed']} ClowdApp(s), {info['frontends_deployed']} Frontend(s) deployed\n"
    data += f"Gateway route: {info['gateway_route']}\n"
    data += f"Default user login: {info['default_username']} | {info['default_password']}\n"
    return data


def parse_fe_env(project_name):
    fe_env = get_json("frontendenvironment", f"env-{project_name}")
    fe_host = fe_env.get("spec", {}).get("hostname", "")
    keycloak_url = fe_env.get("spec", {}).get("sso", "")
    return fe_host, keycloak_url


def get_keycloak_creds(project_name):
    secret = get_json("secret", name=f"env-{project_name}-keycloak", namespace=project_name)
    kc_creds = {}
    if secret and "data" in secret:
        for key in ("username", "password", "defaultUsername", "defaultPassword"):
            kc_creds[key] = decode_b64(secret["data"].get(key, ""))
    else:
        # Namespace might be terminating or secret doesn't exist
        for key in ("username", "password", "defaultUsername", "defaultPassword"):
            kc_creds[key] = "N/A"
    return kc_creds


def decode_b64(item: str):
    return base64.b64decode(item).decode("UTF-8")

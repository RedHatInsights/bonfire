import copy
import datetime
import logging
import json
import random
import time
import uuid
import yaml
import threading
from wait_for import TimedOutError

import bonfire.config as conf
from bonfire.qontract import get_namespaces_for_env, get_secret_names_in_namespace
from bonfire.openshift import (
    oc,
    on_k8s,
    get_all_namespaces,
    get_json,
    copy_namespace_secrets,
    process_template,
    wait_for_all_resources,
    whoami,
)


NS_RESERVED = "ephemeral-ns-reserved"
NS_READY = "ephemeral-ns-ready"
NS_REQUESTER = "ephemeral-ns-requester"
NS_DURATION = "ephemeral-ns-duration"
NS_EXPIRES = "ephemeral-ns-expires"
NS_REQUESTER_NAME = "ephemeral-ns-requester-name"
NS_REQUIRED_LABELS = [
    NS_DURATION,
    NS_EXPIRES,
    NS_READY,
    NS_REQUESTER,
    NS_REQUESTER_NAME,
    NS_RESERVED,
]


RESERVATION_DELAY_SEC = 5

log = logging.getLogger(__name__)


TIME_FMT = "%Y-%m-%d_T%H-%M-%S_%Z"


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
    def refresh(self):
        self.__init__(namespace_data=get_json("namespace", self.name))
        return self

    def __init__(self, name=None, namespace_data=None):
        if not namespace_data:
            # we don't yet have the data for this namespace... load it
            if not name:
                raise ValueError('Namespace needs one of: "name", "namespace_data"')
            self.name = name
            self.refresh()
            return

        self.data = copy.deepcopy(namespace_data)
        self.name = self.data["metadata"]["name"]

        self._initialize_labels = False
        if "labels" not in self.data["metadata"]:
            self.data["metadata"]["labels"] = {}
            self._initialize_labels = True

        self.labels = self.data["metadata"]["labels"]

        self.reserved = self.labels.get(NS_RESERVED, "false") == "true"
        self.ready = self.labels.get(NS_READY, "false") == "true"
        requester = self.labels.get(NS_REQUESTER)
        self.requester = str(requester) if requester else None
        duration = self.labels.get(NS_DURATION)
        self.duration = int(duration) if duration else None
        # convert time format to one that can be used in a label
        self.expires = _parse_time(self.labels.get(NS_EXPIRES))
        requester_name = self.labels.get(NS_REQUESTER_NAME)
        self.requester_name = str(requester_name) if requester_name else None

    @property
    def is_reservable(self):
        """
        Check whether a namespace has the required labels set on it.
        """
        if all([label in self.labels for label in NS_REQUIRED_LABELS]):
            return True
        return False

    @property
    def expires_in(self):
        if not self.expires:
            # reconciler needs to set the time ...
            return "TBD"
        utcnow = _utcnow()
        delta = self.expires - utcnow
        return _pretty_time_delta(delta.total_seconds())

    @property
    def owned_by_me(self):
        if on_k8s():
            return True
        return self.requester_name == whoami()

    @property
    def available(self):
        return not self.reserved and self.ready

    def __str__(self):
        return (
            f"ns {self.name} (reservable: {self.is_reservable}, owned_by_me: {self.owned_by_me}, "
            f"available: {self.available})"
        )

    def update(self):
        patch = []

        if self._initialize_labels:
            # prevent 'The  "" is invalid' error due to missing 'labels' path
            patch.append({"op": "add", "path": "/metadata/labels", "value": {}})

        patch.extend(
            [
                {
                    "op": "replace",
                    "path": f"/metadata/labels/{NS_RESERVED}",
                    "value": str(self.reserved).lower(),
                },
                {
                    "op": "replace",
                    "path": f"/metadata/labels/{NS_READY}",
                    "value": str(self.ready).lower(),
                },
                {
                    "op": "replace",
                    "path": f"/metadata/labels/{NS_REQUESTER}",
                    "value": str(self.requester) if self.requester else None,
                },
                {
                    "op": "replace",
                    "path": f"/metadata/labels/{NS_DURATION}",
                    "value": str(self.duration) if self.duration else None,
                },
                {
                    "op": "replace",
                    "path": f"/metadata/labels/{NS_EXPIRES}",
                    # convert time format to one that can be used in a label
                    "value": _fmt_time(self.expires),
                },
                {
                    "op": "replace",
                    "path": f"/metadata/labels/{NS_REQUESTER_NAME}",
                    "value": str(self.requester_name) if self.requester_name else None,
                },
            ]
        )

        oc("patch", "namespace", self.name, type="json", p=json.dumps(patch))


def _get_env_ready_status():
    clowd_env_ready_for_ns = {}
    clowd_envs = get_json("clowdenvironment")
    for clowd_env in clowd_envs["items"]:
        status = clowd_env.get("status", {})
        target_ns = status.get("targetNamespace")
        ready = status.get("ready", False)
        clowd_env_ready_for_ns[target_ns] = ready
        if not ready:
            log.debug("found target ns '%s' with env status not ready", target_ns)
    return clowd_env_ready_for_ns


def get_namespaces(available=False, mine=False):
    """
    Look up reservable namespaces in the cluster.

    available (bool) -- return only namespaces that are ready and not reserved
    mine (bool) -- return only namespaces owned by current user
    """
    log.debug("get_namespaces(available=%s, mine=%s)", available, mine)
    all_namespaces = [Namespace(namespace_data=ns) for ns in get_all_namespaces()]

    log.debug("namespaces found:\n%s", "\n".join([str(n) for n in all_namespaces]))

    # get clowd envs to ensure that ClowdEnvironment is ready for the namespaces
    env_ready_for_ns = _get_env_ready_status()

    ephemeral_namespaces = []
    for ns in all_namespaces:
        ns.ready = ns.ready and env_ready_for_ns.get(ns.name, False)
        if not ns.is_reservable:
            continue
        get_all = not mine and not available
        if get_all or (mine and ns.owned_by_me) or (available and ns.available):
            ephemeral_namespaces.append(ns)

    return ephemeral_namespaces


def _reserve_ns_for_duration(namespace, duration):
    requester_id = uuid.uuid4()
    namespace.reserved = True
    namespace.ready = False
    namespace.requester = requester_id
    namespace.duration = duration
    namespace.expires = None  # let the reconciler tell us when it expires
    namespace.requester_name = whoami()
    namespace.update()
    return requester_id


def _should_renew_ns(namespace, duration):
    # if the ns is already reserved by us, don't re-reserve it if the requested duration is less
    # than the expires_in time (in other words, if you have reserved an ns already that expires in
    # 2 days you would not want to reset it to expire in 60 minutes)
    if namespace.owned_by_me:
        if not namespace.expires:
            # we're not sure when this expires yet, let's not re-reserve it
            log.warning("namespace owned by you but expires time unknown, not renewing")
            return False

        expires_in_delta = namespace.expires - _utcnow()
        expires_in_hrs = expires_in_delta.total_seconds() / 3600
        if duration <= expires_in_hrs:
            log.warning(
                "namespace owned by you, expires in '%s' >= duration '%dh', not renewing",
                _pretty_time_delta(expires_in_delta.total_seconds()),
                duration,
            )
            return False

    return True


def reserve_namespace(duration, retries, specific_namespace=None, attempt=0):
    attempt = attempt + 1

    ns_name = specific_namespace if specific_namespace else ""
    log.info("attempt [%d] to reserve namespace %s", attempt, ns_name)

    if specific_namespace:
        log.debug("specific namespace requested: %s", ns_name)
        # look up both available ns's and ns's owned by 'me' to allow for renewing reservation
        available_namespaces = get_namespaces(available=True, mine=True)
        available_namespaces = [ns for ns in available_namespaces if ns.name == specific_namespace]
    else:
        # if a specific namespace was not requested, only look up available ones
        available_namespaces = get_namespaces(available=True, mine=False)

    if not available_namespaces:
        log.info("all namespaces currently unavailable")

        if retries and attempt > retries:
            log.error("maximum retries reached")
            return None

        log.info("waiting 60sec before retrying")
        time.sleep(60)
        return reserve_namespace(duration, retries, specific_namespace, attempt=attempt)

    namespace = random.choice(available_namespaces)

    if not _should_renew_ns(namespace, duration):
        return namespace

    requester_id = _reserve_ns_for_duration(namespace, duration)

    # to avoid race conditions, wait and verify we still own this namespace
    time.sleep(RESERVATION_DELAY_SEC)
    namespace.refresh()
    if str(namespace.requester) != str(requester_id):
        log.warning("hit namespace reservation conflict")

        if retries and attempt > retries:
            log.error("maximum retries reached")
            return None

        return reserve_namespace(duration, retries, specific_namespace, attempt=attempt)

    return namespace


def release_namespace(namespace):
    ns = Namespace(name=namespace)
    ns.reserved = False
    ns.requester = None
    ns.requester_name = None
    ns.ready = False
    ns.update()


def _delete_resources(namespace):
    # delete some of our own operator resources first
    resources_to_delete = [
        "cyndipipelines",  # delete this first to prevent hanging
        "xjoinpipelines",
        "clowdjobinvocations",
        "clowdapps",
    ]
    for resource in resources_to_delete:
        oc("delete", resource, "--all", n=namespace, timeout="60s")

    # delete the ClowdEnvironment for this namespace
    if get_json("clowdenvironment", conf.ENV_NAME_FORMAT.format(namespace=namespace)):
        oc(
            "delete",
            "clowdenvironment",
            conf.ENV_NAME_FORMAT.format(namespace=namespace),
            timeout="60s",
        )

    # delete the FrontendEnvironment for this namespace
    if get_json("frontendenvironment", conf.ENV_NAME_FORMAT.format(namespace=namespace)):
        oc(
            "delete",
            "frontendenvironment",
            conf.ENV_NAME_FORMAT.format(namespace=namespace),
            timeout="60s",
        )

    # delete any other lingering specific resource types from the namespace
    resources_to_delete = [
        "ingresses",
        "frontends",
        "bundles",
        "elasticsearches",
        "horizontalpodautoscalers",
        "kafkabridges",
        "kafkaconnectors",
        "kafkaconnects",
        "kafkaconnects2is",
        "kafkamirrormaker2s",
        "kafkamirrormakers",
        "kafkarebalances",
        "kafkas",
        "kafkatopics",
        "kafkausers",
        "deployments",
        "deploymentconfigs",
        "statefulsets",
        "daemonsets",
        "replicasets",
        "cronjobs",
        "jobs",
        "services",
        "routes",
        "pods",
        "secrets",
        "configmaps",
        "persistentvolumeclaims",
    ]
    for resource in resources_to_delete:
        oc("delete", resource, "--all", n=namespace, timeout="60s")


def add_base_resources(namespace, secret_names):
    copy_namespace_secrets(conf.BASE_NAMESPACE_NAME, namespace, secret_names)

    with open(conf.EPHEMERAL_CLUSTER_CLOWDENV_TEMPLATE) as fp:
        template_data = yaml.safe_load(fp)

    processed_template = process_template(
        template_data,
        params={
            "ENV_NAME": conf.ENV_NAME_FORMAT.format(namespace=namespace),
            "NAMESPACE": namespace,
        },
    )

    oc("apply", f="-", _in=json.dumps(processed_template))

    # wait for any deployed base resources to become 'ready'
    wait_for_all_resources(namespace, timeout=conf.RECONCILE_TIMEOUT)


def _reconcile_ns(ns, base_secret_names):
    log.info("namespace '%s' - checking", ns.name)
    update_needed = False

    if ns.reserved and ns.expires:
        # check if the reservation has expired
        utcnow = _utcnow()
        log.info("namespace '%s' - expires: %s, utcnow: %s", ns.name, ns.expires, utcnow)
        if utcnow > ns.expires:
            log.info("namespace '%s' - reservation expired, releasing", ns.name)
            ns.reserved = False
            ns.ready = False
            ns.duration = None
            ns.expires = None
            ns.requester = None
            ns.requester_name = None
            _delete_resources(ns.name)
            update_needed = True
        log.info("namespace '%s' - not expired", ns.name)

    if not ns.reserved and not ns.ready:
        # check if any released namespaces need to be prepped
        log.info("namespace '%s' - not reserved, but not 'ready', prepping", ns.name)
        _delete_resources(ns.name)
        try:
            add_base_resources(ns.name, base_secret_names)
        except TimedOutError:
            # base resources failed to come up, don't mark it ready and try again next time...
            log.error("namespace '%s' - timed out waiting for resources after prep", ns.name)
        else:
            ns.ready = True
            ns.duration = None
            ns.expires = None
            ns.requester = None
            ns.requester_name = None
            update_needed = True

    if ns.reserved and ns.duration and not ns.expires:
        # this is a newly reserved namespace, set the expires time
        log.info("namespace '%s' - setting expiration time", ns.name)
        ns.expires = _utcnow() + datetime.timedelta(hours=ns.duration)
        update_needed = True

    if update_needed:
        ns.update()

    log.info("namespace '%s' - done", ns.name)


def get_namespaces_for_reconciler():
    """
    Query app-interface to get list of namespaces the reconciler operates on.
    """
    ephemeral_namespace_names = get_namespaces_for_env(conf.EPHEMERAL_ENV_NAME)
    log.debug(
        "namespaces found for env '%s': %s", conf.EPHEMERAL_ENV_NAME, ephemeral_namespace_names
    )
    all_namespaces = get_json("project")["items"]
    log.debug(
        "all namespaces found on cluster: %s", [ns["metadata"]["name"] for ns in all_namespaces]
    )
    ephemeral_namespaces = []

    # get clowd envs to ensure that ClowdEnvironment is ready for the namespaces
    env_ready_for_ns = _get_env_ready_status()
    for ns in all_namespaces:
        ns_name = ns["metadata"]["name"]
        if ns_name == conf.BASE_NAMESPACE_NAME:
            log.debug("ns '%s' is base namespace, will not reconcile it")
            continue
        if ns_name not in ephemeral_namespace_names:
            log.debug(
                "ns '%s' is not a member of env '%s', will not reconcile it",
                ns_name,
                conf.EPHEMERAL_ENV_NAME,
            )
            continue
        if not conf.RESERVABLE_NAMESPACE_REGEX.match(ns_name):
            log.debug(
                "ns '%s' does not match reservable namespace regex, will not reconcile it", ns_name
            )
            continue
        ns = Namespace(namespace_data=ns)
        ns.ready = ns.ready and env_ready_for_ns.get(ns.name, False)
        ephemeral_namespaces.append(ns)

    return ephemeral_namespaces


def reconcile():
    # run graphql queries outside of the threads since the client isn't natively thread-safe
    namespaces = get_namespaces_for_reconciler()
    base_secret_names = get_secret_names_in_namespace(conf.BASE_NAMESPACE_NAME)

    threads = []
    for ns in namespaces:
        t = threading.Thread(target=_reconcile_ns, args=(ns, base_secret_names))
        t.name = ns.name
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

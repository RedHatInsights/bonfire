import copy
import datetime
import logging
import json
import random
import time
import uuid
import yaml
import threading
from pkg_resources import resource_filename
from wait_for import TimedOutError

import bonfire.config as conf
from bonfire.qontract import get_namespaces_for_env, get_secret_names_in_namespace
from bonfire.openshift import (
    oc,
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

RESERVATION_DELAY_SEC = 5

ENV_TEMPLATE = resource_filename("bonfire", "resources/ephemeral-clowdenvironment.yaml")

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
    def expires_in(self):
        if not self.expires:
            # reconciler needs to set the time ...
            return "TBD"
        utcnow = _utcnow()
        delta = self.expires - utcnow
        return _pretty_time_delta(delta.total_seconds())

    @property
    def owned_by_me(self):
        return self.requester_name == whoami()

    @property
    def available(self):
        return self.owned_by_me or (not self.reserved and self.ready)

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


def get_namespaces(available_only=False, mine=False):
    ephemeral_namespace_names = get_namespaces_for_env(conf.EPHEMERAL_ENV_NAME)
    ephemeral_namespace_names.remove(conf.BASE_NAMESPACE_NAME)
    # Use 'oc get project' since we cannot list all 'namespace' resources in a cluster
    all_namespaces = get_json("project")["items"]
    ephemeral_namespaces = []
    for ns in all_namespaces:
        if ns["metadata"]["name"] not in ephemeral_namespace_names:
            continue
        if not conf.RESERVABLE_NAMESPACE_REGEX.match(ns["metadata"]["name"]):
            continue
        ns = Namespace(namespace_data=ns)
        if mine:
            if ns.owned_by_me:
                ephemeral_namespaces.append(ns)
        elif not available_only or ns.available:
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

    available_namespaces = get_namespaces(available_only=True)

    if specific_namespace:
        available_namespaces = [ns for ns in available_namespaces if ns.name == specific_namespace]

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
    oc("label", "--overwrite", "namespace", namespace, f"{NS_RESERVED}=false")


def reset_namespace(namespace):
    release_namespace(namespace)
    oc("label", "--overwrite", "namespace", namespace, f"{NS_READY}=false")


def _delete_resources(namespace):
    # installation of certain operators on the cluster may break 'oc delete all'
    # oc("delete", "all", "--all", n=namespace)

    # delete the ClowdApps in this namespace
    oc("delete", "clowdapp", "--all", n=namespace)

    # delete the ClowdEnvironment for this namespace
    if get_json("clowdenvironment", conf.ENV_NAME_FORMAT.format(namespace=namespace)):
        oc(
            "delete",
            "clowdenvironment",
            conf.ENV_NAME_FORMAT.format(namespace=namespace),
        )

    # delete other specific resource types from the namespace
    resources_to_delete = [
        "secret",
        "configmap",
        "pvc",
        "pod",
        "deployment",
        "deploymentconfig",
        "statefulset",
        "daemonset",
        "replicaset",
        "cronjob",
        "job",
        "service",
        "route",
    ]
    for resource in resources_to_delete:
        oc("delete", resource, "--all", n=namespace)


def add_base_resources(namespace, secret_names):
    copy_namespace_secrets(conf.BASE_NAMESPACE_NAME, namespace, secret_names)

    with open(ENV_TEMPLATE) as fp:
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
    wait_for_all_resources(namespace, timeout=conf.RECONCILE_TIMEOUT, wait_on_app=False)


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
        log.info("namespace '%s' - released but needs prep, prepping", ns.name)
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


def reconcile():
    # run graphql queries outside of the threads since the client isn't natively thread-safe
    namespaces = get_namespaces()
    base_secret_names = get_secret_names_in_namespace(conf.BASE_NAMESPACE_NAME)

    threads = []
    for ns in namespaces:
        t = threading.Thread(target=_reconcile_ns, args=(ns, base_secret_names))
        t.name = ns.name
        threads.append(t)
        t.start()
    for t in threads:
        t.join()

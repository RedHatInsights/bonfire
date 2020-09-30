import copy
import datetime
import logging
import json
import random
import time
import uuid

import bonfire.config as conf
from bonfire.qontract import get_namespaces_for_env, get_secret_names_in_namespace
from bonfire.openshift import oc, get_json, copy_namespace_secrets


NS_RESERVED = "ephemeral-ns-reserved"
NS_READY = "ephemeral-ns-ready"
NS_REQUESTER = "ephemeral-ns-requester"
NS_DURATION = "ephemeral-ns-duration"
NS_EXPIRES = "ephemeral-ns-expires"

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


class Namespace:
    def __init__(self, namespace_data):
        self.data = copy.deepcopy(namespace_data)
        self.name = self.data["metadata"]["name"]

        if "labels" not in self.data["metadata"]:
            self.data["metadata"]["labels"] = {}
        self.labels = self.data["metadata"]["labels"]

        self.reserved = self.labels.get(NS_RESERVED, "false") == "true"
        self.ready = self.labels.get(NS_READY, "false") == "true"
        requester = self.labels.get(NS_REQUESTER)
        self.requester = str(requester) if requester else None
        duration = self.labels.get(NS_DURATION)
        self.duration = int(duration) if duration else None
        # convert time format to one that can be used in a label
        self.expires = _parse_time(self.labels.get(NS_EXPIRES))

    def refresh(self):
        self.__init__(get_json("namespace", self.name))

    def update(self):
        patch = [
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
        ]

        oc("patch", "namespace", self.name, type="json", p=json.dumps(patch))


def get_namespaces(available_only=False):
    ephemeral_namespace_names = get_namespaces_for_env(conf.EPHEMERAL_ENV_NAME)
    ephemeral_namespace_names.remove(conf.BASE_NAMESPACE_NAME)
    # Use 'oc get project' since we cannot list all 'namespace' resources in a cluster
    all_namespaces = get_json("project")["items"]
    ephemeral_namespaces = []
    for ns in all_namespaces:
        if ns["metadata"]["name"] not in ephemeral_namespace_names:
            continue
        ns = Namespace(ns)
        if not available_only or (not ns.reserved and ns.ready):
            ephemeral_namespaces.append(ns)

    return ephemeral_namespaces


def reserve_namespace(duration, retries, attempt=0):
    attempt = attempt + 1

    log.info("attempt [%d] to reserve a namespace", attempt)

    available_namespaces = get_namespaces(available_only=True)

    if not available_namespaces:
        log.info("no namespaces currently available")

        if retries and attempt > retries:
            log.error("maximum retries reached")
            return None

        log.info("waiting 60sec before retrying")
        time.sleep(60)
        return reserve_namespace(duration, retries, attempt=attempt)

    namespace = random.choice(available_namespaces)
    requester_id = uuid.uuid4()
    namespace.reserved = True
    namespace.ready = False
    namespace.requester = requester_id
    namespace.duration = duration
    namespace.update()

    # to avoid race conditions, wait and verify we still own this namespace
    time.sleep(RESERVATION_DELAY_SEC)
    namespace.refresh()
    if str(namespace.requester) != str(requester_id):
        log.warning("hit namespace reservation conflict")

        if retries and attempt > retries:
            log.error("maximum retries reached")
            return None

        return reserve_namespace(duration, retries, attempt=attempt)

    return namespace


def release_namespace(namespace):
    # TODO: currently there's nothing stopping you from checking in a namespace you did not check
    # out yourself
    oc("label", "--overwrite", "namespace", namespace, f"{NS_RESERVED}=false")


def reset_namespace(namespace):
    release_namespace(namespace)
    oc("label", "--overwrite", "namespace", namespace, f"{NS_READY}=false")


def _delete_resources(namespace):
    oc("delete", "all", "--all", n=namespace)
    oc("delete", "pvc", "--all", n=namespace)
    oc("delete", "clowdenvironment", "--all", n=namespace)
    oc("delete", "clowdapp", "--all", n=namespace)


def copy_base_resources(namespace):
    secret_names = get_secret_names_in_namespace(conf.BASE_NAMESPACE_NAME)
    copy_namespace_secrets(conf.BASE_NAMESPACE_NAME, namespace, secret_names)
    oc(
        "apply",
        f="-",
        n=namespace,
        _in=oc(
            "get",
            "clowdenvironment",
            "ephemeral",
            "--export",
            n=conf.BASE_NAMESPACE_NAME,
            o="json",
            _hide_output=True,
        ),
    )


def reconcile():
    namespaces = get_namespaces()
    for ns in namespaces:
        log.info("namespace '%s' - checking", ns.name)
        update_needed = False

        if ns.reserved and ns.expires:
            # check if the reservation has expired
            if _utcnow() > ns.expires:
                log.info("namespace '%s' - reservation expired, releasing", ns.name)
                ns.reserved = False
                ns.ready = False
                ns.duration = None
                ns.expires = None
                ns.requester = None
                _delete_resources(ns.name)
                update_needed = True

        if not ns.reserved and not ns.ready:
            # check if any released namespaces need to be prepped
            log.info("namespace '%s' - released but needs prep, prepping", ns.name)
            _delete_resources(ns.name)
            copy_base_resources(ns.name)
            ns.ready = True
            update_needed = True

        if ns.reserved and ns.duration and not ns.expires:
            # this is a newly reserved namespace, set the expires time
            log.info("namespace '%s' - setting expiration time", ns.name)
            ns.expires = _utcnow() + datetime.timedelta(minutes=ns.duration)
            update_needed = True

        if update_needed:
            ns.update()

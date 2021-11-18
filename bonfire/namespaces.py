import copy
import datetime
import logging
import json
import yaml
import threading
from wait_for import TimedOutError

import bonfire.config as conf
from bonfire.qontract import get_namespaces_for_env, get_secret_names_in_namespace
from bonfire.openshift import (
    apply_config,
    oc,
    on_k8s,
    get_all_namespaces,
    get_json,
    get_reservation,
    copy_namespace_secrets,
    process_template,
    wait_for_all_resources,
    wait_on_reservation,
    whoami,
)
from bonfire.processor import process_reservation
from bonfire.utils import FatalError


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

        if "annotations" not in self.data["metadata"]:
            self.data["metadata"]["annotations"] = {}

        self.annotations = self.data["metadata"]["annotations"]

        self.reserved = self.annotations.get("reserved", "false") == "true"
        self.status = self.annotations.get("status", "false")
        self.operator_ns = self.annotations.get("operator-ns", "false") == "true"

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
        return self.requester == whoami()

    @property
    def available(self):
        return not self.reserved and self.status == "ready"

    def __str__(self):
        return (
            f"ns {self.name} (reservable: {self.is_reservable}, owned_by_me: {self.owned_by_me}, "
            f"available: {self.available})"
        )

    def clowdapps(self):
        if not self.reserved:
            self.clowdapps = None
        else:
            clowd_apps = get_json("app", namespace=self.name)
            managed = len(clowd_apps["items"])
            ready = 0
            for app in clowd_apps["items"]:
                if "status" in app:
                    deployments = app["status"]["deployments"]
                    if deployments["managedDeployments"] == deployments["readyDeployments"]:
                        ready += 1

            self.clowdapps = f"{ready}/{managed}"

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
    # env_ready_for_ns = _get_env_ready_status()

    ephemeral_namespaces = []
    for ns in all_namespaces:
        if not ns.is_reservable:
            continue
        get_all = not mine and not available
        if get_all or (mine and ns.owned_by_me) or (available and ns.available):
            ns.clowdapps()
            ephemeral_namespaces.append(ns)

    return ephemeral_namespaces


def reserve_namespace(name, requester, duration, timeout):
    try:
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
    except KeyboardInterrupt as err:
        log.error("aborted by keyboard interrupt!")
        return None, err
    except TimedOutError as err:
        log.error("hit timeout error: %s", err)
        return None, err
    except FatalError as err:
        log.error("hit fatal error: %s", err)
        return None, err
    except Exception as err:
        log.exception("hit unexpected error: %s", err)
        return None, err
    else:
        log.info(
            "namespace '%s' is reserved by '%s' for '%s'",
            ns_name,
            requester,
            duration,
        )

    return ns_name, None


def release_namespace(namespace):
    try:
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
    except KeyboardInterrupt as err:
        log.error("aborted by keyboard interrupt!")
        return err
    except TimedOutError as err:
        log.error("hit timeout error: %s", err)
        return err
    except FatalError as err:
        log.error("hit fatal error: %s", err)
        return err
    except Exception as err:
        log.exception("hit unexpected error: %s", err)
        return err

    return None


def extend_namespace(namespace, duration):
    try:
        res = get_reservation(namespace=namespace)
        if res:
            if res["status"]["state"] == "expired":
                log.error(
                    "The reservation for namespace %s has expired. "
                    "Please reserve a new namespace",
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
    except KeyboardInterrupt as err:
        log.error("aborted by keyboard interrupt!")
        return err
    except TimedOutError as err:
        log.error("hit timeout error: %s", err)
        return err
    except FatalError as err:
        log.error("hit fatal error: %s", err)
        return err
    except Exception as err:
        log.exception("hit unexpected error: %s", err)
        return err

    log.info("reservation for ns '%s' extended by '%s'", namespace, duration)

    return None


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

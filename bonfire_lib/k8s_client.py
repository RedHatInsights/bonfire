"""Kubernetes API client for ephemeral resource CRDs.

Uses the kubernetes Python client directly (no ocviapy/oc dependency).
Supports three auth modes: explicit server+token, in-cluster, kubeconfig.
"""

import atexit
import base64
import logging
import os
import tempfile

from kubernetes import client, config
from kubernetes.client import ApiException
from kubernetes.dynamic import DynamicClient

log = logging.getLogger(__name__)

CRD_API_VERSION = "cloud.redhat.com/v1alpha1"

DEFAULT_READ_TIMEOUT = 30
DEFAULT_WRITE_TIMEOUT = 60


def _sanitize_username(name: str) -> str:
    """Sanitize a username for use as a K8s label value.

    Matches bonfire's existing sanitization in openshift.py:whoami().
    """
    return name.replace("@", "_at_").replace(":", "_")


def _extract_username(context_user: str) -> str:
    """Extract the username from a kubeconfig context user string.

    Kubeconfig context user strings often include the cluster API URL
    (e.g., 'gbuchana/api-crc-eph-r9lp-p1-openshiftapps-com:6443').
    This extracts just the username part before the first '/'.
    """
    if "/" in context_user:
        return context_user.split("/")[0]
    return context_user


class EphemeralK8sClient:
    """Kubernetes API client for ephemeral resource CRDs.

    Supports three auth modes (auto-detected in priority order):
    1. Explicit server + token
    2. In-cluster service account
    3. Kubeconfig file
    """

    def __init__(
        self,
        kubeconfig_path: str | None = None,
        context: str | None = None,
        server: str | None = None,
        token: str | None = None,
        ca_data: str | None = None,
        skip_tls: bool = False,
    ):
        self._auth_mode = "kubeconfig"
        if server and token:
            self._auth_mode = "token"
            configuration = client.Configuration()
            configuration.host = server
            configuration.api_key = {"authorization": f"Bearer {token}"}
            if skip_tls:
                configuration.verify_ssl = False
            elif ca_data:
                ca_file = tempfile.NamedTemporaryFile(delete=False, suffix=".crt")
                ca_file.write(base64.b64decode(ca_data))
                ca_file.close()
                configuration.ssl_ca_cert = ca_file.name
                atexit.register(os.unlink, ca_file.name)
            self._api_client = client.ApiClient(configuration)
        elif self._is_in_cluster():
            self._auth_mode = "in-cluster"
            config.load_incluster_config()
            self._api_client = client.ApiClient()
        else:
            config.load_kube_config(
                config_file=kubeconfig_path,
                context=context,
            )
            self._api_client = client.ApiClient()

        self._dynamic = DynamicClient(self._api_client)
        self._core_v1 = client.CoreV1Api(self._api_client)

    @staticmethod
    def _is_in_cluster() -> bool:
        """Check if running inside a Kubernetes pod."""
        return os.path.exists("/var/run/secrets/kubernetes.io/serviceaccount/token")

    def _get_resource(self, kind: str):
        """Get a DynamicClient resource handle for a cloud.redhat.com/v1alpha1 CRD."""
        return self._dynamic.resources.get(api_version=CRD_API_VERSION, kind=kind)

    # --- NamespaceReservation operations ---

    def create_reservation(self, body: dict) -> dict:
        """Create a NamespaceReservation CR."""
        resource = self._get_resource("NamespaceReservation")
        return resource.create(body=body, _request_timeout=DEFAULT_WRITE_TIMEOUT).to_dict()

    def get_reservation(self, name: str) -> dict | None:
        """Get a NamespaceReservation by name. Returns None if not found."""
        resource = self._get_resource("NamespaceReservation")
        try:
            return resource.get(name=name, _request_timeout=DEFAULT_READ_TIMEOUT).to_dict()
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    def list_reservations(self, label_selector: str | None = None) -> list[dict]:
        """List all NamespaceReservation CRs."""
        resource = self._get_resource("NamespaceReservation")
        kwargs = {"_request_timeout": DEFAULT_READ_TIMEOUT}
        if label_selector:
            kwargs["label_selector"] = label_selector
        return [item.to_dict() for item in resource.get(**kwargs).items]

    def patch_reservation(self, name: str, body: dict) -> dict:
        """Patch a NamespaceReservation CR (merge patch)."""
        resource = self._get_resource("NamespaceReservation")
        return resource.patch(
            name=name,
            body=body,
            content_type="application/merge-patch+json",
            _request_timeout=DEFAULT_WRITE_TIMEOUT,
        ).to_dict()

    # --- NamespacePool operations ---

    def list_pools(self) -> list[dict]:
        """List all NamespacePool CRs."""
        resource = self._get_resource("NamespacePool")
        return [
            item.to_dict() for item in resource.get(_request_timeout=DEFAULT_READ_TIMEOUT).items
        ]

    def get_pool(self, name: str) -> dict | None:
        """Get a NamespacePool by name."""
        resource = self._get_resource("NamespacePool")
        try:
            return resource.get(name=name, _request_timeout=DEFAULT_READ_TIMEOUT).to_dict()
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    # --- ClusterReservation operations ---

    def create_cluster_reservation(self, body: dict) -> dict:
        """Create a ClusterReservation CR."""
        resource = self._get_resource("ClusterReservation")
        return resource.create(body=body, _request_timeout=DEFAULT_WRITE_TIMEOUT).to_dict()

    def get_cluster_reservation(self, name: str) -> dict | None:
        """Get a ClusterReservation by name. Returns None if not found."""
        resource = self._get_resource("ClusterReservation")
        try:
            return resource.get(name=name, _request_timeout=DEFAULT_READ_TIMEOUT).to_dict()
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    def list_cluster_reservations(self, label_selector: str | None = None) -> list[dict]:
        """List all ClusterReservation CRs."""
        resource = self._get_resource("ClusterReservation")
        kwargs = {"_request_timeout": DEFAULT_READ_TIMEOUT}
        if label_selector:
            kwargs["label_selector"] = label_selector
        return [item.to_dict() for item in resource.get(**kwargs).items]

    def patch_cluster_reservation(self, name: str, body: dict) -> dict:
        """Patch a ClusterReservation CR (merge patch)."""
        resource = self._get_resource("ClusterReservation")
        return resource.patch(
            name=name,
            body=body,
            content_type="application/merge-patch+json",
            _request_timeout=DEFAULT_WRITE_TIMEOUT,
        ).to_dict()

    # --- ClusterPool operations ---

    def list_cluster_pools(self) -> list[dict]:
        """List all ClusterPool CRs."""
        resource = self._get_resource("ClusterPool")
        return [
            item.to_dict() for item in resource.get(_request_timeout=DEFAULT_READ_TIMEOUT).items
        ]

    def get_cluster_pool(self, name: str) -> dict | None:
        """Get a ClusterPool by name."""
        resource = self._get_resource("ClusterPool")
        try:
            return resource.get(name=name, _request_timeout=DEFAULT_READ_TIMEOUT).to_dict()
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    # --- Namespace operations (via CoreV1Api) ---

    def get_namespace(self, name: str) -> dict | None:
        """Get a namespace by name."""
        try:
            return self._core_v1.read_namespace(
                name=name, _request_timeout=DEFAULT_READ_TIMEOUT
            ).to_dict()
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    def get_configmap(self, name: str, namespace: str) -> dict | None:
        """Get a ConfigMap by name and namespace."""
        try:
            return self._core_v1.read_namespaced_config_map(
                name=name, namespace=namespace, _request_timeout=DEFAULT_READ_TIMEOUT
            ).to_dict()
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    def get_secret(self, name: str, namespace: str) -> dict | None:
        """Get a Secret by name and namespace."""
        try:
            return self._core_v1.read_namespaced_secret(
                name=name, namespace=namespace, _request_timeout=DEFAULT_READ_TIMEOUT
            ).to_dict()
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    def list_namespaces(self, label_selector: str | None = None) -> list[dict]:
        """List namespaces, optionally filtered by label."""
        kwargs = {"_request_timeout": DEFAULT_READ_TIMEOUT}
        if label_selector:
            kwargs["label_selector"] = label_selector
        return [item.to_dict() for item in self._core_v1.list_namespace(**kwargs).items]

    # --- Generic CRD operations (for ClowdApp, Frontend, etc.) ---

    def list_crds(self, kind: str, namespace: str | None = None) -> list[dict]:
        """List CRDs of a given kind, optionally in a namespace."""
        resource = self._get_resource(kind)
        kwargs = {"_request_timeout": DEFAULT_READ_TIMEOUT}
        if namespace:
            kwargs["namespace"] = namespace
        return [item.to_dict() for item in resource.get(**kwargs).items]

    def get_crd(self, kind: str, name: str, namespace: str | None = None) -> dict | None:
        """Get a single CRD by kind and name."""
        resource = self._get_resource(kind)
        try:
            kwargs = {"name": name, "_request_timeout": DEFAULT_READ_TIMEOUT}
            if namespace:
                kwargs["namespace"] = namespace
            return resource.get(**kwargs).to_dict()
        except ApiException as e:
            if e.status == 404:
                return None
            raise

    # --- Identity ---

    def whoami(self) -> str:
        """Get the current authenticated user identity.

        For token auth: uses TokenReview to resolve the token's identity.
        For kubeconfig auth: reads the user from the active context.
        For in-cluster auth: uses TokenReview with the service account token.
        Falls back to 'unknown' if identity cannot be determined.

        The returned name is sanitized for use as a K8s label value:
        '@' -> '_at_', ':' -> '_'
        """
        if self._auth_mode == "kubeconfig":
            try:
                _, active_context = config.list_kube_config_contexts()
                if active_context:
                    user = active_context.get("context", {}).get("user", "")
                    if user:
                        return _sanitize_username(_extract_username(user))
            except config.ConfigException:
                pass

        try:
            auth_v1 = client.AuthenticationV1Api(self._api_client)
            review = auth_v1.create_token_review(
                body=client.V1TokenReview(
                    spec=client.V1TokenReviewSpec(
                        token=self._api_client.configuration.api_key.get(
                            "authorization", ""
                        ).replace("Bearer ", "")
                    )
                ),
                _request_timeout=DEFAULT_READ_TIMEOUT,
            )
            username = review.status.user.username
            if username:
                return _sanitize_username(username)
        except Exception:
            pass

        return "unknown"

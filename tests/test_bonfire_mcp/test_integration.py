"""Integration tests for the ephemeral MCP tool flow.

These tests require a live Kubernetes cluster with the ephemeral namespace
operator installed. They are skipped by default and run with:

    pytest -m integration tests/test_bonfire_mcp/test_integration.py -sv

Required environment:
    - KUBECONFIG pointing to a valid kubeconfig, OR
    - K8S_SERVER + K8S_TOKEN set for direct auth
"""

import logging
import os
import time

import pytest

from bonfire_lib.k8s_client import EphemeralK8sClient
from bonfire_lib.utils import FatalError

log = logging.getLogger(__name__)

pytestmark = pytest.mark.integration

_INTEGRATION_POOL = os.getenv("INTEGRATION_TEST_POOL", "default")
_INTEGRATION_TIMEOUT = int(os.getenv("INTEGRATION_TEST_TIMEOUT", "300"))


def _has_cluster_config() -> bool:
    if os.getenv("K8S_SERVER") and os.getenv("K8S_TOKEN"):
        return True
    if os.getenv("KUBECONFIG"):
        return True
    kubeconfig = os.path.expanduser("~/.kube/config")
    return os.path.exists(kubeconfig)


requires_cluster = pytest.mark.skipif(
    not _has_cluster_config(),
    reason="No KUBECONFIG or K8S_SERVER+K8S_TOKEN set; skipping integration tests",
)


@pytest.fixture(scope="module")
def client():
    """Create a real EphemeralK8sClient from environment configuration."""
    server = os.getenv("K8S_SERVER")
    token = os.getenv("K8S_TOKEN")
    ca_data = os.getenv("K8S_CA_DATA")
    skip_tls = os.getenv("K8S_SKIP_TLS_VERIFY", "false").lower() == "true"

    if server and token:
        return EphemeralK8sClient(server=server, token=token, ca_data=ca_data, skip_tls=skip_tls)
    return EphemeralK8sClient()


@pytest.fixture
def reservation_cleanup(client):
    """Track reservation names and release any that remain after the test."""
    created = []
    yield created
    for res_name in created:
        try:
            from bonfire_lib.reservations import release

            release(client, name=res_name)
        except Exception as exc:
            log.warning("cleanup: failed to release reservation '%s': %s", res_name, exc)


@requires_cluster
class TestEphemeralMCPFlow:
    """Full MCP tool flow: list_pools -> reserve -> status -> extend -> release."""

    def test_list_pools(self, client):
        from bonfire_lib.pools import list_pools

        pools = list_pools(client)
        assert isinstance(pools, list)
        assert len(pools) > 0
        pool_names = [p["name"] for p in pools]
        assert _INTEGRATION_POOL in pool_names, (
            f"Expected pool '{_INTEGRATION_POOL}' not found. Available: {pool_names}"
        )

    def test_get_pool_capacity(self, client):
        from bonfire_lib.pools import get_pool_capacity

        cap = get_pool_capacity(client, _INTEGRATION_POOL)
        assert cap is not None
        assert cap["name"] == _INTEGRATION_POOL
        assert "ready" in cap
        assert "size" in cap

    def test_reserve_status_extend_release(self, client, reservation_cleanup):
        from bonfire_lib.reservations import reserve, extend, release
        from bonfire_lib.status import get_reservation, list_reservations

        result = reserve(
            client,
            duration="1h",
            pool=_INTEGRATION_POOL,
            timeout=_INTEGRATION_TIMEOUT,
        )
        res_name = result["name"]
        reservation_cleanup.append(res_name)

        assert result["namespace"], "Expected namespace to be assigned"
        assert result["pool"] == _INTEGRATION_POOL

        res = get_reservation(client, name=res_name)
        assert res is not None
        assert res["status"]["state"] == "active"

        all_res = list_reservations(client)
        found = [r for r in all_res if r["name"] == res_name]
        assert len(found) == 1

        ext_result = extend(client, namespace=result["namespace"], duration="30m")
        assert ext_result["name"] == res_name
        assert ext_result["new_duration"] == "1h30m0s"

        rel_result = release(client, name=res_name)
        assert rel_result["released"] is True
        reservation_cleanup.remove(res_name)

    def test_describe_namespace(self, client, reservation_cleanup):
        from bonfire_lib.reservations import reserve, release
        from bonfire_lib.status import describe_namespace

        result = reserve(
            client,
            duration="1h",
            pool=_INTEGRATION_POOL,
            timeout=_INTEGRATION_TIMEOUT,
        )
        res_name = result["name"]
        reservation_cleanup.append(res_name)

        ns_name = result["namespace"]
        time.sleep(5)

        info = describe_namespace(client, ns_name)
        assert info["namespace"] == ns_name
        assert "clowdapps_deployed" in info
        assert "frontends_deployed" in info

        release(client, name=res_name)
        reservation_cleanup.remove(res_name)

    def test_reserve_duplicate_name_fails(self, client, reservation_cleanup):
        from bonfire_lib.reservations import reserve

        result = reserve(
            client,
            duration="1h",
            pool=_INTEGRATION_POOL,
            timeout=_INTEGRATION_TIMEOUT,
        )
        res_name = result["name"]
        reservation_cleanup.append(res_name)

        with pytest.raises(FatalError, match="already exists"):
            reserve(
                client,
                name=res_name,
                duration="1h",
                pool=_INTEGRATION_POOL,
            )

    def test_get_console_url(self, client):
        from bonfire_lib.status import get_console_url

        url = get_console_url(client)
        # May be None if cluster doesn't have console-public configmap
        if url:
            assert url.startswith("http")

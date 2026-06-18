"""Tests for bonfire_mcp.server module — tool definitions and dispatch."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bonfire_mcp.server import call_tool, list_tools, TOOLS
from mcp.types import CallToolResult


class TestToolDefinitions:
    @pytest.mark.asyncio
    async def test_list_tools_returns_all(self):
        tools = await list_tools()
        names = {t.name for t in tools}
        assert names == {
            "ephemeral_list_pools",
            "ephemeral_reserve",
            "ephemeral_status",
            "ephemeral_extend",
            "ephemeral_release",
            "ephemeral_list_reservations",
            "ephemeral_describe",
            "ephemeral_get_kubeconfig",
            "ephemeral_deploy_rosa",
        }

    @pytest.mark.asyncio
    async def test_all_tools_have_descriptions(self):
        tools = await list_tools()
        for tool in tools:
            assert tool.description, f"Tool {tool.name} has no description"

    @pytest.mark.asyncio
    async def test_all_tools_have_input_schemas(self):
        tools = await list_tools()
        for tool in tools:
            assert tool.inputSchema, f"Tool {tool.name} has no inputSchema"
            assert tool.inputSchema["type"] == "object"

    def test_reserve_tool_has_type_param(self):
        reserve = next(t for t in TOOLS if t.name == "ephemeral_reserve")
        props = reserve.inputSchema["properties"]
        assert "type" in props
        assert props["type"]["enum"] == ["default_namespace", "rosa_cluster"]

    def test_list_pools_type_enum(self):
        tool = next(t for t in TOOLS if t.name == "ephemeral_list_pools")
        props = tool.inputSchema["properties"]
        assert props["type"]["enum"] == ["default_namespace", "rosa_cluster", "all"]

    def test_list_reservations_type_enum(self):
        tool = next(t for t in TOOLS if t.name == "ephemeral_list_reservations")
        props = tool.inputSchema["properties"]
        assert props["type"]["enum"] == ["default_namespace", "rosa_cluster", "all"]

    def test_get_kubeconfig_requires_name(self):
        tool = next(t for t in TOOLS if t.name == "ephemeral_get_kubeconfig")
        assert "name" in tool.inputSchema.get("required", [])

    def test_describe_tool_requires_namespace(self):
        describe = next(t for t in TOOLS if t.name == "ephemeral_describe")
        assert "namespace" in describe.inputSchema.get("required", [])

    def test_deploy_rosa_has_no_name_param(self):
        tool = next(t for t in TOOLS if t.name == "ephemeral_deploy_rosa")
        assert "name" not in tool.inputSchema["properties"]

    def test_deploy_rosa_has_duration_param(self):
        tool = next(t for t in TOOLS if t.name == "ephemeral_deploy_rosa")
        assert "duration" in tool.inputSchema["properties"]

    def test_deploy_rosa_has_timeout_param(self):
        tool = next(t for t in TOOLS if t.name == "ephemeral_deploy_rosa")
        assert "timeout" in tool.inputSchema["properties"]


class TestNamespaceToolDispatch:
    @pytest.fixture(autouse=True)
    def setup_mock_client(self):
        self.mock_client = MagicMock()
        with patch("bonfire_mcp.server._get_client", return_value=self.mock_client):
            yield

    @pytest.mark.asyncio
    async def test_list_pools_default_namespace(self):
        with patch("bonfire_mcp.server.pools") as mock_pools:
            mock_pools.list_pools.return_value = [
                {
                    "name": "default",
                    "ready": 3,
                    "creating": 0,
                    "reserved": 1,
                    "size": 5,
                    "size_limit": 10,
                }
            ]
            result = await call_tool("ephemeral_list_pools", {"type": "default_namespace"})
            assert "default" in result[0].text
            mock_pools.list_pools.assert_called_once_with(self.mock_client)

    @pytest.mark.asyncio
    async def test_list_pools_all(self):
        with patch("bonfire_mcp.server.pools") as mock_pools:
            mock_pools.list_pools.return_value = [
                {
                    "name": "default",
                    "ready": 3,
                    "creating": 0,
                    "reserved": 1,
                    "size": 5,
                    "size_limit": 10,
                }
            ]
            result = await call_tool("ephemeral_list_pools", {})
            assert "default" in result[0].text

    @pytest.mark.asyncio
    async def test_list_pools_rosa_cluster(self):
        with patch("bonfire_mcp.server.pools") as mock_pools:
            mock_pools.list_pools.return_value = [
                {"name": "rosa", "ready": 2, "creating": 0, "reserved": 1, "size": 3},
                {"name": "default", "ready": 3, "creating": 0, "reserved": 1, "size": 5},
            ]
            result = await call_tool("ephemeral_list_pools", {"type": "rosa_cluster"})
            assert "rosa" in result[0].text

    @pytest.mark.asyncio
    async def test_reserve_default_namespace(self):
        with patch("bonfire_mcp.server.reservations") as mock_res:
            mock_res.reserve.return_value = {
                "name": "my-res",
                "namespace": "ephemeral-xyz",
                "state": "active",
                "expiration": "2026-04-09T13:00:00Z",
                "requester": "user",
                "pool": "default",
            }
            result = await call_tool("ephemeral_reserve", {"name": "my-res", "duration": "1h"})
            assert "my-res" in result[0].text
            assert "ephemeral-xyz" in result[0].text

    @pytest.mark.asyncio
    async def test_reserve_rosa_cluster_uses_rosa_pool(self):
        with patch("bonfire_mcp.server.reservations") as mock_res:
            mock_res.reserve.return_value = {
                "name": "my-rosa-res",
                "namespace": "ephemeral-rosa-abc",
                "state": "active",
                "expiration": "2026-04-09T13:00:00Z",
                "requester": "user",
                "pool": "rosa",
            }
            result = await call_tool(
                "ephemeral_reserve",
                {"type": "rosa_cluster", "name": "my-rosa-res", "duration": "2h"},
            )
            assert "my-rosa-res" in result[0].text
            # Verify the pool used was "rosa"
            call_kwargs = mock_res.reserve.call_args
            assert call_kwargs.kwargs.get("pool") == "rosa"

    @pytest.mark.asyncio
    async def test_reserve_invalid_name(self):
        result = await call_tool("ephemeral_reserve", {"name": "INVALID_NAME"})
        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert "Validation error" in result.content[0].text

    @pytest.mark.asyncio
    async def test_status_by_name(self):
        with patch("bonfire_mcp.server.status") as mock_status:
            raw_res = {
                "metadata": {"name": "my-res"},
                "spec": {"requester": "user", "pool": "default"},
                "status": {
                    "state": "active",
                    "namespace": "ns-1",
                    "expiration": "2026-04-09T13:00:00Z",
                },
            }
            mock_status.get_reservation.return_value = raw_res
            mock_status.get_reservation_summary.return_value = {
                "name": "my-res",
                "namespace": "ns-1",
                "state": "active",
                "expiration": "2026-04-09T13:00:00Z",
                "requester": "user",
                "pool": "default",
            }
            result = await call_tool("ephemeral_status", {"name": "my-res"})
            assert "my-res" in result[0].text
            assert "active" in result[0].text

    @pytest.mark.asyncio
    async def test_status_not_found(self):
        with patch("bonfire_mcp.server.status") as mock_status:
            mock_status.get_reservation.return_value = None
            result = await call_tool("ephemeral_status", {"name": "nonexistent"})
            assert "No reservation found" in result[0].text

    @pytest.mark.asyncio
    async def test_extend_namespace(self):
        with patch("bonfire_mcp.server.reservations") as mock_res:
            mock_res.extend.return_value = {"name": "my-res", "new_duration": "2h0m0s"}
            result = await call_tool("ephemeral_extend", {"namespace": "ns-1", "duration": "1h"})
            assert "2h0m0s" in result[0].text

    @pytest.mark.asyncio
    async def test_extend_requires_namespace(self):
        result = await call_tool("ephemeral_extend", {"duration": "1h"})
        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert "Error" in result.content[0].text

    @pytest.mark.asyncio
    async def test_release_namespace(self):
        with patch("bonfire_mcp.server.reservations") as mock_res:
            mock_res.release.return_value = {"name": "my-res", "released": True}
            result = await call_tool("ephemeral_release", {"name": "my-res"})
            assert "released" in result[0].text

    @pytest.mark.asyncio
    async def test_release_requires_name_or_namespace(self):
        result = await call_tool("ephemeral_release", {})
        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert "Error" in result.content[0].text

    @pytest.mark.asyncio
    async def test_list_reservations_all(self):
        with patch("bonfire_mcp.server.status") as mock_status:
            mock_status.list_reservations.return_value = [
                {
                    "name": "res-1",
                    "namespace": "ns-1",
                    "state": "active",
                    "requester": "user",
                    "pool": "default",
                    "duration": "1h",
                }
            ]
            result = await call_tool("ephemeral_list_reservations", {})
            assert "res-1" in result[0].text

    @pytest.mark.asyncio
    async def test_list_reservations_rosa_cluster_filters_by_pool(self):
        with patch("bonfire_mcp.server.status") as mock_status:
            mock_status.list_reservations.return_value = [
                {"name": "res-1", "namespace": "ns-1", "state": "active", "pool": "default"},
                {"name": "res-rosa", "namespace": "ns-rosa", "state": "active", "pool": "rosa"},
            ]
            result = await call_tool("ephemeral_list_reservations", {"type": "rosa_cluster"})
            assert "res-rosa" in result[0].text
            assert "res-1" not in result[0].text

    @pytest.mark.asyncio
    async def test_describe(self):
        with patch("bonfire_mcp.server.status") as mock_status:
            mock_status.describe_namespace.return_value = {
                "namespace": "ns-1",
                "console_namespace_route": "https://console/ns-1",
                "clowdapps_deployed": 2,
                "frontends_deployed": 1,
            }
            result = await call_tool("ephemeral_describe", {"namespace": "ns-1"})
            assert "ns-1" in result[0].text

    @pytest.mark.asyncio
    async def test_get_kubeconfig(self):
        with patch("bonfire_mcp.server.reservations") as mock_res:
            mock_res.get_kubeconfig.return_value = (
                "apiVersion: v1\nclusters:\n- cluster:\n    server: https://api.example.com:6443"
            )
            result = await call_tool("ephemeral_get_kubeconfig", {"name": "my-rosa"})
            assert "apiVersion: v1" in result[0].text
            assert "my-rosa" in result[0].text

    @pytest.mark.asyncio
    async def test_unknown_tool(self):
        result = await call_tool("nonexistent_tool", {})
        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert "Unknown tool" in result.content[0].text

    @pytest.mark.asyncio
    async def test_fatal_error_handling(self):
        from bonfire_lib.utils import FatalError

        with patch("bonfire_mcp.server.reservations") as mock_res:
            mock_res.reserve.side_effect = FatalError("already exists")
            result = await call_tool("ephemeral_reserve", {"name": "dup"})
            assert isinstance(result, CallToolResult)
            assert result.isError is True
            assert "Error" in result.content[0].text
            assert "already exists" in result.content[0].text

    @pytest.mark.asyncio
    async def test_timeout_error_handling(self):
        with patch("bonfire_mcp.server.reservations") as mock_res:
            mock_res.reserve.side_effect = TimeoutError("timed out")
            result = await call_tool("ephemeral_reserve", {"name": "slow"})
            assert isinstance(result, CallToolResult)
            assert result.isError is True
            assert "Timeout" in result.content[0].text


class TestDeployRosa:
    @pytest.fixture(autouse=True)
    def setup_mock_client(self):
        self.mock_client = MagicMock()
        with patch("bonfire_mcp.server._get_client", return_value=self.mock_client):
            yield

    @pytest.mark.asyncio
    async def test_deploy_rosa_success(self):
        """Test successful rosa deployment — mock subprocess and describe_namespace."""
        mock_proc = MagicMock()
        mock_proc.returncode = 0
        mock_proc.communicate = AsyncMock(
            return_value=(
                b"Deploying rosa...\nephemeral-rosa-abc\n",
                b"",
            )
        )

        describe_result = {
            "namespace": "ephemeral-rosa-abc",
            "console_namespace_route": "https://console.example.com/k8s/cluster/projects/ephemeral-rosa-abc",
            "gateway_route": "https://my-gateway.example.com",
            "clowdapps_deployed": 3,
            "frontends_deployed": 2,
            "keycloak_admin_route": "https://keycloak.example.com",
            "keycloak_admin_username": "admin",
            "keycloak_admin_password": "secret",
            "default_username": "user@example.com",
            "default_password": "userpass",
        }

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("bonfire_mcp.server.status") as mock_status:
                mock_status.describe_namespace.return_value = describe_result
                result = await call_tool(
                    "ephemeral_deploy_rosa",
                    {"duration": "2h", "timeout": 1800},
                )

        assert not isinstance(result, CallToolResult) or not result.isError
        text = result[0].text
        assert "ROSA Cluster Deployed" in text
        assert "ephemeral-rosa-abc" in text

    @pytest.mark.asyncio
    async def test_deploy_rosa_failure(self):
        """Test that non-zero exit code returns isError=True."""
        mock_proc = MagicMock()
        mock_proc.returncode = 1
        mock_proc.communicate = AsyncMock(
            return_value=(
                b"",
                b"bonfire deploy rosa: error: no namespace available in pool\n",
            )
        )

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            result = await call_tool(
                "ephemeral_deploy_rosa",
                {"duration": "2h"},
            )

        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert "Error" in result.content[0].text
        assert "failed" in result.content[0].text

    @pytest.mark.asyncio
    async def test_deploy_rosa_invalid_duration(self):
        """Test that an invalid duration string returns a validation error."""
        result = await call_tool(
            "ephemeral_deploy_rosa",
            {"duration": "not-a-duration"},
        )
        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert "Validation error" in result.content[0].text

    @pytest.mark.asyncio
    async def test_deploy_rosa_timeout(self):
        """Test that subprocess timeout returns a Timeout error."""
        import asyncio as _asyncio

        mock_proc = MagicMock()
        mock_proc.returncode = None
        mock_proc.kill = MagicMock()
        # communicate is an AsyncMock that blocks, but wait_for will raise before it resolves
        mock_proc.communicate = AsyncMock(side_effect=_asyncio.TimeoutError())

        with patch("asyncio.create_subprocess_exec", return_value=mock_proc):
            with patch("asyncio.wait_for", side_effect=_asyncio.TimeoutError()):
                result = await call_tool(
                    "ephemeral_deploy_rosa",
                    {"duration": "2h", "timeout": 1},
                )

        assert isinstance(result, CallToolResult)
        assert result.isError is True
        assert "Timeout" in result.content[0].text

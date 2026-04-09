"""Tests for bonfire_mcp.server module — tool definitions and dispatch."""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from bonfire_mcp.server import app, call_tool, list_tools, TOOLS


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

    def test_reserve_tool_schema(self):
        reserve = next(t for t in TOOLS if t.name == "ephemeral_reserve")
        props = reserve.inputSchema["properties"]
        assert "name" in props
        assert "duration" in props
        assert "pool" in props
        assert "requester" in props
        assert "team" in props
        assert "timeout" in props

    def test_extend_tool_requires_namespace_and_duration(self):
        extend = next(t for t in TOOLS if t.name == "ephemeral_extend")
        assert "namespace" in extend.inputSchema.get("required", [])
        assert "duration" in extend.inputSchema.get("required", [])

    def test_describe_tool_requires_namespace(self):
        describe = next(t for t in TOOLS if t.name == "ephemeral_describe")
        assert "namespace" in describe.inputSchema.get("required", [])


class TestToolDispatch:
    @pytest.fixture(autouse=True)
    def setup_mock_client(self):
        self.mock_client = MagicMock()
        with patch("bonfire_mcp.server._get_client", return_value=self.mock_client):
            yield

    @pytest.mark.asyncio
    async def test_list_pools(self):
        with patch("bonfire_mcp.server.pools") as mock_pools:
            mock_pools.list_pools.return_value = [
                {"name": "default", "ready": 3, "creating": 0, "reserved": 1, "size": 5, "size_limit": 10}
            ]
            result = await call_tool("ephemeral_list_pools", {})
            assert len(result) == 1
            assert "default" in result[0].text
            mock_pools.list_pools.assert_called_once_with(self.mock_client)

    @pytest.mark.asyncio
    async def test_reserve(self):
        with patch("bonfire_mcp.server.reservations") as mock_res:
            mock_res.reserve.return_value = {
                "name": "my-res",
                "namespace": "ephemeral-xyz",
                "state": "active",
                "expiration": "2026-04-09T13:00:00Z",
                "requester": "user",
                "pool": "default",
            }
            result = await call_tool("ephemeral_reserve", {
                "name": "my-res",
                "duration": "1h",
                "pool": "default",
            })
            assert "my-res" in result[0].text
            assert "ephemeral-xyz" in result[0].text

    @pytest.mark.asyncio
    async def test_reserve_invalid_name(self):
        result = await call_tool("ephemeral_reserve", {"name": "INVALID_NAME"})
        assert "Validation error" in result[0].text

    @pytest.mark.asyncio
    async def test_status_by_name(self):
        with patch("bonfire_mcp.server.status") as mock_status:
            mock_status.get_reservation.return_value = {
                "metadata": {"name": "my-res"},
                "spec": {"requester": "user", "pool": "default"},
                "status": {"state": "active", "namespace": "ns-1", "expiration": "2026-04-09T13:00:00Z"},
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
    async def test_status_missing_args(self):
        result = await call_tool("ephemeral_status", {})
        assert "Error" in result[0].text

    @pytest.mark.asyncio
    async def test_extend(self):
        with patch("bonfire_mcp.server.reservations") as mock_res:
            mock_res.extend.return_value = {"name": "my-res", "new_duration": "2h0m0s"}
            result = await call_tool("ephemeral_extend", {
                "namespace": "ns-1",
                "duration": "1h",
            })
            assert "2h0m0s" in result[0].text

    @pytest.mark.asyncio
    async def test_release_by_name(self):
        with patch("bonfire_mcp.server.reservations") as mock_res:
            mock_res.release.return_value = {"name": "my-res", "released": True}
            result = await call_tool("ephemeral_release", {"name": "my-res"})
            assert "released" in result[0].text

    @pytest.mark.asyncio
    async def test_release_missing_args(self):
        result = await call_tool("ephemeral_release", {})
        assert "Error" in result[0].text

    @pytest.mark.asyncio
    async def test_list_reservations(self):
        with patch("bonfire_mcp.server.status") as mock_status:
            mock_status.list_reservations.return_value = [
                {"name": "r1", "namespace": "ns-1", "state": "active", "requester": "u1", "pool": "default", "duration": "1h"},
            ]
            result = await call_tool("ephemeral_list_reservations", {})
            assert "r1" in result[0].text

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
    async def test_unknown_tool(self):
        result = await call_tool("nonexistent_tool", {})
        assert "Unknown tool" in result[0].text

    @pytest.mark.asyncio
    async def test_fatal_error_handling(self):
        from bonfire_lib.utils import FatalError

        with patch("bonfire_mcp.server.reservations") as mock_res:
            mock_res.reserve.side_effect = FatalError("already exists")
            result = await call_tool("ephemeral_reserve", {"name": "dup"})
            assert "Error" in result[0].text
            assert "already exists" in result[0].text

    @pytest.mark.asyncio
    async def test_timeout_error_handling(self):
        with patch("bonfire_mcp.server.reservations") as mock_res:
            mock_res.reserve.side_effect = TimeoutError("timed out")
            result = await call_tool("ephemeral_reserve", {"name": "slow"})
            assert "Timeout" in result[0].text

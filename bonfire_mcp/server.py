"""MCP server for ephemeral environment operations.

Exposes reservation lifecycle (reserve, release, extend, list, status)
as MCP tools usable by any MCP-compatible AI agent.
"""

import logging

from mcp.server import Server
from mcp.types import TextContent, Tool

from bonfire_lib.config import Settings
from bonfire_lib.k8s_client import EphemeralK8sClient
from bonfire_lib.utils import FatalError, validate_dns_name
import bonfire_lib.reservations as reservations
import bonfire_lib.pools as pools
import bonfire_lib.status as status

from bonfire_mcp.auth import load_k8s_client
from bonfire_mcp.formatters import (
    format_describe,
    format_extend,
    format_pool_list,
    format_release,
    format_reservation,
    format_reservation_list,
)

log = logging.getLogger(__name__)

app = Server("bonfire-mcp")

_client: EphemeralK8sClient | None = None
_settings: Settings | None = None


def _get_client() -> EphemeralK8sClient:
    global _client
    if _client is None:
        _client = load_k8s_client()
    return _client


def _get_settings() -> Settings:
    global _settings
    if _settings is None:
        _settings = Settings.from_env()
    return _settings


TOOLS = [
    Tool(
        name="ephemeral_list_pools",
        description=(
            "List available ephemeral namespace pools with capacity stats "
            "(ready, creating, reserved counts and size limits)."
        ),
        inputSchema={
            "type": "object",
            "properties": {},
        },
    ),
    Tool(
        name="ephemeral_reserve",
        description=(
            "Reserve an ephemeral namespace from a pool. "
            "Creates a NamespaceReservation CR and waits for the operator to assign a namespace. "
            "Returns the reservation details including the assigned namespace name."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": (
                        "Reservation name (DNS-1123 label: lowercase alphanumeric + hyphens, "
                        "1-63 chars). Auto-generated if omitted."
                    ),
                },
                "duration": {
                    "type": "string",
                    "description": "Duration (e.g., '1h', '2h30m', '45m'). Default: '1h'.",
                    "default": "1h",
                },
                "pool": {
                    "type": "string",
                    "description": "Pool to reserve from. Default: 'default'.",
                    "default": "default",
                },
                "requester": {
                    "type": "string",
                    "description": (
                        "Requester identity for the reservation. "
                        "Defaults to the authenticated K8s user."
                    ),
                },
                "team": {
                    "type": "string",
                    "description": "Team name for cost attribution (optional).",
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max seconds to wait for namespace assignment. Default: 600.",
                    "default": 600,
                },
            },
        },
    ),
    Tool(
        name="ephemeral_status",
        description=(
            "Get the status of a reservation by name or by namespace. "
            "Returns state, assigned namespace, expiration, requester, and pool."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Reservation name to look up.",
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace name to find the reservation for.",
                },
            },
        },
    ),
    Tool(
        name="ephemeral_extend",
        description=(
            "Extend the duration of an active reservation. "
            "Adds the specified duration to the reservation's current total."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Namespace of the reservation to extend.",
                },
                "duration": {
                    "type": "string",
                    "description": "Additional duration to add (e.g., '1h', '30m').",
                },
            },
            "required": ["namespace", "duration"],
        },
    ),
    Tool(
        name="ephemeral_release",
        description=(
            "Release an ephemeral reservation. "
            "The namespace will be reclaimed by the operator within ~10 seconds."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Reservation name to release.",
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace name to find and release the reservation for.",
                },
            },
        },
    ),
    Tool(
        name="ephemeral_list_reservations",
        description=(
            "List active reservations, optionally filtered by requester. "
            "Shows reservation name, namespace, state, expiration, and pool."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "requester": {
                    "type": "string",
                    "description": "Filter reservations by requester identity (optional).",
                },
            },
        },
    ),
    Tool(
        name="ephemeral_describe",
        description=(
            "Get detailed information about an ephemeral namespace including "
            "ClowdApp count, frontend count, console URL, gateway route, "
            "and keycloak credentials."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "namespace": {
                    "type": "string",
                    "description": "Namespace to describe.",
                },
            },
            "required": ["namespace"],
        },
    ),
]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent]:
    try:
        client = _get_client()

        if name == "ephemeral_list_pools":
            result = pools.list_pools(client)
            return [TextContent(type="text", text=format_pool_list(result))]

        elif name == "ephemeral_reserve":
            res_name = arguments.get("name")
            if res_name:
                validate_dns_name(res_name)
            result = reservations.reserve(
                client,
                name=res_name,
                duration=arguments.get("duration", "1h"),
                requester=arguments.get("requester"),
                pool=arguments.get("pool", "default"),
                team=arguments.get("team"),
                timeout=arguments.get("timeout", 600),
            )
            return [TextContent(type="text", text=format_reservation(result))]

        elif name == "ephemeral_status":
            res_name = arguments.get("name")
            namespace = arguments.get("namespace")
            if not res_name and not namespace:
                return [TextContent(
                    type="text",
                    text="Error: provide either 'name' or 'namespace' to look up a reservation.",
                )]
            res = status.get_reservation(client, name=res_name, namespace=namespace)
            if not res:
                return [TextContent(
                    type="text",
                    text=f"No reservation found for "
                    f"{'name=' + res_name if res_name else 'namespace=' + namespace}.",
                )]
            result = {
                "name": res["metadata"]["name"],
                "namespace": res.get("status", {}).get("namespace", ""),
                "state": res.get("status", {}).get("state", ""),
                "expiration": res.get("status", {}).get("expiration", ""),
                "requester": res.get("spec", {}).get("requester", ""),
                "pool": res.get("spec", {}).get("pool", "default"),
            }
            return [TextContent(type="text", text=format_reservation(result))]

        elif name == "ephemeral_extend":
            result = reservations.extend(
                client,
                namespace=arguments["namespace"],
                duration=arguments["duration"],
            )
            return [TextContent(type="text", text=format_extend(result))]

        elif name == "ephemeral_release":
            res_name = arguments.get("name")
            namespace = arguments.get("namespace")
            if not res_name and not namespace:
                return [TextContent(
                    type="text",
                    text="Error: provide either 'name' or 'namespace' to release a reservation.",
                )]
            result = reservations.release(client, name=res_name, namespace=namespace)
            return [TextContent(type="text", text=format_release(result))]

        elif name == "ephemeral_list_reservations":
            result = status.list_reservations(
                client,
                requester=arguments.get("requester"),
            )
            return [TextContent(type="text", text=format_reservation_list(result))]

        elif name == "ephemeral_describe":
            result = status.describe_namespace(client, arguments["namespace"])
            return [TextContent(type="text", text=format_describe(result))]

        else:
            return [TextContent(type="text", text=f"Unknown tool: {name}")]

    except FatalError as e:
        return [TextContent(type="text", text=f"Error: {e}")]
    except TimeoutError as e:
        return [TextContent(type="text", text=f"Timeout: {e}")]
    except ValueError as e:
        return [TextContent(type="text", text=f"Validation error: {e}")]
    except RuntimeError as e:
        return [TextContent(type="text", text=f"Connection error: {e}")]
    except Exception as e:
        log.exception("unexpected error in tool %s", name)
        return [TextContent(type="text", text=f"Unexpected error: {e}")]


async def run_server():
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main():
    import asyncio

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_server())

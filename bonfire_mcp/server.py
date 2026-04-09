"""MCP server for ephemeral environment operations.

Exposes reservation lifecycle (reserve, release, extend, list, status)
as MCP tools usable by any MCP-compatible AI agent. Supports both
namespace and cluster resource types with polymorphic dispatch.
"""

import logging

from mcp.server import Server
from mcp.types import TextContent, Tool

from bonfire_lib.config import Settings
from bonfire_lib.k8s_client import EphemeralK8sClient
from bonfire_lib.utils import FatalError, validate_dns_name
import bonfire_lib.reservations as reservations
import bonfire_lib.clusters as clusters
import bonfire_lib.pools as pools
import bonfire_lib.status as status

from bonfire_mcp.auth import load_k8s_client
from bonfire_mcp.formatters import (
    format_cluster_reservation,
    format_cluster_pool_list,
    format_describe,
    format_extend,
    format_kubeconfig,
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
            "List available ephemeral resource pools with capacity stats. "
            "Returns both namespace pools and cluster pools (if available)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["namespace", "cluster", "all"],
                    "description": "Filter by pool type. Default: 'all'.",
                    "default": "all",
                },
            },
        },
    ),
    Tool(
        name="ephemeral_reserve",
        description=(
            "Reserve an ephemeral resource (namespace or cluster). "
            "For namespaces: polls until assigned (seconds). "
            "For clusters: returns immediately — poll with ephemeral_status()."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["namespace", "cluster"],
                    "description": "Resource type. Default: 'namespace'.",
                    "default": "namespace",
                },
                "name": {
                    "type": "string",
                    "description": (
                        "Reservation name (DNS-1123 label: lowercase alphanumeric + hyphens, "
                        "1-63 chars). Auto-generated if omitted."
                    ),
                },
                "duration": {
                    "type": "string",
                    "description": (
                        "Duration (e.g., '1h', '2h30m'). "
                        "Default: '1h' for namespaces, '4h' for clusters."
                    ),
                },
                "pool": {
                    "type": "string",
                    "description": (
                        "Pool to reserve from. "
                        "Default: 'default' for namespaces, 'rosa-default' for clusters."
                    ),
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
                    "description": (
                        "Max seconds to wait for namespace assignment (namespace only). "
                        "Default: 600. Ignored for clusters."
                    ),
                    "default": 600,
                },
            },
        },
    ),
    Tool(
        name="ephemeral_status",
        description=(
            "Get the status of a reservation by name or by namespace. "
            "For clusters, shows state (waiting/provisioning/active), "
            "cluster name, and console URL."
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
                    "description": "Namespace name to find the reservation for (namespace type only).",
                },
                "type": {
                    "type": "string",
                    "enum": ["namespace", "cluster"],
                    "description": "Resource type. Default: 'namespace'.",
                    "default": "namespace",
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
                "name": {
                    "type": "string",
                    "description": "Reservation name (required for clusters).",
                },
                "namespace": {
                    "type": "string",
                    "description": "Namespace of the reservation to extend (namespace type only).",
                },
                "duration": {
                    "type": "string",
                    "description": "Additional duration to add (e.g., '1h', '30m').",
                },
                "type": {
                    "type": "string",
                    "enum": ["namespace", "cluster"],
                    "description": "Resource type. Default: 'namespace'.",
                    "default": "namespace",
                },
            },
            "required": ["duration"],
        },
    ),
    Tool(
        name="ephemeral_release",
        description=(
            "Release an ephemeral reservation. "
            "The resource will be reclaimed by the operator."
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
                    "description": "Namespace name to find and release (namespace type only).",
                },
                "type": {
                    "type": "string",
                    "enum": ["namespace", "cluster"],
                    "description": "Resource type. Default: 'namespace'.",
                    "default": "namespace",
                },
            },
        },
    ),
    Tool(
        name="ephemeral_list_reservations",
        description=(
            "List active reservations, optionally filtered by requester. "
            "Shows reservation name, assigned resource, state, and pool."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "requester": {
                    "type": "string",
                    "description": "Filter reservations by requester identity (optional).",
                },
                "type": {
                    "type": "string",
                    "enum": ["namespace", "cluster", "all"],
                    "description": "Filter by reservation type. Default: 'all'.",
                    "default": "all",
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
    Tool(
        name="ephemeral_get_kubeconfig",
        description=(
            "Fetch kubeconfig YAML for a provisioned ROSA HCP cluster reservation. "
            "The cluster must be in 'active' state. Use ephemeral_status() to check."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "name": {
                    "type": "string",
                    "description": "Cluster reservation name.",
                },
            },
            "required": ["name"],
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
        resource_type = arguments.get("type", "namespace")

        if name == "ephemeral_list_pools":
            if resource_type == "cluster":
                result = pools.list_cluster_pools(client)
                return [TextContent(type="text", text=format_cluster_pool_list(result))]
            elif resource_type == "namespace":
                result = pools.list_pools(client)
                return [TextContent(type="text", text=format_pool_list(result))]
            else:
                ns_pools = pools.list_pools(client)
                cl_pools = pools.list_cluster_pools(client)
                text = format_pool_list(ns_pools)
                if cl_pools:
                    text += "\n\n" + format_cluster_pool_list(cl_pools)
                return [TextContent(type="text", text=text)]

        elif name == "ephemeral_reserve":
            res_name = arguments.get("name")
            if res_name:
                validate_dns_name(res_name)

            if resource_type == "cluster":
                result = clusters.reserve_cluster(
                    client,
                    name=res_name,
                    duration=arguments.get("duration", "4h"),
                    requester=arguments.get("requester"),
                    pool=arguments.get("pool", "rosa-default"),
                    team=arguments.get("team"),
                )
                return [TextContent(type="text", text=format_cluster_reservation(result))]
            else:
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

            if resource_type == "cluster":
                if not res_name:
                    return [TextContent(
                        type="text",
                        text="Error: 'name' is required for cluster status lookup.",
                    )]
                result = clusters.get_cluster_status(client, res_name)
                if not result:
                    return [TextContent(type="text", text=f"No cluster reservation found for name='{res_name}'.")]
                return [TextContent(type="text", text=format_cluster_reservation(result))]
            else:
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
            if resource_type == "cluster":
                res_name = arguments.get("name")
                if not res_name:
                    return [TextContent(type="text", text="Error: 'name' is required for cluster extend.")]
                result = clusters.extend_cluster(client, res_name, arguments["duration"])
            else:
                namespace = arguments.get("namespace")
                if not namespace:
                    return [TextContent(type="text", text="Error: 'namespace' is required for namespace extend.")]
                result = reservations.extend(client, namespace=namespace, duration=arguments["duration"])
            return [TextContent(type="text", text=format_extend(result))]

        elif name == "ephemeral_release":
            res_name = arguments.get("name")
            namespace = arguments.get("namespace")

            if resource_type == "cluster":
                if not res_name:
                    return [TextContent(type="text", text="Error: 'name' is required for cluster release.")]
                result = clusters.release_cluster(client, res_name)
            else:
                if not res_name and not namespace:
                    return [TextContent(
                        type="text",
                        text="Error: provide either 'name' or 'namespace' to release a reservation.",
                    )]
                result = reservations.release(client, name=res_name, namespace=namespace)
            return [TextContent(type="text", text=format_release(result))]

        elif name == "ephemeral_list_reservations":
            requester = arguments.get("requester")
            parts = []

            if resource_type in ("namespace", "all"):
                ns_result = status.list_reservations(client, requester=requester)
                parts.append(format_reservation_list(ns_result))

            if resource_type in ("cluster", "all"):
                cl_reservations = _list_cluster_reservations(client, requester)
                if cl_reservations or resource_type == "cluster":
                    parts.append(_format_cluster_reservation_list(cl_reservations))

            return [TextContent(type="text", text="\n\n".join(parts))]

        elif name == "ephemeral_describe":
            result = status.describe_namespace(client, arguments["namespace"])
            return [TextContent(type="text", text=format_describe(result))]

        elif name == "ephemeral_get_kubeconfig":
            kubeconfig = clusters.get_kubeconfig(client, arguments["name"])
            return [TextContent(type="text", text=format_kubeconfig(arguments["name"], kubeconfig))]

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


def _list_cluster_reservations(client: EphemeralK8sClient, requester: str | None) -> list[dict]:
    """List cluster reservations, optionally filtered by requester."""
    try:
        if requester:
            raw = client.list_cluster_reservations(label_selector=f"requester={requester}")
        else:
            raw = client.list_cluster_reservations()
    except Exception:
        log.debug("ClusterReservation CRD not available")
        return []

    result = []
    for res in raw:
        s = res.get("status", {})
        sp = res.get("spec", {})
        result.append({
            "name": res["metadata"]["name"],
            "type": "cluster",
            "cluster_name": s.get("clusterName", ""),
            "state": s.get("state", ""),
            "expiration": s.get("expiration", ""),
            "requester": sp.get("requester", ""),
            "pool": sp.get("pool", "rosa-default"),
            "duration": sp.get("duration", ""),
        })
    return result


def _format_cluster_reservation_list(reservations_list: list[dict]) -> str:
    """Format a list of cluster reservations."""
    if not reservations_list:
        return "No active cluster reservations found."

    lines = ["Active Cluster Reservations:", ""]
    header = (
        f"  {'Name':<35} {'Cluster':<25} {'State':<14} "
        f"{'Requester':<20} {'Pool':<15} {'Duration':<10}"
    )
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    for res in reservations_list:
        lines.append(
            f"  {res.get('name', ''):<35} {res.get('cluster_name', ''):<25} "
            f"{res.get('state', ''):<14} {res.get('requester', ''):<20} "
            f"{res.get('pool', ''):<15} {res.get('duration', ''):<10}"
        )

    return "\n".join(lines)


async def run_server():
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main():
    import asyncio

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_server())

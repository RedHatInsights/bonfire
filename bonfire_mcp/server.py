"""MCP server for ephemeral environment operations.

Exposes reservation lifecycle (reserve, release, extend, list, status)
as MCP tools usable by any MCP-compatible AI agent. Supports both
default_namespace and rosa_cluster resource types — both are namespace
reservations that differ only by pool selection.
"""

import asyncio
import logging

from mcp.server import Server
from mcp.types import CallToolResult, TextContent, Tool

from bonfire_lib.config import Settings
from bonfire_lib.k8s_client import EphemeralK8sClient
from bonfire_lib.utils import FatalError, validate_dns_name, validate_time_string
import bonfire_lib.reservations as reservations
import bonfire_lib.pools as pools
import bonfire_lib.status as status

from bonfire_mcp.auth import load_k8s_client
from bonfire_mcp.formatters import (
    format_deploy_rosa,
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
            "List available ephemeral namespace pools with capacity stats. "
            "Filter by type to see only default_namespace or rosa_cluster pools."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["default_namespace", "rosa_cluster", "all"],
                    "description": "Filter by pool type. Default: 'all'.",
                    "default": "all",
                },
            },
        },
    ),
    Tool(
        name="ephemeral_reserve",
        description=(
            "Reserve an ephemeral namespace. "
            "Use type='default_namespace' for a standard namespace from the default pool, "
            "or type='rosa_cluster' for a namespace from the rosa pool. "
            "Polls until a namespace is assigned (may take a few seconds)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "type": {
                    "type": "string",
                    "enum": ["default_namespace", "rosa_cluster"],
                    "description": (
                        "Resource type. 'default_namespace' uses pool='default', "
                        "'rosa_cluster' uses pool='rosa'. Default: 'default_namespace'."
                    ),
                    "default": "default_namespace",
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
                    "description": "Duration (e.g., '1h', '2h30m'). Default: '1h'.",
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
        description=("Get the status of a namespace reservation by name or by namespace."),
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
                "type": {
                    "type": "string",
                    "enum": ["default_namespace", "rosa_cluster"],
                    "description": "Resource type (informational). Default: 'default_namespace'.",
                    "default": "default_namespace",
                },
            },
        },
    ),
    Tool(
        name="ephemeral_extend",
        description=(
            "Extend the duration of an active namespace reservation. "
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
                "type": {
                    "type": "string",
                    "enum": ["default_namespace", "rosa_cluster"],
                    "description": "Resource type (informational). Default: 'default_namespace'.",
                    "default": "default_namespace",
                },
            },
            "required": ["duration"],
        },
    ),
    Tool(
        name="ephemeral_release",
        description=(
            "Release an ephemeral namespace reservation. "
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
                    "description": "Namespace name to find and release.",
                },
                "type": {
                    "type": "string",
                    "enum": ["default_namespace", "rosa_cluster"],
                    "description": "Resource type (informational). Default: 'default_namespace'.",
                    "default": "default_namespace",
                },
            },
        },
    ),
    Tool(
        name="ephemeral_list_reservations",
        description=(
            "List active reservations, optionally filtered by requester or pool type. "
            "Shows reservation name, assigned namespace, state, and pool."
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
                    "enum": ["default_namespace", "rosa_cluster", "all"],
                    "description": "Filter by reservation type/pool. Default: 'all'.",
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
    Tool(
        name="ephemeral_deploy_rosa",
        description=(
            "Deploy a ROSA ephemeral cluster. Reserves a namespace from the rosa pool, "
            "deploys the rosa-ephemeral-cluster component, waits for readiness, "
            "and returns connection info. This is a long-running operation (may take several minutes)."
        ),
        inputSchema={
            "type": "object",
            "properties": {
                "duration": {
                    "type": "string",
                    "description": "Reservation duration (e.g., '2h', '1h30m'). Default: '2h'.",
                    "default": "2h",
                },
                "requester": {
                    "type": "string",
                    "description": (
                        "Requester identity, defaults to authenticated user. "
                        "In CI this is typically a job identifier."
                    ),
                },
                "timeout": {
                    "type": "integer",
                    "description": "Max seconds to wait for deployment. Default: 1800.",
                    "default": 1800,
                },
            },
        },
    ),
]


@app.list_tools()
async def list_tools() -> list[Tool]:
    return TOOLS


def _error_result(message: str) -> CallToolResult:
    """Build a CallToolResult with isError=True for proper MCP error signaling."""
    return CallToolResult(
        content=[TextContent(type="text", text=message)],
        isError=True,
    )


async def _deploy_rosa(
    duration: str | None = None,
    requester: str | None = None,
    timeout: int = 1800,
) -> dict:
    """Run bonfire deploy rosa as an async subprocess and return result dict."""
    if duration:
        validate_time_string(duration)

    cmd = ["bonfire", "deploy", "rosa"]
    if duration:
        cmd += ["--duration", duration]
    if requester:
        cmd += ["--requester", requester]
    if timeout:
        cmd += ["--timeout", str(timeout)]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=timeout + 60
        )
    except asyncio.TimeoutError:
        proc.kill()
        raise TimeoutError(f"bonfire deploy rosa timed out after {timeout + 60}s")

    stdout = stdout_bytes.decode("utf-8", errors="replace")
    stderr = stderr_bytes.decode("utf-8", errors="replace")

    if proc.returncode != 0:
        raise FatalError(f"bonfire deploy rosa failed (exit {proc.returncode}):\n{stderr}")

    # The CLI prints the namespace name as the last non-empty line of stdout
    lines = [line for line in stdout.splitlines() if line.strip()]
    if not lines:
        raise FatalError("bonfire deploy rosa produced no output — could not determine namespace")

    namespace = lines[-1].strip()

    client = _get_client()
    describe_info = status.describe_namespace(client, namespace)

    return {
        "namespace": namespace,
        "describe": describe_info,
        "deploy_output": stdout,
    }


@app.call_tool()
async def call_tool(name: str, arguments: dict) -> list[TextContent] | CallToolResult:
    try:
        client = _get_client()
        resource_type = arguments.get("type", "default_namespace")

        if name == "ephemeral_list_pools":
            # Both types list namespace pools; filter by pool name if requested
            all_ns_pools = pools.list_pools(client)
            if resource_type == "default_namespace":
                result = [p for p in all_ns_pools if p["name"] != "rosa"]
            elif resource_type == "rosa_cluster":
                result = [p for p in all_ns_pools if p["name"] == "rosa"]
            else:
                result = all_ns_pools
            return [TextContent(type="text", text=format_pool_list(result))]

        elif name == "ephemeral_reserve":
            res_name = arguments.get("name")
            if res_name:
                validate_dns_name(res_name)

            duration = arguments.get("duration")
            if duration:
                validate_time_string(duration)

            settings = _get_settings()

            # Map type to pool: default_namespace -> "default", rosa_cluster -> "rosa"
            pool = "rosa" if resource_type == "rosa_cluster" else settings.default_namespace_pool

            result = await asyncio.to_thread(
                reservations.reserve,
                client,
                name=res_name,
                duration=duration or settings.default_reservation_duration,
                requester=arguments.get("requester"),
                pool=pool,
                team=arguments.get("team"),
                timeout=arguments.get("timeout", 600),
            )
            return [TextContent(type="text", text=format_reservation(result))]

        elif name == "ephemeral_status":
            res_name = arguments.get("name")
            namespace = arguments.get("namespace")

            if not res_name and not namespace:
                return _error_result(
                    "Error: provide either 'name' or 'namespace' to look up a reservation."
                )
            res = status.get_reservation(client, name=res_name, namespace=namespace)
            if not res:
                return [
                    TextContent(
                        type="text",
                        text=f"No reservation found for "
                        f"{'name=' + res_name if res_name else 'namespace=' + namespace}.",
                    )
                ]
            result = status.get_reservation_summary(res)
            return [TextContent(type="text", text=format_reservation(result))]

        elif name == "ephemeral_extend":
            namespace = arguments.get("namespace")
            if not namespace:
                return _error_result("Error: 'namespace' is required for extend.")
            result = reservations.extend(
                client, namespace=namespace, duration=arguments["duration"]
            )
            return [TextContent(type="text", text=format_extend(result))]

        elif name == "ephemeral_release":
            res_name = arguments.get("name")
            namespace = arguments.get("namespace")

            if not res_name and not namespace:
                return _error_result(
                    "Error: provide either 'name' or 'namespace' to release a reservation."
                )
            result = reservations.release(client, name=res_name, namespace=namespace)
            return [TextContent(type="text", text=format_release(result))]

        elif name == "ephemeral_list_reservations":
            requester = arguments.get("requester")
            all_reservations = status.list_reservations(client, requester=requester)

            # Filter by pool when a specific type is requested
            if resource_type == "default_namespace":
                result = [r for r in all_reservations if r.get("pool") != "rosa"]
            elif resource_type == "rosa_cluster":
                result = [r for r in all_reservations if r.get("pool") == "rosa"]
            else:
                result = all_reservations

            return [TextContent(type="text", text=format_reservation_list(result))]

        elif name == "ephemeral_describe":
            result = status.describe_namespace(client, arguments["namespace"])
            return [TextContent(type="text", text=format_describe(result))]

        elif name == "ephemeral_get_kubeconfig":
            kubeconfig = reservations.get_kubeconfig(client, arguments["name"])
            return [TextContent(type="text", text=format_kubeconfig(arguments["name"], kubeconfig))]

        elif name == "ephemeral_deploy_rosa":
            result = await _deploy_rosa(
                duration=arguments.get("duration"),
                requester=arguments.get("requester"),
                timeout=arguments.get("timeout", 1800),
            )
            return [TextContent(type="text", text=format_deploy_rosa(result))]

        else:
            return _error_result(f"Unknown tool: {name}")

    except FatalError as e:
        return _error_result(f"Error: {e}")
    except TimeoutError as e:
        return _error_result(f"Timeout: {e}")
    except ValueError as e:
        return _error_result(f"Validation error: {e}")
    except RuntimeError as e:
        return _error_result(f"Connection error: {e}")
    except Exception as e:
        log.exception("unexpected error in tool %s", name)
        return _error_result(f"Unexpected error: {e}")


async def run_server():
    from mcp.server.stdio import stdio_server

    async with stdio_server() as (read_stream, write_stream):
        await app.run(read_stream, write_stream, app.create_initialization_options())


def main():
    import asyncio

    logging.basicConfig(level=logging.INFO)
    asyncio.run(run_server())

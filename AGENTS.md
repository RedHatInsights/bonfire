# AGENTS.md

## Project Overview

Bonfire is a CLI tool and MCP server for deploying and managing ephemeral test environments on OpenShift/Kubernetes clusters for console.redhat.com applications. The codebase has **three distinct packages** that serve different purposes and have different dependency trees:

| Package | Purpose | Key Dependencies |
|---------|---------|-----------------|
| `bonfire` | CLI tool (Click-based) for deploying apps via OpenShift templates | `click`, `ocviapy`, `gql`, `sh`, `tabulate` |
| `bonfire_lib` | Shared library for ephemeral reservation lifecycle | `kubernetes`, `jinja2`, `pyyaml` (no `oc` binary needed) |
| `bonfire_mcp` | MCP server exposing reservation tools to AI agents | `mcp`, `bonfire_lib` |

## Commands

### Install (development)

```bash
# Full CLI with all extras
pip install -e ".[cli,test,mcp]"

# MCP server only (minimal deps)
pip install -e ".[test,mcp]"
```

### Test

```bash
# All tests (excludes integration tests by default via pytest config)
pytest -sv

# Specific test suites
pytest tests/test_bonfire_mcp/ -sv   # MCP server tests
pytest tests/test_bonfire_lib/ -sv   # Shared library tests
pytest tests/test_bonfire.py -sv     # CLI tests

# Integration tests (require live K8s cluster — never run in CI)
pytest -m integration -sv
```

### Lint / Format

```bash
ruff check --fix .
ruff format .
```

### Build

```bash
python -m build -o dist/
```

## Architecture

### Data Flow

```
bonfire CLI (Click commands)         bonfire_mcp (MCP server)
    │                                    │
    │ uses ocviapy/oc binary             │ calls bonfire_lib directly
    │ for K8s operations                 │ (no oc binary needed)
    ↓                                    ↓
bonfire.openshift / bonfire.namespaces   bonfire_lib.*
    │                                    │
    ↓                                    ↓
K8s API via oc CLI                  K8s API via kubernetes Python client
    │                                    │
    ↓                                    ↓
Ephemeral Namespace Operator (ENO) — manages NamespaceReservation / ClusterReservation CRDs
```

### Two Parallel K8s Integration Paths

The codebase has **two independent paths** to the K8s API — this is the most important architectural detail:

1. **`bonfire` (CLI)**: Uses `ocviapy` which shells out to the `oc` binary. Lives in `bonfire/openshift.py` and `bonfire/namespaces.py`. Requires `oc` to be installed and `oc login` to have been run.

2. **`bonfire_lib` (shared library)**: Uses the `kubernetes` Python client directly via `EphemeralK8sClient`. No `oc` binary dependency. Used by `bonfire_mcp`.

These two paths are **not interchangeable**. The CLI imports from `bonfire.*`, the MCP server imports from `bonfire_lib.*`. The CLI has a bridge point in `bonfire/namespaces.py` where `_get_lib_client()` creates an `EphemeralK8sClient` for some operations.

### CRD API

All custom resources use the same API version: `cloud.redhat.com/v1alpha1`. Key CRD kinds:

- `NamespaceReservation` — reserves an ephemeral namespace
- `NamespacePool` — defines a pool of namespaces
- `ClusterReservation` — reserves a ROSA HCP cluster (async, 20-40 min provisioning)
- `ClusterPool` — defines a pool of clusters
- `ClowdApp`, `ClowdEnvironment`, `ClowdJobInvocation` — Clowder operator CRDs
- `Frontend`, `FrontendEnvironment` — Frontend operator CRDs

### bonfire_lib Module Structure

Each module in `bonfire_lib` is a thin, stateless function layer over `EphemeralK8sClient`:

- `reservations.py` — reserve/release/extend namespace reservations
- `clusters.py` — reserve/release/extend/kubeconfig for cluster reservations
- `pools.py` — list namespace and cluster pools
- `status.py` — get/list reservations, polling, namespace describe
- `core_resources.py` — Jinja2 template rendering for CRs
- `k8s_client.py` — `EphemeralK8sClient` wrapping `kubernetes` DynamicClient
- `config.py` — `Settings` dataclass (from env vars or explicit construction)
- `utils.py` — `FatalError`, duration parsing, DNS name validation

### bonfire_mcp Structure

- `server.py` — MCP `Server` instance, tool definitions (`TOOLS` list), and `call_tool()` dispatcher
- `auth.py` — `load_k8s_client()` with three auth modes (token, in-cluster, kubeconfig) + preflight CRD check
- `formatters.py` — Plain-text formatting functions for MCP responses (no JSON — text is more useful for LLMs)
- `__main__.py` — Entry point for `python -m bonfire_mcp`

### Release Mechanism

Releasing a reservation sets `spec.duration` to `"0s"` via a merge patch. The ENO poller picks this up within ~10 seconds and cascades deletion via OwnerRef. This is not a delete operation — it's a patch.

## Testing Patterns

### Async Tests

MCP server tests use `pytest-asyncio` with **strict mode** (`asyncio_mode = "strict"` in pyproject.toml). Every async test **must** be decorated with `@pytest.mark.asyncio`:

```python
@pytest.mark.asyncio
async def test_something(self):
    result = await call_tool("ephemeral_reserve", {"name": "test"})
```

### Mocking Strategy

Tests mock at the K8s client boundary — never hit a real cluster:

- **bonfire_lib tests**: Mock `EphemeralK8sClient` via `MagicMock(spec=EphemeralK8sClient)` in conftest
- **bonfire_mcp tests**: Patch `bonfire_mcp.server._get_client` and patch individual modules (`bonfire_mcp.server.reservations`, `bonfire_mcp.server.clusters`, etc.)
- **bonfire CLI tests**: Patch `bonfire.namespaces._get_lib_client`

All conftest fixtures provide a `mock_client` with `whoami()` pre-configured to return a test user.

### MCP Error Testing

The MCP server returns `CallToolResult(isError=True)` for errors, not exceptions. Tests check:
```python
assert isinstance(result, CallToolResult)
assert result.isError is True
assert "Error" in result.content[0].text
```

Successful results return `list[TextContent]`, not `CallToolResult`.

### Integration Tests

Tests marked `@pytest.mark.integration` are excluded by default (configured in `pyproject.toml` `addopts`). They require a live K8s cluster and are never run in CI.

## Gotchas and Non-Obvious Patterns

### Namespace vs. Cluster Reservations

Namespace reservations are **synchronous** (the `reserve()` function polls until a namespace is assigned). Cluster reservations are **asynchronous** — `reserve_cluster()` returns immediately with `state: "waiting"` and the caller must poll `get_cluster_status()`. This asymmetry flows through to the MCP server's `ephemeral_reserve` tool, which handles both via the `type` parameter.

### Duration Validation

Durations must be between 30 minutes and 14 days. Format is `NhNmNs` (e.g., `"1h30m"`, `"45m"`, `"2h"`). The `validate_time_string()` function in `bonfire_lib/utils.py` enforces this. The CLI in `bonfire/bonfire.py` has its own `validate_time_string()` in `bonfire/utils.py` — they are separate implementations.

### Username Sanitization

K8s label values can't contain `@` or `:`. The `_sanitize_username()` function in `k8s_client.py` replaces `@` with `_at_` and `:` with `_`. All requester values stored as labels go through this. The `whoami()` method for kubeconfig auth also strips the cluster URL suffix from context user strings (e.g., `user/api-cluster:6443` → `user`).

### MCP Server Global State

`bonfire_mcp/server.py` uses module-level globals `_client` and `_settings` with lazy initialization via `_get_client()` and `_get_settings()`. Tests must patch `_get_client` to avoid real K8s connections. The `_client` is shared across all tool calls.

### ClusterPool/ClusterReservation CRD Optionality

Cluster CRDs may not exist on all management clusters. `list_cluster_pools()` and `list_cluster_reservations()` catch all exceptions and return empty lists if the CRD isn't installed, rather than failing.

### bonfire CLI Entry Points

Two entry points are defined in `pyproject.toml`:
- `bonfire` → `bonfire.bonfire:main_with_handler`
- `bonfire-mcp` → `bonfire_mcp.server:main`

### Pre-commit

Uses ruff for both linting (`ruff check --fix`) and formatting (`ruff format`). Line length is 100 chars, indent width is 4 spaces.

### CI Matrix

Tests run on Python 3.10, 3.11, 3.12 across Ubuntu and macOS. CI installs the built wheel with all extras (`[cli,test,mcp]`) and requires `oc` 4.16 to be available for CLI tests.

### Jinja2 Templates

`bonfire_lib/core_resources.py` renders CRs from Jinja2 templates in `bonfire_lib/templates/`. These are separate from the OpenShift Template YAML files in `bonfire/resources/` — the CLI uses `oc process` on the latter, while `bonfire_lib` uses Jinja2 rendering.

### `bonfire/resources/` vs `bonfire_lib/templates/`

These are **not** the same templates. `bonfire/resources/` contains OpenShift Template YAML files processed by `oc process`. `bonfire_lib/templates/` contains Jinja2 templates rendered by Python. Don't confuse them.

### Package Version

Version is managed by `setuptools_scm` (derived from git tags). There is no hardcoded version string in the source.

### Environment Variables

Key env vars for MCP server auth:
- `K8S_SERVER` + `K8S_TOKEN` — explicit token auth
- `K8S_CA_DATA` — base64-encoded CA cert (optional with token auth)
- `K8S_SKIP_TLS_VERIFY` — skip TLS verification
- `KUBECONFIG` — kubeconfig file path
- `K8S_CONTEXT` — kubeconfig context name

Key env vars for bonfire_lib settings:
- `BONFIRE_DEFAULT_NAMESPACE_POOL` — default pool (default: `"default"`)
- `BONFIRE_DEFAULT_DURATION` — default reservation duration (default: `"1h"`)
- `BONFIRE_NS_REQUESTER` — override requester identity
- `BONFIRE_BOT` — set to `"true"` for automated/CI usage (disables interactive prompts and context switching)

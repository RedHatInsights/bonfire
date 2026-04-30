# Ephemeral MCP Server

An [MCP (Model Context Protocol)](https://modelcontextprotocol.io/) server that exposes ephemeral environment operations as tools, enabling any MCP-compatible AI agent to programmatically reserve, manage, and release ephemeral namespaces on an OpenShift cluster managed by the [Ephemeral Namespace Operator (ENO)](https://github.com/RedHatInsights/ephemeral-namespace-operator).

## Architecture

```
AI Agent (Claude, GPT, etc.)
    ↓ MCP protocol (stdio)
bonfire_mcp (this server)
    ↓ calls
bonfire_lib (shared library)
    ↓ kubernetes Python client
Management Cluster K8s API
    ↓ CRDs
Ephemeral Namespace Operator
```

The MCP server is a thin dispatch layer over `bonfire_lib`, which implements the reservation lifecycle using the [`kubernetes` Python client](https://github.com/kubernetes-client/python) directly — no `oc` binary required.

## Installation

```bash
pip install crc-bonfire[mcp]
```

Or for development:

```bash
cd bonfire/
pip install -e ".[test,mcp]"
```

## Authentication

The server mirrors the auth model of [`containers/kubernetes-mcp-server`](https://github.com/containers/kubernetes-mcp-server), with three modes auto-detected in priority order:

### 1. Environment Variables (recommended for CI/containers)

```
K8S_SERVER=https://api.mgmt-cluster.example.com:6443
K8S_TOKEN=sha256~...
K8S_CA_DATA=LS0tLS1CRUdJTi...   (optional, base64-encoded CA cert)
K8S_SKIP_TLS_VERIFY=false        (optional)
```

### 2. In-Cluster (automatic in pods)

When running inside a Kubernetes pod, the server auto-detects the projected service account token at `/var/run/secrets/kubernetes.io/serviceaccount/token`.

### 3. Kubeconfig (default for local development)

```
KUBECONFIG=/path/to/kubeconfig    (optional, defaults to ~/.kube/config)
K8S_CONTEXT=my-context            (optional, defaults to current-context)
```

## MCP Client Configuration

### Claude Desktop

Add to `~/.config/claude/claude_desktop_config.json`:

**Using environment variables:**

```json
{
  "mcpServers": {
    "ephemeral": {
      "command": "bonfire-mcp",
      "env": {
        "K8S_SERVER": "https://api.mgmt-cluster.example.com:6443",
        "K8S_TOKEN": "sha256~your-token-here"
      }
    }
  }
}
```

**Using kubeconfig:**

```json
{
  "mcpServers": {
    "ephemeral": {
      "command": "bonfire-mcp",
      "env": {
        "KUBECONFIG": "/home/user/.kube/mgmt-cluster.kubeconfig",
        "K8S_CONTEXT": "mgmt-cluster"
      }
    }
  }
}
```

**Using `python -m`:**

```json
{
  "mcpServers": {
    "ephemeral": {
      "command": "python",
      "args": ["-m", "bonfire_mcp"],
      "env": {
        "KUBECONFIG": "/home/user/.kube/config"
      }
    }
  }
}
```

## Available Tools

| Tool | Type | Description |
|------|------|-------------|
| `ephemeral_list_pools` | Read | List namespace and/or cluster pools with capacity stats (ready/creating/reserved counts) |
| `ephemeral_reserve` | Mutate | Reserve a namespace or cluster. Namespaces: polls until assigned. Clusters: returns immediately (async provisioning). |
| `ephemeral_status` | Read | Get reservation status by name or namespace. For clusters: shows state (waiting/provisioning/active), cluster name, console URL. |
| `ephemeral_extend` | Mutate | Extend a reservation's duration |
| `ephemeral_release` | Mutate | Release a reservation (namespace reclaimed within ~10s) |
| `ephemeral_list_reservations` | Read | List active reservations, filterable by requester and type |
| `ephemeral_describe` | Read | Detailed namespace info: ClowdApps, frontends, console URL, keycloak creds |
| `ephemeral_get_kubeconfig` | Read | Fetch kubeconfig YAML for a provisioned ROSA HCP cluster reservation |

### Tool Parameters

#### `ephemeral_list_pools`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `type` | string | No | `"all"` | Filter by pool type: `"namespace"`, `"cluster"`, or `"all"` |

#### `ephemeral_reserve`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `type` | string | No | `"namespace"` | Resource type: `"namespace"` or `"cluster"` |
| `name` | string | No | auto-generated | Reservation name (DNS-1123 label) |
| `duration` | string | No | `"1h"` (ns) / `"4h"` (cluster) | Duration (e.g., `"1h"`, `"2h30m"`) |
| `pool` | string | No | `"default"` (ns) / `"rosa-default"` (cluster) | Pool to reserve from |
| `requester` | string | No | K8s identity | Requester for the reservation |
| `team` | string | No | | Team for cost attribution |
| `timeout` | integer | No | `600` | Max seconds to wait for namespace assignment (namespace only, ignored for clusters) |

#### `ephemeral_status`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `type` | string | No | `"namespace"` | Resource type: `"namespace"` or `"cluster"` |
| `name` | string | No* | | Reservation name |
| `namespace` | string | No* | | Namespace name (namespace type only) |

*For namespaces, one of `name` or `namespace` is required. For clusters, `name` is required.

#### `ephemeral_extend`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `type` | string | No | `"namespace"` | Resource type: `"namespace"` or `"cluster"` |
| `name` | string | Cluster only | | Reservation name (required for clusters) |
| `namespace` | string | Namespace only | | Namespace to extend (required for namespaces) |
| `duration` | string | Yes | | Additional duration (e.g., `"1h"`) |

#### `ephemeral_release`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `type` | string | No | `"namespace"` | Resource type: `"namespace"` or `"cluster"` |
| `name` | string | No* | | Reservation name (required for clusters) |
| `namespace` | string | No* | | Namespace name (namespace type only) |

*For namespaces, one of `name` or `namespace` is required. For clusters, `name` is required.

#### `ephemeral_list_reservations`

| Parameter | Type | Required | Default | Description |
|-----------|------|----------|---------|-------------|
| `type` | string | No | `"all"` | Filter by type: `"namespace"`, `"cluster"`, or `"all"` |
| `requester` | string | No | | Filter by requester |

#### `ephemeral_describe`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `namespace` | string | Yes | Namespace to describe |

#### `ephemeral_get_kubeconfig`

| Parameter | Type | Required | Description |
|-----------|------|----------|-------------|
| `name` | string | Yes | Cluster reservation name (cluster must be in `active` state) |

## Example Agent Interaction

### Namespace workflow

```
Agent: ephemeral_list_pools()
MCP:   Namespace Pools:
         Name          Ready  Creating  Reserved  Size  Limit
         default           3         1         2     5     10

Agent: ephemeral_reserve(name="my-test", duration="2h", pool="default")
MCP:   Reservation: my-test
         State: active
         Namespace: ephemeral-abc123
         Pool: default
         Requester: user_at_redhat.com
         Expiration: 2026-04-09T14:00:00Z

Agent: ephemeral_describe(namespace="ephemeral-abc123")
MCP:   Namespace: ephemeral-abc123
       Console URL: https://console.example.com/k8s/cluster/projects/ephemeral-abc123
       ClowdApps deployed: 0
       Frontends deployed: 0

Agent: ephemeral_extend(namespace="ephemeral-abc123", duration="1h")
MCP:   Reservation 'my-test' extended. New total duration: 3h0m0s.

Agent: ephemeral_release(name="my-test")
MCP:   Reservation 'my-test' released. Resource will be reclaimed by the operator.
```

### Cluster workflow

```
Agent: ephemeral_reserve(type="cluster", name="my-rosa", duration="4h")
MCP:   Cluster Reservation: my-rosa
         State: waiting
         Pool: rosa-default
         Requester: user_at_redhat.com
         Note: Poll with ephemeral_status(name='my-rosa', type='cluster') to track progress.

Agent: ephemeral_status(type="cluster", name="my-rosa")
MCP:   Cluster Reservation: my-rosa
         State: provisioning
         Pool: rosa-default
         Requester: user_at_redhat.com

Agent: ephemeral_status(type="cluster", name="my-rosa")
MCP:   Cluster Reservation: my-rosa
         State: active
         Cluster: rosa-abc123
         Console: https://console.apps.rosa-abc123.example.com
         Expiration: 2026-04-09T16:00:00Z

Agent: ephemeral_get_kubeconfig(name="my-rosa")
MCP:   Kubeconfig for cluster reservation 'my-rosa':
         <kubeconfig YAML>

Agent: ephemeral_release(type="cluster", name="my-rosa")
MCP:   Reservation 'my-rosa' released. Resource will be reclaimed by the operator.
```

## Running Tests

```bash
pytest tests/test_bonfire_mcp/ -sv
```

## Prerequisites

- Python 3.10+
- Access to a management cluster running the [Ephemeral Namespace Operator](https://github.com/RedHatInsights/ephemeral-namespace-operator)
- Valid K8s credentials (kubeconfig, token, or in-cluster SA)

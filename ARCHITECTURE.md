# Architecture

`crc-bonfire` is a single-distribution Python package (`pyproject.toml`) containing three
sub-packages with distinct responsibilities. This document describes internal design decisions,
component relationships, data flows, and tradeoffs. For installation and usage, see [README.md](README.md).

## Table of Contents

- [Package Structure](#package-structure)
- [Sub-package Relationships](#sub-package-relationships)
- [CLI Entry Point and Command Structure](#cli-entry-point-and-command-structure)
- [Core Data Flows](#core-data-flows)
- [MCP Server Architecture](#mcp-server-architecture)
- [Dual Kubernetes Integration Paths](#dual-kubernetes-integration-paths)
- [Configuration and Environment Variables](#configuration-and-environment-variables)
- [AppSRE / qontract GraphQL Integration](#appsre--qontract-graphql-integration)
- [Namespace and Cluster Reservation Lifecycle](#namespace-and-cluster-reservation-lifecycle)
- [Template Processing](#template-processing)
- [Key Abstractions](#key-abstractions)
- [Error Handling](#error-handling)
- [Known Tradeoffs](#known-tradeoffs)

---

## Package Structure

The distribution ships three top-level Python packages, all discovered by setuptools via
`packages.find` with `include = ["bonfire*", "bonfire_lib*", "bonfire_mcp*"]`.

### `bonfire/` — CLI sub-package

Requires the `oc` binary. Entry point: `bonfire.bonfire:main_with_handler`.

| File | Responsibility |
|---|---|
| `bonfire/bonfire.py` | Top-level Click group, all command definitions, alias resolution, error wrappers |
| `bonfire/config.py` | Module-level env-var constants, YAML config loader, alias loader, dotenv bootstrap |
| `bonfire/qontract.py` | AppSRE GraphQL client: `APPS_QUERY`, `ENVS_QUERY`, four-layer parameter merging |
| `bonfire/processor.py` | `TemplateProcessor`: fetches and processes OpenShift Templates via `oc process` |
| `bonfire/openshift.py` | All `ocviapy`-based Kubernetes calls (lru-cached, wraps `oc` binary) |
| `bonfire/namespaces.py` | Bridge between CLI and `bonfire_lib`: `Namespace` class, reserve/release/extend |
| `bonfire/utils.py` | `FatalError`, `RepoFile` (template fetcher), `AppOrComponentSelector`, helpers |
| `bonfire/local.py` | Reads local YAML config for `--source=file` mode |
| `bonfire/output.py` | Rich-based terminal rendering (tables, spinners, panels) |
| `bonfire/secrets.py` | Imports secrets from a local directory via `oc apply` |
| `bonfire/configmaps.py` | Imports configmaps from a local directory via `oc apply` |
| `bonfire/elastic_logging.py` | Optional Elasticsearch telemetry (non-blocking, ThreadPoolExecutor) |

### `bonfire_lib/` — Shared library sub-package

Pure Python; uses the `kubernetes` client directly — no `oc` binary required. Consumed by both
the CLI bridge (`bonfire/namespaces.py`) and the MCP server.

| File | Responsibility |
|---|---|
| `bonfire_lib/k8s_client.py` | `EphemeralK8sClient`: DynamicClient wrapper, three auth modes, typed CRUD |
| `bonfire_lib/reservations.py` | `reserve()`, `release()`, `extend()` namespace reservation lifecycle |
| `bonfire_lib/clusters.py` | `reserve_cluster()`, `release_cluster()`, `extend_cluster()`, `get_kubeconfig()` |
| `bonfire_lib/pools.py` | `list_pools()`, `list_cluster_pools()`, `list_all_pools()` |
| `bonfire_lib/status.py` | `get_reservation()`, `list_reservations()`, `wait_on_reservation()`, `describe_namespace()` |
| `bonfire_lib/core_resources.py` | Jinja2 renderers for CRs: `render_reservation()`, `render_clowdenv()`, `render_cji()`, `render_cluster_reservation()` |
| `bonfire_lib/config.py` | `Settings` dataclass loaded from env vars via `Settings.from_env()` |
| `bonfire_lib/utils.py` | `FatalError`, `validate_dns_name()`, `hms_to_seconds()`, `duration_fmt()` |

Jinja2 templates referenced by `core_resources.py` live in `bonfire_lib/templates/`:

| Template | Output CR Kind |
|---|---|
| `reservation.yaml.j2` | `NamespaceReservation` |
| `clusterreservation.yaml.j2` | `ClusterReservation` |
| `clowdenvironment.yaml.j2` | `ClowdEnvironment` |
| `clowdjobinvocation.yaml.j2` | `ClowdJobInvocation` |

### `bonfire_mcp/` — MCP server sub-package

Entry point: `bonfire_mcp.server:main`. Requires the `mcp` optional dependency
(`pip install crc-bonfire[mcp]`). Imports only from `bonfire_lib.*` — never from `bonfire.*`.

| File | Responsibility |
|---|---|
| `bonfire_mcp/server.py` | `Server("bonfire-mcp")`, tool registry, async dispatcher |
| `bonfire_mcp/auth.py` | Three-mode auth detection, preflight connectivity check |
| `bonfire_mcp/formatters.py` | Plain-text formatters for all tool outputs (returns `str`) |
| `bonfire_mcp/__main__.py` | `python -m bonfire_mcp` entry point |

---

## Sub-package Relationships

```
bonfire/ (CLI — requires oc binary)
├── bonfire.config          ← module-level env constants, YAML config
├── bonfire.openshift       ← oc-based K8s ops (ocviapy)
├── bonfire.qontract        ← AppSRE GraphQL client
├── bonfire.processor       ← TemplateProcessor (oc process)
├── bonfire.local           ← local YAML config reader
├── bonfire.output          ← Rich terminal UI
├── bonfire.utils           ← FatalError, RepoFile, helpers
└── bonfire.namespaces      ← CLI/lib bridge (THE SEAM)
      ├── bonfire.openshift
      ├── bonfire_lib.k8s_client   ← EphemeralK8sClient constructed here
      ├── bonfire_lib.reservations ← reserve/release/extend delegation
      └── bonfire_lib.status       ← describe_namespace delegation

bonfire_mcp/ (MCP server — no oc binary needed)
├── bonfire_lib.k8s_client
├── bonfire_lib.config
├── bonfire_lib.reservations
├── bonfire_lib.clusters
├── bonfire_lib.pools
├── bonfire_lib.status
├── bonfire_lib.utils
├── bonfire_mcp.auth
└── bonfire_mcp.formatters

bonfire_lib/ (shared library — no oc binary needed)
├── k8s_client.py  → kubernetes (DynamicClient + CoreV1Api)
├── reservations.py → k8s_client, core_resources, status, utils
├── clusters.py    → k8s_client, core_resources, utils
├── pools.py       → k8s_client
├── status.py      → k8s_client, utils
├── core_resources.py → jinja2, yaml  (no K8s imports)
└── config.py      → dataclasses, os  (no K8s imports)
```

**The critical rule:** `bonfire_mcp` never imports from `bonfire.*`. The CLI
(`bonfire.*`) reaches into `bonfire_lib.*` only through the bridge in
`bonfire/namespaces.py`. This keeps `bonfire_lib` free of the `oc` binary
dependency and independently usable.

---

## CLI Entry Point and Command Structure

`main_with_handler()` (`bonfire/bonfire.py`) calls `truststore.inject_into_ssl()` (for corporate
CA bundles) then delegates to `main()`.

```
main  [Click group — global options: --namespace/-n, --debug/-d]
│
├── namespace  [group]
│   ├── list             → _list_namespaces()
│   ├── reserve          → _cmd_namespace_reserve()  [click_exception_wrapper]
│   ├── release          → _cmd_namespace_release()  [click_exception_wrapper]
│   ├── extend           → _cmd_namespace_extend()   [click_exception_wrapper]
│   ├── wait-on-resources → _cmd_namespace_wait_on_resources()
│   └── describe         → _describe_namespace()
│
├── config  [group]
│   ├── write-default    → _cmd_write_default_config()
│   ├── edit             → _cmd_edit_default_config()
│   └── list-aliases     → _cmd_list_aliases()
│
├── apps  [group]
│   ├── list             → _cmd_apps_list()
│   └── what-depends-on  → _cmd_apps_what_depends_on()
│
├── pool  [group]
│   └── list             → _cmd_pool_types()
│
├── process              → _cmd_process()           → TemplateProcessor
├── deploy               → _cmd_config_deploy()     → reserve + process + apply + wait
├── process-env          → _cmd_process_clowdenv()  → process_clowd_env()
├── deploy-env           → _cmd_deploy_clowdenv()
├── process-iqe-cji      → _cmd_process_iqe_cji()  → process_iqe_cji()
├── deploy-iqe-cji       → _cmd_deploy_iqe_cji()
├── version              → _cmd_version()
└── test  [hidden group, for unit testing]
    └── test process     → _cmd_test_process()
```

### Option Reuse

Shared option lists (`_process_options`, `_ns_reserve_options`, `_timeout_options`) are applied
via a custom `options()` decorator that loops the list in reverse order, keeping option definitions
DRY across commands.

### Alias Resolution

`_resolve_alias()` expands a single `app_name` against the user's alias map (merged in
`load_aliases()` from built-in `DEFAULT_ALIASES` and `~/.config/bonfire/config.yaml`). Expansion
sets defaults for app lists and option overrides without clobbering values the user explicitly
passed — it checks via `ctx.get_parameter_source()`.

---

## Core Data Flows

### Deploy (`bonfire deploy <app>`)

```
_cmd_config_deploy()
  ├── _resolve_alias()                             # expand alias if applicable
  ├── get_base_namespace_for_env()                 # qontract: find base namespace for env
  ├── _get_namespace()
  │     ├── has_ns_operator()                      # openshift.py: lru-cached oc API check
  │     ├── _check_and_reserve_namespace()
  │     │     ├── get_namespace_pools()            # openshift.py: oc get namespacepool
  │     │     ├── check_for_existing_reservation() # openshift.py
  │     │     └── reserve_namespace()              # namespaces.py → bonfire_lib
  │     │           ├── EphemeralK8sClient()       # k8s_client.py (kubeconfig mode)
  │     │           ├── render_reservation()       # core_resources.py: Jinja2 → dict
  │     │           ├── client.create_reservation() # DynamicClient POST
  │     │           └── wait_on_reservation()      # status.py: 2s poll loop
  │     └── set_current_namespace()                # ocviapy
  ├── import_secrets_from_dir() / import_configmaps_from_dir()   [if requested]
  ├── find_clowd_env_for_ns()                      # openshift.py: oc get clowdenvironment
  ├── _process()
  │     ├── _get_apps_config()
  │     │     ├── get_apps_for_env()               # qontract.py: GraphQL APPS_QUERY
  │     │     ├── sub_refs()                       # qontract.py: overwrite git refs
  │     │     ├── get_local_apps()                 # local.py: --source=file
  │     │     └── merge_app_configs()              # utils.py
  │     └── TemplateProcessor(...).process()
  │           └── _process_app() → _process_component()
  │                 ├── RepoFile.fetch()           # HTTP: GitHub / GitLab raw URL
  │                 ├── _process_template()        # ocviapy → oc process
  │                 ├── _sub_image_tags()
  │                 ├── _remove_untrusted_configs_for_template()
  │                 ├── _set_replicas()
  │                 └── _handle_dependencies()     # recurse for ClowdApp deps
  ├── apply_config()                               # ocviapy → oc apply
  └── _wait_on_namespace_resources()
        └── wait_for_all_resources()               # openshift.py: ResourceWatcher + threaded waiters
```

### Reserve (`bonfire namespace reserve`)

```
_cmd_namespace_reserve()
  └── _check_and_reserve_namespace()
        └── reserve_namespace()                    # bonfire/namespaces.py
              ├── EphemeralK8sClient()             # kubeconfig auth (no oc needed here)
              └── bonfire_lib.reservations.reserve()
                    ├── render_reservation()       # Jinja2 → YAML dict
                    ├── client.create_reservation()
                    └── wait_on_reservation()      # polls until status.namespace populated
```

### Release (`bonfire namespace release`)

```
_cmd_namespace_release()
  └── release_reservation()                        # bonfire/namespaces.py
        ├── EphemeralK8sClient()
        └── bonfire_lib.reservations.release()
              ├── _find_reservation()              # client.list_reservations() → match by namespace
              └── client.patch_reservation(name, {"spec": {"duration": "0s"}})
                    # Sets duration to 0s — ENO detects this within ~10s and cascades deletion
                    # via OwnerRef. This is NOT a delete call.
```

---

## MCP Server Architecture

### Tool Inventory

The server registers 8 tools (`TOOLS` list in `bonfire_mcp/server.py`). All tools are
polymorphic on a `type` argument (`"namespace"` | `"cluster"` | `"all"`).

| Tool | `bonfire_lib` call | Blocking? |
|---|---|---|
| `ephemeral_list_pools` | `pools.list_pools()` / `list_cluster_pools()` / `list_all_pools()` | No |
| `ephemeral_reserve` | `reservations.reserve()` (namespace) or `clusters.reserve_cluster()` (cluster) | Yes (namespace); No (cluster) |
| `ephemeral_status` | `status.get_reservation()` or `clusters.get_cluster_status()` | No |
| `ephemeral_extend` | `reservations.extend()` or `clusters.extend_cluster()` | No |
| `ephemeral_release` | `reservations.release()` or `clusters.release_cluster()` | No |
| `ephemeral_list_reservations` | `status.list_reservations()` and/or `clusters.list_cluster_reservations()` | No |
| `ephemeral_describe` | `status.describe_namespace()` | No |
| `ephemeral_get_kubeconfig` | `clusters.get_kubeconfig()` | No |

`reservations.reserve()` contains a synchronous poll loop and is wrapped in
`asyncio.to_thread()` to avoid blocking the MCP event loop. All other calls are short
Kubernetes API round-trips and run directly.

### Auth Modes

Detected in priority order by `bonfire_mcp/auth.py:load_k8s_client()`:

| Priority | Trigger | Mode |
|---|---|---|
| 1 | `K8S_SERVER` + `K8S_TOKEN` env vars present | Token auth |
| 2 | `/var/run/secrets/kubernetes.io/serviceaccount/token` exists | In-cluster |
| 3 | `KUBECONFIG` env var or `~/.kube/config` | Kubeconfig (`K8S_CONTEXT` selects context) |

After constructing `EphemeralK8sClient`, `_preflight_check()` calls
`client.list_pools()` and `client.list_reservations()` to validate connectivity
and CRD presence:
- HTTP 401 → `RuntimeError` (auth failure, hard stop)
- HTTP 403 → warning logged, execution continues (operator may restrict some verbs)
- HTTP 404 → `RuntimeError` (CRD not installed)

### Lazy Initialization

`_client` and `_settings` globals in `server.py` are `None` at module load. They are
initialized on the first `call_tool()` invocation via `_get_client()` / `_get_settings()`.
This keeps server startup fast and avoids auth failures at import time.

### Output Format

All tools return `list[TextContent]` where the content is a human-readable plain-text string
produced by a formatter in `bonfire_mcp/formatters.py`. Errors return
`CallToolResult(isError=True)` — never raw Python exceptions.

---

## Dual Kubernetes Integration Paths

This is the most significant architectural tradeoff in the codebase.

| Dimension | Path 1: `ocviapy` / `oc` binary | Path 2: `kubernetes` Python client |
|---|---|---|
| **Used by** | `bonfire/openshift.py`, `bonfire/processor.py`, `bonfire/secrets.py` | `bonfire_lib/k8s_client.py` (all of bonfire_lib and bonfire_mcp) |
| **Requires** | `oc` binary on PATH, `oc login` / active kubeconfig context | Only kubeconfig or env-var credentials |
| **Auth** | Inherited from active `oc` session | Explicit: token, in-cluster, or kubeconfig |
| **Template processing** | `oc process` (full OpenShift template support) | Not applicable (Jinja2 only for CRs) |
| **Resource watching** | `ocviapy.ResourceWatcher`, `wait_for_ready_threaded` | Poll loop (2s interval) |
| **Apply** | `oc apply -f -` (streaming) | Not implemented (not needed) |
| **CRD operations** | `get_json("namespacepool")`, raw dict results | `DynamicClient.resources.get(kind=...)`, typed responses |
| **lru-caching** | Yes, for API discovery (`has_ns_operator`, `has_clowder`) | No |

### The Bridge Point

`bonfire/namespaces.py:_get_lib_client()` constructs an `EphemeralK8sClient()` with no
arguments, which triggers the kubeconfig auth mode. This means the CLI's reservation
lifecycle (reserve/release/extend/describe) runs through the Python Kubernetes client even
though the rest of the CLI uses `ocviapy`. The `oc` binary is still needed for template
processing, `apply`, and resource watching.

### Why Two Paths Exist

Path 1 (`ocviapy`) predates Path 2. `bonfire_lib` was introduced to provide a library
usable without the `oc` binary — enabling the MCP server and potential programmatic use.
Rather than rewriting the entire CLI, `bonfire/namespaces.py` was added as a bridge to
delegate reservation lifecycle to `bonfire_lib` while keeping the rest of the CLI on
`ocviapy`.

---

## Configuration and Environment Variables

### CLI Configuration (`bonfire/config.py`)

`bonfire/config.py` uses module-level `os.getenv()` calls that execute at import time,
after loading `~/.config/bonfire/env` via `python-dotenv`. All consuming modules import
the config module as `conf` and access constants directly (e.g., `conf.QONTRACT_BASE_URL`).

**Key CLI env vars:**

| Env Var | Default | Purpose |
|---|---|---|
| `QONTRACT_BASE_URL` | Red Hat production GraphQL URL | AppSRE GraphQL endpoint |
| `QONTRACT_TOKEN` | — | Bearer token for qontract auth |
| `QONTRACT_USERNAME` / `QONTRACT_PASSWORD` | — | Basic auth for qontract |
| `BONFIRE_NS_REQUESTER` | — | Override requester identity for reservations |
| `BONFIRE_BOT` | `"false"` | Suppresses interactive prompts when `"true"` |
| `BONFIRE_DEFAULT_PREFER` | `"ENV_NAME=frontends"` | Parameter preference for target deduplication |
| `BONFIRE_DEFAULT_REF_ENV` | `"insights-production"` | Default reference environment for `sub_refs` |
| `EPHEMERAL_ENV_NAME` | `"insights-ephemeral"` | Target OpenShift environment name |
| `BONFIRE_TRUSTED_APPS` | `["host-inventory"]` | Apps exempt from resource limit stripping |
| `GITHUB_TOKEN` | — | GitHub API auth for template fetching |
| `ENABLE_TELEMETRY` | `"false"` | Enables Elasticsearch usage telemetry |

**User config file:** `$XDG_CONFIG_HOME/bonfire/config.yaml` (default:
`~/.config/bonfire/config.yaml`). Created with defaults on first run. Structure:

```yaml
apps:       # local app definitions (--source=file mode)
appsFile:   # remote apps file reference
aliases:    # CLI command aliases
```

### Library Configuration (`bonfire_lib/config.py`)

`Settings` is a proper dataclass (unlike CLI's module-level constants), making it
constructible in tests without env-var side effects.

```python
@dataclass
class Settings:
    default_namespace_pool: str = "default"
    default_reservation_duration: str = "1h"
    default_requester: str = ""
    is_bot: bool = False
```

`Settings.from_env()` reads `BONFIRE_DEFAULT_NAMESPACE_POOL`, `BONFIRE_DEFAULT_DURATION`,
`BONFIRE_NS_REQUESTER`, `BONFIRE_BOT`.

### MCP Auth Env Vars (`bonfire_mcp/auth.py`)

| Env Var | Purpose |
|---|---|
| `K8S_SERVER` | API server URL (token auth mode) |
| `K8S_TOKEN` | Bearer token (token auth mode) |
| `K8S_CA_DATA` | Base64-encoded CA certificate |
| `K8S_SKIP_TLS_VERIFY` | Skip TLS verification (`"true"`) |
| `KUBECONFIG` | Path to kubeconfig file |
| `K8S_CONTEXT` | Kubeconfig context name override |

---

## AppSRE / qontract GraphQL Integration

All AppSRE querying lives in `bonfire/qontract.py`. The module maintains a module-level
singleton `_client` (no per-query caching — every `get_apps()` / `get_env()` call hits
the network).

### GraphQL Queries

**`ENVS_QUERY`** returns all environments:
```graphql
{ envs: environments_v1 {
    name
    parameters          # JSON string of env-level parameters
    namespaces { name, path, labels }
}}
```

**`APPS_QUERY`** returns all apps with their saas file deployment targets:
```graphql
{ apps: apps_v1 {
    name
    parentApp { name }
    saasFiles {
      path, name, parameters     # saas-file-level parameters
      resourceTemplates {
        name, path, url, hash_length, parameters  # component-level parameters
        targets {
          namespace { name, path, cluster { name } }
          ref           # git commit SHA or branch
          parameters    # target-level parameters
        }
      }
    }
}}
```

### Four-Layer Parameter Merging

`get_apps_for_env()` merges parameters from four layers (later layers win):

```
1. Environment-level parameters   (environments_v1.parameters)
2. Saas-file-level parameters     (saasFile.parameters)
3. Resource-template-level params (resourceTemplate.parameters)
4. Target-level parameters        (target.parameters)
```

`_process_env_parameters()` resolves `${VAR}` cross-references within a parameter set before
merging. The result is a flat `{KEY: VALUE}` dict attached to each component.

### App Filtering

Only apps whose `parentApp.name` is in `CONSOLEDOT_PARENT_APPS = ("insights", "image-builder")`
are considered. This filters the full AppSRE catalog down to cloud.redhat.com applications.

### Target Deduplication

A single component may have multiple targets across different namespaces in the same
environment (e.g., a `frontends` namespace and a `default` namespace). `_check_replace_other()`
scores each candidate target on:
- Presence of parameters in `BONFIRE_DEFAULT_PREFER` (e.g., `ENV_NAME=frontends`)
- `CLOWDER_ENABLED=true`
- `REPLICAS` / `MIN_REPLICAS` > 0

The higher-scoring target wins; ties keep the first one encountered.

### Reference Environment Substitution (`sub_refs`)

When `--ref-env` is specified, `sub_refs()` fetches app configs for both the reference
environment and an optional fallback reference environment. For each component in the
target environment's config, it finds the matching component in the ref env and copies
over its `ref` (git SHA) and any `IMAGE_TAG*` parameters. Falls back to `master` branch
ref if the component is not found in either reference environment.

### Component Data Model

The output of `get_apps_for_env()` has this shape:

```python
{
    "app-name": {
        "name": "app-name",
        "components": [
            {
                "name": "component-name",
                "path": "/path/to/template.yaml",
                "host": "github" | "gitlab",
                "repo": "org/repo",
                "ref": "abc1234",
                "hash_length": 7,
                "parameters": {
                    "IMAGE_TAG": "abc1234",
                    "ENV_NAME": "insights-ephemeral",
                    "CLOWDER_ENABLED": "true",
                    ...
                }
            }
        ]
    }
}
```

---

## Namespace and Cluster Reservation Lifecycle

### NamespaceReservation State Machine

The Ephemeral Namespace Operator (ENO) manages `NamespaceReservation` CRs on the cluster.
Bonfire creates and patches these CRs; ENO drives their state:

```
[create CR] → waiting → active → expired
                                   ↑
                  [patch spec.duration = "0s"] immediately
```

- **`waiting`**: ENO has not yet assigned a namespace from the pool.
- **`active`**: `status.namespace` is populated; `status.expiration` is set.
- **`expired`**: Duration elapsed or duration set to `"0s"`. ENO reclaims the namespace via OwnerRef cascade.

### Reserve Flow (`bonfire_lib/reservations.py:reserve`)

1. Generate reservation name: `"bonfire-reservation-<uuid>"` if not provided.
2. Resolve requester via `client.whoami()` if not provided.
3. Check for existing reservation with same name → `FatalError` if found.
4. `render_reservation()` → Jinja2 → YAML dict.
5. `client.create_reservation(body)` → `DynamicClient.create()`.
6. `wait_on_reservation()` polls `client.get_reservation(name)` every 2 seconds until
   `status.namespace` is populated or timeout is reached.
7. On timeout: calls `release()` to clean up the pending CR before raising `TimeoutError`.

### Release Mechanism

```python
client.patch_reservation(name, {"spec": {"duration": "0s"}})
```

Release does **not** delete the CR directly. Setting `spec.duration = "0s"` signals ENO,
which detects the change within ~10 seconds and cascades deletion via OwnerRef. This
ensures ENO can perform any necessary namespace cleanup before reclamation.

### Extend Mechanism

```python
prev = hms_to_seconds(res["spec"]["duration"])
added = hms_to_seconds(duration)
client.patch_reservation(name, {"spec": {"duration": duration_fmt(prev + added)}})
```

Duration is always expressed as an absolute total (not incremental) in the patch.

### Duration Constraints

Both `bonfire/utils.py` and `bonfire_lib/utils.py` contain independent but identical
`validate_time_string()` implementations enforcing:
- Format: regex `(Nh)?(Nm)?(Ns)?`
- Minimum: 1800 seconds (30 minutes)
- Maximum: 1209600 seconds (14 days)

The duplication is intentional: `bonfire_lib` must not import from `bonfire`.

### Cluster Reservations

`ClusterReservation` CRs (managed by a CAPI-compatible operator) follow a different
lifecycle from namespace reservations:

- **`reserve_cluster()`** is non-blocking: creates the CR and returns immediately with
  state `"waiting"`. Callers use `ephemeral_status` to poll.
- **`release_cluster()`** patches `spec.lifetime = "0s"` (same signal pattern as
  namespace reservations).
- Pool listing gracefully returns an empty list if the `ClusterPool` CRD is not present,
  making cluster support optional.

### Pool Capacity Enforcement

The CLI (`bonfire/openshift.py`) checks pool limits before reserving:
- `get_pool_size_limit(pool)` → reads `namespacepool.spec.sizeLimit`
- `get_reserved_namespace_quantity(pool)` → counts namespaces with `pool=<pool>` label
  and `reserved=true` annotation

If at capacity, a `FatalError` is raised before creating any CR. The ENO itself also
enforces capacity, but the CLI check provides a faster, more informative error.

---

## Template Processing

There are two independent template systems in bonfire with different scopes and mechanisms.

### System 1: OpenShift Templates via `oc process` (CLI only)

Used by `bonfire/processor.py` to render application manifests from saas file templates.

**Processing pipeline in `TemplateProcessor._get_component_items()`:**

1. Parse component config (source: qontract or local file).
2. `RepoFile.fetch()` → HTTP GET to GitHub/GitLab raw URL.
   - First resolves branch → commit SHA via GitHub/GitLab API.
   - Falls back to alternate branch names: `master → [main, stable]`.
   - Rate-limit retry: exponential backoff on HTTP 429 / 403-rate-limit (up to 3 attempts).
3. `yaml.safe_load(template_content)` → parse OpenShift Template YAML.
4. Build parameter dict from component parameters + injected defaults:
   - `IMAGE_TAG = commit_sha[:hash_length]` (if not overridden)
   - `NAMESPACE = self.namespace`
   - `ENV_NAME = self.clowd_env`
   - `FRONTEND_CONTEXT_NAME = self.clowd_env`
   - `_KUBE_API_SERVER = get_kube_api_server()`
5. Apply `--set-parameter` overrides via `_sub_params()`.
6. Strip untrusted resource limits via `_remove_untrusted_configs_for_template()`.
7. `ocviapy.process_template(template, params)` → `oc process` → list of K8s objects.
8. Apply `--set-image-tag` overrides via regex substitution on the JSON string.
9. Apply `--remove-dependencies` via `_alter_dependency_config()`.
10. Enforce `minReplicas=1`, `replicas=1` if `--single-replicas`.

**Recursive dependency resolution:** `_process_component()` calls `_handle_dependencies()`
which reads `ClowdApp.spec.dependencies` and `optionalDependencies` from the processed
output, then recurses into `_process_component()` for each. The `processed_components`
dict (keyed by component name) prevents infinite loops.

**`RepoFile`** (in `bonfire/utils.py`) handles fetching:
- GitHub: uses GitHub API to resolve branch → SHA; falls back to raw.githubusercontent.com.
- GitLab: downloads corporate CA cert from a Red Hat internal URL (cached, cleaned up
  on exit via `atexit`).
- Local: reads from `os.getcwd()`.
- Shared `requests.Session` for connection pooling.

### System 2: Jinja2 Templates for Custom Resources (`bonfire_lib/core_resources.py`)

Used to generate CR bodies for `NamespaceReservation`, `ClusterReservation`,
`ClowdEnvironment`, and `ClowdJobInvocation`. Templates live in
`bonfire_lib/templates/*.yaml.j2`.

```python
# Loaded once at import time:
_ENV = jinja2.Environment(loader=FileSystemLoader(_TEMPLATE_DIR))

def render_reservation(name, duration, requester, pool="default", team=None, ...):
    tmpl = _ENV.get_template("reservation.yaml.j2")
    rendered = tmpl.render(name=name, duration=duration, ...)
    return yaml.safe_load(rendered)  # returns dict, not string
```

The rendered dict is passed directly to `EphemeralK8sClient.create_reservation()`.

---

## Key Abstractions

### `EphemeralK8sClient` (`bonfire_lib/k8s_client.py`)

The sole Kubernetes interface for `bonfire_lib` and `bonfire_mcp`. Accepts an `EphemeralK8sClient`
as the first argument to every `bonfire_lib.*` function (dependency injection — no module-level
K8s state in the library).

- **Auth:** `_auth_mode` ∈ `{"token", "in-cluster", "kubeconfig"}`.
- **Dynamic CRDs:** `_get_resource(kind)` → `DynamicClient.resources.get(api_version="cloud.redhat.com/v1alpha1", kind=kind)`.
- **Core resources:** `_core_v1 = kubernetes.client.CoreV1Api` for namespaces, configmaps, secrets.
- **Patch content type:** all patch operations use `content_type="application/merge-patch+json"`.
- **Timeouts:** `DEFAULT_READ_TIMEOUT = 30s`, `DEFAULT_WRITE_TIMEOUT = 60s`.
- **`whoami()`:** kubeconfig mode reads `active_context["context"]["user"]`; token/in-cluster mode creates a `V1TokenReview`.

### `TemplateProcessor` (`bonfire/processor.py`)

Stateful accumulator for a single `bonfire process` or `bonfire deploy` invocation.

- `apps_config`: full app/component dict (from qontract or local).
- `requested_app_names`: set of apps to process (explicit + transitive deps).
- `processed_components`: `{name: ProcessedComponent}` — deduplication guard.
- `k8s_list`: growing `{"kind": "List", "items": [...]}` output.
- `_components_for_app`: `@cached_property {app_name: [component_names]}`.

`ProcessedComponent` dataclass: `name`, `items`, `deps_handled`, `optional_deps_handled`, `should_apply`.

### `Namespace` (`bonfire/namespaces.py`)

CLI-side namespace view. All properties are lazily evaluated on first access via `ocviapy`
calls. Key properties:
- `reserved`, `status`, `ready`, `available`, `owned_by_me`
- `reservation` — lazy fetch via `get_reservation(namespace=name)`
- `clowdapps` — `"{ready}/{total}"` string from `get_json("clowdapp", namespace=...)`
- `clusters` — CAPI cluster count from `cluster.cluster.x-k8s.io` resources
- `expires_in` — computed from `reservation.status.expiration`

### `AppOrComponentSelector` (`bonfire/utils.py`)

Models a CLI selector argument for options like `--remove-resources`, `--remove-dependencies`.

- `select_all: bool` — the `"all"` keyword.
- `apps: List[str]` — `app:<app_name>` prefixed entries.
- `components: dict[str, Set]` — `component_name → {dependency_names or wildcards}`.

### `Settings` (`bonfire_lib/config.py`)

Dataclass counterpart to `bonfire/config.py`'s module-level constants. Constructible
explicitly in tests without env-var side effects. `Settings.from_env()` is the production
path.

### `ElasticLogger` (`bonfire/elastic_logging.py`)

Optional non-blocking telemetry sink. Uses `ThreadPoolExecutor(max_workers=10)` for HTTP
POST to Elasticsearch. Active only when both `ENABLE_TELEMETRY=true` and
`ELASTICSEARCH_APIKEY` are set. CLI invocation args are sanitized before sending
(`--set-parameter` / `-p` values are masked).

---

## Error Handling

### CLI Error Propagation

Most namespace and deploy commands are wrapped with `click_exception_wrapper()`:

```python
except KeyboardInterrupt     → _error("aborted by keyboard interrupt")
except (TimedOutError,
        FatalError,
        StatusError)         → _error(f"hit error: {err}")
except Exception             → log.exception() + _error("hit unexpected error")
```

`_error(msg)` sends telemetry, prints to stderr, and calls `sys.exit(1)`.

Deploy failures additionally call `log_namespace_events(ns)` and optionally release
the namespace (suppressed with `--no-release-on-fail`).

`main_with_handler()` provides an outer catch for `StatusError` (from ocviapy) and
`FatalError` that escape the Click command handlers.

### `FatalError` Duplication

`bonfire/utils.py` and `bonfire_lib/utils.py` each define their own `FatalError` class.
These are distinct types: `bonfire.*` code raises and catches `bonfire.utils.FatalError`;
`bonfire_lib.*` code raises `bonfire_lib.utils.FatalError`. The MCP server catches
`bonfire_lib.utils.FatalError`.

### bonfire_lib Error Propagation

- `FatalError` (`bonfire_lib/utils.py`): logical errors (reservation not found, already exists, expired).
- `TimeoutError` (built-in): raised by `wait_on_reservation()` after releasing the
  pending CR for cleanup.
- `kubernetes.client.ApiException`: `EphemeralK8sClient` converts 404 to `None` return
  value; all other status codes propagate.

### MCP Error Handling

`call_tool()` catches all exceptions and converts them to `CallToolResult(isError=True)`:

```python
except FatalError    → "Error: ..."
except TimeoutError  → "Timeout: ..."
except ValueError    → "Validation error: ..."
except RuntimeError  → "Connection error: ..."
except Exception     → log.exception() + "Unexpected error: ..."
```

No Python exceptions propagate out of `call_tool()`. Input validation errors
(invalid DNS names, bad duration strings, missing required args) are caught and returned
as error results before any library call is made.

### Cluster CRD Optionality

`bonfire_lib/clusters.py:list_cluster_reservations()` and
`bonfire_lib/pools.py:list_cluster_pools()` catch all exceptions from their respective
list calls and return empty lists with a debug log. This makes cluster support optional:
clusters where the `ClusterReservation`/`ClusterPool` CRDs are not installed behave
identically to clusters with no cluster reservations.

### Retry Logic

| Location | Trigger | Strategy |
|---|---|---|
| `bonfire/utils.py:RepoFile._get()` | HTTP 429 or 403 with "rate limit" | Up to 3 attempts; sleep from `retry-after`, `x-ratelimit-reset`, or default 60s |
| `bonfire_lib/status.py:wait_on_reservation()` | Poll loop | 2s sleep per iteration, raises `TimeoutError` at limit; no retry |
| `bonfire/elastic_logging.py` | Telemetry POST failure | No retry; swallowed with `log.error()` |

---

## Known Tradeoffs

| Tradeoff | Current State | Implication |
|---|---|---|
| **Dual K8s paths** | `ocviapy`/`oc` for CLI template ops; Python `kubernetes` client for reservation lifecycle and MCP | Adds an `oc` binary runtime dependency for the full CLI; `bonfire_lib` and `bonfire_mcp` work without it |
| **`oc process` dependency** | Template processing cannot be done without the `oc` binary | Non-OpenShift environments or pure-library use cannot process saas file templates |
| **No per-query caching in qontract** | Every `get_apps_for_env()` call issues a full `APPS_QUERY` | Performance degrades with large AppSRE catalogs; repeated bonfire invocations re-fetch the full dataset |
| **Duplicate `FatalError` / `validate_time_string`** | Independent identical implementations in `bonfire/` and `bonfire_lib/` | Maintenance burden; changes must be applied in both places |
| **Synchronous poll loop in `reservations.reserve()`** | Blocks the calling thread for up to `timeout` seconds (default: 15 minutes) | MCP server wraps it in `asyncio.to_thread()` to avoid blocking the event loop; CLI callers block intentionally |
| **Module-level constants in `bonfire/config.py`** | Constants are evaluated at import time from env vars | Makes testing harder than `Settings.from_env()` style; a test that changes env vars must reload the module |
| **`oc` binary version coupling** | `ocviapy>=1.7.0` is the only version constraint | Breaking changes in `oc` CLI output format would silently affect all JSON-parsed responses |
| **GitLab CA cert fetched at runtime** | `RepoFile._fetch_gitlab()` downloads from `certs.corp.redhat.com` | Breaks in non-Red Hat network environments; cert is cached in a tempfile and cleaned up via `atexit` |
| **`MCP` optional dependency** | `mcp>=1.0.0` is in `[project.optional-dependencies.mcp]` | Default install does not include MCP support; users must install `crc-bonfire[mcp]` explicitly |

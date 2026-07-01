# AGENTS.md — Go implementation

Developer and agent instructions for the Go code in this directory.
For the Python codebase, see the root [AGENTS.md](../AGENTS.md).

## Overview

`go/pkg/ephemeral` is a Go port of `bonfire_lib` — the namespace and cluster reservation
lifecycle library. It speaks directly to `cloud.redhat.com/v1alpha1` CRDs via `client-go`
with no dependency on the `oc` binary or the Python runtime.

This directory is a **staging area**. It is not the standard Go repo layout (the `go.mod` is
one level below the repo root). The intention is to move it to a dedicated repo once Phase 2
(MCP server) is complete.

## Package structure

```
go/
├── go.mod                        # module: github.com/redhatinsights/bonfire, Go 1.24
└── pkg/
    └── ephemeral/
        ├── client_iface.go       # Client interface — all domain functions accept this
        ├── k8s_client.go         # EphemeralK8sClient: 3 auth modes, CRD + core v1 ops
        ├── config.go             # Settings struct + SettingsFromEnv()
        ├── utils.go              # FatalError, HMSToSeconds, DurationFmt, ValidateDNSName, ValidateTimeString
        ├── json.go               # nestedString/Int64/Map — nil-safe unstructured map traversal
        ├── reservations.go       # Reserve, Release, Extend
        ├── clusters.go           # ReserveCluster, ReleaseCluster, ExtendCluster, GetClusterStatus, GetKubeconfig
        ├── pools.go              # ListPools, ListClusterPools, GetPoolCapacity
        ├── status.go             # GetReservation, ListReservations, WaitOnReservation, DescribeNamespace
        └── *_test.go             # Table-driven tests; no live cluster required
```

## Development commands

```bash
# All commands run from go/ (not the repo root — go.mod is here)

# Run all tests
go test ./pkg/ephemeral/... -v

# Build
go build ./...

# Tidy dependencies
go mod tidy
```

## Design rules

**Client interface over concrete type.**
All domain functions accept `Client` (defined in `client_iface.go`), not `*EphemeralK8sClient`.
`*EphemeralK8sClient` satisfies `Client` at compile time (enforced by `var _ Client = (*EphemeralK8sClient)(nil)`).
In tests, always inject `testClient` — never construct a real client.

**No Jinja2 templates.**
CR bodies are built as `map[string]any` inline in `renderReservation` and `renderClusterReservation`.
The four `bonfire_lib/templates/*.yaml.j2` files have no Go equivalent; the struct replaces them.

**Nil-safe map traversal.**
Unstructured CRs come back as `map[string]any`. Never use raw type assertions on nested keys.
Use `nestedString`, `nestedInt64`, `nestedMap` from `json.go` — they return zero values on
missing or nil keys without panicking.

**Test doubles via function fields.**
Tests use `testClient` (in `mock_client_test.go`) — a struct of function fields, one per
`Client` method. `noopClient()` returns one with all fields stubbed to return zero values.
Override only the fields your test needs. No third-party mock library (gomock, testify) required.

**Auth priority order** (matches Python `bonfire_mcp/auth.py`):
1. `K8S_SERVER` + `K8S_TOKEN` env vars set → token auth
2. `/var/run/secrets/kubernetes.io/serviceaccount/token` exists → in-cluster
3. `KUBECONFIG` env var or `~/.kube/config` → kubeconfig

## Environment variables

| Env var | Default | Purpose |
|---|---|---|
| `BONFIRE_DEFAULT_NAMESPACE_POOL` | `default` | Default pool for namespace reservations |
| `BONFIRE_DEFAULT_DURATION` | `1h` | Default reservation duration |
| `BONFIRE_NS_REQUESTER` | — | Override requester identity |
| `EPHEMERAL_ENV_NAME` | `insights-ephemeral` | Target environment name |
| `DEFAULT_BASE_NAMESPACE` | `ephemeral-base` | Fallback base namespace |
| `BONFIRE_BOT` | `false` | Suppress interactive behaviour |
| `K8S_SERVER` | — | API server URL (token auth) |
| `K8S_TOKEN` | — | Bearer token (token auth) |
| `K8S_CA_DATA` | — | Base64-encoded CA cert (token auth) |
| `K8S_SKIP_TLS_VERIFY` | `false` | Skip TLS verification |
| `KUBECONFIG` | `~/.kube/config` | Kubeconfig file path |

## Common mistakes

1. **Running `go` commands from the repo root.** The `go.mod` is in `go/`, not the repo root.
   Always `cd go/` first, or use `go -C go/ test ./...`.

2. **Direct type assertions on nested CR fields.** `res["status"].(map[string]any)["namespace"]`
   panics if any key is missing or nil. Use `nestedString(res, "status", "namespace")` instead.

3. **Constructing `EphemeralK8sClient` in tests.** It dials a real cluster. Use `noopClient()`
   and override the function fields your test needs.

4. **Forgetting that cluster reservations are non-blocking.** `ReserveCluster` returns immediately
   with state `"waiting"`. The caller must poll `GetClusterStatus` until state is `"active"`.
   `Reserve` (namespace) blocks and polls internally — the Go version uses a `time.Ticker` loop,
   not `asyncio.to_thread`.

5. **Import paths include `/go/`.** e.g. `github.com/redhatinsights/bonfire/go/pkg/ephemeral`.
   This is a known awkwardness of the staging layout and will be fixed when the code moves to
   its own repo. Do not add a `replace` directive to work around it.

## Roadmap

### Phase 1 — `pkg/ephemeral` library ✓

- [x] `k8s_client.go` — `EphemeralK8sClient`: DynamicClient wrapper, 3 auth modes, typed CRUD
- [x] `client_iface.go` — `Client` interface; compile-time check `EphemeralK8sClient` satisfies it
- [x] `reservations.go` — `Reserve()`, `Release()`, `Extend()` namespace reservation lifecycle
- [x] `clusters.go` — `ReserveCluster()`, `ReleaseCluster()`, `ExtendCluster()`, `GetKubeconfig()`
- [x] `pools.go` — `ListPools()`, `ListClusterPools()`, `ListAllPools()`
- [x] `status.go` — `GetReservation()`, `ListReservations()`, `WaitOnReservation()`, `DescribeNamespace()`
- [x] `config.go` — `Settings` dataclass loaded from env vars via `SettingsFromEnv()`
- [x] `utils.go` — `FatalError`, `ValidateDNSName()`, `HMSToSeconds()`, `DurationFmt()`
- [x] 67 table-driven tests, no live cluster required
- [x] Deliverable: `go/pkg/ephemeral` — importable Go library replacing `bonfire_lib`

### Phase 2 — MCP server (`bonfire-mcp` Go binary)

- [ ] Add `go/pkg/mcp/` — MCP server using `github.com/mark3labs/mcp-go`
- [ ] Port 8 tools from `bonfire_mcp/server.py`: `ephemeral_list_pools`, `ephemeral_reserve`,
      `ephemeral_status`, `ephemeral_extend`, `ephemeral_release`, `ephemeral_list_reservations`,
      `ephemeral_describe`, `ephemeral_get_kubeconfig`
- [ ] Port auth detection from `bonfire_mcp/auth.py` — already implemented in `k8s_client.go`,
      wire up preflight check (401 → hard stop, 403 → warning, 404 → hard stop)
- [ ] Port formatters from `bonfire_mcp/formatters.py` — plain-text output for all tool results
- [ ] `cmd/bonfire-mcp/main.go` — stdio entry point (replaces `bonfire_mcp/__main__.py`)
- [ ] Port MCP server tests from `tests/test_bonfire_mcp/`
- [ ] Deliverable: single static binary `bonfire-mcp` with no Python or `oc` runtime dep

### Phase 3 — CLI namespace/cluster commands

- [ ] Add `cmd/bonfire/` — cobra CLI entry point
- [ ] Port `bonfire namespace reserve/release/extend/describe` — thin wrappers over `pkg/ephemeral`
- [ ] Port `bonfire pool list` and `bonfire cluster` commands
- [ ] Port config loading from `bonfire_lib/config.py` (already done as `Settings`)
- [ ] Deliverable: `bonfire` binary covering all non-deploy subcommands without `oc`

### Phase 4 — Template processing / deploy pipeline

Template processing uses `github.com/openshift/library-go` natively — no `oc` subprocess.

- [ ] Add `go/pkg/template/` — wrap `openshift/library-go/pkg/template/templateprocessing`
- [ ] Port `bonfire/utils.py:RepoFile` — fetch OpenShift Template YAML from GitHub/GitLab raw URLs,
      resolve branch → SHA via GitHub/GitLab API, exponential backoff on rate limits
- [ ] Port `bonfire/processor.py:TemplateProcessor` — parameter injection, `--set-parameter`,
      `--set-image-tag`, `--single-replicas`, recursive ClowdApp dependency resolution,
      untrusted resource limit stripping
- [ ] Port `bonfire/qontract.py` — GraphQL client (`APPS_QUERY`, `ENVS_QUERY`),
      4-layer parameter merge, `sub_refs`
- [ ] Port `bonfire deploy` end-to-end: reserve → fetch → process → apply → wait
- [ ] Deliverable: full `bonfire` CLI with no Python or `oc` runtime dep

### Move to dedicated repo or replace this repo (after Phase 2)

- [ ] Create `github.com/redhatinsights/bonfire-go` (or take over `bonfire` name)
- [ ] Move `go/` contents to repo root — standard Go layout (`go.mod` at root, `cmd/`, `pkg/`)
- [ ] Fix import paths (drop the `/go/` segment)
- [ ] Set up CI: `go build`, `go test`, `go vet`, `golangci-lint`
- [ ] Publish binary releases via GitHub Actions (goreleaser)

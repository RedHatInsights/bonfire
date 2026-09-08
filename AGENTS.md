# AGENTS.md

## Project Overview

Bonfire is a CLI tool and MCP server for deploying and managing ephemeral test environments on
OpenShift/Kubernetes clusters for console.redhat.com applications. It is distributed on PyPI as
`crc-bonfire` and contains three distinct sub-packages in a single distribution: `bonfire` (CLI),
`bonfire_lib` (shared library, no `oc` binary required), and `bonfire_mcp` (MCP server). The CLI
requires the `oc` binary; the library and MCP server use the `kubernetes` Python client directly.

| Package | Purpose | Key Dependencies |
|---------|---------|-----------------|
| `bonfire` | Click-based CLI for deploying apps via OpenShift templates | `click`, `ocviapy`, `gql`, `sh`, `tabulate` |
| `bonfire_lib` | Shared library for ephemeral reservation lifecycle | `kubernetes`, `jinja2`, `pyyaml` |
| `bonfire_mcp` | MCP server exposing reservation tools to AI agents | `mcp`, `bonfire_lib` |

## Dependencies

**Runtime:** `click >= 7.1.2`, `ocviapy >= 1.7.0`, `kubernetes >= 29.0.0`, `mcp >= 1.0.0` (optional),
`jinja2 >= 3.1.0`, `gql[requests] >= 3.5.0`, `requests >= 2.33.0`, `rich >= 13.0.0`, `PyYAML`,
`tabulate`, `python-dotenv`, `sh`, `setuptools_scm`, `truststore`, `app-common-python >= 0.1.6`.

**Dev/test:** `pytest`, `pytest-asyncio`, `pytest-mock`, `requests-mock`, `mock`. Install with
`pip install -e ".[test,mcp]"`.

## Development Commands

See [Local Development](README.md#local-development) in the README for the full setup reference.
Key commands for agent-driven workflows:

```bash
# Install in editable mode with test and MCP extras
pip install -e ".[test,mcp]"

# Run all tests (integration tests excluded by default)
pytest -sv

# Run a specific test suite
pytest tests/test_bonfire_mcp/ -sv
pytest tests/test_bonfire_lib/ -sv
pytest tests/test_bonfire.py -sv

# Integration tests (require live K8s cluster — never run in CI)
pytest -m integration -sv

# Lint and format
ruff check --fix .
ruff format .

# Build wheel + sdist
python -m build -o dist/
```

**CI runs:** `ruff check`, pre-commit hooks, `python -m build`, `twine check --strict`, and
`pytest -sv` on Python 3.10/3.11/3.12 (Ubuntu + macOS) with `oc` 4.16 available.

> **Note:** The `cli` extra referenced in some older docs is not defined in `pyproject.toml`.
> Use the base install or `.[test,mcp]` instead.

## Architecture

Three sub-packages share one `pyproject.toml`: `bonfire/` (Click CLI, requires `oc` binary),
`bonfire_lib/` (shared library using the `kubernetes` Python client, no `oc` needed), and
`bonfire_mcp/` (MCP server, imports only from `bonfire_lib.*`). Entry points:
`bonfire` → `bonfire.bonfire:main_with_handler`; `bonfire-mcp` → `bonfire_mcp.server:main`.
The CLI bridges reservation lifecycle into `bonfire_lib` via `bonfire/namespaces.py`.

For full details — data flows, dual K8s path tradeoffs, CRD API, qontract GraphQL integration,
reservation lifecycle, template processing, and key abstractions — see [ARCHITECTURE.md](ARCHITECTURE.md).

## Code Style

**Linter/formatter:** `ruff` (v0.15.16). Configured in `[tool.ruff]` in `pyproject.toml`:
line-length 100, indent-width 4. Run `ruff check --fix .` and `ruff format .`.

**`.flake8` is a legacy artifact** — it is not invoked in CI or pre-commit. `ruff` is the sole
authoritative tool.

**Python version:** 3.10+ is required. Type hints follow `from __future__ import annotations`
style where used. No f-string walrus operators or other 3.12+ syntax.

## Testing

MCP server tests use `pytest-asyncio` with **strict mode** (`asyncio_mode = "strict"` in
`pyproject.toml`). Every async test **must** be decorated with `@pytest.mark.asyncio`:

```python
@pytest.mark.asyncio
async def test_something(self):
    result = await call_tool("ephemeral_reserve", {"name": "test"})
```

Tests mock at the K8s client boundary — never hit a real cluster:

- **bonfire_lib tests**: `MagicMock(spec=EphemeralK8sClient)` in conftest
- **bonfire_mcp tests**: Patch `bonfire_mcp.server._get_client` and individual modules
  (`bonfire_mcp.server.reservations`, `bonfire_mcp.server.clusters`, etc.)
- **CLI tests**: Patch `bonfire.namespaces._get_lib_client`

The MCP server returns `CallToolResult(isError=True)` for errors, not exceptions:

```python
assert isinstance(result, CallToolResult)
assert result.isError is True
assert "Error" in result.content[0].text
```

Successful results return `list[TextContent]`, not `CallToolResult`.

Tests marked `@pytest.mark.integration` require a live cluster and are excluded by default.

## Common Mistakes

1. **Using the `cli` extra that doesn't exist.** `pyproject.toml` defines `lib`, `mcp`, and
   `test` extras. The `cli` extra does not exist — `pip install crc-bonfire[cli,test,mcp]` will
   fail. Use `pip install -e ".[test,mcp]"` for development.

2. **Importing `bonfire.*` from `bonfire_mcp`.** The MCP server must only import from
   `bonfire_lib.*`. `bonfire.*` has an `oc` binary dependency that is absent in MCP environments.
   The one-way rule: `bonfire_mcp` → `bonfire_lib` → (no imports from `bonfire`).

3. **Confusing `bonfire/resources/` with `bonfire_lib/templates/`.** These are different template
   systems. `bonfire/resources/` contains OpenShift Template YAML files processed via `oc process`.
   `bonfire_lib/templates/` contains Jinja2 `*.yaml.j2` files rendered by Python. Do not mix them.

4. **Treating namespace and cluster reservations as symmetric.** Namespace `reserve()` blocks
   synchronously (polls until namespace is assigned, up to 15 minutes). Cluster `reserve_cluster()`
   is non-blocking — it returns immediately with `state: "waiting"` and the caller must poll
   `get_cluster_status()`.

5. **Patching at the wrong layer in MCP tests.** Patch `bonfire_mcp.server._get_client` (not
   `bonfire_lib.k8s_client.EphemeralK8sClient`) and patch individual module references (e.g.,
   `bonfire_mcp.server.reservations`) rather than the original module, to correctly intercept
   calls inside `call_tool()`.

6. **Modifying `bonfire/config.py` constants in tests without reloading.** Module-level constants
   are evaluated at import time from `os.getenv()`. Changing env vars in a test does not
   retroactively update already-imported constants — the module must be reloaded or the constants
   patched directly (e.g., `monkeypatch.setattr(conf, "QONTRACT_BASE_URL", ...)`).

7. **Assuming `.flake8` is active.** The `.flake8` config is a legacy artifact not used in CI or
   pre-commit. Only `ruff` is authoritative. Do not add flake8 ignore comments — use
   `# noqa` with ruff rule codes if suppression is needed.

## Deployment

Released to PyPI as `crc-bonfire` via GitHub Actions (`release.yml`) on tag push using OIDC
trusted publishing. A container image is published to
`quay.io/redhat-user-workloads/hcm-eng-prod-tenant/bonfire/bonfire` via Tekton (Konflux)
on every push to `master`. Version is derived from git tags by `setuptools_scm` — there is no
hardcoded version string in source.

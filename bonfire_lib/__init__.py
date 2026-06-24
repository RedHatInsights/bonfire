"""Shared library for ephemeral environment lifecycle operations.

Provides reservation lifecycle (reserve, release, extend), pool queries,
status polling, and core resource rendering — all using the kubernetes
Python client directly (no ocviapy/oc dependency).
"""

__all__ = [
    "config",
    "core_resources",
    "deploy",
    "k8s_client",
    "pools",
    "qontract",
    "repo_fetch",
    "reservations",
    "status",
    "utils",
]

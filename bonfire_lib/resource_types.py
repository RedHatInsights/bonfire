"""Resource type enum for polymorphic ephemeral resource dispatch."""

from enum import Enum


class ResourceType(str, Enum):
    """Ephemeral resource types supported by the system.

    Each resource type maps to different CRDs, has different provisioning
    characteristics, and returns different target credentials.
    """

    NAMESPACE = "namespace"
    CLUSTER = "cluster"
    # Future: SANDBOX = "sandbox"

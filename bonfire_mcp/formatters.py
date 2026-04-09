"""MCP output formatters for ephemeral environment resources."""


def format_reservation(reservation: dict) -> str:
    """Format a reservation dict as human-readable text for MCP responses."""
    name = reservation.get("name", "unknown")
    ns = reservation.get("namespace", "pending")
    state = reservation.get("state", "unknown")
    expiration = reservation.get("expiration", "")
    requester = reservation.get("requester", "")
    pool = reservation.get("pool", "default")

    lines = [
        f"Reservation: {name}",
        f"  State: {state}",
        f"  Namespace: {ns}",
        f"  Pool: {pool}",
        f"  Requester: {requester}",
    ]
    if expiration:
        lines.append(f"  Expiration: {expiration}")
    return "\n".join(lines)


def format_pool_list(pools: list[dict]) -> str:
    """Format a list of pool dicts as a readable table."""
    if not pools:
        return "No namespace pools found."

    lines = ["Namespace Pools:", ""]
    header = f"  {'Name':<25} {'Ready':>5} {'Creating':>8} {'Reserved':>8} {'Size':>4} {'Limit':>5}"
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    for pool in pools:
        limit = str(pool.get("size_limit", "")) if pool.get("size_limit") else "-"
        lines.append(
            f"  {pool['name']:<25} {pool.get('ready', 0):>5} "
            f"{pool.get('creating', 0):>8} {pool.get('reserved', 0):>8} "
            f"{pool.get('size', 0):>4} {limit:>5}"
        )

    return "\n".join(lines)


def format_reservation_list(reservations: list[dict]) -> str:
    """Format a list of reservation summary dicts."""
    if not reservations:
        return "No active reservations found."

    lines = ["Active Reservations:", ""]
    header = (
        f"  {'Name':<35} {'Namespace':<25} {'State':<10} "
        f"{'Requester':<20} {'Pool':<10} {'Duration':<10}"
    )
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    for res in reservations:
        lines.append(
            f"  {res.get('name', ''):<35} {res.get('namespace', ''):<25} "
            f"{res.get('state', ''):<10} {res.get('requester', ''):<20} "
            f"{res.get('pool', ''):<10} {res.get('duration', ''):<10}"
        )

    return "\n".join(lines)


def format_describe(info: dict) -> str:
    """Format namespace description dict as detailed output."""
    lines = [
        f"Namespace: {info.get('namespace', 'unknown')}",
    ]

    console_url = info.get("console_namespace_route", "")
    if console_url:
        lines.append(f"Console URL: {console_url}")

    gateway = info.get("gateway_route", "")
    if gateway:
        lines.append(f"Gateway route: {gateway}")

    lines.append(f"ClowdApps deployed: {info.get('clowdapps_deployed', 0)}")
    lines.append(f"Frontends deployed: {info.get('frontends_deployed', 0)}")

    kc_route = info.get("keycloak_admin_route", "")
    if kc_route:
        lines.append(f"Keycloak admin route: {kc_route}")
        lines.append(
            f"Keycloak admin login: "
            f"{info.get('keycloak_admin_username', 'N/A')} | "
            f"{info.get('keycloak_admin_password', 'N/A')}"
        )

    default_user = info.get("default_username", "")
    if default_user and default_user != "N/A":
        lines.append(
            f"Default user login: {default_user} | "
            f"{info.get('default_password', 'N/A')}"
        )

    return "\n".join(lines)


def format_release(result: dict) -> str:
    """Format a release result."""
    name = result.get("name", "unknown")
    return f"Reservation '{name}' released. Resource will be reclaimed by the operator."


def format_extend(result: dict) -> str:
    """Format an extend result."""
    name = result.get("name", "unknown")
    new_duration = result.get("new_duration", "unknown")
    return f"Reservation '{name}' extended. New total duration: {new_duration}."


def format_cluster_reservation(reservation: dict) -> str:
    """Format a cluster reservation dict for MCP responses."""
    name = reservation.get("name", "unknown")
    state = reservation.get("state", "unknown")
    cluster_name = reservation.get("cluster_name", "")
    console_url = reservation.get("console_url", "")
    requester = reservation.get("requester", "")
    pool = reservation.get("pool", "rosa-default")
    expiration = reservation.get("expiration", "")
    created = reservation.get("created", "")

    lines = [
        f"Cluster Reservation: {name}",
        f"  State: {state}",
        f"  Pool: {pool}",
        f"  Requester: {requester}",
    ]
    if cluster_name:
        lines.append(f"  Cluster: {cluster_name}")
    if console_url:
        lines.append(f"  Console: {console_url}")
    if expiration:
        lines.append(f"  Expiration: {expiration}")
    if state in ("waiting", "provisioning") and not cluster_name:
        lines.append("  Note: Poll with ephemeral_status(name='%s', type='cluster') to track progress." % name)
    return "\n".join(lines)


def format_cluster_pool_list(pools: list[dict]) -> str:
    """Format a list of cluster pool dicts as a readable table."""
    if not pools:
        return "No cluster pools found."

    lines = ["Cluster Pools:", ""]
    header = (
        f"  {'Name':<25} {'Ready':>5} {'Provisioning':>12} "
        f"{'Reserved':>8} {'Size':>4} {'Limit':>5}"
    )
    lines.append(header)
    lines.append("  " + "-" * (len(header) - 2))

    for pool in pools:
        lines.append(
            f"  {pool['name']:<25} {pool.get('ready', 0):>5} "
            f"{pool.get('provisioning', 0):>12} {pool.get('reserved', 0):>8} "
            f"{pool.get('size', 0):>4} {pool.get('size_limit', 0):>5}"
        )

    return "\n".join(lines)


def format_kubeconfig(name: str, kubeconfig: str) -> str:
    """Format a kubeconfig response."""
    return f"Kubeconfig for cluster reservation '{name}':\n\n{kubeconfig}"

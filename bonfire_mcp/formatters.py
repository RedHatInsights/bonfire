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
    return f"Reservation '{name}' released. Namespace will be reclaimed within ~10 seconds."


def format_extend(result: dict) -> str:
    """Format an extend result."""
    name = result.get("name", "unknown")
    new_duration = result.get("new_duration", "unknown")
    return f"Reservation '{name}' extended. New total duration: {new_duration}."

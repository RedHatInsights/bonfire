"""Shared utility functions for bonfire_lib."""

import re


class FatalError(Exception):
    """An error that should cause the caller to stop."""

    pass


_DNS_LABEL_RE = re.compile(r"^[a-z0-9]([a-z0-9\-]{0,61}[a-z0-9])?$")


def validate_dns_name(name: str) -> str:
    """Validate that a name conforms to DNS-1123 label rules.

    Rules: lowercase alphanumeric + hyphens, 1-63 chars,
    must start and end with alphanumeric.
    """
    if not _DNS_LABEL_RE.match(name):
        raise ValueError(
            f"invalid name '{name}': must be a DNS-1123 label "
            "(lowercase alphanumeric + hyphens, 1-63 chars)"
        )
    return name


def hms_to_seconds(s: str) -> int:
    """Convert a duration string (e.g., '1h30m', '45m', '3600s') to seconds.

    Raises ValueError for empty or invalid strings.
    """
    if not s:
        raise ValueError("duration string cannot be empty")
    fmt = r"^(?:(?P<hours>\d+)h)?(?:(?P<minutes>\d+)m)?(?:(?P<seconds>\d+)s)?$"
    split = re.match(fmt, s)
    if not split or not any(split.groupdict().values()):
        raise ValueError(f"invalid duration format: '{s}'")
    seconds = 0
    parts = split.groupdict()
    if parts["hours"]:
        seconds += int(parts["hours"]) * 3600
    if parts["minutes"]:
        seconds += int(parts["minutes"]) * 60
    if parts["seconds"]:
        seconds += int(parts["seconds"])
    return seconds


def duration_fmt(seconds: int) -> str:
    """Convert seconds to a duration string (e.g., '1h30m0s').

    This is the inverse of hms_to_seconds().
    """
    seconds = int(seconds)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if hours > 0:
        return "%dh%dm%ds" % (hours, minutes, seconds)
    elif minutes > 0:
        return "%dm%ds" % (minutes, seconds)
    else:
        return "%ds" % (seconds,)


def pretty_time_delta(seconds: int) -> str:
    """Format seconds as a human-readable time delta (e.g., '2d3h15m0s')."""
    seconds = int(seconds)
    days, seconds = divmod(seconds, 86400)
    hours, seconds = divmod(seconds, 3600)
    minutes, seconds = divmod(seconds, 60)
    if days > 0:
        return "%dd%dh%dm%ds" % (days, hours, minutes, seconds)
    elif hours > 0:
        return "%dh%dm%ds" % (hours, minutes, seconds)
    elif minutes > 0:
        return "%dm%ds" % (minutes, seconds)
    else:
        return "%ds" % (seconds,)


def validate_time_string(time_str: str) -> str:
    """Validate a duration string format and range.

    Must be in h/m/s format (e.g., '1h30m'), between 30 minutes and 14 days.
    """
    valid_time = re.compile(r"^((\d+)h)?((\d+)m)?((\d+)s)?$")
    if not valid_time.match(time_str):
        raise ValueError(
            f"invalid format for duration '{time_str}', expecting h/m/s string. Ex: '1h30m'"
        )
    seconds = hms_to_seconds(time_str)
    if seconds > 1209600:  # 14 days
        raise ValueError(f"invalid duration '{time_str}', must be less than 14 days")
    elif seconds < 1800:  # 30 mins
        raise ValueError(f"invalid duration '{time_str}', must be more than 30 mins")
    return time_str

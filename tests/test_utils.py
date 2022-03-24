import pytest

from bonfire.utils import (
    validate_time_string,
    hms_to_seconds
)


@pytest.mark.parametrize(
    "time, expected",
    [
        (
            "30m",
            "30m"
        ),
        (
            "1h45m",
            "1h45m"
        ),
        (
            "1h20s",
            "1h20s"
        ),
        (
            "2h15m32s",
            "2h15m32s"
        )
    ]
)
def test_validate_time_string(time: str, expected: str):
    result = validate_time_string(time)

    assert result == expected


@pytest.mark.parametrize(
    "seconds, expected",
    [
        (
            "1h",
            3600,
        ),
        (
            "45m",
            2700
        ),
        (
            "65s",
            65
        ),
        (
            "1h30m",
            5400
        )
    ]
)
def test_hms_to_seconds(seconds: str, expected: int):
    result = hms_to_seconds(seconds)

    assert result == expected

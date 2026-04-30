import pytest

from bonfire_lib.utils import (
    FatalError,
    hms_to_seconds,
    duration_fmt,
    pretty_time_delta,
    validate_dns_name,
    validate_time_string,
)


class TestFatalError:
    def test_is_exception_subclass(self):
        assert issubclass(FatalError, Exception)

    def test_can_raise(self):
        with pytest.raises(FatalError, match="test error"):
            raise FatalError("test error")


class TestHmsToSeconds:
    def test_hours_only(self):
        assert hms_to_seconds("1h") == 3600

    def test_minutes_only(self):
        assert hms_to_seconds("30m") == 1800

    def test_seconds_only(self):
        assert hms_to_seconds("90s") == 90

    def test_hours_and_minutes(self):
        assert hms_to_seconds("1h30m") == 5400

    def test_all_units(self):
        assert hms_to_seconds("1h0m30s") == 3630

    def test_empty_string(self):
        with pytest.raises(ValueError):
            hms_to_seconds("")

    def test_zero(self):
        assert hms_to_seconds("0s") == 0

    def test_large_values(self):
        assert hms_to_seconds("24h") == 86400


class TestDurationFmt:
    def test_hours_minutes_seconds(self):
        assert duration_fmt(5400) == "1h30m0s"

    def test_minutes_seconds(self):
        assert duration_fmt(90) == "1m30s"

    def test_seconds_only(self):
        assert duration_fmt(45) == "45s"

    def test_zero(self):
        assert duration_fmt(0) == "0s"

    def test_exact_hour(self):
        assert duration_fmt(3600) == "1h0m0s"

    def test_roundtrip(self):
        assert hms_to_seconds(duration_fmt(5400)) == 5400


class TestPrettyTimeDelta:
    def test_with_days(self):
        assert pretty_time_delta(90061) == "1d1h1m1s"

    def test_hours(self):
        assert pretty_time_delta(3661) == "1h1m1s"

    def test_minutes(self):
        assert pretty_time_delta(61) == "1m1s"

    def test_seconds(self):
        assert pretty_time_delta(5) == "5s"


class TestValidateDnsName:
    def test_valid_names(self):
        assert validate_dns_name("my-reservation") == "my-reservation"
        assert validate_dns_name("abc123") == "abc123"
        assert validate_dns_name("a") == "a"

    def test_invalid_uppercase(self):
        with pytest.raises(ValueError, match="invalid name"):
            validate_dns_name("INVALID")

    def test_invalid_starts_with_hyphen(self):
        with pytest.raises(ValueError, match="invalid name"):
            validate_dns_name("-invalid")

    def test_invalid_ends_with_hyphen(self):
        with pytest.raises(ValueError, match="invalid name"):
            validate_dns_name("invalid-")

    def test_invalid_too_long(self):
        with pytest.raises(ValueError, match="invalid name"):
            validate_dns_name("a" * 64)

    def test_invalid_special_chars(self):
        with pytest.raises(ValueError, match="invalid name"):
            validate_dns_name("invalid_name")

    def test_empty_string(self):
        with pytest.raises(ValueError, match="invalid name"):
            validate_dns_name("")


class TestValidateTimeString:
    def test_valid_duration(self):
        assert validate_time_string("1h") == "1h"
        assert validate_time_string("1h30m") == "1h30m"
        assert validate_time_string("45m") == "45m"

    def test_invalid_format(self):
        with pytest.raises(ValueError, match="invalid format"):
            validate_time_string("abc")

    def test_too_short(self):
        with pytest.raises(ValueError, match="must be more than 30 mins"):
            validate_time_string("10m")

    def test_too_long(self):
        with pytest.raises(ValueError, match="must be less than 14 days"):
            validate_time_string("360h")

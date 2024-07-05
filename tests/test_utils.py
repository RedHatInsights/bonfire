import pytest

from bonfire.utils import (
    get_version,
    hms_to_seconds,
    split_equals,
    validate_time_string,
    check_pypi,
    PYPI_URL,
)
from bonfire.utils import check_url_connection, FatalError


@pytest.mark.parametrize(
    "list_of_str, expected",
    [
        (["t1=test1", "t2=test2"], {"t1": "test1", "t2": "test2"}),
        (["t3=test3", "t4=test4"], {"t3": "test3", "t4": "test4"}),
    ],
)
def test_split_equals_pass(list_of_str: str, expected: str):
    result = split_equals(list_of_str)

    assert result == expected


@pytest.mark.parametrize(
    "list_of_str",
    [
        (["t1 = test1", "t2 = test2"],),
        (["t1 test1", "t2 test2"],),
    ],
)
def test_split_equals_raises_error(list_of_str: list):
    with pytest.raises(ValueError):
        split_equals(list_of_str)


@pytest.mark.parametrize(
    "time, expected",
    [
        ("30m", "30m"),
        ("1h45m", "1h45m"),
        ("1h20s", "1h20s"),
        ("2h15m32s", "2h15m32s"),
    ],
)
def test_validate_time_string(time: str, expected: str):
    result = validate_time_string(time)

    assert result == expected


@pytest.mark.parametrize("time", [("5m"), ("480h"), ("130")])
def test_validate_time_raises_error(time: str):
    with pytest.raises(ValueError):
        validate_time_string(time)


def test_get_version():
    result = get_version()

    assert result != "0.0.0"


@pytest.mark.parametrize(
    "seconds, expected",
    [
        ("1h", 3600),
        ("45m", 2700),
        ("65s", 65),
        ("1h30m", 5400),
    ],
)
def test_hms_to_seconds(seconds: str, expected: int):
    result = hms_to_seconds(seconds)

    assert result == expected


def test_url_connection_raises_on_invalid_url():
    with pytest.raises(ValueError, match=r".*invalidhosturl.*"):
        check_url_connection("foo-invalidhosturl")


def test_url_connection_checks_hostname(mocker):
    socket_library_mock = mocker.patch("bonfire.utils.socket.socket")
    socket_mock = socket_library_mock.return_value.__enter__.return_value
    check_url_connection("https://validhost.com")
    socket_mock.connect.assert_called_with(("validhost.com", 443))
    socket_mock.settimeout.assert_called_once()


def test_url_connection_timeout_handling(mocker):
    socket_library_mock = mocker.patch("bonfire.utils.socket.socket")
    socket_mock = socket_library_mock.return_value.__enter__.return_value
    socket_mock.connect.side_effect = TimeoutError("timed out!")

    with pytest.raises(FatalError, match=r"Unable to connect to.*after.*seconds.*is VPN needed.*"):
        check_url_connection("https://timingout.com")


def test_ip_timeout():
    with pytest.raises(FatalError, match="Unable to connect to.*after 1 seconds.*is VPN needed.*"):
        check_url_connection("https://10.255.255.1", timeout=1)


def test_url_connection_dns_lookup_fails():
    with pytest.raises(FatalError, match=r".*DNS lookup failed.*"):
        check_url_connection("https://baddomain.invalid")


def test_check_version_when_there_is_a_new_update(requests_mock, mocker):
    mocker.patch("bonfire.utils.Path").exists.return_value = False
    log_mock = mocker.patch("bonfire.utils.log")
    mocker.patch("bonfire.utils.importlib_metadata").version.return_value = "1.0.0"
    requests_mock.get(PYPI_URL, json={"info": {"version": "1.0.1"}})

    check_pypi()

    log_mock.info.assert_called()
    assert "checking pypi" in log_mock.info.call_args_list[0].args[0]
    assert "new release found" in log_mock.info.call_args_list[1].args[0]
    assert "yours: 1.0.0, available: 1.0.1" in log_mock.info.call_args_list[1].args[0]


def test_check_version_when_there_are_no_updates(requests_mock, mocker):
    mocker.patch("bonfire.utils.Path").exists.return_value = True
    log_mock = mocker.patch("bonfire.utils.log")
    mocker.patch("bonfire.utils.importlib_metadata").version.return_value = "1.0.0"
    requests_mock.get(PYPI_URL, json={"info": {"version": "1.0.0"}})

    check_pypi()

    log_mock.info.assert_called()
    assert "checking pypi" in log_mock.info.call_args_list[0].args[0]
    assert "new release found" not in log_mock.info.call_args_list[1].args[0]
    assert "up-to-date" in log_mock.info.call_args_list[1].args[0]


def test_check_version_unexpected_json(requests_mock, mocker):
    mocker.patch("bonfire.utils.Path").exists.return_value = False
    log_mock = mocker.patch("bonfire.utils.log")
    mocker.patch("bonfire.utils.importlib_metadata").version.return_value = "1.0.0"
    requests_mock.get(PYPI_URL, json={"woops": "not found"})

    check_pypi()

    log_mock.error.assert_called_once()
    assert "unable to parse version info" in log_mock.error.call_args_list[0].args[0]


def test_check_version_invalid_response(requests_mock, mocker):
    mocker.patch("bonfire.utils.Path").exists.return_value = False
    log_mock = mocker.patch("bonfire.utils.log")
    mocker.patch("bonfire.utils.importlib_metadata").version.return_value = "1.0.0"
    requests_mock.get(PYPI_URL, text="nothing!")

    check_pypi()

    log_mock.error.assert_called_once()
    assert "error fetching version from pypi" in log_mock.error.call_args_list[0].args[0]

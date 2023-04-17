import json
from pathlib import Path
from unittest.mock import ANY

import pytest
from click.testing import CliRunner

from bonfire import bonfire
from bonfire.utils import FatalError

DATA_PATH = Path(__file__).parent.joinpath("data")


@pytest.fixture(scope="module")
def namespace_list():
    with open(DATA_PATH.joinpath("namespace_data.json"), "r") as namespace_data_file:
        return json.load(namespace_data_file)["items"]


@pytest.fixture(scope="module")
def reservation_list():
    with open(DATA_PATH.joinpath("reservation_data.json"), "r") as reservation_data_file:
        return json.load(reservation_data_file)["items"]


@pytest.mark.parametrize(
    "name",
    [
        ("ns-6"),
        ("ns-7"),
    ],
)
def test_ns_reserve_flag_name(mocker, caplog, name: str):
    caplog.set_level(100000)

    mocker.patch("bonfire.bonfire.get_namespace_pools", return_value=["default"])
    mocker.patch("bonfire.bonfire.get_pool_size_limit", return_value=0)
    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.bonfire._get_requester", return_value="user-3")
    mocker.patch("bonfire.bonfire.check_for_existing_reservation", return_value=False)
    mocker.patch("bonfire.namespaces.get_reservation", return_value=None)
    mocker.patch("bonfire.processor.process_template", return_value={})

    mock_process_reservation = mocker.patch("bonfire.namespaces.process_reservation")

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["reserve", "--name", name])
    print(result.output)

    mock_process_reservation.assert_called_once_with(name, "user-3", "1h", "default", local=True)


@pytest.mark.parametrize(
    "requester",
    [
        ("user-3"),
        ("user-2"),
    ],
)
def test_ns_reserve_flag_requester(mocker, caplog, requester: str):
    caplog.set_level(100000)

    mocker.patch("bonfire.bonfire.get_namespace_pools", return_value=["default"])
    mocker.patch("bonfire.bonfire.get_pool_size_limit", return_value=0)
    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.bonfire._get_requester", return_value=requester)
    mocker.patch("bonfire.bonfire.check_for_existing_reservation", return_value=False)
    mocker.patch("bonfire.namespaces.get_reservation", return_value=None)
    mocker.patch("bonfire.processor.process_template", return_value={})

    mock_process_reservation = mocker.patch("bonfire.namespaces.process_reservation")

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["reserve", "--requester", requester])
    print(result.output)

    mock_process_reservation.assert_called_once_with(None, requester, "1h", "default", local=True)


@pytest.mark.parametrize(
    "duration",
    [
        ("1h"),
        (None),
        ("30m"),
    ],
)
def test_ns_reserve_flag_duration(mocker, caplog, duration: str):
    caplog.set_level(100000)

    mocker.patch("bonfire.bonfire.get_namespace_pools", return_value=["default"])
    mocker.patch("bonfire.bonfire.get_pool_size_limit", return_value=0)
    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.bonfire._get_requester", return_value="user-3")
    mocker.patch("bonfire.bonfire.check_for_existing_reservation", return_value=False)
    mocker.patch("bonfire.namespaces.get_reservation", return_value=None)
    mocker.patch("bonfire.processor.process_template", return_value={})

    mock_process_reservation = mocker.patch("bonfire.namespaces.process_reservation")

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["reserve", "--duration", duration])
    print(result.output)

    if duration:
        mock_process_reservation.assert_called_once_with(
            None, "user-3", duration, "default", local=True
        )
    else:
        mock_process_reservation.assert_called_once_with(
            None, "user-3", "1h", "default", local=True
        )


def test_ns_list_option(mocker, caplog, namespace_list: list, reservation_list: list):
    caplog.set_level(100000)

    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.namespaces.get_all_namespaces", return_value=namespace_list)
    mocker.patch("bonfire.namespaces.get_json", return_value={})
    mocker.patch("bonfire.namespaces.get_all_reservations", return_value=reservation_list)
    mocker.patch("bonfire.namespaces.on_k8s", return_value=False)
    mocker.patch("bonfire.namespaces.whoami", return_value="user-1")
    mocker.patch("bonfire.processor.process_template", return_value={})

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["list"])
    print(result.output)

    actual = " ".join(result.output.split())

    assert " ".join(["ns-1", "true", "false", "none", "user-1", "minimal"]) in actual
    assert " ".join(["ns-2", "true", "false", "none", "user-2", "default"]) in actual
    assert " ".join(["ns-3", "false", "ready", "none", "default"]) in actual
    assert " ".join(["ns-4", "false", "ready", "none", "default"]) in actual
    assert " ".join(["ns-5", "true", "false", "none", "user-5", "default"]) in actual


def test_ns_list_options_available(mocker, caplog, namespace_list: list, reservation_list: list):
    caplog.set_level(100000)

    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.namespaces.get_all_namespaces", return_value=namespace_list)
    mocker.patch("bonfire.namespaces.get_json", return_value={})
    mocker.patch("bonfire.namespaces.get_all_reservations", return_value=reservation_list)
    mocker.patch("bonfire.namespaces.on_k8s", return_value=False)
    mocker.patch("bonfire.namespaces.whoami", return_value="user-1")
    mocker.patch("bonfire.processor.process_template", return_value={})

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["list", "--available"])

    actual = " ".join(result.output.split())

    assert " ".join(["ns-1", "true", "false", "none", "user-1"]) not in actual
    assert " ".join(["ns-2", "true", "false", "none", "user-2"]) not in actual
    assert " ".join(["ns-3", "false", "ready", "none"]) in actual
    assert " ".join(["ns-4", "false", "ready", "none"]) in actual
    assert " ".join(["ns-5", "true", "false", "none", "user-5"]) not in actual


def test_ns_list_option_mine(mocker, caplog, namespace_list: list, reservation_list: list):
    caplog.set_level(100000)

    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.namespaces.get_all_namespaces", return_value=namespace_list)
    mocker.patch("bonfire.namespaces.get_json", return_value={})
    mocker.patch("bonfire.namespaces.get_all_reservations", return_value=reservation_list)
    mocker.patch("bonfire.namespaces.on_k8s", return_value=False)
    mocker.patch("bonfire.namespaces.whoami", return_value="user-1")
    mocker.patch("bonfire.processor.process_template", return_value={})

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["list", "--mine"])
    print(result.output)

    actual = " ".join(result.output.split())

    assert " ".join(["ns-1", "true", "false", "none", "user-1"]) in actual
    assert " ".join(["ns-2", "true", "false", "none", "user-2"]) not in actual
    assert " ".join(["ns-3", "false", "ready", "none"]) not in actual
    assert " ".join(["ns-4", "false", "ready", "none"]) not in actual
    assert " ".join(["ns-5", "true", "false", "none", "user-5"]) not in actual


def test_ns_list_flag_output(
    mocker,
    caplog,
    namespace_list: list,
    reservation_list: list,
):
    caplog.set_level(100000)

    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.namespaces.get_all_namespaces", return_value=namespace_list)
    mocker.patch("bonfire.namespaces.get_json", return_value={})
    mocker.patch("bonfire.namespaces.get_all_reservations", return_value=reservation_list)
    mocker.patch("bonfire.namespaces.on_k8s", return_value=False)
    mocker.patch("bonfire.namespaces.whoami", return_value="user-1")
    mocker.patch("bonfire.processor.process_template", return_value={})

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["list", "--output", "json"])
    print(result.output)

    actual_ns_1 = json.loads(result.output).get("ns-1")
    actual_ns_2 = json.loads(result.output).get("ns-2")
    actual_ns_3 = json.loads(result.output).get("ns-3")
    actual_ns_4 = json.loads(result.output).get("ns-4")
    actual_ns_5 = json.loads(result.output).get("ns-5")

    del actual_ns_1["expires_in"]
    del actual_ns_2["expires_in"]
    del actual_ns_3["expires_in"]
    del actual_ns_4["expires_in"]
    del actual_ns_5["expires_in"]

    test_items_1 = {
        "reserved": True,
        "status": "false",
        "requester": "user-1",
        "pool_type": "minimal",
    }
    test_items_2 = {
        "reserved": True,
        "status": "false",
        "requester": "user-2",
        "pool_type": "default",
    }
    test_items_3 = {"reserved": False, "status": "ready", "requester": None, "pool_type": "default"}
    test_items_4 = {"reserved": False, "status": "ready", "requester": None, "pool_type": "default"}
    test_items_5 = {
        "reserved": True,
        "status": "false",
        "requester": "user-5",
        "pool_type": "default",
    }

    assert all([item in test_items_1.items() for item in actual_ns_1.items()])
    assert all([item in test_items_2.items() for item in actual_ns_2.items()])
    assert all([item in test_items_3.items() for item in actual_ns_3.items()])
    assert all([item in test_items_4.items() for item in actual_ns_4.items()])
    assert all([item in test_items_5.items() for item in actual_ns_5.items()])


@pytest.mark.parametrize(
    "user, namespace, timeout",
    [
        ("user-6", "ns-6", 600),
        ("user-7", "ns-7", 700),
    ],
)
def test_ns_reserve_flag_timeout(mocker, caplog, user: str, namespace: str, timeout: int):
    caplog.set_level(100000)

    mocker.patch("bonfire.bonfire.get_namespace_pools", return_value=["default"])
    mocker.patch("bonfire.bonfire.get_pool_size_limit", return_value=0)
    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.namespaces.whoami", return_value=user)
    mocker.patch("bonfire.bonfire.check_for_existing_reservation", return_value=False)
    mocker.patch("bonfire.namespaces.get_reservation", return_value=None)
    mocker.patch("bonfire.namespaces.process_reservation")
    mocker.patch("bonfire.namespaces.apply_config")

    mock_wait_on_res = mocker.patch("bonfire.namespaces.wait_on_reservation")

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["reserve", "--timeout", timeout])
    print(result.output)

    mock_wait_on_res.assert_called_once_with(ANY, timeout)


def test_pool_list_command(mocker, caplog):
    caplog.set_level(100000)

    fake_pools = ["very", "fake", "pools"]
    mocker.patch("bonfire.bonfire.get_namespace_pools", return_value=fake_pools)

    runner = CliRunner()
    result = runner.invoke(bonfire.pool, ["list"])
    print(result.output)

    output = [str(r) for r in result.output.split("\n") if r != ""]

    assert output == fake_pools


default_kc = {
    "username": "admin",
    "password": "adminPassword",
    "defaultUsername": "jdoe",
    "defaultPassword": "password",
}
eph_test_route = "env-ephemeral-blah-howdy.apps.c-rh-c-eph.8p0c.p1.openshiftapps.com"


def test_describe_ephemeral_ns(mocker):
    mocker.patch("bonfire.namespaces.get_console_url", return_value="yes.redhat.com")
    mocker.patch("bonfire.namespaces.get_keycloak_creds", return_value=default_kc)
    mocker.patch("bonfire.namespaces.parse_fe_env", return_value=(eph_test_route, "foo"))
    mocker.patch("bonfire.namespaces.get_json")
    mocker.patch("bonfire.namespaces.Namespace")
    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["describe", "ephemeral-blah"])
    print(result.output)

    assert "jdoe | password" in result.output
    assert "env-ephemeral-blah-howdy" in result.output
    assert "yes.redhat.com" in result.output


def test_describe_ephemeral_ns_from_ctx(mocker):
    mocker.patch("bonfire.namespaces.get_console_url", return_value="yes.redhat.com")
    mocker.patch("bonfire.namespaces.get_keycloak_creds", return_value=default_kc)
    mocker.patch("bonfire.namespaces.parse_fe_env", return_value=(eph_test_route, "foo"))
    mocker.patch("bonfire.namespaces.get_json")
    mocker.patch("bonfire.namespaces.Namespace")
    mocker.patch("bonfire.bonfire.current_namespace_or_error", return_value="ephemeral-blah")
    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["describe"])
    print(result.output)

    assert "jdoe | password" in result.output
    assert "env-ephemeral-blah-howdy" in result.output
    assert "yes.redhat.com" in result.output


def test_describe_default_ns(mocker):
    mocker.patch("bonfire.namespaces.get_console_url", return_value="yes.redhat.com")
    mocker.patch("bonfire.namespaces.get_keycloak_creds", return_value=default_kc)
    mocker.patch("bonfire.namespaces.parse_fe_env", return_value=(eph_test_route, "foo"))
    mocker.patch("bonfire.namespaces.get_json")
    runner = CliRunner()
    try:
        result = runner.invoke(bonfire.namespace, ["describe", "default"])
        print(result.output)
    except FatalError:
        assert True


def test_describe_wrong_ns(mocker):
    mocker.patch("bonfire.namespaces.get_json", return_value=None)
    runner = CliRunner()
    try:
        result = runner.invoke(bonfire.namespace, ["describe", "ephemeral-memes"])
        print(result.output)
    except FatalError:
        assert True

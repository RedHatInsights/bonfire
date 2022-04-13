import pytest
from click.testing import CliRunner
from mock import Mock
import json

#from data import data

from bonfire import bonfire


namespace_data = {}
reservation_data = {}

with open("data/namespace_data.json", 'r') as namespace_data_file:
    namespace_data = json.load(namespace_data_file)

with open("data/reservation_data.json", 'r') as reservation_data_file:
    reservation_data = json.load(reservation_data_file)

namespace_list = namespace_data["items"]
reservation_list = reservation_data["items"]

namespace_data_file.close()
reservation_data_file.close()


@pytest.mark.parametrize(
    "name",
    [
        ("namespace-6"),
        ("namespace-7"),
    ],
)
def test_ns_reserve_options_name(mocker, name: str):
    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.bonfire._get_requester", return_value="user-3")
    mocker.patch("bonfire.bonfire.check_for_existing_reservation", return_value=False)
    mocker.patch("bonfire.namespaces.get_reservation", return_value=None)

    mock_process_reservation = mocker.patch("bonfire.namespaces.process_reservation")

    runner = CliRunner()
    runner.invoke(bonfire.namespace, ["reserve", "--name", name])

    mock_process_reservation.assert_called_once_with(name, "user-3", '1h', local=True)


@pytest.mark.parametrize(
    "requester",
    [
        ("user-3"),
        ("user-2"),
    ],
)
def test_ns_reserve_options_requester(mocker, requester: str):
    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.bonfire._get_requester", return_value=requester)
    mocker.patch("bonfire.bonfire.check_for_existing_reservation", return_value=False)
    mocker.patch("bonfire.namespaces.get_reservation", return_value=None)

    mock_process_reservation = mocker.patch("bonfire.namespaces.process_reservation")

    runner = CliRunner()
    runner.invoke(bonfire.namespace, ["reserve", "--requester", requester])

    mock_process_reservation.assert_called_once_with(None, requester, '1h', local=True)


@pytest.mark.parametrize(
    "duration",
    [
        ("1h"),
        #(None),
        #("30m"),
    ],
)
def test_ns_reserve_options_duration(mocker, duration: str):
    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.bonfire._get_requester", return_value="user-3")
    mocker.patch("bonfire.bonfire.check_for_existing_reservation", return_value=False)
    mocker.patch("bonfire.namespaces.get_reservation", return_value=None)

    mock_process_reservation = mocker.patch("bonfire.namespaces.process_reservation")

    runner = CliRunner()
    runner.invoke(bonfire.namespace, ["reserve", "--duration", duration])

    mock_process_reservation.assert_called_once_with(None, "user-3", duration, local=True)


def test_ns_list_option(mocker):
    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.namespaces.get_all_namespaces", return_value=namespace_list)
    mocker.patch("bonfire.namespaces.get_json", return_value={})
    mocker.patch("bonfire.namespaces.get_all_reservations", return_value=reservation_list)
    mocker.patch("bonfire.namespaces.on_k8s", return_value=False)
    mocker.patch("bonfire.namespaces.whoami", return_value="user-1")

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["list"])

    print(result.output)

    assert ' '.join(["namespace-1", "true", "false", "none", "user-1"]) in ' '.join(result.output.split())
    assert ' '.join(["namespace-2",  "true", "false", "none", "user-2"]) in ' '.join(result.output.split())
    assert ' '.join(["namespace-3",  "false", "ready", "none"]) in ' '.join(result.output.split())
    assert ' '.join(["namespace-4",  "false", "ready", "none"]) in ' '.join(result.output.split())
    assert ' '.join(["namespace-5",  "true", "false", "none", "user-5"]) in ' '.join(result.output.split())


def test_ns_list_options_available(mocker):
    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.namespaces.get_all_namespaces", return_value=namespace_list)
    mocker.patch("bonfire.namespaces.get_json", return_value={})
    mocker.patch("bonfire.namespaces.get_all_reservations", return_value=reservation_list)
    mocker.patch("bonfire.namespaces.on_k8s", return_value=False)
    mocker.patch("bonfire.namespaces.whoami", return_value="user-1")

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["list", "--available"])

    print(result.output)

    assert ' '.join(["namespace-1", "true", "false", "none", "user-1"]) not in ' '.join(result.output.split())
    assert ' '.join(["namespace-2",  "true", "false", "none", "user-2"]) not in ' '.join(result.output.split())
    assert ' '.join(["namespace-3",  "false", "ready", "none"]) in ' '.join(result.output.split())
    assert ' '.join(["namespace-4",  "false", "ready", "none"]) in ' '.join(result.output.split())
    assert ' '.join(["namespace-5",  "true", "false", "none", "user-5"]) not in ' '.join(result.output.split())


def test_ns_list_option_mine(mocker):
    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.namespaces.get_all_namespaces", return_value=namespace_list)
    mocker.patch("bonfire.namespaces.get_json", return_value={})
    mocker.patch("bonfire.namespaces.get_all_reservations", return_value=reservation_list)
    mocker.patch("bonfire.namespaces.on_k8s", return_value=False)
    mocker.patch("bonfire.namespaces.whoami", return_value="user-1")

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["list", "--mine"])

    print(result.output)

    assert ' '.join(["namespace-1", "true", "false", "none", "user-1"]) in ' '.join(result.output.split())
    assert ' '.join(["namespace-2",  "true", "false", "none", "user-2"]) not in ' '.join(result.output.split())
    assert ' '.join(["namespace-3",  "false", "false", "none"]) not in ' '.join(result.output.split())
    assert ' '.join(["namespace-4",  "false", "false", "none"]) not in ' '.join(result.output.split())
    assert ' '.join(["namespace-5",  "true", "false", "none", "user-5"]) not in ' '.join(result.output.split())

import pytest
from click.testing import CliRunner
from pathlib import Path
import json

from bonfire import bonfire


DATA_PATH = Path(__file__).parent.joinpath("data")


@pytest.fixture(scope="module")
def namespace_list() -> list:
    with open(DATA_PATH.joinpath("namespace_data.json"), "r") as namespace_data_file:
        return json.load(namespace_data_file)["items"]


@pytest.fixture(scope="module")
def reservation_list() -> list:
    with open(
        DATA_PATH.joinpath("reservation_data.json"), "r"
    ) as reservation_data_file:
        return json.load(reservation_data_file)["items"]


@pytest.mark.parametrize(
    "name",
    [
        ("namespace-6"),
        ("namespace-7"),
    ],
)
def test_ns_reserve_options_name(mocker, caplog, name: str):
    caplog.set_level(100000)

    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.bonfire._get_requester", return_value="user-3")
    mocker.patch("bonfire.bonfire.check_for_existing_reservation", return_value=False)
    mocker.patch("bonfire.namespaces.get_reservation", return_value=None)
    mocker.patch("bonfire.openshift.process_template", return_value={})

    mock_process_reservation = mocker.patch("bonfire.namespaces.process_reservation")

    runner = CliRunner()
    runner.invoke(bonfire.namespace, ["reserve", "--name", name])

    mock_process_reservation.assert_called_once_with(name, "user-3", "1h", local=True)


@pytest.mark.parametrize(
    "requester",
    [
        ("user-3"),
        ("user-2"),
    ],
)
def test_ns_reserve_options_requester(mocker, caplog, requester: str):
    caplog.set_level(100000)

    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.bonfire._get_requester", return_value=requester)
    mocker.patch("bonfire.bonfire.check_for_existing_reservation", return_value=False)
    mocker.patch("bonfire.namespaces.get_reservation", return_value=None)
    mocker.patch("bonfire.openshift.process_template", return_value={})

    mock_process_reservation = mocker.patch("bonfire.namespaces.process_reservation")

    runner = CliRunner()
    runner.invoke(bonfire.namespace, ["reserve", "--requester", requester])

    mock_process_reservation.assert_called_once_with(None, requester, "1h", local=True)


@pytest.mark.parametrize(
    "duration",
    [
        ("1h"),
        (None),
        ("30m"),
    ],
)
def test_ns_reserve_options_duration(mocker, caplog, duration: str):
    caplog.set_level(100000)

    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.bonfire._get_requester", return_value="user-3")
    mocker.patch("bonfire.bonfire.check_for_existing_reservation", return_value=False)
    mocker.patch("bonfire.namespaces.get_reservation", return_value=None)
    mocker.patch("bonfire.openshift.process_template", return_value={})

    mock_process_reservation = mocker.patch("bonfire.namespaces.process_reservation")

    runner = CliRunner()
    runner.invoke(bonfire.namespace, ["reserve", "--duration", duration])

    if duration:
        mock_process_reservation.assert_called_once_with(
            None, "user-3", duration, local=True
        )
    else:
        mock_process_reservation.assert_called_once_with(
            None, "user-3", "1h", local=True
        )


def test_ns_list_option(mocker, caplog, namespace_list: list, reservation_list: list):
    caplog.set_level(100000)

    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.namespaces.get_all_namespaces", return_value=namespace_list)
    mocker.patch("bonfire.namespaces.get_json", return_value={})
    mocker.patch(
        "bonfire.namespaces.get_all_reservations", return_value=reservation_list
    )
    mocker.patch("bonfire.namespaces.on_k8s", return_value=False)
    mocker.patch("bonfire.namespaces.whoami", return_value="user-1")
    mocker.patch("bonfire.openshift.process_template", return_value={})

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["list"])

    actual = " ".join(result.output.split())

    assert " ".join(["namespace-1", "true", "false", "none", "user-1"]) in actual
    assert " ".join(["namespace-2", "true", "false", "none", "user-2"]) in actual
    assert " ".join(["namespace-3", "false", "ready", "none"]) in actual
    assert " ".join(["namespace-4", "false", "ready", "none"]) in actual
    assert " ".join(["namespace-5", "true", "false", "none", "user-5"]) in actual


def test_ns_list_options_available(
    mocker, caplog, namespace_list: list, reservation_list: list
):
    caplog.set_level(100000)

    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.namespaces.get_all_namespaces", return_value=namespace_list)
    mocker.patch("bonfire.namespaces.get_json", return_value={})
    mocker.patch(
        "bonfire.namespaces.get_all_reservations", return_value=reservation_list
    )
    mocker.patch("bonfire.namespaces.on_k8s", return_value=False)
    mocker.patch("bonfire.namespaces.whoami", return_value="user-1")
    mocker.patch("bonfire.openshift.process_template", return_value={})

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["list", "--available"])

    actual = " ".join(result.output.split())

    assert " ".join(["namespace-1", "true", "false", "none", "user-1"]) not in actual
    assert " ".join(["namespace-2", "true", "false", "none", "user-2"]) not in actual
    assert " ".join(["namespace-3", "false", "ready", "none"]) in actual
    assert " ".join(["namespace-4", "false", "ready", "none"]) in actual
    assert " ".join(["namespace-5", "true", "false", "none", "user-5"]) not in actual


def test_ns_list_option_mine(
    mocker, caplog, namespace_list: list, reservation_list: list
):
    caplog.set_level(100000)

    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.namespaces.get_all_namespaces", return_value=namespace_list)
    mocker.patch("bonfire.namespaces.get_json", return_value={})
    mocker.patch(
        "bonfire.namespaces.get_all_reservations", return_value=reservation_list
    )
    mocker.patch("bonfire.namespaces.on_k8s", return_value=False)
    mocker.patch("bonfire.namespaces.whoami", return_value="user-1")
    mocker.patch("bonfire.openshift.process_template", return_value={})

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["list", "--mine"])

    actual = " ".join(result.output.split())

    assert " ".join(["namespace-1", "true", "false", "none", "user-1"]) in actual
    assert " ".join(["namespace-2", "true", "false", "none", "user-2"]) not in actual
    assert " ".join(["namespace-3", "false", "ready", "none"]) not in actual
    assert " ".join(["namespace-4", "false", "ready", "none"]) not in actual
    assert " ".join(["namespace-5", "true", "false", "none", "user-5"]) not in actual


@pytest.mark.parametrize(
    "namespace, data",
    [
        ("namespace-1", {"reserved": True, "status": "false", "requester": "user-1"}),
        ("namespace-2", {"reserved": True, "status": "false", "requester": "user-2"}),
        ("namespace-3", {"reserved": False, "status": "ready", "requester": None}),
        ("namespace-4", {"reserved": False, "status": "ready", "requester": None}),
        ("namespace-5", {"reserved": True, "status": "false", "requester": "user-5"}),
    ],
)
def test_ns_list_option_output(
    mocker,
    caplog,
    namespace_list: list,
    reservation_list: list,
    namespace: str,
    data: dict,
):
    caplog.set_level(100000)

    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.namespaces.get_all_namespaces", return_value=namespace_list)
    mocker.patch("bonfire.namespaces.get_json", return_value={})
    mocker.patch(
        "bonfire.namespaces.get_all_reservations", return_value=reservation_list
    )
    mocker.patch("bonfire.namespaces.on_k8s", return_value=False)
    mocker.patch("bonfire.namespaces.whoami", return_value="user-1")
    mocker.patch("bonfire.openshift.process_template", return_value={})

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["list", "--output", "json"])

    actual_ns_1 = json.loads(result.output).get("namespace-1")
    actual_ns_2 = json.loads(result.output).get("namespace-2")
    actual_ns_3 = json.loads(result.output).get("namespace-3")
    actual_ns_4 = json.loads(result.output).get("namespace-4")
    actual_ns_5 = json.loads(result.output).get("namespace-5")

    print(actual_ns_1)
    print(actual_ns_2)
    print(actual_ns_3)
    print(actual_ns_4)
    print(actual_ns_5)

    assert {
        "reserved": True,
        "status": "false",
        "requester": "user-1",
    }.items() <= actual_ns_1.items()
    assert {
        "reserved": True,
        "status": "false",
        "requester": "user-2",
    }.items() <= actual_ns_2.items()
    assert {
        "reserved": False,
        "status": "ready",
        "requester": None,
    }.items() <= actual_ns_3.items()
    assert {
        "reserved": False,
        "status": "ready",
        "requester": None,
    }.items() <= actual_ns_4.items()
    assert {
        "reserved": True,
        "status": "false",
        "requester": "user-5",
    }.items() <= actual_ns_5.items()

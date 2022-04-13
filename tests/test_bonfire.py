import pytest
from click.testing import CliRunner
from mock import Mock

from bonfire import bonfire
from bonfire import namespaces


all_namespaces = [
    {
        "metadata": {
            "name": "namespace-1",
            "namespace": "namspace-1",
            "annotations": {
                "status": "false",
                "operator-ns": "true",
                "reserved": "true"
            }
        },
        "status": {
            "namespace": "namespace-1",
        },
    },
    {
        "metadata": {
            "name": "namespace-2",
            "namespace": "namspace-2",
            "annotations": {
                "status": "false",
                "operator-ns": "true",
                "reserved": "true"
            }
        },
        "status": {
            "namespace": "namespace-2",
        }
    },
    {
        "metadata": {
            "name": "namespace-3",
            "namespace": "namspace-3",
            "annotations": {
                "status": "ready",
                "operator-ns": "true",
                "reserved": "false,"
            }
        },
        "status": {
            "namespace": "namespace-3",
        }
    },
    {
        "metadata": {
            "name": "namespace-4",
            "namespace": "namspace-4",
            "annotations": {
                "status": "ready",
                "operator-ns": "true",
                "reserved": "false,"
            }
        },
        "status": {
            "namespace": "namespace-4",
        }
    },
    {
        "metadata": {
            "name": "namespace-5",
            "namespace": "namespace-5",
            "annotations": {
                "status": "false",
                "operator-ns": "true",
                "reserved": "true"
            }
        },
        "status": {
            "namespace": "namespace-5",
        }
    },
]

all_reservations = [
    {
        "metadata": {
            "name": "namespace-1"
        },
        "status": {
            "namespace": "namespace-1",
            "state": "active",
            "expiration": "2024-04-13T22:00:00Z"
        },
        "spec": {
            "requester": "user-1",
        }
    },
    {
        "metadata": {
            "name": "namespace-2"
        },
        "status": {
            "namespace": "namespace-2",
            "state": "active",
            "expiration": "2024-04-29T22:00:00Z"
        },
        "spec": {
            "requester": "user-2",
        }
    },
    {
        "metadata": {
            "name": "namespace-5"
        },
        "status": {
            "namespace": "namespace-5",
            "state": "active",
            "expiration": "2024-04-19T16:30:00Z"
        },
        "spec": {
            "requester": "user-5",
        }
    },
]


@pytest.mark.parametrize(
    "name, expected",
    [
        ("namespacereservation", "ephemeral-namespace-test-1"),
        ("namespacereservation", "ephemeral-namespace-test-2"),
    ],
)
def test_ns_reserve_options_name(mocker, name: str, expected: str):
    ns = Mock()
    ns.name = expected

    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.openshift.has_ns_operator", return_value=True)
    mocker.patch("bonfire.openshift.get_api_resources", return_value={"name": name})
    mocker.patch("bonfire.openshift.check_for_existing_reservation", return_value=True)
    mocker.patch("bonfire.openshift.parse_restype", return_value="")
    mocker.patch("bonfire.openshift.get_all_reservations", return_value="")
    mocker.patch("bonfire.bonfire.reserve_namespace", return_value=ns)

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["reserve", "--name", name])

    print(result.output)

    assert result.output.rstrip() == expected


@pytest.mark.parametrize(
    "user",
    [
        ("user1"),
        ("user2"),
    ],
)
def test_ns_reserve_options_requester(mocker, user: str):
    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.bonfire.check_for_existing_reservation", return_value=False)
    mocker.patch("bonfire.openshift.get_api_resources", return_value={"name": user})
    mocker.patch("bonfire.namespaces.apply_config")
    mocker.patch("bonfire.openshift.has_ns_operator", return_value=True)
    mocker.patch("bonfire.openshift.parse_restype", return_value="")
    mocker.patch("bonfire.openshift._exec_oc")
    mocker.patch("bonfire.namespaces.wait_on_reservation", return_value=user)

    mock_process_reservation = mocker.patch("bonfire.namespaces.process_reservation")

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["reserve", "--requester", user])
    
    print(result.output)

    mock_process_reservation.assert_called_with(None, user, '1h', local=True)


# @pytest.mark.parametrize(
#     "duration",
#     [
#         ("1h"),
#         (None),
#         ("30m"),
#     ],
# )
# def test_ns_reserve_options_duration(mocker, duration: str):
#     mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
#     mocker.patch("bonfire.bonfire.check_for_existing_reservation", return_value=False)
#     mocker.patch("bonfire.openshift.get_api_resources", return_value={"name": "user-1"})
#     mocker.patch("bonfire.namespaces.apply_config")
#     mocker.patch("bonfire.openshift.has_ns_operator", return_value=True)
#     mocker.patch("bonfire.openshift.parse_restype", return_value="")
#     mocker.patch("bonfire.openshift._exec_oc")
#     mocker.patch("bonfire.namespaces.wait_on_reservation", return_value="user-1")
    
#     mock_process_reservation = mocker.patch("bonfire.namespaces.process_reservation")

#     runner = CliRunner()
#     runner.invoke(bonfire.namespace, ["reserve", "--duration", duration])

#     print(result.output)
#     mock_process_reservation.assert_called_with(None, 'user-1', duration, local=True)


def test_ns_list_option(mocker):
    mocker.patch("bonfire.bonfire.has_ns_operator", return_value=True)
    mocker.patch("bonfire.namespaces.get_all_namespaces", return_value=all_namespaces)
    mocker.patch("bonfire.namespaces.get_json", return_value={})
    mocker.patch("bonfire.namespaces.get_all_reservations", return_value=all_reservations)
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
    mocker.patch("bonfire.namespaces.get_all_namespaces", return_value=all_namespaces)
    mocker.patch("bonfire.namespaces.get_json", return_value={})
    mocker.patch("bonfire.namespaces.get_all_reservations", return_value=all_reservations)
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
    mocker.patch("bonfire.namespaces.get_all_namespaces", return_value=all_namespaces)
    mocker.patch("bonfire.namespaces.get_json", return_value={})
    mocker.patch("bonfire.namespaces.get_all_reservations", return_value=all_reservations)
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

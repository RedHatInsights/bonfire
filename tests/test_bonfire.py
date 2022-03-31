from unicodedata import name
import click
from click.testing import CliRunner
import pytest
from mock import patch, Mock
from tabulate import tabulate

from bonfire import bonfire
from bonfire import openshift


@pytest.mark.parametrize(
    "name, expected",
    [
        (
            "namespacereservation", "ephemeral-namespace-test-1"
        ),
        (
            "namespacereservation", "ephemeral-namespace-test-2"
        ),
    ]
)
def test_ns_reserve_options_name(mocker, caplog, name, expected):
    caplog.set_level(100000)

    ns = Mock()
    ns.name=expected

    mocker.patch('bonfire.bonfire.has_ns_operator', return_value=True)
    mocker.patch('bonfire.openshift.has_ns_operator', return_value=True)
    mocker.patch('bonfire.openshift.get_api_resources', return_value={"name": name})
    mocker.patch('bonfire.openshift.check_for_existing_reservation', return_value=True)
    mocker.patch('bonfire.openshift.parse_restype', return_value="")
    mocker.patch('bonfire.openshift.get_json', return_value="")
    mocker.patch('bonfire.openshift.get_all_reservations', return_value="")
    mocker.patch('bonfire.bonfire.reserve_namespace', return_value=ns)
    
    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["reserve", "--name", name])

    assert result.output.rstrip() == expected


@pytest.mark.parametrize(
    "user, expected",
    [
        (
            "user1", "user1"
        ),
        (
            "user2", "user2"
        ),
    ]
)
def test_ns_reserve_options_requester(mocker, caplog, user, expected):
    caplog.set_level(100000)

    ns = Mock()
    ns.name=expected

    mocker.patch('bonfire.bonfire.has_ns_operator', return_value=True)
    mocker.patch('bonfire.openshift.has_ns_operator', return_value=True)
    mocker.patch('bonfire.openshift.get_api_resources', return_value={"name": user})
    mocker.patch('bonfire.openshift.check_for_existing_reservation', return_value=True)
    mocker.patch('bonfire.openshift.parse_restype', return_value="")
    mocker.patch('bonfire.openshift.get_json', return_value="")
    mocker.patch('bonfire.openshift.get_all_reservations', return_value="")
    mocker.patch('bonfire.bonfire.reserve_namespace', return_value=ns)
    
    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["reserve", "--requester", user])

    assert result.output.rstrip() == expected


@pytest.mark.parametrize(
    "duration, expected",
    [
        (
            "1h", "1h"
        ),
        (
            None, "1h"
        ),
        (
            "30m", "30m"
        ),
    ]
)
def test_ns_reserve_options_duration(mocker, caplog, duration, expected):
    caplog.set_level(100000)

    ns = Mock()
    ns.name=expected

    mocker.patch('bonfire.bonfire.has_ns_operator', return_value=True)
    mocker.patch('bonfire.openshift.has_ns_operator', return_value=True)
    mocker.patch('bonfire.openshift.get_api_resources', return_value={"name": duration})
    mocker.patch('bonfire.openshift.check_for_existing_reservation', return_value=True)
    mocker.patch('bonfire.openshift.parse_restype', return_value="")
    mocker.patch('bonfire.openshift.get_json', return_value="")
    mocker.patch('bonfire.openshift.get_all_reservations', return_value="")
    mocker.patch('bonfire.bonfire.reserve_namespace', return_value=ns)
    
    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["reserve", "--duration", duration])
    
    assert result.output.rstrip() == expected


def test_ns_list_options_available(mocker, caplog):
    caplog.set_level(100000)

    all_ns = []
    
    ns_1 = Mock(reserved=False, status="ready", clowdapps="none", requester="", expires_in="")
    ns_1.name = "namespace-1"
    ns_2 = Mock(reserved=True, status="ready", clowdapps="none", requester="user-1", expires_in="31m")
    ns_2.name = "namespace-2"
    ns_3 = Mock(reserved=False, status="ready", clowdapps="none", requester="", expires_in="")
    ns_3.name = "namespace-3"

    all_ns.append(ns_1)
    all_ns.append(ns_2)
    all_ns.append(ns_3)

    expected = "NAME         RESERVED    ENV STATUS    APPS READY    REQUESTER    EXPIRES IN  \n" \
               "-----------  ----------  ------------  ------------  -----------  ------------\n" \
               "namespace-1  false       ready         none                                   \n" \
               "namespace-3  false       ready         none                                   \n"

    mocker.patch('bonfire.namespaces.get_all_namespaces', return_value=all_ns)
    mocker.patch('bonfire.openshift.get_all_reservations', return_value="")
    mocker.patch('bonfire.bonfire.get_namespaces', return_value=all_ns)

    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["list", "--available"])
    
    assert result.output == expected

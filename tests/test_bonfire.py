import click
from click.testing import CliRunner
import pytest
from mock import patch, Mock

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
def test_ns_reserve_options_name(mocker, name, expected):
    ns = Mock()
    ns.name=expected
    mocker.patch('bonfire.bonfire.has_ns_operator', return_value=True)
    mocker.patch('bonfire.openshift.has_ns_operator', return_value=True)
    mocker.patch('bonfire.openshift.get_api_resources', return_value={"name": name})
    #mocker.patch('bonfire.bonfire.reserve_namespace', return_value={"name": expected})
    mocker.patch('bonfire.openshift.check_for_existing_reservation', return_value=True)
    mocker.patch('bonfire.openshift.parse_restype', return_value="")
    mocker.patch('bonfire.openshift.get_json', return_value="")
    mocker.patch('bonfire.openshift.get_all_reservations', return_value="")
    mocker.patch('bonfire.bonfire.reserve_namespace', return_value=ns)
    
    runner = CliRunner()
    result = runner.invoke(bonfire.namespace, ["reserve", "--name", name])

    assert result.output.rstrip() == expected

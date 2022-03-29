import click
from click.testing import CliRunner
import pytest
from mock import patch

from bonfire.bonfire import (
    _validate_reservation_duration,
    _cmd_namespace_reserve,
    _ns_reserve_options,
    namespace
)

from bonfire.openshift import (
    process_template,
    has_ns_operator,
    get_api_resources
)


@pytest.mark.parametrize(
    "name, expected",
    [
        (
            "test_name_1", "test_name_1"
        ),
        (
            "test_name_2", "test_name_2"
        ),
    ]
)
@patch('bonfire.openshift.get_api_resources')
@patch('bonfire.openshift.has_ns_operator')
@patch('bonfire.openshift.process_template')
@patch('bonfire.namespaces.reserve_namespace')
def test_ns_reserve_options_name(mock_reserve_namespace,
                                mock_process_template,
                                mock_has_ns_operator,
                                mock_get_api_resources,
                                name,
                                expected):
    mock_get_api_resources.return_value = ""
    mock_has_ns_operator.return_value = True
    mock_process_template.return_value = ""
    mock_reserve_namespace.return_value = expected
    
    runner = CliRunner()
    result = runner.invoke(namespace, ["reserve", "--name", name])
    print(result.output)
    assert result.output == mock_reserve_namespace()

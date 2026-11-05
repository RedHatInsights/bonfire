from click.testing import CliRunner

import bonfire.config as conf
from bonfire import bonfire


def test_main_context_option_configures_selected_context(mocker):
    configure_context = mocker.patch("bonfire.bonfire.configure_kube_context")
    mocker.patch("bonfire.bonfire.check_pypi")

    result = CliRunner().invoke(bonfire.main, ["--context", "eph", "test", "--help"])

    assert result.exit_code == 0, result.output
    configure_context.assert_called_once_with("eph")
    assert conf.K8S_CONTEXT == "eph"

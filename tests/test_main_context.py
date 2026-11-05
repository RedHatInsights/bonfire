from contextlib import nullcontext

from click.testing import CliRunner

import bonfire.config as conf
from bonfire import bonfire


def test_main_context_option_configures_selected_context(mocker):
    configure_context = mocker.patch("bonfire.bonfire.configure_kube_context")
    mocker.patch("bonfire.bonfire.check_pypi")

    result = CliRunner().invoke(bonfire.main, ["--context", "eph", "test", "--help"])

    assert result.exit_code == 0, result.output
    configure_context.assert_not_called()
    assert conf.BONFIRE_K8S_CONTEXT == "eph"


def test_main_context_uses_bonfire_context_environment_variable(mocker):
    configure_context = mocker.patch("bonfire.bonfire.configure_kube_context")
    mocker.patch("bonfire.bonfire.check_pypi")

    result = CliRunner().invoke(
        bonfire.main,
        ["test", "--help"],
        env={"BONFIRE_K8S_CONTEXT": "eph"},
    )

    assert result.exit_code == 0, result.output
    configure_context.assert_not_called()
    assert conf.BONFIRE_K8S_CONTEXT == "eph"


def test_main_context_configures_kubernetes_command(mocker):
    configure_context = mocker.patch(
        "bonfire.bonfire.configure_kube_context", return_value=nullcontext()
    )
    mocker.patch("bonfire.bonfire.check_pypi")
    mocker.patch("bonfire.bonfire.get_namespace_pools", return_value=[])
    mocker.patch("bonfire.bonfire.render_pool_list")

    result = CliRunner().invoke(bonfire.main, ["--context", "eph", "pool", "list"])

    assert result.exit_code == 0, result.output
    configure_context.assert_called_once_with("eph")

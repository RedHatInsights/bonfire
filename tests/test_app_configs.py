import pytest

from bonfire.bonfire import _get_apps_config, APP_SRE_SRC, FILE_SRC

import bonfire


LOCAL_CONFIG_FILE_DATA = {
    "apps": [
        {
            "name": "appA",
            "components": [
                {
                    "name": "appAcomponent1",
                    "host": "github",
                    "repo": "someorg/appAcomponent1",
                    "path": "deploy/template.yaml",
                    "ref": "master",
                    "parameters": {},
                },
                {
                    "name": "appAcomponent2",
                    "host": "github",
                    "repo": "someorg/appAcomponent2",
                    "path": "deploy/template.yaml",
                    "ref": "master",
                    "parameters": {},
                },
            ],
        },
        {
            "name": "appB",
            "components": [
                {
                    "name": "appBcomponent1",
                    "host": "github",
                    "repo": "someorg/appBcomponent1",
                    "path": "deploy/template.yaml",
                    "ref": "master",
                    "parameters": {},
                },
                {
                    "name": "appBcomponent2",
                    "host": "github",
                    "repo": "someorg/appBcomponent2",
                    "path": "deploy/template.yaml",
                    "ref": "master",
                    "parameters": {},
                },
            ],
        },
    ]
}

LOCAL_APPS = {a["name"]: a for a in LOCAL_CONFIG_FILE_DATA["apps"]}

REMOTE_TARGET_APPS = {
    "appA": {
        "name": "appA",
        "components": [
            {
                "name": "appAcomponent1",
                "host": "github",
                "repo": "someorg/appAcomponent1",
                "path": "deploy/template.yaml",
                "ref": "appAcomponent1_target_ref",
                "parameters": {},
            },
            {
                "name": "appAcomponent2",
                "host": "github",
                "repo": "someorg/appAcomponent2",
                "path": "deploy/template.yaml",
                "ref": "appAcomponent2_target_ref",
                "parameters": {},
            },
        ],
    },
    "appB": {
        "name": "appB",
        "components": [
            {
                "name": "appBcomponent1",
                "host": "github",
                "repo": "someorg/appBcomponent1",
                "path": "deploy/template.yaml",
                "ref": "appBcomponent1_target_ref",
                "parameters": {},
            },
            {
                "name": "appBcomponent2",
                "host": "github",
                "repo": "someorg/appBcomponent2",
                "path": "deploy/template.yaml",
                "ref": "appBcomponent2_target_ref",
                "parameters": {},
            },
        ],
    },
}

REMOTE_REFERENCE_APPS = {
    "appA": {
        "name": "appA",
        "components": [
            {
                "name": "appAcomponent1",
                "host": "github",
                "repo": "someorg/appAcomponent1",
                "path": "deploy/template.yaml",
                "ref": "appAcomponent1_reference_ref",
                "parameters": {},
            },
            {
                "name": "appAcomponent2",
                "host": "github",
                "repo": "someorg/appAcomponent2",
                "path": "deploy/template.yaml",
                "ref": "appAcomponent2_reference_ref",
                "parameters": {},
            },
        ],
    },
    "appB": {
        "name": "appB",
        "components": [
            {
                "name": "appBcomponent1",
                "host": "github",
                "repo": "someorg/appBcomponent1",
                "path": "deploy/template.yaml",
                "ref": "appBcomponent1_reference_ref",
                "parameters": {},
            },
            {
                "name": "appBcomponent2",
                "host": "github",
                "repo": "someorg/appBcomponent2",
                "path": "deploy/template.yaml",
                "ref": "appBcomponent2_reference_ref",
                "parameters": {},
            },
        ],
    },
}


REMOTE_REFERENCE_APPS_MASTER_REFS = {
    "appA": {
        "name": "appA",
        "components": [
            {
                "name": "appAcomponent1",
                "host": "github",
                "repo": "someorg/appAcomponent1",
                "path": "deploy/template.yaml",
                "ref": "master",
                "parameters": {},
            },
            {
                "name": "appAcomponent2",
                "host": "github",
                "repo": "someorg/appAcomponent2",
                "path": "deploy/template.yaml",
                "ref": "master",
                "parameters": {},
            },
        ],
    },
    "appB": {
        "name": "appB",
        "components": [
            {
                "name": "appBcomponent1",
                "host": "github",
                "repo": "someorg/appBcomponent1",
                "path": "deploy/template.yaml",
                "ref": "master",
                "parameters": {},
            },
            {
                "name": "appBcomponent2",
                "host": "github",
                "repo": "someorg/appBcomponent2",
                "path": "deploy/template.yaml",
                "ref": "master",
                "parameters": {},
            },
        ],
    },
}


def _mock_get_apps_for_env(env):
    if env is None or env == "test_env_with_no_apps":
        return {}
    elif env == "test_target_env":
        return REMOTE_TARGET_APPS
    elif env == "test_ref_env":
        return REMOTE_REFERENCE_APPS
    else:
        raise ValueError(f"invalid env '{env}' provided to mock function")


@pytest.mark.parametrize("local_config_method", ("merge", "override"))
def test_local_no_remote_apps_found_qontract(mocker, local_config_method):
    mocker.patch("bonfire.qontract.get_apps_for_env", return_value={})
    mocker.patch("bonfire.bonfire.get_apps_for_env", return_value={})
    mocker.patch(
        "bonfire.bonfire.conf.load_config", return_value=LOCAL_CONFIG_FILE_DATA
    )
    actual = _get_apps_config(
        source=APP_SRE_SRC,
        target_env="test_target_env",
        ref_env="test_ref_env",
        local_config_path="na",
        local_config_method=local_config_method,
    )
    expected = LOCAL_APPS
    assert actual == expected


@pytest.mark.parametrize("local_config_method", ("merge", "override"))
def test_local_no_remote_apps_found_appsfile(mocker, local_config_method):
    mocker.patch("bonfire.bonfire.get_appsfile_apps", return_value={})
    mocker.patch(
        "bonfire.bonfire.conf.load_config", return_value=LOCAL_CONFIG_FILE_DATA
    )
    actual = _get_apps_config(
        source=FILE_SRC,
        target_env=None,
        ref_env=None,
        local_config_path="na",
        local_config_method=local_config_method,
    )
    expected = LOCAL_APPS
    assert actual == expected


@pytest.mark.parametrize("local_config_method", ("merge", "override"))
def test_empty_local_config_qontract(monkeypatch, local_config_method):
    monkeypatch.setattr(bonfire.qontract, "get_apps_for_env", _mock_get_apps_for_env)
    monkeypatch.setattr(bonfire.bonfire, "get_apps_for_env", _mock_get_apps_for_env)
    monkeypatch.setattr(bonfire.bonfire.conf, "load_config", lambda _: {})
    actual = _get_apps_config(
        source=APP_SRE_SRC,
        target_env="test_target_env",
        ref_env="test_ref_env",
        local_config_path="na",
        local_config_method=local_config_method,
    )
    expected = REMOTE_REFERENCE_APPS
    assert actual == expected


@pytest.mark.parametrize("local_config_method", ("merge", "override"))
def test_empty_local_config_appsfile(monkeypatch, local_config_method):
    monkeypatch.setattr(
        bonfire.bonfire, "get_appsfile_apps", lambda _: REMOTE_TARGET_APPS
    )
    monkeypatch.setattr(bonfire.qontract, "get_apps_for_env", _mock_get_apps_for_env)
    monkeypatch.setattr(bonfire.bonfire, "get_apps_for_env", _mock_get_apps_for_env)
    monkeypatch.setattr(bonfire.bonfire.conf, "load_config", lambda _: {})
    actual = _get_apps_config(
        source=FILE_SRC,
        target_env="test_target_env",
        ref_env="test_ref_env",
        local_config_path="na",
        local_config_method=local_config_method,
    )
    expected = REMOTE_REFERENCE_APPS
    assert actual == expected


@pytest.mark.parametrize("local_config_method", ("merge", "override"))
def test_master_branch_used_when_no_reference_app_found(
    monkeypatch, local_config_method
):
    monkeypatch.setattr(
        bonfire.bonfire, "get_appsfile_apps", lambda _: REMOTE_TARGET_APPS
    )
    monkeypatch.setattr(bonfire.qontract, "get_apps_for_env", _mock_get_apps_for_env)
    monkeypatch.setattr(bonfire.bonfire, "get_apps_for_env", _mock_get_apps_for_env)
    monkeypatch.setattr(bonfire.bonfire.conf, "load_config", lambda _: {})
    actual = _get_apps_config(
        source=FILE_SRC,
        target_env="test_target_env",
        ref_env="test_env_with_no_apps",
        local_config_path="na",
        local_config_method=local_config_method,
    )
    expected = REMOTE_REFERENCE_APPS_MASTER_REFS
    assert actual == expected

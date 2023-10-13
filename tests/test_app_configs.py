import pytest

from bonfire.bonfire import _get_apps_config, APP_SRE_SRC, FILE_SRC

import bonfire

# Make sure to use functions for these test dictionaries instead of global vars.
# Otherwise, data gets polluted between the tests due to re-using the same dict object in memory.


def _target_apps():
    return {
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
                    "parameters": {
                        "EXISTING_PARAM1": "EXISTING_VALUE1",
                        "EXISTING_PARAM2": "EXISTING_VALUE2",
                    },
                },
            ],
        },
    }


def _reference_apps():
    return {
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


def _target_apps_w_refs_subbed():
    return {
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
                    "parameters": {
                        "EXISTING_PARAM1": "EXISTING_VALUE1",
                        "EXISTING_PARAM2": "EXISTING_VALUE2",
                    },
                },
            ],
        },
    }


def _mock_get_apps_for_env(env):
    if env is None or env == "test_env_with_no_apps":
        return {}
    elif env == "test_target_env":
        return _target_apps()
    elif env == "test_ref_env":
        return _reference_apps()
    else:
        raise ValueError(f"invalid env '{env}' provided to mock function")


def _setup_monkeypatch(monkeypatch, source, local_cfg):
    # always patch this func since it is used in bonfire.qontract.sub_refs()
    monkeypatch.setattr(bonfire.qontract, "get_apps_for_env", _mock_get_apps_for_env)

    # patch loading of local cfg
    monkeypatch.setattr(bonfire.bonfire.conf, "load_config", lambda _: local_cfg)

    # patch fetching of remote app config
    if source == APP_SRE_SRC:
        monkeypatch.setattr(bonfire.bonfire, "get_apps_for_env", _mock_get_apps_for_env)
    elif source == FILE_SRC:
        monkeypatch.setattr(bonfire.bonfire, "get_appsfile_apps", lambda _: _target_apps())
    else:
        raise ValueError(f"invalid source '{source}' provided to mock function")


@pytest.mark.parametrize("local_config_method", ("merge", "override"))
@pytest.mark.parametrize("source", (APP_SRE_SRC, FILE_SRC))
def test_local_no_remote_target_apps_found(monkeypatch, source, local_config_method):
    local_cfg = {"apps": [val for _, val in _target_apps().items()]}
    _setup_monkeypatch(monkeypatch, source, local_cfg)
    actual = _get_apps_config(
        source=source,
        target_env="test_env_with_no_apps",
        ref_env=None,
        local_config_path="na",
        local_config_method=local_config_method,
    )
    assert actual == _target_apps()


@pytest.mark.parametrize("local_config_method", ("merge", "override"))
@pytest.mark.parametrize("source", (APP_SRE_SRC, FILE_SRC))
def test_new_local_app_added_to_remote_apps(monkeypatch, source, local_config_method):
    local_cfg = {
        "apps": [
            {
                "name": "appC",
                "components": [
                    {
                        "name": "appC_component1",
                        "host": "gitlab",
                        "repo": "someorg/somerepo",
                        "path": "template.yml",
                    }
                ],
            }
        ]
    }
    _setup_monkeypatch(monkeypatch, source, local_cfg)
    actual = _get_apps_config(
        source=source,
        target_env="test_target_env",
        ref_env=None,
        local_config_path="na",
        local_config_method=local_config_method,
    )
    expected = _target_apps()
    expected["appC"] = local_cfg["apps"][0]
    assert actual == expected


@pytest.mark.parametrize("source", (APP_SRE_SRC, FILE_SRC))
def test_new_local_component_merged(monkeypatch, source):
    local_cfg = {
        "apps": [
            {
                "name": "appB",
                "components": [
                    {
                        "name": "appB_component3",
                        "host": "gitlab",
                        "repo": "someorg/somerepo",
                        "path": "template.yml",
                    }
                ],
            }
        ]
    }
    _setup_monkeypatch(monkeypatch, source, local_cfg)
    actual = _get_apps_config(
        source=source,
        target_env="test_target_env",
        ref_env=None,
        local_config_path="na",
        local_config_method="merge",
    )
    expected = _target_apps()
    expected["appB"]["components"].append(local_cfg["apps"][0]["components"][0])
    assert actual == expected


@pytest.mark.parametrize("local_config_method", ("merge", "override"))
@pytest.mark.parametrize("source", (APP_SRE_SRC, FILE_SRC))
def test_empty_local_config(monkeypatch, source, local_config_method):
    local_cfg = {}
    _setup_monkeypatch(monkeypatch, source, local_cfg)
    actual = _get_apps_config(
        source=source,
        target_env="test_target_env",
        ref_env="test_ref_env",
        local_config_path="na",
        local_config_method=local_config_method,
    )
    assert actual == _target_apps_w_refs_subbed()


@pytest.mark.parametrize(
    "bad_local_cfg",
    (
        {"apps": [{"name": "bad_app", "components": {"oops": "bad_type"}}]},
        {"apps": "bad_type"},
        {"apps": [{"name": "bad_app", "components": [{"oops": "missing_keys"}]}]},
    ),
    ids=(
        "wrong_type_for_components_list",
        "wrong_type_for_apps_dict",
        "missing_keys_in_components_dict",
    ),
)
@pytest.mark.parametrize("local_config_method", ("merge", "override"))
@pytest.mark.parametrize("source", (APP_SRE_SRC, FILE_SRC))
def test_bad_local_config(monkeypatch, source, local_config_method, bad_local_cfg):
    _setup_monkeypatch(monkeypatch, source, bad_local_cfg)
    with pytest.raises(bonfire.utils.FatalError) as exc:
        _get_apps_config(
            source=source,
            target_env="test_env_with_no_apps",
            ref_env=None,
            local_config_path="na",
            local_config_method=local_config_method,
        )
        assert str(exc).startswith(bonfire.utils.SYNTAX_ERR)


@pytest.mark.parametrize("local_config_method", ("merge", "override"))
@pytest.mark.parametrize("source", (APP_SRE_SRC, FILE_SRC))
def test_master_branch_used_when_no_reference_app_found(monkeypatch, source, local_config_method):
    local_cfg = {}
    _setup_monkeypatch(monkeypatch, source, local_cfg)

    apps_config = _get_apps_config(
        source=source,
        target_env="test_target_env",
        ref_env="test_env_with_no_apps",
        local_config_path="na",
        local_config_method=local_config_method,
    )

    expected = _target_apps_w_refs_subbed()
    for _, app_config in expected.items():
        for component in app_config["components"]:
            component["ref"] = "master"

    assert apps_config == expected


@pytest.mark.parametrize("source", (APP_SRE_SRC, FILE_SRC))
def test_local_config_merge(monkeypatch, source):
    local_cfg = {
        "apps": [
            {
                "name": "appB",
                "components": [
                    {
                        "name": "appBcomponent2",
                        "parameters": {
                            "NEW_PARAM1": "NEW_VALUE1",
                            "NEW_PARAM2": "NEW_VALUE2",
                        },
                    },
                    # intentionally reversing order of components...
                    {
                        "name": "appBcomponent1",
                        "repo": "neworg/newrepo",
                        "ref": "a_new_ref",
                    },
                ],
            },
        ]
    }

    _setup_monkeypatch(monkeypatch, source, local_cfg)

    actual = _get_apps_config(
        source=source,
        target_env="test_target_env",
        ref_env=None,
        local_config_path="na",
        local_config_method="merge",
    )

    expected = _target_apps()
    for _, app_config in expected.items():
        for component in app_config["components"]:
            if component["name"] == "appBcomponent1":
                component["ref"] = "a_new_ref"
                component["repo"] = "neworg/newrepo"
            if component["name"] == "appBcomponent2":
                component["parameters"] = {
                    "EXISTING_PARAM1": "EXISTING_VALUE1",
                    "EXISTING_PARAM2": "EXISTING_VALUE2",
                    "NEW_PARAM1": "NEW_VALUE1",
                    "NEW_PARAM2": "NEW_VALUE2",
                }

    assert actual == expected


@pytest.mark.parametrize("source", (APP_SRE_SRC, FILE_SRC))
def test_local_config_override(monkeypatch, source):
    app_b = {
        "name": "appB",
        "components": [
            {
                "name": "appBcomponent2",
                "host": "gitlab",
                "repo": "somefork/appBcomponent2",
                "path": "deploy/new_template.yaml",
                "ref": "some_custom_ref",
                "parameters": {"SOME_PARAM": "SOME_VALUE"},
            },
        ],
    }
    local_cfg = {"apps": [app_b]}

    _setup_monkeypatch(monkeypatch, source, local_cfg)

    actual = _get_apps_config(
        source=source,
        target_env="test_target_env",
        ref_env=None,
        local_config_path="na",
        local_config_method="override",
    )

    expected = _target_apps()
    expected["appB"] = app_b

    assert actual == expected


@pytest.mark.parametrize("source", (APP_SRE_SRC, FILE_SRC))
def test_local_config_merge_update_param(monkeypatch, source):
    local_cfg = {
        "apps": [
            {
                "name": "appB",
                "components": [
                    {
                        "name": "appBcomponent2",
                        "parameters": {
                            "EXISTING_PARAM1": "NEW_VALUE1",
                            "NEW_PARAM2": "NEW_VALUE2",
                        },
                    },
                ],
            },
        ]
    }

    _setup_monkeypatch(monkeypatch, source, local_cfg)

    actual = _get_apps_config(
        source=source,
        target_env="test_target_env",
        ref_env=None,
        local_config_path="na",
        local_config_method="merge",
    )

    expected = _target_apps()
    component1_found = False
    for _, app_config in expected.items():
        for component in app_config["components"]:
            if component["name"] == "appBcomponent1":
                component1_found = True
            if component["name"] == "appBcomponent2":
                component["parameters"] = {
                    "EXISTING_PARAM1": "NEW_VALUE1",
                    "EXISTING_PARAM2": "EXISTING_VALUE2",
                    "NEW_PARAM2": "NEW_VALUE2",
                }

    assert component1_found  # ensure component 1 is not removed
    assert actual == expected

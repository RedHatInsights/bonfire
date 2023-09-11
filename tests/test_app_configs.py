import pytest

from bonfire.bonfire import _get_apps_config, APP_SRE_SRC, FILE_SRC


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

REMOTE_APPS = [
    {
        "name": "appA",
        "components": [
            {
                "name": "appAcomponent1",
                "host": "github",
                "repo": "someorg/appAcomponent1",
                "path": "deploy/template.yaml",
                "parameters": {},
            },
            {
                "name": "appAcomponent2",
                "host": "github",
                "repo": "someorg/appAcomponent2",
                "path": "deploy/template.yaml",
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
                "parameters": {},
            },
            {
                "name": "appBcomponent2",
                "host": "github",
                "repo": "someorg/appBcomponent2",
                "path": "deploy/template.yaml",
                "parameters": {},
            },
        ],
    },
]


@pytest.mark.parametrize("local_config_method", ("merge", "override"))
def test_local_no_remote_apps_found_qontract(mocker, local_config_method):
    mocker.patch("bonfire.qontract.get_apps_for_env", return_value={})
    mocker.patch("bonfire.bonfire.get_apps_for_env", return_value={})
    mocker.patch(
        "bonfire.bonfire.conf.load_config", return_value=LOCAL_CONFIG_FILE_DATA
    )
    actual = _get_apps_config(
        source=APP_SRE_SRC,
        target_env="mytarget_env",
        ref_env="myref_env",
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

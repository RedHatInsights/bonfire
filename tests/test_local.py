import re

import pytest

from bonfire import local
from bonfire.utils import FatalError


def test_get_local_apps_with_empty_config():

    local_apps_config = local.get_local_apps({})
    assert len(local_apps_config) == 0


def test_get_local_apps_with_one_config():

    app_config = {"name": "one_app"}

    local_apps_config = local.get_local_apps({"apps": [app_config]})
    assert len(local_apps_config) == 1
    assert local_apps_config["one_app"] == app_config


def test_get_local_apps_with_duplicates_raises_fatal_error():

    app_config = {"name": "one_app"}

    with pytest.raises(FatalError, match=r"duplicate.*found.*one_app"):
        local.get_local_apps({"apps": [app_config, app_config]})


def test_get_apps_file_for_ephemeral_apps_is_deprecated(requests_mock):
    app_config = {
        "host": "gitlab",
        "repo": "insights-platform/cicd-common",
        "path": "bonfire_configs/ephemeral_apps.yaml",
    }

    matcher = re.compile("bonfire_configs/ephemeral_apps.yaml")
    requests_mock.get(matcher)
    requests_mock.get(
        re.compile(r"projects/\?per_page"),
        json=[{"path": "cicd-common", "id": 1}],
    )
    requests_mock.get(re.compile(r"projects/1"), json={"commit": {"id": "abcdef"}})
    requests_mock.get(
        re.compile(r"abcdef/{app_config['path']}"),
    )

    "abcdef/bonfire_configs/ephemeral_apps.yaml"
    with pytest.raises(FatalError, match=".*appsFile"):
        local.get_local_apps({"appsFile": app_config})

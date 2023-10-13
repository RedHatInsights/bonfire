import logging

import yaml

from bonfire.utils import FatalError, RepoFile, get_dupes, SYNTAX_ERR

log = logging.getLogger(__name__)


def _fetch_apps_file(config):
    rf = RepoFile.from_config(config["appsFile"])
    commit, content = rf.fetch()
    log.info(
        "loading commit '%s' of %s repo %s/%s at path '%s' for apps config",
        commit,
        rf.host,
        rf.org,
        rf.repo,
        rf.path,
    )
    fetched_apps = yaml.safe_load(content)

    if "apps" not in fetched_apps:
        raise FatalError(f"{SYNTAX_ERR}, fetched apps file has no 'apps' key")

    app_names = [a["name"] for a in fetched_apps["apps"]]
    dupes = get_dupes(app_names)
    if dupes:
        raise FatalError(f"{SYNTAX_ERR}, duplicate app names found in fetched apps file: {dupes}")

    return {a["name"]: a for a in fetched_apps["apps"]}


def _parse_apps_in_cfg(config):
    app_names = []

    for app in config["apps"]:
        if not isinstance(app, dict):
            raise FatalError(f"{SYNTAX_ERR} app type should be a dict type")
        if "components" not in app:
            raise FatalError(f"{SYNTAX_ERR} 'components' missing from an app")
        for component in app["components"]:
            if not isinstance(component, dict):
                raise FatalError(f"{SYNTAX_ERR} component should be a dict type")
        app_names.append(app["name"])

    dupes = get_dupes(app_names)
    if dupes:
        raise FatalError(f"{SYNTAX_ERR} duplicate app names found in config: {dupes}")

    return {a["name"]: a for a in config["apps"]}


def get_local_apps(config):
    """
    Get apps defined locally under 'apps' section of config
    """
    config_apps = {}
    if not isinstance(config, dict):
        raise FatalError(f"{SYNTAX_ERR}, expected local config to be a dictionary")
    if "apps" in config:
        config_apps = _parse_apps_in_cfg(config)
        log.info("local configuration found for apps: %s", list(config_apps.keys()))

    return config_apps


def get_appsfile_apps(config):
    """
    Fetch apps from repo based on appsFile provided in config
    """
    if not isinstance(config, dict):
        raise FatalError(f"{SYNTAX_ERR}, expected local config to be a dictionary")

    if "appsFile" not in config:
        raise FatalError(f"{SYNTAX_ERR}, config has no 'appsFile' defined")

    log.info("local config has a remote 'appsFile' defined, fetching it...")
    fetched_apps = _fetch_apps_file(config)
    return fetched_apps

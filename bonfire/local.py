import logging
import yaml

from bonfire.utils import RepoFile, get_dupes

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
        raise ValueError("fetched apps file has no 'apps' key")

    app_names = [a["name"] for a in fetched_apps["apps"]]
    dupes = get_dupes(app_names)
    if dupes:
        raise ValueError("duplicate app names found in fetched apps file: {dupes}")

    return {a["name"]: a for a in fetched_apps["apps"]}


def _parse_apps_in_cfg(config):
    app_names = [a["name"] for a in config["apps"]]
    dupes = get_dupes(app_names)
    if dupes:
        raise ValueError("duplicate app names found in config: {dupes}")
    return {a["name"]: a for a in config["apps"]}


def get_local_apps(config, fetch_remote=True):
    # get any apps set directly in config
    config_apps = {}
    if "apps" in config:
        config_apps = _parse_apps_in_cfg(config)
        log.info("local app configuration overrides found for: %s", list(config_apps.keys()))

    if not fetch_remote:
        final_apps = config_apps
    else:
        # fetch apps from repo if appsFile is provided in config
        fetched_apps = {}
        if "appsFile" in config:
            log.info("fetching remote apps file...")
            fetched_apps = _fetch_apps_file(config)

        # override fetched apps with local apps if any were defined
        fetched_apps.update(config_apps)
        final_apps = fetched_apps

    return final_apps

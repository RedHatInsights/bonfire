"""
Handles importing of configmaps from a local directory
"""

import glob
import json
import logging
import os

from ocviapy import get_json, oc

from bonfire.utils import FatalError, load_file

log = logging.getLogger(__name__)


def _parse_configmaps_file(path):
    """
    Return a dict of all configmaps in a file with key: configmap name,
    val: parsed configmap json/yaml
    The file can contain 1 configmap, or a list of configmaps
    """
    content = load_file(path)
    configmaps = {}
    if content.get("kind").lower() == "list":
        items = content.get("items", [])
    else:
        items = [content]

    for item in items:
        if item.get("kind").lower() == "configmap":
            try:
                configmaps[item["metadata"]["name"]] = item
            except KeyError:
                raise FatalError("Configmap at path '{}' has no metadata/name".format(path))

    return configmaps


def _get_files_in_dir(path):
    """
    Get a list of all .yml/.yaml/.json files in a dir
    """
    files = list(glob.glob(os.path.join(path, "*.yaml")))
    files.extend(list(glob.glob(os.path.join(path, "*.yml"))))
    files.extend(list(glob.glob(os.path.join(path, "*.json"))))
    return files


def _import_configmaps(configmap_name, configmap_data):
    # get existing configmap in the ns (if it exists)
    current_configmap = get_json("configmap", configmap_name) or {}

    # avoid race conditions when running multiple processes by comparing the data
    data_mismatch = current_configmap.get("data") != configmap_data.get("data")
    if data_mismatch:
        log.info("replacing configmap '%s' using local copy", configmap_name)
        # delete from dst ns so that applying 'null' values will work
        oc("delete", "--ignore-not-found", "configmap", configmap_name, _silent=True)
        oc("apply", "-f", "-", _silent=True, _in=json.dumps(configmap_data))


def import_configmaps_from_dir(path):
    if not os.path.exists(path):
        raise FatalError(f"configmaps directory not found: {path}")

    if not os.path.isdir(path):
        raise FatalError(f"invalid configmaps directory: {path}")

    files = _get_files_in_dir(path)
    configmaps = {}
    log.info("importing configmaps from local path: %s", path)
    for confmaps_file in files:
        confmaps_in_file = _parse_configmaps_file(confmaps_file)
        log.info(
            "loaded %d configmap(s) from file '%s'",
            len(confmaps_in_file),
            confmaps_file,
        )
        for confmaps_name in confmaps_in_file:
            if confmaps_name in configmaps:
                raise FatalError(
                    f"configmap with name '{confmaps_name}' defined twice in configmaps dir"
                )
        configmaps.update(confmaps_in_file)

    for configmap_name, configmap_data in configmaps.items():
        _import_configmaps(configmap_name, configmap_data)

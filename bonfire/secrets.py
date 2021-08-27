"""
Handles importing of secrets from a local directory
"""
import glob
import json
import logging
import os

from bonfire.openshift import oc, get_json
from bonfire.utils import load_file, FatalError


log = logging.getLogger(__name__)


def _parse_secret_file(path):
    """
    Return a dict of all secrets in a file with key: secret name, val: parsed secret json/yaml
    The file can contain 1 secret, or a list of secrets
    """
    content = load_file(path)
    secrets = {}
    if content.get("kind").lower() == "list":
        items = content.get("items", [])
    else:
        items = [content]

    for item in items:
        if item.get("kind").lower() == "secret":
            try:
                secrets[item["metadata"]["name"]] = item
            except KeyError:
                raise FatalError("Secret at path '{}' has no metadata/name".format(path))

    return secrets


def _get_files_in_dir(path):
    """
    Get a list of all .yml/.yaml/.json files in a dir
    """
    files = list(glob.glob(os.path.join(path, "*.yaml")))
    files.extend(list(glob.glob(os.path.join(path, "*.yml"))))
    files.extend(list(glob.glob(os.path.join(path, "*.json"))))
    return files


def _import_secret(secret_name, secret_data):
    # get existing secret in the ns (if it exists)
    current_secret = get_json("secret", secret_name) or {}

    # avoid race conditions when running multiple processes by comparing the data
    data_mismatch = current_secret.get("data") != secret_data.get("data")
    str_data_mismatch = current_secret.get("stringData") != secret_data.get("stringData")
    if data_mismatch or str_data_mismatch:
        log.info("replacing secret '%s' using local copy", secret_name)
        # delete from dst ns so that applying 'null' values will work
        oc("delete", "--ignore-not-found", "secret", secret_name, _silent=True)
        oc("apply", "-f", "-", _silent=True, _in=json.dumps(secret_data))


def import_secrets_from_dir(path):
    if not os.path.exists(path):
        raise FatalError(f"secrets directory not found: {path}")

    if not os.path.isdir(path):
        raise FatalError(f"invalid secrets directory: {path}")

    files = _get_files_in_dir(path)
    secrets = {}
    log.info("importing secrets from local path: %s", path)
    for secret_file in files:
        secrets_in_file = _parse_secret_file(secret_file)
        log.info("loaded %d secret(s) from file '%s'", len(secrets_in_file), secret_file)
        for secret_name in secrets_in_file:
            if secret_name in secrets:
                raise FatalError(f"secret with name '{secret_name}' defined twice in secrets dir")
        secrets.update(secrets_in_file)

    for secret_name, secret_data in secrets.items():
        _import_secret(secret_name, secret_data)

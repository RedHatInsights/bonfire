"""
Read configurations and status objects from a clowder-managed namespace to get app connection info
"""
import base64
import json
import os
import tempfile
import time

from bonfire.config import ENV_NAME_FORMAT
from bonfire.openshift import oc, get_json
from app_common_python.types import AppConfig


class EnvParser:
    def __init__(self, namespace):
        self.namespace = namespace
        self._status_for = {}
        self._cdapp_config_for = {}

    def get_clowdenv_status(self, app_name):
        if app_name not in self._status_for:                
            status = get_json(
                "clowdenvironment", ENV_NAME_FORMAT.format(namespace=self.namespace)
            )["status"]
            for app in status.get("apps", []):
                self._status_for[app["name"]] = app
            if app_name not in self._status_for:
                raise ValueError(f"app '{app_name}' not found in status")
        return self._status_for[app_name]

    def get_cdapp_config(self, app_name):
        if app_name not in self._cdapp_config_for:
            secret = get_json("secret", app_name, namespace=self.namespace)
            if not secret:
                raise ValueError(f"secret '{app_name}' not found in namespace")
            content = json.loads(base64.b64decode(secret["data"]["cdappconfig.json"]))
            self._cdapp_config_for[app_name] = AppConfig.dictToObject(content)
        return self._cdapp_config_for[app_name]


"""
Read configurations and status objects from a clowder-managed namespace to get app connection info
"""
import base64
import json

from bonfire.openshift import get_json, find_clowd_env_for_ns
from app_common_python.types import AppConfig


class EnvParser:
    def __init__(self, namespace):
        self.namespace = namespace
        self._status_for = {}
        self._cdapp_config_for = {}

    def get_clowdenv_status(self, app_name):
        if app_name not in self._status_for:
            clowd_env = find_clowd_env_for_ns(self.namespace)
            if not clowd_env:
                raise ValueError(
                    f"unable to locate ClowdEnvironment associated with ns '{self.namespace}'"
                )
            status = clowd_env["status"]
            for app in status.get("apps", []):
                self._status_for[app["name"]] = app
            if app_name not in self._status_for:
                raise ValueError(f"app '{app_name}' not found in status")
        return self._status_for[app_name]

    def app_present(self, app_name):
        try:
            self.get_clowdenv_status(app_name)
            return True
        except ValueError:
            return False

    def get_deployment_status(self, app_name, component_name):
        status = self.get_clowdenv_status(app_name)
        for deployment in status.get("deployments", []):
            if deployment["name"] == component_name:
                return deployment
        raise ValueError(f"no deployment found with name '{component_name}' on app '{app_name}'")

    def get_hostname(self, app_name, component_name):
        status = self.get_deployment_status(app_name, component_name)
        if "hostname" not in status:
            raise ValueError(f"no hostname listed for '{component_name}' on app '{app_name}'")
        return status["hostname"]

    def get_port(self, app_name, component_name):
        status = self.get_deployment_status(app_name, component_name)
        if "port" not in status:
            raise ValueError(f"no hostname listed for '{component_name}' on app '{app_name}'")
        return status["port"]

    def get_cdapp_config(self, app_name):
        if app_name not in self._cdapp_config_for:
            secret = get_json("secret", app_name, namespace=self.namespace)
            if not secret:
                raise ValueError(f"secret '{app_name}' not found in namespace")
            content = json.loads(base64.b64decode(secret["data"]["cdappconfig.json"]))
            self._cdapp_config_for[app_name] = AppConfig.dictToObject(content)
        return self._cdapp_config_for[app_name]

    def get_kafka_hostname(self, app_name):
        try:
            return self.get_cdapp_config(app_name).kafka.brokers[0].hostname
        except (IndexError, TypeError):
            raise ValueError(f"brokers config not present for app {app_name}")

    def get_kafka_port(self, app_name):
        try:
            return self.get_cdapp_config(app_name).kafka.brokers[0].port
        except (IndexError, TypeError):
            raise ValueError(f"brokers config not present for app {app_name}")

    def get_kafka_topic(self, app_name, topic_name):
        try:
            topics = self.get_cdapp_config(app_name).kafka.topics
        except (TypeError):
            raise ValueError(f"topics config not present for app {app_name}")

        for topic_config in topics:
            if topic_config.requestedName == topic_name:
                return topic_config.name

        raise ValueError(
            f"no topic config found on app '{app_name}' with requestedName '{topic_name}'"
        )

    def get_db_config(self, app_name):
        """
        Return app_common_python.types.DatabaseConfig if it exists for the app
        """
        db_config = self.get_cdapp_config(app_name).database
        if not db_config:
            raise ValueError(f"no database config present for app '{app_name}'")
        return db_config

    def get_storage_config(self, app_name):
        """
        Return app_common_python.types.ObjectStoreConfig if it exists for the app
        """
        config = self.get_cdapp_config(app_name).objectStore
        if not config:
            raise ValueError(f"no object storage config present for app '{app_name}'")
        return config

    def get_bucket_config(self, app_name, bucket_name):
        """
        Return app_common_python.types.ObjectStoreBucket for bucket with matching 'requestedName'
        """
        buckets = self.get_storage_config(app_name).buckets
        for b in buckets:
            if b.requestedName == bucket_name:
                return b

        raise ValueError(
            f"no bucket config found on app '{app_name}' with requestedName '{bucket_name}'"
        )

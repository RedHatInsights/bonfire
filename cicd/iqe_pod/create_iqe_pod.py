import base64
import logging
import click
import json
import sys
import yaml

from bonfire.openshift import oc, wait_for_ready
from bonfire.utils import split_equals

from env_parser import EnvParser

SECRET_NAME = "iqe-settings"


def _get_base_pod_cfg():
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": "iqe-tests"},
        "spec": {
            "containers": [
                {
                    "command": ["/bin/cat"],
                    "image": "quay.io/cloudservices/iqe-tests:latest",
                    "imagePullPolicy": "Always",
                    "name": "iqe-tests",
                    "resources": {
                        "limits": {"cpu": "1", "memory": "2Gi"},
                        "requests": {"cpu": "500m", "memory": "512Mi"},
                    },
                    "stdin": True,
                    "tty": True,
                    "env": [{"name": "IQE_SETTINGS_LOCAL_CONF_PATH", "value": "/iqe_settings"}],
                    "volumeMounts": [{"mountPath": "/iqe_settings", "name": "iqe-settings-volume"}],
                }
            ],
            "imagePullSecrets": [{"name": "quay-cloudservices-pull"}],
            "restartPolicy": "Never",
            "volumes": [
                {
                    "name": "iqe-settings-volume",
                    "secret": {"defaultMode": 420, "secretName": SECRET_NAME},
                }
            ],
        },
    }


def _build_test_conf(env_parser):
    conf = {}
    env_name = "clowder_smoke"
    env_conf = conf[env_name] = {}

    env_conf["MQ"] = {
        "service_objects": {
            "kafka": {
                "config": {
                    "hostname": env_parser.get_kafka_hostname("host-inventory"),
                    "port": env_parser.get_kafka_port("host-inventory"),
                }
            }
        }
    }

    if env_parser.app_present("ingress"):
        env_conf["INGRESS"] = {
            "service_objects": {
                "api_v1": {
                    "config": {
                        "hostname": env_parser.get_hostname("ingress", "ingress-service"),
                        "port": env_parser.get_port("ingress", "ingress-service"),
                        "scheme": "http",
                    }
                }
            }
        }

    if env_parser.app_present("host-inventory"):
        env_conf["HOST_INVENTORY"] = {
            # todo: potentially look these deployment names up dynamically?
            # but we know their name at the moment is "app name" + "deployment name"
            "inventory_mq_dc_name": "host-inventory-inventory-mq-p1",
            "inventory_api_dc_name": "host-inventory-service",
            "kafka": {
                "ingress_topic": env_parser.get_kafka_topic(
                    "host-inventory", "platform.inventory.host-ingress"
                ),
                "events_topic": env_parser.get_kafka_topic(
                    "host-inventory", "platform.inventory.events"
                ),
                "egress_timeout": 30,
            },
            "service_objects": {
                "api": {
                    "config": {
                        "hostname": env_parser.get_hostname(
                            "host-inventory", "host-inventory-service"
                        ),
                        "port": env_parser.get_port("host-inventory", "host-inventory-service"),
                        "scheme": "http",
                    }
                }
            },
            "db": {
                "hostname": env_parser.get_db_config("host-inventory").hostname,
                "database": env_parser.get_db_config("host-inventory").name,
                "username": env_parser.get_db_config("host-inventory").username,
                "password": env_parser.get_db_config("host-inventory").password,
                "port": env_parser.get_db_config("host-inventory").port,
            },
        }

    return conf


def _create_conf_secret(namespace):
    env_parser = EnvParser(namespace)
    conf_data = _build_test_conf(env_parser)
    encoded_conf = base64.b64encode(yaml.dump(conf_data).encode()).decode()
    secret = {
        "apiVersion": "v1",
        "kind": "Secret",
        "metadata": {"name": SECRET_NAME},
        "data": {"settings.local.yaml": encoded_conf,},
    }
    oc("create", f="-", n=namespace, _in=json.dumps(secret))


def _create_pod(namespace, pod_name, env):
    pod = _get_base_pod_cfg()

    pod["metadata"]["name"] = pod_name
    env_vars = split_equals(env, allow_null=True)
    if env_vars:
        pod_env_vars = pod["spec"]["containers"][0]["env"]
        for key, val in env_vars.items():
            if val:
                pod_env_vars.append({"name": key, "value": val})

    oc("create", f="-", n=namespace, _in=json.dumps(pod))


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("namespace", type=str, required=True)
@click.option("--pod-name", type=str, default="iqe-tests", help="name of pod (default: iqe-tests)")
@click.option(
    "--env", "-e", type=str, multiple=True, help="Env var to set on container using format KEY=VAL",
)
def main(namespace, pod_name, env):
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("sh").setLevel(logging.CRITICAL)

    _create_conf_secret(namespace)
    _create_pod(namespace, pod_name, env)

    if not wait_for_ready(namespace, "pod", pod_name):
        sys.exit(1)
    print(pod_name)


if __name__ == "__main__":
    main()

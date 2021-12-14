import base64
import logging
import click
import json
import os
import sys
import yaml

from bonfire.openshift import oc, wait_for_ready
from bonfire.utils import split_equals

from env_parser import EnvParser

SECRET_NAME = "iqe-settings"


def _get_base_pod_cfg():
    iqe_image = os.getenv("IQE_IMAGE", "quay.io/cloudservices/iqe-tests:latest")
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": "iqe-tests"},
        "spec": {
            "serviceAccountName": "iqe",
            "containers": [
                {
                    "command": ["/bin/cat"],
                    "image": iqe_image,
                    "imagePullPolicy": "Always",
                    "name": "iqe-tests",
                    "resources": {
                        "limits": {"cpu": "1", "memory": "2Gi"},
                        "requests": {"cpu": "500m", "memory": "1Gi"},
                    },
                    "stdin": True,
                    "tty": True,
                    "env": [{"name": "IQE_TESTS_LOCAL_CONF_PATH", "value": "/iqe_settings"}],
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

    # mq plugin configuration is now present in the plugin's settings.default.yaml

    # ingress configuration is now present in the plugin's settings.default.yaml

    # host-inventory configuration is now present in the plugin's settings.default.yaml

    if env_parser.app_present("marketplace"):
        mp_storage_cfg = env_parser.get_storage_config("marketplace")
        bucket = env_parser.get_bucket_config("marketplace", "marketplace-s3")
        env_conf["MARKETPLACE"] = {
            "aws_access_key_id": bucket.accessKey,
            "aws_secret_access_key": bucket.secretKey,
            "aws_s3_endpoint": f"{mp_storage_cfg.hostname}:{mp_storage_cfg.port}",
            "aws_s3_bucket": bucket.name,
            "aws_s3_secure": "false",
            "service_objects": {
                "api_v1": {
                    "config": {
                        "hostname": env_parser.get_hostname("ingress", "ingress-service"),
                        "port": env_parser.get_port("ingress", "ingress-service"),
                        "scheme": "http",
                    }
                }
            },
        }

    if env_parser.app_present("advisor"):
        env_conf["ADVISOR"] = {
            "kafka_dc_name": env_parser.get_kafka_hostname("advisor").split(".")[0],
            "db_dc_name": "advisor-db",
            "service_dc_name": "advisor-service",
            "api_dc_name": "advisor-api",
            "upload_dc_name": "ingress-service",
            "pup_dc_name": "puptoo-processor",
            "kafka_dc_port": env_parser.get_kafka_port("advisor"),
            "engine_results_topic": env_parser.get_kafka_topic(
                "advisor", "platform.engine.results"
            ),
            "inventory_events_topic": env_parser.get_kafka_topic(
                "advisor", "platform.legacy-bridge.events"
            ),
            "payload_tracker_topic": env_parser.get_kafka_topic(
                "advisor", "platform.payload-status"
            ),
            "kafka_hooks_topic": env_parser.get_kafka_topic("advisor", "hooks.outbox"),
            "db_hostname": env_parser.get_db_config("advisor").hostname,
            "db_database": env_parser.get_db_config("advisor").name,
            "db_username": env_parser.get_db_config("advisor").username,
            "db_password": env_parser.get_db_config("advisor").password,
            "db_port": env_parser.get_db_config("advisor").port,
            "service_objects": {
                "api": {
                    "config": {
                        "hostname": env_parser.get_hostname("advisor", "api"),
                        "port": env_parser.get_port("advisor", "api"),
                        "scheme": "http",
                    }
                }
            },
        }
        if env_parser.app_present("rbac"):
            hostname = env_parser.get_hostname("rbac", "service")
            port = env_parser.get_port("rbac", "service")
            env_conf["ADVISOR"][
                "rbac_url"
            ] = f"http://{hostname}:{port}/api/rbac/v1/access/?application=advisor"
        if env_parser.app_present("host-inventory"):
            env_conf["ADVISOR"]["egress_topic"] = (
                env_parser.get_kafka_topic("host-inventory", "platform.inventory.host-egress"),
            )

    if env_parser.app_present("playbook-dispatcher"):
        env_conf["RHC"] = {
            "kafka": {
                "playbook_validation_topic": env_parser.get_kafka_topic(
                    "playbook-dispatcher", "platform.upload.validation"
                ),
            },
            "service_objects": {
                "playbook_dispatcher_api_v1": {
                    "config": {
                        "hostname": env_parser.get_hostname(
                            "playbook-dispatcher", "playbook-dispatcher-api"
                        ),
                        "port": env_parser.get_port(
                            "playbook-dispatcher", "playbook-dispatcher-api"
                        ),
                        "scheme": "http",
                    }
                },
                "playbook_dispatcher_internal_api_v1": {
                    "config": {
                        "hostname": env_parser.get_hostname(
                            "playbook-dispatcher", "playbook-dispatcher-api"
                        ),
                        "port": env_parser.get_port(
                            "playbook-dispatcher", "playbook-dispatcher-api"
                        ),
                        "scheme": "http",
                    }
                },
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
        "data": {"settings.local.yaml": encoded_conf},
    }
    oc("apply", f="-", n=namespace, _in=json.dumps(secret))


def _create_pod(namespace, pod_name, env):
    pod = _get_base_pod_cfg()

    pod["metadata"]["name"] = pod_name
    env_vars = split_equals(env, allow_null=True)
    if env_vars:
        pod_env_vars = pod["spec"]["containers"][0]["env"]
        for key, val in env_vars.items():
            if val:
                pod_env_vars.append({"name": key, "value": val})

    oc("apply", f="-", n=namespace, _in=json.dumps(pod))


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("namespace", type=str, required=True)
@click.option("--pod-name", type=str, default="iqe-tests", help="name of pod (default: iqe-tests)")
@click.option(
    "--env",
    "-e",
    type=str,
    multiple=True,
    help="Env var to set on container using format KEY=VAL",
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

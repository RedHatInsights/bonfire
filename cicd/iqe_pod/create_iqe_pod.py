import logging
import click
import json
import sys

from bonfire.openshift import oc, wait_for_ready
from bonfire.utils import split_equals


def _get_base_pod_cfg():
    return {
        "apiVersion": "v1",
        "kind": "Pod",
        "metadata": {"name": "iqe-tests"},
        "spec": {
            "containers": [
                {
                    "command": ["/bin/cat"],
                    "image": "quay.io/cloudservices/iqe-core:latest",
                    "imagePullPolicy": "Always",
                    "name": "iqe-tests",
                    "resources": {
                        "limits": {"cpu": "1", "memory": "2Gi"},
                        "requests": {"cpu": "500m", "memory": "512Mi"},
                    },
                    "stdin": True,
                    "tty": True,
                }
            ],
            "imagePullSecrets": [{"name": "quay-cloudservices-pull"}],
            "restartPolicy": "Never",
        },
    }


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("namespace", type=str, required=True)
@click.option("--pod-name", type=str, default="iqe-tests", help="name of pod (default: iqe-tests)")
@click.option(
    "--env", "-e", type=str, multiple=True, help="Env var to set on container using format KEY=VAL"
)
def main(namespace, pod_name, env):
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("sh").setLevel(logging.CRITICAL)

    pod = _get_base_pod_cfg()

    pod["metadata"]["name"] = pod_name
    env_vars = split_equals(env, allow_null=True)
    if env_vars:
        pod["spec"]["containers"][0]["env"] = pod_env_vars = []
        for key, val in env_vars.items():
            if val:
                pod_env_vars.append({"name": key, "value": val})

    oc("create", f="-", n=namespace, _in=json.dumps(pod))
    if not wait_for_ready(namespace, "pod", pod_name):
        sys.exit(1)
    print(pod_name)


if __name__ == "__main__":
    main()

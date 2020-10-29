import logging
import click

from bonfire.openshift import oc, wait_for_ready


pod_yaml = """
apiVersion: v1
kind: Pod
metadata:
  name: {pod_name}
spec:
  containers:
  - command:
    - /bin/cat
    image: quay.io/cloudservices/iqe-core:latest
    imagePullPolicy: Always
    name: iqe-tests
    resources:
      limits:
        cpu: "1"
        memory: 2Gi
      requests:
        cpu: 500m
        memory: 512Mi
    stdin: true
    tty: true
  imagePullSecrets:
  - name: quay-cloudservices-pull
  restartPolicy: Never
"""


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("namespace", type=str, required=True)
@click.option("--pod-name", type=str, default="iqe-tests", help="name of pod (default: iqe-tests)")
def main(namespace, pod_name):
    logging.basicConfig(level=logging.INFO)
    logging.getLogger("sh").setLevel(logging.CRITICAL)
    oc("create", f="-", n=namespace, _in=pod_yaml.format(pod_name=pod_name))
    wait_for_ready(namespace, "pod", pod_name)
    print(pod_name)


if __name__ == "__main__":
    main()

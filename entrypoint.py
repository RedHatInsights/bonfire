import os
import subprocess
import sys


def check_kube_config():
    home = os.environ.get("HOME", "")
    kubeconfig = os.environ.get("KUBECONFIG", "")
    if kubeconfig and os.access(kubeconfig, os.R_OK):
        return True
    return os.access(os.path.join(home, ".kube", "config"), os.R_OK)


def main():
    if not check_kube_config():
        server = os.environ.get("OC_LOGIN_SERVER")
        token = os.environ.get("OC_LOGIN_TOKEN")
        if server and token:
            result = subprocess.run(["oc", "login", f"--server={server}", f"--token={token}"])
            if result.returncode != 0:
                print("Failed to log into OpenShift!")
                sys.exit(1)

    os.execvp("bonfire", ["bonfire"] + sys.argv[1:])


if __name__ == "__main__":
    main()

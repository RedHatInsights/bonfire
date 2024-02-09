#!/bin/bash

init_check() {

    if check_kube_config; then
        return 0
    fi

    if openshift_credentials_present; then
        if ! try_login_openshift; then
            echo "Failed to log into OpenShift!"
            return 1
        fi
    fi
}

check_kube_config() {
    [[ -r "${HOME}/.kube/config" ]] || [[ -r "$KUBECONFIG" ]]
}

openshift_credentials_present() {
    [[ -n "$OC_LOGIN_SERVER" ]] && [[ -n "$OC_LOGIN_TOKEN" ]]
}

try_login_openshift() {
    oc login --server="$OC_LOGIN_SERVER" --token="$OC_LOGIN_TOKEN" 
}

if ! init_check; then
    exit 1
fi

bonfire "$@"

#!/bin/bash

init_check() {

    if check_kube_config; then
        return 0
    fi

    if [ -z "$OC_LOGIN_SERVER" ]; then
        echo "OC_LOGIN_SERVER environment variable not found"
        return 1
    fi

    if [ -z "$OC_LOGIN_TOKEN" ]; then
        echo "OC_LOGIN_TOKEN environment variable not found"
        return 1
    fi
}

check_kube_config() {
    [[ -r "${HOME}/.kube/config" ]] || [[ -r "$KUBECONFIG" ]]
}

if ! init_check; then
    exit 1
fi

oc login --server="$OC_LOGIN_SERVER" --token="$OC_LOGIN_TOKEN" 

bonfire "$@"

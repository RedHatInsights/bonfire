#!/bin/bash

# Env vars set by bootstrap.sh:
# DOCKER_CONFIG -- docker conf path

# Env vars normally supplied by CI environment:
#QUAY_USER
#QUAY_TOKEN
#QUAY_API_TOKEN
#RH_REGISTRY_USER
#RH_REGISTRY_TOKEN

set -e

function login {
    if test -f /etc/redhat-release && grep -q -i "release 7" /etc/redhat-release; then
        # on RHEL7, use docker
        docker_login
    else
        # on RHEL8 or anything else, use podman
        podman_login
    fi
}

function docker_login {
    set -x
    docker login -u="$QUAY_USER" -p="$QUAY_TOKEN" quay.io
    docker login -u="$RH_REGISTRY_USER" -p="$RH_REGISTRY_TOKEN" registry.redhat.io
    set +x
}

function podman_login {
    podman login -u="$QUAY_USER" -p="$QUAY_TOKEN" quay.io
    podman login -u="$RH_REGISTRY_USER" -p="$RH_REGISTRY_TOKEN" registry.redhat.io
}

if [[ -z "$QUAY_USER" || -z "$QUAY_TOKEN" ]]; then
    echo "QUAY_USER and QUAY_TOKEN must be set"
    exit 1
fi

if [[ -z "$RH_REGISTRY_USER" || -z "$RH_REGISTRY_TOKEN" ]]; then
    echo "RH_REGISTRY_USER and RH_REGISTRY_TOKEN must be set"
    exit 1
fi


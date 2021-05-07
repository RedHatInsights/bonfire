#!/bin/bash

# Env vars caller defines:
#IMAGE="quay.io/myorg/myapp" -- docker image URI to push to

# Env vars set by bootstrap.sh:
#IMAGE_TAG="abcd123" -- image tag to push to
#APP_ROOT="/path/to/app/root" -- path to the cloned app repo

# Env vars normally supplied by CI environment:
#QUAY_USER
#QUAY_TOKEN
#RH_REGISTRY_USER
#RH_REGISTRY_TOKEN

set -ex

if [[ -z "$QUAY_USER" || -z "$QUAY_TOKEN" ]]; then
    echo "QUAY_USER and QUAY_TOKEN must be set"
    exit 1
fi

if [[ -z "$RH_REGISTRY_USER" || -z "$RH_REGISTRY_TOKEN" ]]; then
    echo "RH_REGISTRY_USER and RH_REGISTRY_TOKEN  must be set"
    exit 1
fi

if [ ! -f "$APP_ROOT/Dockerfile" ]; then
    echo "ERROR: No Dockerfile found"
    exit 1
fi
echo "LABEL quay.expires-after=3d" >> $APP_ROOT/Dockerfile  # tag expires in 3 days


AUTH_CONF_DIR="$(pwd)/.podman"
mkdir -p $AUTH_CONF_DIR
export REGISTRY_AUTH_FILE=$AUTH_CONF_DIR
podman login -u="$QUAY_USER" -p="$QUAY_TOKEN" quay.io
podman login -u="$RH_REGISTRY_USER" -p="$RH_REGISTRY_TOKEN" registry.redhat.io
podman build -f $APP_ROOT/Dockerfile -t "${IMAGE}:${IMAGE_TAG}" $APP_ROOT
podman push "${IMAGE}:${IMAGE_TAG}"


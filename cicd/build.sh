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


DOCKER_CONF="$PWD/.docker"
mkdir -p "$DOCKER_CONF"
docker --config="$DOCKER_CONF" login -u="$QUAY_USER" -p="$QUAY_TOKEN" quay.io
docker --config="$DOCKER_CONF" login -u="$RH_REGISTRY_USER" -p="$RH_REGISTRY_TOKEN" registry.redhat.io
docker --config="$DOCKER_CONF" build -t "${IMAGE}:${IMAGE_TAG}" $APP_ROOT -f $APP_ROOT/Dockerfile
docker --config="$DOCKER_CONF" push "${IMAGE}:${IMAGE_TAG}"


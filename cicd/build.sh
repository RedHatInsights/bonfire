#!/bin/bash

# Env vars caller defines:
#IMAGE="quay.io/myorg/myapp" -- docker image URI to push to
#DOCKERFILE=Dockerfile.custom  -- dockerfile to use (optional)
#CACHE_FROM_LATEST_IMAGE=true  -- build image from cache from latest image (optional)

# Env vars set by bootstrap.sh:
#IMAGE_TAG="abcd123" -- image tag to push to
#APP_ROOT="/path/to/app/root" -- path to the cloned app repo

# Env vars normally supplied by CI environment:
#QUAY_USER
#QUAY_TOKEN
#QUAY_API_TOKEN
#RH_REGISTRY_USER
#RH_REGISTRY_TOKEN

set -ex

function build {
    if [ ! -f "$APP_ROOT/$DOCKERFILE" ]; then
        echo "ERROR: No $DOCKERFILE found"
        exit 1
    fi

    echo "LABEL quay.expires-after=3d" >> $APP_ROOT/$DOCKERFILE  # tag expires in 3 days

    if test -f /etc/redhat-release && grep -q -i "release 7" /etc/redhat-release; then
        # on RHEL7, use docker
        docker_build
    else
        # on RHEL8 or anything else, use podman
        podman_build
    fi
}

function docker_build {
    DOCKER_CONF="$PWD/.docker"
    mkdir -p "$DOCKER_CONF"
    docker --config="$DOCKER_CONF" login -u="$QUAY_USER" -p="$QUAY_TOKEN" quay.io
    docker --config="$DOCKER_CONF" login -u="$RH_REGISTRY_USER" -p="$RH_REGISTRY_TOKEN" registry.redhat.io
    if [ "$CACHE_FROM_LATEST_IMAGE" == "true" ]; then
        echo "Attempting to build image using cache"
        {
            docker --config="$DOCKER_CONF" pull "${IMAGE}" &&
            docker --config="$DOCKER_CONF" build -t "${IMAGE}:${IMAGE_TAG}" $APP_ROOT -f $APP_ROOT/$DOCKERFILE --cache-from "${IMAGE}"
        } || {
            echo "Build from cache failed, attempting build without cache"
            docker --config="$DOCKER_CONF" build -t "${IMAGE}:${IMAGE_TAG}" $APP_ROOT -f $APP_ROOT/$DOCKERFILE
        }
    else
        docker --config="$DOCKER_CONF" build -t "${IMAGE}:${IMAGE_TAG}" $APP_ROOT -f $APP_ROOT/$DOCKERFILE
    fi
    docker --config="$DOCKER_CONF" push "${IMAGE}:${IMAGE_TAG}"
}

function podman_build {
    AUTH_CONF_DIR="$(pwd)/.podman"
    mkdir -p $AUTH_CONF_DIR
    export REGISTRY_AUTH_FILE="$AUTH_CONF_DIR/auth.json"
    podman login -u="$QUAY_USER" -p="$QUAY_TOKEN" quay.io
    podman login -u="$RH_REGISTRY_USER" -p="$RH_REGISTRY_TOKEN" registry.redhat.io
    podman build -f $APP_ROOT/$DOCKERFILE -t "${IMAGE}:${IMAGE_TAG}" $APP_ROOT
    podman push "${IMAGE}:${IMAGE_TAG}"
}


: ${DOCKERFILE:="Dockerfile"}
: ${CACHE_FROM_LATEST_IMAGE:="false"}

if [[ -z "$QUAY_USER" || -z "$QUAY_TOKEN" ]]; then
    echo "QUAY_USER and QUAY_TOKEN must be set"
    exit 1
fi

if [[ -z "$RH_REGISTRY_USER" || -z "$RH_REGISTRY_TOKEN" ]]; then
    echo "RH_REGISTRY_USER and RH_REGISTRY_TOKEN must be set"
    exit 1
fi

if [[ $IMAGE == quay.io/* ]]; then
    # if using quay, check to see if this tag already exists
    echo "checking if image '$IMAGE:$IMAGE_TAG' already exists in quay.io..."
    QUAY_REPO=${IMAGE#"quay.io/"}
    RESPONSE=$( \
        curl -Ls -I -o /dev/null -w "%{http_code}" -H "Authorization: Bearer $QUAY_API_TOKEN" \
        https://quay.io/api/v1/repository/$QUAY_REPO/tag/$IMAGE_TAG/images \
    )
    echo "received HTTP response: $RESPONSE"
    if [[ $RESPONSE == 200 ]]; then
        echo "$IMAGE:$IMAGE_TAG already present in quay, not rebuilding"
    else
        # image does not yet exist, build and push it
        build
    fi
else
    # if not pushing to quay, always build
    build
fi

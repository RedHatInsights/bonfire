#!/usr/bin/env bash

C_ENGINE="$1"
BUILD_CONTEXT="${2:-.}"
DOCKERFILE_NAME="${3:-Dockerfile}"
DOCKERFILE="${BUILD_CONTEXT}/${DOCKERFILE_NAME}"
IMAGE='localhost/simpletest'
LABEL='somefancylabel'

init() {

    if [ -z "$C_ENGINE" ]; then
        echo "usage: $0 CONTAINER_ENGINE BUILD_CONTEXT DOCKERFILE_NAME"
        exit 1
    fi

    if ! _command_exists "$C_ENGINE"; then
        echo "command '$C_ENGINE' not found"
        exit 1
    fi

    if ! [[ "$C_ENGINE" =~ ^(docker|podman)$ ]]; then
        echo "container engine $C_ENGINE not supported"
        exit 1
    fi

    if ! [ -r "$DOCKERFILE" ]; then
        echo "Dockerfile '$DOCKERFILE' not found!"
        exit 1
    fi
}

_command_exists() {
    command -v "$1" >/dev/null
}

delete_all() {
    read -ra IMAGE_REFS < <($C_ENGINE images -q $IMAGE)

    if [ ${#IMAGE_REFS[@]} -ne 0 ]; then
        $C_ENGINE image rm -f "${IMAGE_REFS[@]}"
    fi
}

build_image() {
    if ! $C_ENGINE build -t $IMAGE:label --label="${LABEL}=true" -f "$DOCKERFILE" "$BUILD_CONTEXT" ;then
        echo "labelerror building image '$IMAGE:label'"
        exit 1
    fi

    if ! $C_ENGINE build -t $IMAGE:nolabel -f "$DOCKERFILE" "$BUILD_CONTEXT";then
        echo "error building image '$IMAGE:nolabel'"
        exit 1
    fi
}

test_labels() {
    if ! $C_ENGINE inspect $IMAGE:label | grep -q "$LABEL"; then
        echo "ERROR - label '$LABEL' not found when inspecting '$IMAGE:label'"
        exit 1
    fi
    if $C_ENGINE inspect $IMAGE:nolabel | grep -q "$LABEL"; then
        echo "ERROR - label '$LABEL' found when inspecting '$IMAGE:nolabel'"
        exit 1
    fi
}

init
delete_all
build_image
test_labels

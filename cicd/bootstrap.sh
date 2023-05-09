#!/bin/bash

install_bonfire() {
  python3 -m venv "${BONFIRE_VENV}"
  source "${BONFIRE_VENV}/bin/activate"

  python3 -m pip install --upgrade pip 'setuptools<58' wheel
  python3 -m pip install --upgrade 'crc-bonfire>=4.10.4'
}

# Gives access to helper commands such as "oc_wrapper"
add_cicd_bin_to_path() {
  export PATH="${PATH}:${CICD_ROOT}/bin"
}

check_available_server() {
  echo "Checking connectivity to ephemeral cluster ..."
  if ! curl -s "$OC_LOGIN_SERVER" > /dev/null; then
    echo "Connectivity check failed"
    return 1
  fi
}

# Hotswap based on availability
login_to_available_server() {
  if check_available_server; then
    # log in to ephemeral cluster
    oc_wrapper login --token=$OC_LOGIN_TOKEN --server=$OC_LOGIN_SERVER
    echo "logging in to Ephemeral cluster"
  else
    # switch to crcd cluster
    oc_wrapper login --token=$OC_LOGIN_TOKEN_DEV --server=$OC_LOGIN_SERVER_DEV
    echo "logging in to CRCD cluster"
  fi
}

set -e

# check that unit_test.sh complies w/ best practices
URL="https://github.com/RedHatInsights/bonfire/tree/master/cicd/examples"
if test -f unit_test.sh; then
  if grep 'exit $result' unit_test.sh; then
    echo "----------------------------"
    echo "ERROR: unit_test.sh is calling 'exit' improperly, refer to examples at $URL"
    echo "----------------------------"
    exit 1
  fi
fi

export INSTALL_BONFIRE="${INSTALL_BONFIRE:-true}"
export APP_ROOT=$(pwd)
export WORKSPACE=${WORKSPACE:-$APP_ROOT}  # if running in jenkins, use the build's workspace
export BONFIRE_DIR_NAME="${BONFIRE_DIR_NAME:-.bonfire}"
export BONFIRE_ROOT="${WORKSPACE}/${BONFIRE_DIR_NAME}"
export CICD_ROOT=${BONFIRE_ROOT}/cicd
export IMAGE_TAG=$(git rev-parse --short=7 HEAD)
export BONFIRE_BOT="true"
export BONFIRE_NS_REQUESTER="${JOB_NAME}-${BUILD_NUMBER}"
# which branch to fetch cidd scripts from in bonfire repo
export BONFIRE_REPO_BRANCH="${BONFIRE_REPO_BRANCH:-master}"
export BONFIRE_REPO_ORG="${BONFIRE_REPO_ORG:-RedHatInsights}"
export BONFIRE_VENV_NAME="${BONFIRE_VENV_NAME:-.bonfire_venv}"
export BONFIRE_VENV="${APP_ROOT}/${BONFIRE_VENV_NAME}"

set -x
# Set up docker cfg
export DOCKER_CONFIG="$WORKSPACE/.docker"
rm -fr $DOCKER_CONFIG
mkdir $DOCKER_CONFIG

# Set up kube cfg
export KUBECONFIG_DIR="$WORKSPACE/.kube"
export KUBECONFIG="$KUBECONFIG_DIR/config"
rm -fr $KUBECONFIG_DIR
mkdir $KUBECONFIG_DIR

set +x

# if this is a PR, use a different tag, since PR tags expire
if [ ! -z "$ghprbPullId" ]; then
  export IMAGE_TAG="pr-${ghprbPullId}-${IMAGE_TAG}"
fi

if [ ! -z "$gitlabMergeRequestIid" ]; then
  export IMAGE_TAG="pr-${gitlabMergeRequestIid}-${IMAGE_TAG}"
fi

export GIT_COMMIT=$(git rev-parse HEAD)
export ARTIFACTS_DIR="$WORKSPACE/artifacts"

rm -fr $ARTIFACTS_DIR && mkdir -p $ARTIFACTS_DIR

# TODO: create custom jenkins agent image that has a lot of this stuff pre-installed
export LANG=en_US.utf-8
export LC_ALL=en_US.utf-8

if [[ "$INSTALL_BONFIRE" == "true" ]]; then
    install_bonfire
fi

# clone repo to download cicd scripts
rm -fr $BONFIRE_ROOT
echo "Fetching branch '$BONFIRE_REPO_BRANCH' of https://github.com/${BONFIRE_REPO_ORG}/bonfire.git"
git clone --branch "$BONFIRE_REPO_BRANCH" "https://github.com/${BONFIRE_REPO_ORG}/bonfire.git" "$BONFIRE_ROOT"

# Do a docker login to ensure our later 'docker pull' calls have an auth file created
source ${CICD_ROOT}/_common_container_logic.sh
login

if ! command -v oc_wrapper; then
  add_cicd_bin_to_path
fi

login_to_available_server

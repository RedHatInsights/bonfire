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

# log in to ephemeral cluster
oc login --token=$OC_LOGIN_TOKEN --server=$OC_LOGIN_SERVER

export APP_ROOT=$(pwd)
export WORKSPACE=${WORKSPACE:-$APP_ROOT}  # if running in jenkins, use the build's workspace
export BONFIRE_ROOT=${WORKSPACE}/bonfire
export CICD_ROOT=${BONFIRE_ROOT}/cicd
export IMAGE_TAG=$(git rev-parse --short=7 HEAD)

# Set up docker cfg
set -x
export DOCKER_CONF="$WORKSPACE/.docker"
rm -fr $DOCKER_CONF
mkdir $DOCKER_CONF

# Set up podman cfg
AUTH_CONF_DIR="$WORKSPACE/.podman"
rm -fr $AUTH_CONF_DIR
mkdir $AUTH_CONF_DIR
export REGISTRY_AUTH_FILE="$AUTH_CONF_DIR/auth.json"
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

python3 -m venv .bonfire_venv
source .bonfire_venv/bin/activate

pip install --upgrade pip 'setuptools<58' wheel
pip install --upgrade 'crc-bonfire>=2.17.2'

# clone repo to download cicd scripts
git clone https://github.com/RedHatInsights/bonfire.git $BONFIRE_ROOT

# --------------------------------------------
# Env vars that must be set by app owner prior to calling this script
# --------------------------------------------
#APP_NAME="myapp"  # name of app-sre "application" folder this component lives in
#COMPONENT_NAME="mycomponent"  # name of app-sre "resourceTemplate" in deploy.yaml for this component
#IMAGE="quay.io/cloudservices/mycomponent"  # image that this application uses

#IQE_PLUGINS=("plugin1" "plugin2")
#IQE_MARKER_EXPRESSION="mymarker"
#IQE_FILTER_EXPRESSION="something AND something_else"


# ---------------------------
# We'll take it from here ...
# ---------------------------

set -ex

# TODO: check quay to see if image is already built
BUILD_NEEDED=true

if [ $BUILD_NEEDED ]; then
    source build_deploy.sh
fi

IMAGE_TAG=$(git rev-parse --short=7 HEAD)
GIT_COMMIT=$(git rev-parse HEAD)

# TODO: create custom jenkins agent image that has a lot of this stuff pre-installed
export LANG=en_US.utf-8
export LC_ALL=en_US.utf-8
git clone https://github.com/RedHatInsights/bonfire.git
cd bonfire
python3 -m venv .venv
source .venv/bin/activate
pip install --upgrade pip setuptools wheel
pip install .


# Deploy k8s resources for app and its dependencies (use insights-stage instead of insights-production for now)
# -> use this PR as the template ref when downloading configurations for this component
# -> use this PR's newly built image in the deployed configurations
export NAMESPACE=$(bonfire config deploy \
    --ref-env insights-stage \
    --app $APP_NAME \
    --set-template-ref $COMPONENT_NAME=$GIT_COMMIT \
    --set-image-tag $IMAGE=$IMAGE_TAG \
    --get-dependencies)

trap "bonfire namespace release $NAMESPACE" EXIT ERR SIGINT SIGTERM

# Spin up iqe pod
IQE_POD_NAME=$(python utils/create_iqe_pod.py $NAMESPACE)

oc cp utils/run_iqe_tests.sh $IQE_POD_NAME
oc exec $IQE_POD_NAME -- \
    IQE_PLUGINS=$IQE_PLUGINS \
    IQE_MARKER_EXPRESSION=$IQE_MARKER_EXPRESSION \
    IQE_FILTER_EXPRESSION=$IQE_FILTER_EXPRESSION \
    bash run_iqe_tests.sh

oc cp $IQE_POD_NAME:artifacts/ .

ls -l artifacts
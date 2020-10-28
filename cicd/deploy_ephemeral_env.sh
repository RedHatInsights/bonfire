# --------------------------------------------
# Env vars that must be set by app owner prior to calling this script
# --------------------------------------------
#APP_NAME="myapp"  # name of app-sre "application" folder this component lives in
#COMPONENT_NAME="mycomponent"  # name of app-sre "resourceTemplate" in deploy.yaml for this component
#IMAGE="quay.io/cloudservices/mycomponent"  # image that this application uses

set -ex

# TODO: check quay to see if image is already built
BUILD_NEEDED=true

if [ $BUILD_NEEDED ]; then
    source build_deploy.sh  # this script should already be present in app team's repo
fi

IMAGE_TAG=$(git rev-parse --short=7 HEAD)
GIT_COMMIT=$(git rev-parse HEAD)


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


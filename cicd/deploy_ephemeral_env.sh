# Env vars caller defines:
#APP_NAME="myapp"  # name of app-sre "application" folder this component lives in
#COMPONENT_NAME="mycomponent"  # name of app-sre "resourceTemplate" in deploy.yaml for this component
#IMAGE="quay.io/cloudservices/mycomponent"  # image that this application uses

# Env vars set by 'bootstrap.sh':
#IMAGE_TAG="abcd123"  # image tag for the PR being tested
#GIT_COMMIT="abcd123defg456"  # full git commit hash of the PR being tested

set -ex

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


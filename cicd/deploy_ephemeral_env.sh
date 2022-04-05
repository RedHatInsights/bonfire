source ${CICD_ROOT}/_common_deploy_logic.sh

# Caller can define any extra deploy arguments to be passed to bonfire
: ${EXTRA_DEPLOY_ARGS:=""}

# Caller can alter the default dependency fetching method if desired
: ${OPTIONAL_DEPS_METHOD:="hybrid"}

# Deploy k8s resources for app and its dependencies (use insights-stage instead of insights-production for now)
# -> use this PR as the template ref when downloading configurations for this component
# -> use this PR's newly built image in the deployed configurations
set -x
export BONFIRE_NS_REQUESTER="${JOB_NAME}-${BUILD_NUMBER}"
export NAMESPACE=$(bonfire namespace reserve)
SMOKE_NAMESPACE=$NAMESPACE  # track which namespace was used here for 'teardown' in common_deploy_logic

bonfire deploy \
    ${APP_NAME} \
    --source=appsre \
    --ref-env ${REF_ENV} \
    --set-template-ref ${COMPONENT_NAME}=${GIT_COMMIT} \
    --set-image-tag ${IMAGE}=${IMAGE_TAG} \
    --namespace ${NAMESPACE} \
    --timeout ${DEPLOY_TIMEOUT} \
    --optional-deps-method ${OPTIONAL_DEPS_METHOD} \
    ${COMPONENTS_ARG} \
    ${COMPONENTS_RESOURCES_ARG} \
    ${EXTRA_DEPLOY_ARGS}
set +x

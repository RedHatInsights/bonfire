source ${CICD_ROOT}/_common_deploy_logic.sh

# Deploy k8s resources for app and its dependencies (use insights-stage instead of insights-production for now)
# -> use this PR as the template ref when downloading configurations for this component
# -> use this PR's newly built image in the deployed configurations
set -x
export NAMESPACE=$(bonfire namespace reserve)
bonfire deploy \
    ${APP_NAME} \
    --source=appsre \
    --ref-env insights-stage \
    --set-template-ref ${COMPONENT_NAME}=${GIT_COMMIT} \
    --set-image-tag ${IMAGE}=${IMAGE_TAG} \
    --namespace ${NAMESPACE} \
    --timeout ${DEPLOY_TIMEOUT} \
    ${COMPONENTS_ARG} \
    ${COMPONENTS_RESOURCES_ARG}
set +x

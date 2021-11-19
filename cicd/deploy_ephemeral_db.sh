# Reserve a namespace, deploy your app without dependencies just to get a DB set up
# Stores database env vars

source ${CICD_ROOT}/_common_deploy_logic.sh

# the db that the unit test relies on can be set before 'source'ing this script via
# DB_DEPLOYMENT_NAME -- by default it is '<ClowdApp name>-db'
DB_DEPLOYMENT_NAME="${DB_DEPLOYMENT_NAME:-$COMPONENT_NAME-db}"

# Deploy k8s resources for app without its dependencies
NAMESPACE=$(bonfire namespace reserve)
# TODO: add code to bonfire to deploy an app if it is defined in 'sharedAppDbName' on the ClowdApp
# TODO: add a bonfire command to deploy just an app's DB
set -x
bonfire process \
    $APP_NAME \
    --source=appsre \
    --ref-env insights-stage \
    --set-template-ref ${COMPONENT_NAME}=${GIT_COMMIT} \
    --set-image-tag $IMAGE=$IMAGE_TAG \
    --namespace $NAMESPACE \
    --no-get-dependencies \
    $COMPONENTS_ARG \
    $COMPONENTS_RESOURCES_ARG | oc apply -f - -n $NAMESPACE

bonfire namespace wait-on-resources $NAMESPACE --db-only
set +x

# Set up port-forward for DB
LOCAL_DB_PORT=$(python -c 'import socket; s=socket.socket(); s.bind(("", 0)); print(s.getsockname()[1]); s.close()')
oc port-forward svc/$DB_DEPLOYMENT_NAME $LOCAL_DB_PORT:5432 -n $NAMESPACE &
PORT_FORWARD_PID=$!

# Store database access info to env vars
oc get secret $COMPONENT_NAME -o json -n $NAMESPACE | jq -r '.data["cdappconfig.json"]' | base64 -d | jq .database > db-creds.json

export DATABASE_NAME=$(jq -r .name < db-creds.json)
export DATABASE_ADMIN_USERNAME=$(jq -r .adminUsername < db-creds.json)
export DATABASE_ADMIN_PASSWORD=$(jq -r .adminPassword < db-creds.json)
export DATABASE_USER=$(jq -r .username < db-creds.json)
export DATABASE_PASSWORD=$(jq -r .password < db-creds.json)
export DATABASE_HOST=localhost
export DATABASE_PORT=$LOCAL_DB_PORT

if [ -z "$DATABASE_NAME" ]; then
    echo "DATABASE_NAME is null, error with ephemeral env / clowder config, exiting"
    exit 1
else
    echo "DB_DEPLOYMENT_NAME: ${DB_DEPLOYMENT_NAME}"
    echo "DATABASE_NAME: ${DATABASE_NAME}"
fi

# If we got here, the DB came up successfully, clear the k8s artifacts dir in case
# 'source deploy_ephemeral_env.sh' is called later
rm -f $K8S_ARTIFACTS_DIR

# Reserve a namespace, deploy your app without dependencies just to get a DB set up
# Stores database env vars

source _common_deploy_logic.sh

function kill_port_fwd {
    echo "Caught signal, kill port forward"
    if [ ! -z "$PORT_FORWARD_PID" ]; then kill $PORT_FORWARD_PID; fi
}

# Deploy k8s resources for app without its dependencies
NAMESPACE=$(bonfire namespace reserve)
# TODO: after move to bonfire v1.0, make sure to use '--no-get-dependencies' here
bonfire config get
    --ref-env insights-stage \
    --app $APP_NAME \
    --set-template-ref $COMPONENT_NAME=$GIT_COMMIT \
    --set-image-tag $IMAGE=$IMAGE_TAG | oc apply -f - -n $NAMESPACE
sleep 5  # give clowder a chance to create the DB deployment
oc rollout status -w deployment/$APP_NAME-db

# Set up port-forward for DB
LOCAL_DB_PORT=$(python -c 'import socket; s=socket.socket(); s.bind(("", 0)); print(s.getsockname()[1]); s.close()')
oc port-forward svc/$APP_NAME-db $LOCAL_DB_PORT:5432 &
PORT_FORWARD_PID=$!
trap "teardown" EXIT ERR SIGINT SIGTERM

# Store database access info to env vars
oc get secret $APP_NAME -o json | jq -r '.data["cdappconfig.json"]' | base64 -d | jq .database > db-creds.json
export DATABASE_NAME=$(jq -r .name < db-creds.json)
export DATABASE_ADMIN_USERNAME=$(jq -r .adminUsername < db-creds.json)
export DATABASE_ADMIN_PASSWORD=$(jq -r .adminPassword < db-creds.json)
export DATABASE_USER=$(jq -r .user < db-creds.json)
export DATABASE_PASSWORD=$(jq -r .password < db-creds.json)
export DATABASE_HOST=localhost
export DATABASE_PORT=$LOCAL_DB_PORT

# If we got here, the DB came up successfully, clear the k8s artifacts dir in case
# 'source deploy_ephemeral_env.sh' is called later
rm -f $K8S_ARTIFACTS_DIR

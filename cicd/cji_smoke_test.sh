# Run smoke tests as a ClowdJobInvocation deployed by bonfire

# Env vars defined by caller:
#COMPONENT_NAME -- name of ClowdApp to run tests against /  app-sre "resourceTemplate"
#IQE_CJI_TIMEOUT="10m" -- timeout value to pass to 'oc wait', should be slightly higher than expected test run time
#IQE_MARKER_EXPRESSION="something AND something_else" -- pytest marker, can be "" if no filter desired
#IQE_FILTER_EXPRESSION="something AND something_else" -- pytest filter, can be "" if no filter desired
#IQE_REQUIREMENTS="something,something_else" -- iqe requirements filter, can be "" if no filter desired
#IQE_REQUIREMENTS_PRIORITY="something,something_else" -- iqe requirements filter, can be "" if no filter desired
#IQE_TEST_IMPORTANCE="something,something_else" -- iqe test importance filter, can be "" if no filter desired
#NAMESPACE="mynamespace" -- namespace to deploy iqe pod into, usually set by 'deploy_ephemeral_env.sh'

# Env vars set by 'bootstrap.sh':
#ARTIFACTS_DIR -- directory where test run artifacts are stored

# In order for the deploy-iqe-cji to run correctly, we must set the marker and filter to "" if they
# are not already set by caller
# https://unix.stackexchange.com/questions/122845/using-a-b-for-variable-assignment-in-scripts/122848#122848
set -e

: "${IQE_MARKER_EXPRESSION:='""'}"
: "${IQE_FILTER_EXPRESSION:='""'}"
: "${IQE_IMAGE_TAG:='""'}"
: "${IQE_REQUIREMENTS:='""'}"
: "${IQE_REQUIREMENTS_PRIORITY:='""'}"
: "${IQE_TEST_IMPORTANCE:='""'}"

# minio client is used to fetch test artifacts from minio in the ephemeral ns
MC_IMAGE="quay.io/cloudservices/mc:latest"
docker pull $MC_IMAGE

CJI_NAME="$COMPONENT_NAME"

if [[ -z $IQE_CJI_TIMEOUT ]]; then
    echo "Error: no timeout set; export IQE_CJI_TIMEOUT before invoking cji_smoke_test.sh"
    exit 1
fi

# Invoke the CJI using the options set via env vars
set -x
POD=$(
    bonfire deploy-iqe-cji $COMPONENT_NAME \
    --marker "$IQE_MARKER_EXPRESSION" \
    --filter "$IQE_FILTER_EXPRESSION" \
    --image-tag "${IQE_IMAGE_TAG}" \
    --requirements "$IQE_REQUIREMENTS" \
    --requirements-priority "$IQE_REQUIREMENTS_PRIORITY" \
    --test-importance "$IQE_TEST_IMPORTANCE" \
    --env "clowder_smoke" \
    --cji-name $CJI_NAME \
    --namespace $NAMESPACE)
set +x

# Pipe logs to background to keep them rolling in jenkins
oc logs -n $NAMESPACE $POD -f &

# Wait for the job to Complete or Fail before we try to grab artifacts
# condition=complete does trigger when the job fails
set -x
oc wait --timeout=$IQE_CJI_TIMEOUT --for=condition=JobInvocationComplete -n $NAMESPACE cji/$CJI_NAME
set +x

# Set up port-forward for minio
LOCAL_SVC_PORT=$(python -c 'import socket; s=socket.socket(); s.bind(("", 0)); print(s.getsockname()[1]); s.close()')
oc port-forward svc/env-$NAMESPACE-minio $LOCAL_SVC_PORT:9000 -n $NAMESPACE &
sleep 5
PORT_FORWARD_PID=$!

# Get the secret from the env
oc get secret env-$NAMESPACE-minio -o json -n $NAMESPACE | jq -r '.data' > minio-creds.json

# Grab the needed creds from the secret
export MINIO_ACCESS=$(jq -r .accessKey < minio-creds.json | base64 -d)
export MINIO_SECRET_KEY=$(jq -r .secretKey < minio-creds.json | base64 -d)
export MINIO_HOST=localhost
export MINIO_PORT=$LOCAL_SVC_PORT

# Setup the minio client to auth to the local eph minio in the ns
echo "Fetching artifacts from minio..."

CONTAINER_NAME="mc-${JOB_NAME}-${BUILD_NUMBER}"
BUCKET_NAME="${POD}-artifacts"
CMD="mkdir -p /artifacts &&
mc --no-color --quiet alias set minio http://${MINIO_HOST}:${MINIO_PORT} ${MINIO_ACCESS} ${MINIO_SECRET_KEY} &&
mc --no-color --quiet mirror --overwrite minio/${BUCKET_NAME} /artifacts/
"

run_mc () {
    echo "running: docker run -t --net=host --name=$CONTAINER_NAME --entrypoint=\"/bin/sh\" $MC_IMAGE -c \"$CMD\""
    set +e
    docker run -t --net=host --name=$CONTAINER_NAME --entrypoint="/bin/sh" $MC_IMAGE -c "$CMD"
    RET_CODE=$?
    docker cp $CONTAINER_NAME:/artifacts/. $ARTIFACTS_DIR
    docker rm $CONTAINER_NAME
    set -e
    return $RET_CODE
}

# Add retry logic for intermittent minio connection failures
MINIO_SUCCESS=false
for i in $(seq 1 5); do
    if run_mc; then
        MINIO_SUCCESS=true
        break
    else
        if [ "$i" -lt "5" ]; then
            echo "WARNING: minio artifact copy failed, retrying in 5sec..."
            sleep 5
        fi
    fi
done

if [ "$MINIO_SUCCESS" = false ]; then
    echo "ERROR: minio artifact copy failed"
    exit 1
fi

echo "copied artifacts from iqe pod: "
ls -l $ARTIFACTS_DIR

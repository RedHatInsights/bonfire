# Run smoke tests as a ClowdJobInvocation deployed by bonfire

# Env vars defined by caller:
#COMPONENT_NAME -- name of ClowdApp to run tests against /  app-sre "resourceTemplate"
#IQE_CJI_TIMEOUT="10m" -- timeout value to pass to 'oc wait', should be slightly higher than expected test run time
#IQE_MARKER_EXPRESSION="something AND something_else" -- pytest marker, can be "" if no filter desired
#IQE_FILTER_EXPRESSION="something AND something_else" -- pytest filter, can be "" if no filter desired
#IQE_REQUIREMENTS="{'something','something_else'}" -- iqe requirements filter, can be "" if no filter desired
#IQE_REQUIREMENTS_PRIORITY="{'something','something_else'}" -- iqe requirements filter, can be "" if no filter desired
#IQE_TEST_IMPORTANCE="{'something','something_else'}" -- iqe requirements filter, can be "" if no filter desired
#NAMESPACE="mynamespace" -- namespace to deploy iqe pod into, usually set by 'deploy_ephemeral_env.sh'

# In order for the deploy-iqe-cji to run correctly, we must set the marker and filter to "" if they
# are not already set by caller
# https://unix.stackexchange.com/questions/122845/using-a-b-for-variable-assignment-in-scripts/122848#122848
: "${IQE_MARKER_EXPRESSION:='""'}"
: "${IQE_FILTER_EXPRESSION:='""'}"
: "${IQE_IMAGE_TAG:='""'}"
: "${IQE_REQUIREMENTS:='""'}"
: "${IQE_REQUIREMENTS_PRIORITY:='""'}"
: "${IQE_TEST_IMPORTANCE:='""'}"

CJI_NAME="$COMPONENT_NAME-smoke-tests"

if [[ -z $IQE_CJI_TIMEOUT ]]; then
    echo "Error: no timeout set; export IQE_CJI_TIMEOUT before invoking cji_smoke_test.sh"
    exit 1
fi

# Invoke the CJI using the options set via env vars
set -x
pod=$(
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
oc logs -n $NAMESPACE $pod -f &

# Wait for the job to Complete or Fail before we try to grab artifacts
# condition=complete does trigger when the job fails
set -x
oc wait --timeout=$IQE_CJI_TIMEOUT --for=condition=JobInvocationComplete -n $NAMESPACE cji/$CJI_NAME
set +x

# Get the minio client
# TODO: bake this into jenkins agent template
curl https://dl.min.io/client/mc/release/linux-amd64/mc -o mc
chmod +x mc

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
./mc alias set minio http://$MINIO_HOST:$MINIO_PORT $MINIO_ACCESS $MINIO_SECRET_KEY

# "mirror" copies the entire artifacts dir from the pod and writes it to the jenkins node
./mc mirror --overwrite minio/$pod-artifacts artifacts/

echo "copied artifacts from iqe pod: "
ls -l $WORKSPACE/artifacts

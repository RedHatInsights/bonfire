# Run smoke tests as a ClowdJobInvocation deployed by bonfire

# Env vars defined by caller:
#IQE_FILTER_EXPRESSION="something AND something_else" -- pytest filter, can be "" if no filter desired
#NAMESPACE="mynamespace" -- namespace to deploy iqe pod into, can be set by 'deploy_ephemeral_env.sh'

# In order for the deploy-iqe-cji to run correctly, we must set the marker and filter to "" if they
# are not set in pr_check.sh
# https://unix.stackexchange.com/questions/122845/using-a-b-for-variable-assignment-in-scripts/122848#122848
IQE_MARKER_EXPRESSION="${IQE_MARKER_EXPRESSION:='""'}"
IQE_FILTER_EXPRESSION="${IQE_FILTER_EXPRESSION:='""'}"

CJI_NAME="$APP_NAME-smoke-tests"

function kill_port_fwd {
    echo "Caught signal, kill port forward"
    if [ ! -z "$PORT_FORWARD_PID" ]; then kill $PORT_FORWARD_PID; fi
}

if [[ -z $IQE_CJI_TIMEOUT ]]; then
    echo "Error: no timeout set; export IQE_CJI_TIMEOUT in the main pr_check.sh file"
    exit 1
fi

# Invoke the CJI with the exported vars from pr_check
pod=$(bonfire deploy-iqe-cji $APP_NAME -m $IQE_MARKER_EXPRESSION -k $IQE_FILTER_EXPRESSION -e "clowder_smoke" --cji-name $CJI_NAME -n $NAMESPACE)

# Pipe logs to background to keep them rolling in jenkins
oc logs -n $NAMESPACE $pod -f &

# Wait for the job to Complete or Fail before we try to grab artifacts
# condition=complete does trigger when the job fails
oc wait --timeout=$IQE_CJI_TIMEOUT --for=condition=Complete -n $NAMESPACE job/$CJI_NAME-iqe

# Get the minio client
curl https://dl.min.io/client/mc/release/linux-amd64/mc -o mc
chmod +x mc

# Set up port-forward for minio
LOCAL_SVC_PORT=$(python -c 'import socket; s=socket.socket(); s.bind(("", 0)); print(s.getsockname()[1]); s.close()')
oc port-forward svc/env-$NAMESPACE-minio $LOCAL_SVC_PORT:9000 -n $NAMESPACE &
sleep 5
PORT_FORWARD_PID=$!
trap "teardown" EXIT ERR SIGINT SIGTERM

# Get the secret from the env
oc get secret env-$NAMESPACE-minio -o json -n $NAMESPACE | jq -r '.data' > minio-creds.json

# Grab the needed creds from the secret
export MINIO_ACCESS=$(jq -r .accessKey < minio-creds.json | base64 -d)
export MINIO_SECRET_KEY=$(jq -r .secretKey < minio-creds.json | base64 -d)
export MINIO_HOST=localhost
export MINIO_PORT=$LOCAL_SVC_PORT

# Setup the minio client to auth to the local eph minio in the ns
./mc alias set minio http://$MINIO_HOST:$MINIO_PORT $MINIO_ACCESS $MINIO_SECRET_KEY

# "mirror" copies the entire artifacts dir from the pod and writes it to the jenkins node
./mc mirror --overwrite minio/$pod-artifacts artifacts/

echo "copied artifacts from iqe pod: "
ls -l $WORKSPACE/artifacts

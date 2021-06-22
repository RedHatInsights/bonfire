# Spin up iqe pod and execute IQE tests in it

# Env vars defined by caller:
#IQE_PLUGINS="plugin1,plugin2" -- pytest plugins to run separated by ","
#IQE_MARKER_EXPRESSION="mymarker" -- pytest marker expression
#IQE_FILTER_EXPRESSION="something AND something_else" -- pytest filter, can be "" if no filter desired
#NAMESPACE="mynamespace" -- namespace to deploy iqe pod into, can be set by 'deploy_ephemeral_env.sh'

# The CJI var name will need to be exported in the main pr_check.sh
oc apply -n $NAMESPACE -f $APP_ROOT/$CJI_PATH

job_name=$APP_NAME-smoke-tests-iqe
found=false
end=$((SECONDS+60))

echo "Waiting for Job $job_name to appear"

while [ $SECONDS -lt $end ]; do
    if `oc get job $job_name -n $NAMESPACE >/dev/null 2>&1`; then
        found=true
        break
    fi
    sleep 1
done

if [ "$found" == "false" ] ; then
    echo "Job $job_name failed to appear"
    exit 1
fi

echo "Waiting for Job $job_name to be running"
running=false
pod=""

# The jq magic will find all running pods in the ns and regex on the app name
# Loop over for SECONDS and send back the pod's name once found
while [ $SECONDS -lt $end ]; do
    pod=$(oc get pods -n $NAMESPACE -o json | jq -r --arg JOB $job_name '.items[] | select(.status.phase=="Running") | select(.metadata.name|test($JOB)) .metadata.name')
    if [[ -n $pod ]]; then
        running=true
        break
    fi
    sleep 5
done

if [ "$running" == "false" ] ; then
    echo "Job $job_name failed to start"
    exit 1
fi

# Pipe logs to background to keep them rolling in jenkins
oc logs -n $NAMESPACE $pod -f &

# Wait for the job to Complete or Fail before we try to grab artifacts
# condition=complete does trigger when the job fails
oc wait --timeout=3m --for=condition=Complete -n $NAMESPACE job/$job_name 

# Get the minio client (curl would be even more complicated)
curl https://dl.min.io/client/mc/release/linux-amd64/mc -o mc
chmod +x mc


# Get the secret from the env
oc get secret env-$NAMESPACE-minio -o json -n $NAMESPACE | jq '.data | map_values(@base64d)' > minio-creds.json

# Grab the needed creds from the secret
export MINIO_HOST=$(jq -r .hostname < minio-creds.json)
export MINIO_PORT=$(jq -r .port < minio-creds.json)
export MINIO_ACCESS=$(jq -r .accessKey < minio-creds.json)
export MINIO_SECRET_KEY=$(jq -r .secretKey < minio-creds.json)

# Setup the minio client to auth to the local eph minio in the ns
./mc alias set minio $MINIO_HOST:$MINIO_PORT $MINIO_ACCESS $MINIO_SECRET_KEY

# "mirror" copies the entire artifacts dir from the pod and writes it to the jenkins node
./mc mirror --overwrite minio/$pod-artifacts artifacts/

oc cp -n $NAMESPACE $pod:/iqe-venv/artifacts/ $WORKSPACE/artifacts

echo "copied artifacts from iqe pod: "
ls -l $WORKSPACE/artifacts

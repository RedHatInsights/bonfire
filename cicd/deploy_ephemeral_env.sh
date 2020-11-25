# Env vars caller defines:
#APP_NAME="myapp"  # name of app-sre "application" folder this component lives in
#COMPONENT_NAME="mycomponent"  # name of app-sre "resourceTemplate" in deploy.yaml for this component
#IMAGE="quay.io/cloudservices/mycomponent"  # image that this application uses

# Env vars set by 'bootstrap.sh':
#IMAGE_TAG="abcd123"  # image tag for the PR being tested
#GIT_COMMIT="abcd123defg456"  # full git commit hash of the PR being tested

set -ex

K8S_ARTIFACTS_DIR="$WORKSPACE/artifacts/k8s_artifacts/"
START_TIME=$(date +%s)

# adapted from https://stackoverflow.com/a/62475429
# get all events that were emitted at a time greater than $START_TIME, sort by time, and tabulate
function get_oc_events {
    {
        echo $'TIME\tNAMESPACE\tTYPE\tREASON\tOBJECT\tSOURCE\tMESSAGE';
        oc get events -n $NAMESPACE -o json "$@" | jq -r --argjson start_time "$START_TIME" \
            '.items |
            map(. + {t: (.eventTime//.lastTimestamp)}) |
            [ .[] | select(.t | sub("\\.[0-9]+Z$"; "Z") | fromdateiso8601 > $start_time) ] |
            sort_by(.t)[] |
            [.t, .metadata.namespace, .type, .reason, .involvedObject.kind + "/" + .involvedObject.name, .source.component + "," + (.source.host//"-"), .message] |
            @tsv'
    } | column -s $'\t' -t > $K8S_ARTIFACTS_DIR/events.txt
}

function get_pod_logs {
    LOGS_DIR="$K8S_ARTIFACTS_DIR/logs"
    mkdir -p $LOGS_DIR
    PODS=( $(oc get pods -o jsonpath='{range .items[*]}{.metadata.name}{" "}' || echo "") )
    for pod in $PODS; do
        CONTAINERS=( $(oc get pod $pod -n $NAMESPACE -o jsonpath='{range .spec.containers[*]}{.name}{" "}' || echo "") )
        if [ -z "$CONTAINERS" ]; then
            echo "get logs: pod $pod not found"
        fi;
        for container in $CONTAINERS; do
            oc logs $pod -c $container > $LOGS_DIR/${pod}_${container}.log || echo "get logs: ${pod}_${container} failed."
            echo "Saved logs for $pod container $container"
        done
    done
}

function collect_k8s_artifacts {
    mkdir -p $K8S_ARTIFACTS_DIR
    get_pod_logs
    get_oc_events
    oc get all -o yaml > $K8S_ARTIFACTS_DIR/oc_get_all.yaml
    oc get clowdapp -o yaml > $K8S_ARTIFACTS_DIR/oc_get_clowdapp.yaml
    oc get clowdenvironment env-$NAMESPACE -o yaml > $K8S_ARTIFACTS_DIR/oc_get_clowdenvironment.yaml
}

function teardown {
    if [ ! -z "$NAMESPACE" ]; then
        set +e
        collect_k8s_artifacts
        bonfire namespace release $NAMESPACE
    fi
}


# Deploy k8s resources for app and its dependencies (use insights-stage instead of insights-production for now)
# -> use this PR as the template ref when downloading configurations for this component
# -> use this PR's newly built image in the deployed configurations
export NAMESPACE=$(bonfire config deploy \
    --ref-env insights-stage \
    --app $APP_NAME \
    --set-template-ref $COMPONENT_NAME=$GIT_COMMIT \
    --set-image-tag $IMAGE=$IMAGE_TAG \
    --get-dependencies)


trap "teardown" EXIT ERR SIGINT SIGTERM


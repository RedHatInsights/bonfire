# Env vars caller defines:
#APP_NAME="myapp"  # name of app-sre "application" folder this component lives in
#COMPONENT_NAME="mycomponent"  # name of app-sre "resourceTemplate" in deploy.yaml for this component
#IMAGE="quay.io/cloudservices/mycomponent"  # image that this application uses

# Env vars set by 'bootstrap.sh':
#IMAGE_TAG="abcd123"  # image tag for the PR being tested
#GIT_COMMIT="abcd123defg456"  # full git commit hash of the PR being tested
trap "teardown" EXIT ERR SIGINT SIGTERM

set -ex

K8S_ARTIFACTS_DIR="$WORKSPACE/artifacts/k8s_artifacts/"
START_TIME=$(date +%s)
TEARDOWN_RAN=0

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
    } | column -s $'\t' -t > $K8S_ARTIFACTS_DIR/oc_events.txt
}

function get_pod_logs {
    LOGS_DIR="$K8S_ARTIFACTS_DIR/logs"
    mkdir -p $LOGS_DIR
    # get array of pod_name:container for all containers in all pods
    PODS_CONTAINERS=($(oc get pods --ignore-not-found=true -n $NAMESPACE -o 'jsonpath={range .items[*]}{.metadata.name}{range .spec.containers[*]}{":"}{.name}{" "}'))
    for pc in ${PODS_CONTAINERS[@]}; do
	# https://stackoverflow.com/a/4444841
	POD=${pc%%:*}
	CONTAINER=${pc#*:}
        oc logs $POD -c $CONTAINER -n $NAMESPACE > $LOGS_DIR/${POD}_${CONTAINER}.log || continue
    done
}

function collect_k8s_artifacts {
    mkdir -p $K8S_ARTIFACTS_DIR
    get_pod_logs
    get_oc_events
    oc get all -n $NAMESPACE -o yaml > $K8S_ARTIFACTS_DIR/oc_get_all.yaml
    oc get clowdapp -n $NAMESPACE -o yaml > $K8S_ARTIFACTS_DIR/oc_get_clowdapp.yaml
    oc get clowdenvironment env-$NAMESPACE -o yaml > $K8S_ARTIFACTS_DIR/oc_get_clowdenvironment.yaml
}

function teardown {
    [ "$TEARDOWN_RAN" -ne "0" ] && return
    if [ ! -z "$NAMESPACE" ]; then
        set +e
        collect_k8s_artifacts
        bonfire namespace release $NAMESPACE
    fi
    set -e
    TEARDOWN_RAN=1
}


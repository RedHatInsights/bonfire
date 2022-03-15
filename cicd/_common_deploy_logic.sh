# Env vars caller defines:
#APP_NAME="myapp"  # name of app-sre "application" folder this component lives in
#COMPONENT_NAME="mycomponent"  # name of app-sre "resourceTemplate" in deploy.yaml for this component
#IMAGE="quay.io/cloudservices/mycomponent"  # image that this application uses
#COMPONENTS="component1 component2"  # specific components to deploy (optional, default: all)
#COMPONENTS_W_RESOURCES="component1 component2"  # components which should preserve resource settings (optional, default: none)
#DEPLOY_TIMEOUT="600"  # bonfire deployment timeout parameter in seconds
#RELEASE_NAMESPACE="true"  # release namespace after PR check ends (default: true)
#ALWAYS_COLLECT_LOGS="true"  # collect logs on teardown even if tests passed (default: false)
#REF_ENV="insights-production"  # name of bonfire reference environment (default: insights-production)

# Env vars set by 'bootstrap.sh':
#IMAGE_TAG="abcd123"  # image tag for the PR being tested
#GIT_COMMIT="abcd123defg456"  # full git commit hash of the PR being tested
#ARTIFACTS_DIR -- directory where test run artifacts are stored

add_cicd_bin_to_path

function trap_proxy {
    # https://stackoverflow.com/questions/9256644/identifying-received-signal-name-in-bash
    func="$1"; shift
    for sig; do
        trap "$func $sig" "$sig"
    done
}

trap_proxy teardown EXIT ERR SIGINT SIGTERM

set -e

: ${COMPONENTS:=""}
: ${COMPONENTS_W_RESOURCES:=""}
: ${DEPLOY_TIMEOUT:="600"}
: ${REF_ENV:="insights-production"}
: ${RELEASE_NAMESPACE:="true"}
: ${ALWAYS_COLLECT_LOGS:="false"}

K8S_ARTIFACTS_DIR="$ARTIFACTS_DIR/k8s_artifacts"
TEARDOWN_RAN=0

function get_pod_logs() {
    local ns=$1
    LOGS_DIR="$K8S_ARTIFACTS_DIR/$ns/logs"
    mkdir -p $LOGS_DIR
    # get array of pod_name:container1,container2,..,containerN for all containers in all pods
    echo "Collecting container logs..."
    PODS_CONTAINERS=($(oc_wrapper get pods --ignore-not-found=true -n $ns -o "jsonpath={range .items[*]}{' '}{.metadata.name}{':'}{range .spec['containers', 'initContainers'][*]}{.name}{','}"))
    for pc in ${PODS_CONTAINERS[@]}; do
        # https://stackoverflow.com/a/4444841
        POD=${pc%%:*}
        CONTAINERS=${pc#*:}
        for container in ${CONTAINERS//,/ }; do
            oc_wrapper logs $POD -c $container -n $ns > $LOGS_DIR/${POD}_${container}.log 2> /dev/null || continue
            oc_wrapper logs $POD -c $container --previous -n $ns > $LOGS_DIR/${POD}_${container}-previous.log 2> /dev/null || continue
        done
    done
}

function collect_k8s_artifacts() {
    local ns=$1
    DIR="$K8S_ARTIFACTS_DIR/$ns"
    mkdir -p $DIR
    get_pod_logs $ns
    echo "Collecting events and k8s configs..."
    oc_wrapper get events -n $ns --sort-by='.lastTimestamp' > $DIR/oc_get_events.txt
    oc_wrapper get all -n $ns -o yaml > $DIR/oc_get_all.yaml
    oc_wrapper get clowdapp -n $ns -o yaml > $DIR/oc_get_clowdapp.yaml
    oc_wrapper get clowdenvironment env-$ns -o yaml > $DIR/oc_get_clowdenvironment.yaml
    oc_wrapper get clowdjobinvocation -n $ns -o yaml > $DIR/oc_get_clowdjobinvocation.yaml
}

function teardown {
    local CAPTURED_SIGNAL="$1"

    add_cicd_bin_to_path

    set +x
    [ "$TEARDOWN_RAN" -ne "0" ] && return
    echo "------------------------"
    echo "----- TEARING DOWN -----"
    echo "------------------------"
    local ns

    echo "Tear down operation triggered by signal: $CAPTURED_SIGNAL"

    # run teardown on all namespaces possibly reserved in this run
    RESERVED_NAMESPACES=("${NAMESPACE}" "${DB_NAMESPACE}" "${SMOKE_NAMESPACE}")
    # remove duplicates (https://stackoverflow.com/a/13648438)
    UNIQUE_NAMESPACES=($(echo "${RESERVED_NAMESPACES[@]}" | tr ' ' '\n' | sort -u | tr '\n' ' '))

    for ns in ${UNIQUE_NAMESPACES[@]}; do
        echo "Running teardown for ns: $ns"
        set +e

        if [ "$ALWAYS_COLLECT_LOGS" != "true" ] && [ "$CAPTURED_SIGNAL" == "EXIT" ] && check_junit_files "${ARTIFACTS_DIR}/junit-*.xml"; then
            echo "No errors or failures detected on JUnit reports, skipping K8s artifacts collection"
        else
            [ "$ALWAYS_COLLECT_LOGS" != "true" ] && echo "Errors or failures detected, collecting K8s artifacts"
            collect_k8s_artifacts $ns
        fi

        if [ "${RELEASE_NAMESPACE}" != "false" ]; then
            echo "Releasing namespace reservation"
            bonfire namespace release $ns -f
        fi
        set -e
    done
    TEARDOWN_RAN=1
}

function transform_arg {
    # transform components to "$1" options for bonfire
    options=""
    option="$1"; shift;
    components="$@"
    for c in $components; do
        options="$options $option $c"
    done
    echo "$options"
}

if [ ! -z "$COMPONENTS" ]; then
    export COMPONENTS_ARG=$(transform_arg --component $COMPONENTS)
fi

if [ ! -z "$COMPONENTS_W_RESOURCES" ]; then
    export COMPONENTS_RESOURCES_ARG=$(transform_arg --no-remove-resources $COMPONENTS_W_RESOURCES)
fi

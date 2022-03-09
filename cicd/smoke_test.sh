# Spin up iqe pod and execute IQE tests in it

# Env vars defined by caller:
#IQE_PLUGINS="plugin1,plugin2" -- pytest plugins to run separated by ","
#IQE_MARKER_EXPRESSION="mymarker" -- pytest marker expression
#IQE_FILTER_EXPRESSION="something AND something_else" -- pytest filter, can be "" if no filter desired
#NAMESPACE="mynamespace" -- namespace to deploy iqe pod into, can be set by 'deploy_ephemeral_env.sh'

# Env vars set by 'bootstrap.sh':
#ARTIFACTS_DIR -- directory where test run artifacts are stored

IQE_POD_NAME="iqe-tests"

add_cicd_bin_to_path

# create a custom svc acct for the iqe pod to run with that has elevated permissions
SA=$(oc_wrapper get -n $NAMESPACE sa iqe --ignore-not-found -o jsonpath='{.metadata.name}')
if [ -z "$SA" ]; then
    oc_wrapper create -n $NAMESPACE sa iqe
fi
oc_wrapper policy -n $NAMESPACE add-role-to-user edit system:serviceaccount:$NAMESPACE:iqe
oc_wrapper secrets -n $NAMESPACE link iqe quay-cloudservices-pull --for=pull,mount

python $CICD_ROOT/iqe_pod/create_iqe_pod.py $NAMESPACE \
    -e IQE_PLUGINS="$IQE_PLUGINS" \
    -e IQE_MARKER_EXPRESSION="$IQE_MARKER_EXPRESSION" \
    -e IQE_FILTER_EXPRESSION="$IQE_FILTER_EXPRESSION" \
    -e ENV_FOR_DYNACONF=smoke \
    -e NAMESPACE=$NAMESPACE

oc_wrapper cp -n $NAMESPACE $CICD_ROOT/iqe_pod/iqe_runner.sh $IQE_POD_NAME:/iqe_venv/iqe_runner.sh
oc_wrapper exec $IQE_POD_NAME -n $NAMESPACE -- bash /iqe_venv/iqe_runner.sh

oc_wrapper cp -n $NAMESPACE $IQE_POD_NAME:artifacts/ $ARTIFACTS_DIR

echo "copied artifacts from iqe pod: "
ls -l $ARTIFACTS_DIR

# Spin up iqe pod and execute IQE tests in it

# Env vars defined by caller:
#IQE_PLUGINS="plugin1,plugin2" -- pytest plugins to run separated by ","
#IQE_MARKER_EXPRESSION="mymarker" -- pytest marker expression
#IQE_FILTER_EXPRESSION="something AND something_else" -- pytest filter, can be "" if no filter desired
#NAMESPACE="mynamespace" -- namespace to deploy iqe pod into, can be set by 'deploy_ephemeral_env.sh'

IQE_POD_NAME="iqe-tests"

# create a custom svc acct for the iqe pod to run with that has elevated permissions
SA=$(oc get -n $NAMESPACE sa iqe --ignore-not-found -o jsonpath='{.metadata.name}')
if [ -z "$SA" ]; then
    oc create -n $NAMESPACE sa iqe
fi
oc policy -n $NAMESPACE add-role-to-user edit system:serviceaccounts:$NAMESPACE:iqe
oc secrets -n $NAMESPACE link iqe quay-cloudservices-pull --for=pull,mount

python iqe_pod/create_iqe_pod.py $NAMESPACE \
    -e IQE_PLUGINS=$IQE_PLUGINS \
    -e IQE_MARKER_EXPRESSION=$IQE_MARKER_EXPRESSION \
    -e IQE_FILTER_EXPRESSION=$IQE_FILTER_EXPRESSION \
    -e ENV_FOR_DYNACONF=smoke \
    -e NAMESPACE=$NAMESPACE

oc cp -n $NAMESPACE iqe_pod/iqe_runner.sh $IQE_POD_NAME:/iqe_venv/iqe_runner.sh
oc exec $IQE_POD_NAME -n $NAMESPACE -- bash /iqe_venv/iqe_runner.sh

oc cp -n $NAMESPACE $IQE_POD_NAME:artifacts/ $WORKSPACE/artifacts

echo "copied artifacts from iqe pod: "
ls -l $WORKSPACE/artifacts

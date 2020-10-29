# Spin up iqe pod and execute IQE tests in it

# Env vars defined by caller:
#IQE_PLUGINS=("plugin1" "plugin2") -- pytest plugins to run
#IQE_MARKER_EXPRESSION="mymarker" -- pytest marker expression
#IQE_FILTER_EXPRESSION="something AND something_else" -- pytest filter, can be "" if no filter desired
#NAMESPACE="mynamespace" -- namespace to deploy iqe pod into, can be set by 'deploy_ephemeral_env.sh'

IQE_POD_NAME=$(python iqe_pod/create_iqe_pod.py $NAMESPACE)

oc cp -n $NAMESPACE iqe_pod/iqe_runner.sh $IQE_POD_NAME:/iqe_runner.sh
oc exec $IQE_POD_NAME -n $NAMESPACE -- \
    IQE_PLUGINS=$IQE_PLUGINS \
    IQE_MARKER_EXPRESSION=$IQE_MARKER_EXPRESSION \
    IQE_FILTER_EXPRESSION=$IQE_FILTER_EXPRESSION \
    bash /iqe_runner.sh

oc cp -n $NAMESPACE $IQE_POD_NAME:artifacts/ .

# TODO: actually do something with these...
ls -l artifacts

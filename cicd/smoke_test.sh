# Spin up iqe pod and execute IQE tests in it

# Env vars required for this script:

#IQE_PLUGINS=("plugin1" "plugin2")
#IQE_MARKER_EXPRESSION="mymarker"
#IQE_FILTER_EXPRESSION="something AND something_else"
#NAMESPACE="mynamespace"

IQE_POD_NAME=$(python create_iqe_pod.py $NAMESPACE)

oc cp iqe_runner.sh $IQE_POD_NAME
oc exec $IQE_POD_NAME -- \
    IQE_PLUGINS=$IQE_PLUGINS \
    IQE_MARKER_EXPRESSION=$IQE_MARKER_EXPRESSION \
    IQE_FILTER_EXPRESSION=$IQE_FILTER_EXPRESSION \
    bash iqe_runner.sh

oc cp $IQE_POD_NAME:artifacts/ .

ls -l artifacts

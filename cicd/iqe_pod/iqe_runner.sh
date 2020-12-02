#!/bin/bash

# This script is intended to be run in an iqe-tests pod

# Env vars required for this script:

#IQE_PLUGINS="plugin1,plugin2"
#IQE_MARKER_EXPRESSION="mymarker"
#IQE_FILTER_EXPRESSION="something AND something_else"

set -ex

ARTIFACTS_DIR="artifacts"

mkdir -p $ARTIFACTS_DIR

# The plugin *should* be pre-installed in the container
#for plugin in $IQE_PLUGINS; do
#    iqe plugin install $plugin
#done

# TODO: add vault env vars
#export ENV_FOR_DYNACONF=smoke

# TODO: deprecate clowder_smoke env in iqe configs once everything is migrated
export ENV_FOR_DYNACONF=clowder_smoke

PLUGIN_ARRAY=${IQE_PLUGINS//,/ }


set +e  # test pass/fail should be determined by analyzing the junit xml artifacts left in the pod

for plugin in $PLUGIN_ARRAY; do
    # run tests marked for 'parallel'
    marker="parallel and (${IQE_MARKER_EXPRESSION})"
    iqe tests plugin ${plugin} \
        --junitxml=${ARTIFACTS_DIR}/junit-${plugin}-parallel.xml \
        -m "${marker}" \
        -k "${IQE_FILTER_EXPRESSION}" \
        -n 2 \
        --log-file=${ARTIFACTS_DIR}/iqe-${plugin}-parallel.log 2>&1

    # run non-parallel tests in sequence
    marker="not parallel and (${IQE_MARKER_EXPRESSION})"
    iqe tests plugin ${plugin} \
        --junitxml=${ARTIFACTS_DIR}/junit-${plugin}-sequential.xml \
        -m "${marker}" \
        -k "${IQE_FILTER_EXPRESSION}" \
        --log-file=${ARTIFACTS_DIR}/iqe-${plugin}-sequential.log 2>&1
done

ls -l ${ARTIFACTS_DIR}/

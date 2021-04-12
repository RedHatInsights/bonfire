#!/bin/bash

# --------------------------------------------
# Options that must be configured by app owner
# --------------------------------------------
APP_NAME="CHANGEME"  # name of app-sre "application" folder this component lives in
COMPONENT_NAME="CHANGEME"  # name of app-sre "resourceTemplate" in deploy.yaml for this component
IMAGE="quay.io/cloudservices/CHANGEME"  # image location on quay

IQE_PLUGINS="CHANGEME"  # name of the IQE plugin for this app.
IQE_MARKER_EXPRESSION="CHANGEME"  # This is the value passed to pytest -m
IQE_FILTER_EXPRESSION=""  # This is the value passed to pytest -k

# Install bonfire repo/initialize
# https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd/bootstrap.sh
# This script automates the install / config of bonfire
CICD_URL=https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd
curl -s $CICD_URL/bootstrap.sh > .cicd_bootstrap.sh && source .cicd_bootstrap.sh

# The contents of build.sh can be found at:
# https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd/build.sh
# This script is used to build the image that is used in the PR Check
source $CICD_ROOT/build.sh

# Your APP's unit tests should be run in the unit_test.sh script.  Two different
# examples of unit_test.sh are provided in:
# https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd/examples/
#
# One of these scripts should be choosen based on your APP's architecture, modified, and placed
# in your APP's git repository.  The ephemeral DB example is for when the unit tests require a
# real DB, the other is for a more traditional unit test where everything runs self-contained.
#
# One thing to note is that the unit test run results are expected to be in a junit XML format,
# in the examples we demonstrate how to create a 'dummy result file' as a temporary work-around.
source $APP_ROOT/unit_test.sh

# The contents of this script can be found at:
# https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd/deploy_ephemeral_env.sh
# This script is used to deploy the ephemeral environment for smoke tests.
# The manual steps for this can be found in:
# https://internal.cloud.redhat.com/docs/devprod/ephemeral/02-deploying/
source $CICD_ROOT/deploy_ephemeral_env.sh

# The contents of this script can be found at:
# https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd/smoke_test.sh
# This script is used to run the smoke tests for a given APP.  The ENV VARs are
# defined at the top in the "Options that must be configured by app owner" section
# will control the behavior of the test.
source $CICD_ROOT/smoke_test.sh

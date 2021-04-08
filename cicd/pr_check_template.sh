#!/bin/bash

# source unit_test.sh

# --------------------------------------------
# Options that must be configured by app owner
# --------------------------------------------
APP_NAME="CHANGEME"  # name of app-sre "application" folder this component lives in
COMPONENT_NAME="CHANGEME"  # name of app-sre "resourceTemplate" in deploy.yaml for this component
IMAGE="quay.io/cloudservices/CHANGEME"  

IQE_PLUGINS="CHANGEME"  # name of the IQE plugin for this APP
IQE_MARKER_EXPRESSION="smoke"  # Name of the subset of tests to run in IQE
IQE_FILTER_EXPRESSION=""


# Install bonfire repo/initialize
CICD_URL=https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd
curl -s $CICD_URL/bootstrap.sh -o bootstrap.sh

# The contents of the bootstrap script can be found here:
# https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd/bootstrap.sh
# This script automates the install / config of bonfire, the DOCs covering this can be found:
# https://internal.cloud.redhat.com/docs/devprod/ephemeral/01-onboarding/
source bootstrap.sh  # checks out bonfire and changes to "cicd" dir...

# The contents of build.sh can be found at:
# https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd/build.sh
# This script is used to build the image that is used in the PR Check
source build.sh

# The contents of this script can be found at:
# https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd/deploy_ephemeral_env.sh
# This script is used to deploy the ephemeral environment that we are using to deploy / test
# the image we are building in build.sh
# The manual steps for this can be found in:
# https://internal.cloud.redhat.com/docs/devprod/ephemeral/02-deploying/
source deploy_ephemeral_env.sh


# The contents of this script can be found at:
# https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd/smoke_test.sh
# This script is used to run the smoke tests for a given APP.  The ENV VARs are
# defined above in the, "Options that must be configured by app owner"
source smoke_test.sh

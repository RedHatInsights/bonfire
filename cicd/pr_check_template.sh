#!/bin/bash

# --------------------------------------------
# Options that must be configured by app owner
# --------------------------------------------
APP_NAME="CHANGEME"  # name of app-sre "application" folder this component lives in
COMPONENT_NAME="CHANGEME"  # name of app-sre "resourceTemplate" in deploy.yaml for this component
IMAGE="quay.io/cloudservices/CHANGEME"  # This is the image location on quay

IQE_PLUGINS="CHANGEME"  # name of the IQE plugin for this APP
IQE_MARKER_EXPRESSION="smoke"  # This is the value passed to pytest -m
IQE_FILTER_EXPRESSION=""  # This is the value passed to pytest -k

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

# Your APP's unit tests should be run in the unit_test.sh script.  Two different
# examples of unit_test.sh are provided in:
# https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd/unit_test_example_django.sh
# https://raw.githubusercontent.com/RedHatInsights/bonfire/master/cicd/unit_test_example_no_django.sh
# One of these scripts should be choosen based on your APP's architecture, modified, and placed
# in your APP's git repository.  The django example is for when the APP requires a piece of 
# infrastructure, the no django example is for a more traditional unit test.
# One thing to note is that the unit test run results are expected to be in a junit XML format,
# in the examples we have provided ways
source unit_test.sh

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

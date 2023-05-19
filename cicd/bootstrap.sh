#!/bin/bash

set -e

# which branch to fetch cicd scripts from in cicd-tools repo
export CICD_REPO_BRANCH="${CICD_REPO_BRANCH:-main}"

BOOTSTRAP_URL="https://raw.githubusercontent.com/RedHatInsights/cicd-tools/${CICD_REPO_BRANCH}/bootstrap.sh"
BOOTSTRAP_FILE=".cicd_tools_bootstrap.sh"

set -x
echo "Fetching $BOOTSTRAP_URL"
rm -f $BOOTSTRAP_FILE
curl --silent --show-error $BOOTSTRAP_URL > $BOOTSTRAP_FILE && source $BOOTSTRAP_FILE

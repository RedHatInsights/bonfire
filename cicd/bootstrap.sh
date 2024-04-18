#!/bin/bash

# which branch to fetch cicd scripts from in cicd-tools repo
CICD_REPO_BRANCH="${CICD_REPO_BRANCH:-main}"
CICD_REPO_ORG="${CICD_REPO_ORG:-RedHatInsights}"
BOOTSTRAP_SCRIPT_URL="https://raw.githubusercontent.com/${CICD_REPO_ORG}/cicd-tools/${CICD_REPO_BRANCH}/bootstrap.sh"

set -e
source <(curl -sSL "$BOOTSTRAP_SCRIPT_URL")
set +e 

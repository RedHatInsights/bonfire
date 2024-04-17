#!/bin/bash

set -e

export TMP_JOB_DIR=${TMP_JOB_DIR:-$(mktemp -d -p "$HOME" -t "jenkins-${JOB_NAME}-${BUILD_NUMBER}-XXXXXX")}
# which branch to fetch cicd scripts from in cicd-tools repo
CICD_REPO_BRANCH="${CICD_REPO_BRANCH:-main}"
CICD_REPO_ORG="${CICD_REPO_ORG:-RedHatInsights}"
BOOTSTRAP_URL="https://raw.githubusercontent.com/${CICD_REPO_ORG}/cicd-tools/${CICD_REPO_BRANCH}/bootstrap.sh"
BOOTSTRAP_FILE="${TMP_JOB_DIR}/.cicd_tools_bootstrap.sh"

echo "Fetching $BOOTSTRAP_URL"
rm -f $BOOTSTRAP_FILE
RESPONSE_CODE=$(curl --silent -w "%{http_code}" -o "$BOOTSTRAP_FILE" "$BOOTSTRAP_URL")
echo "HTTP response: $RESPONSE_CODE"
source "$BOOTSTRAP_FILE"

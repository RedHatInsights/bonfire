#!/bin/bash

set -e

# which branch to fetch cicd scripts from in cicd-tools repo
CICD_REPO_BRANCH="${CICD_REPO_BRANCH:-main}"
CICD_REPO_ORG="${CICD_REPO_ORG:-RedHatInsights}"
BOOTSTRAP_URL="https://raw.githubusercontent.com/${CICD_REPO_ORG}/cicd-tools/${CICD_REPO_BRANCH}/bootstrap.sh"
BOOTSTRAP_FILE="./.cicd_tools_bootstrap.sh"

echo "Fetching $BOOTSTRAP_URL"
rm -f $BOOTSTRAP_FILE
RESPONSE_CODE=$(curl --silent -w "%{http_code}" -o "$BOOTSTRAP_FILE" "$BOOTSTRAP_URL")
echo "HTTP response: $RESPONSE_CODE"
source "$BOOTSTRAP_FILE"

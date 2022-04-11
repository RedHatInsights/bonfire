#!/bin/bash

# starting the script
echo "Posting test results"

# getting archives uuids
UUIDS="$(ls $ARTIFACTS_DIR | grep .tar.gz | sed -e 's/\.tar.gz$//')"

if [[ -n $UUIDS ]]
then
  # construct the comment message
  message="Test results are available in [Ibutsu](https://url.corp.redhat.com/ibutsu-runs). The test run IDs are:"
  for uuid in $UUIDS
  do
    message="${message}\n${uuid}"
  done

  # post the comment
  curl \
    -X POST \
    -H "Accept: application/vnd.github.v3+json" \
    -H "Authorization: token ${GITHUB_TOKEN}" \
    -H "Content-Type: application/json; charset=utf-8" \
    ${GITHUB_API_URL}/repos/${ghprbGhRepository}/issues/${ghprbPullId}/comments \
    -d "{\"body\":\"$message\"}"
fi

echo "end of posting test results"

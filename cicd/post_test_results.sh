#!/bin/bash

# starting the script
echo "Posting test results"

# getting archives uuids
UUIDS="$(ls $ARTIFACTS_DIR | grep .tar.gz | sed -e 's/\.tar.gz$//')"

if [[ -n $UUIDS ]]
then
  base_message="Test results are available in Ibutsu"

  # if it is a GitHub PR
  if [[ -n $ghprbPullId ]]; then

    # set +e so that if this POST fails, the entire run will not fail
    set +e

    # post a status api message for each test run separately
    for uuid in $UUIDS;
    do
      curl \
        -X POST \
        -H "Accept: application/vnd.github.v3+json" \
        -H "Authorization: token ${GITHUB_TOKEN}" \
        -H "Content-Type: application/json; charset=utf-8" \
        ${GITHUB_API_URL}/repos/${ghprbGhRepository}/statuses/${ghprbActualCommit} \
        -d "{\"state\":\"success\",\"target_url\":\"https://url.corp.redhat.com/ibutsu-runs-${uuid}\",\"description\":\"${base_message}\",\"context\":\"ibutsu/run-${uuid}\"}"
    done

    set -e
  fi

  # if it is a GitLab MR
  if [[ -n $gitlabMergeRequestIid ]]; then
    # construct the comment message
    message="${base_message}:"
    for uuid in $UUIDS
    do
      message="${message}\nhttps://url.corp.redhat.com/ibutsu-runs-${uuid}"
    done

    # set +e so that if this POST fails, the entire run will not fail
    set +e

    # post a comment to GitLab
    curl \
      -X POST \
      -H "PRIVATE-TOKEN: ${GITLAB_TOKEN_IQE_BOT}" \
      -H "Content-Type: application/json; charset=utf-8" \
      ${GITLAB_HOST_IQE_BOT}/api/v4/projects/${gitlabMergeRequestTargetProjectId}/merge_requests/${gitlabMergeRequestIid}/notes \
      -d "{\"body\":\"$message\"}" -v
    set -e
  fi
fi

echo "end of posting test results"

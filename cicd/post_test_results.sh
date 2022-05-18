#!/bin/bash

# starting the script
echo "Posting test results"

# getting archives uuids
UUIDS="$(ls $ARTIFACTS_DIR | grep .tar.gz | sed -e 's/\.tar.gz$//')"

if [[ -n $UUIDS ]]
then
  # if it is a GitHub PR
  if [[ -n $ghprbPullId ]]; then
    # construct the comment message for GitHub
    message="Test results are available in [Ibutsu](https://url.corp.redhat.com/ibutsu-runs). The test run IDs are:"
    for uuid in $UUIDS
    do
      message="${message}\n${uuid}"
    done

    # set +e so that if this POST fails, the entire run will not fail
    set +e

    # check if there's already a comment by InsightsDroid
    last_comment=$(curl \
      -X GET -H "Accept: application/vnd.github.v3+json" \
      -H "Authorization: token ${GITHUB_TOKEN}" \
      -H "Content-Type: application/json; charset=utf-8" \
      ${GITHUB_API_URL}/repos/${ghprbGhRepository}/issues/${ghprbPullId}/comments | \
      jq 'map(select(.user.login == "InsightsDroid"))[-1]')

    if [[ $last_comment != "null" ]]; then
      # edit the comment
      comment_id=$(echo $last_comment | jq '.id')
      curl \
      -X PATCH \
      -H "Accept: application/vnd.github.v3+json" \
      -H "Authorization: token ${GITHUB_TOKEN}" \
      -H "Content-Type: application/json; charset=utf-8" \
      ${GITHUB_API_URL}/repos/${ghprbGhRepository}/issues/comments/${comment_id} \
      -d "{\"body\":\"$message\"}"
    else
      # post a new comment to GitHub
      curl \
        -X POST \
        -H "Accept: application/vnd.github.v3+json" \
        -H "Authorization: token ${GITHUB_TOKEN}" \
        -H "Content-Type: application/json; charset=utf-8" \
        ${GITHUB_API_URL}/repos/${ghprbGhRepository}/issues/${ghprbPullId}/comments \
        -d "{\"body\":\"$message\"}"
      set -e
    fi
  fi

  # if it is a GitLab MR
  if [[ -n $gitlabMergeRequestIid ]]; then
    # construct the comment message for GitLab
    message="Test results are available in Ibutsu:"
    for uuid in $UUIDS
    do
      urls="${urls}${IBUTSU_URL}/runs/${uuid}\n"
    done

    message="${message}\n${urls}"

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

Utilities used to run smoke tests in an ephemeral environment within a CI/CD pipeline


See examples directory for a pr_check template, and some unit test templates. 
# Scripts

## bootstrap.sh

Clone bonfire into workspace, setup python venv, modify PATH, login to container registries, login to Kube/OCP, and set envvars used by following scripts.

## build.sh

Using docker (rhel7) or podman (else) build, tag, and push an image to Quay and Red Hat registries.

If its a GitHub or GitLab PR/MR triggered script execution, tag image with `pr-123-SHA` and `pr-123-testing`, else use a short SHA for the target repo HEAD.

## deploy_ephemeral_db.sh

Deploy using `bonfire process` and `<oc_wrapper> apply`, removing dependencies and setting up database envvars.

## deploy_ephemeral_env.sh

Deploy using `bonfire deploy` into ephemeral, specifying app, component, and relevant image tag args.  Passes `EXTRA_DEPLOY_ARGS` which can be set by the caller via pr_checks.sh.

## cji_smoke_test.sh

Run iqe-tests container for the relevant app plugin using `bonfire deploy-iqe-cji`. Waits for tests to complete, and fetches artifacts using minio.

## post_test_results.sh

Using artifacts fetched from `cji_smoke_test.sh`, add a GitHub status or GitLab comment linking to the relevant test results in Ibutsu.

## smoke_test.sh

DEPRECATED, use `cji_smoke_test.sh`

## iqe_pod

DEPRECATED, use `cji_smoke_test.sh`


# Contributing

Suggested method for testing changes to these scripts:
- Modify `bootstrap.sh` to `git clone` your fork and branch of bonfire.
- Open a PR in a repo using bonfire pr_checks and the relevant scripts, modifying `pr_check` script to clone your fork and branch of bonfire.
- Observe modified scripts running in the relevant CI/CD pipeline.
# 

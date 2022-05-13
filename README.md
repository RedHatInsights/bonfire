# bonfire

A CLI tool used to deploy ephemeral environments for testing cloud.redhat.com applications

`bonfire` interacts with a running instance of [qontract-server](https://github.com/app-sre/qontract-server) (the component that powers the [AppSRE team](https://github.com/app-sre/)'s internal `app-interface` graphql API) or a local configuration file to obtain applications' OpenShift templates, process them, and deploy them.

It also interacts with OpenShift to manage the reservation of ephemeral namespaces for testing.

It is meant to be partnered with the [Clowder](https://github.com/RedHatInsights/clowder) and [namespace reservation operator](https://github.com/RedHatInsights/ephemeral-namespace-operator)
operators to spin up an ephemeral environment for testing on either a remote OpenShift cluster or a local k8s cluster.

## Installation

We'd recommend setting up a virtual environment for bonfire:

```bash
VENV_DIR=~/bonfire_venv
mkdir -p $VENV_DIR
python3 -m venv $VENV_DIR
. $VENV_DIR/bin/activate
pip install crc-bonfire
bonfire --help
```

## Overview

The `bonfire process` command can be used to print processed app configs to stdout.

The `bonfire namespace reserve` command can be used to acquire a namespace on a cluster
if that cluster has been set up with the namespace reservation operator.

The `bonfire deploy` command can be used as a helpful "1-liner" command to reserve a namespace,
process application configs, apply them into a desired namespace, and wait for them to come up successfully.

The `bonfire process-env` command can be used to print a processed ClowdEnvironment config to stdout.

The `bonfire deploy-env` command can be used as a helpful "1-liner" command to apply a ClowdEnvironment
configuration into a cluster and wait for environment resources to come up successfully.

Use `bonfire --help` to get a list of other commands you may find useful.

### Loading an app's ephemeral config from app-interface (default behavior)

When running `bonfire process`/`bonfire deploy`, by default `--source appsre` will be selected. By default app-sre team's internal GraphQL API URL is used. `bonfire` will query the GraphQL API and read the desired application's deploy configuration.

*NOTE*: You need to be on the internal VPN in order to access the default GraphQL API URL.

You can edit the local configuration file (see 'App config overrides' below) if you wish to override any app configurations to allow for "local tinkering". If you define an app under the `apps` key of the config, it will take precedence over that app's configuration that was fetched from app-interface.

### Using a local config

To get up and running without contacting app-interface's `qontract-server` at all, you can utilize
a local config file. `bonfire` ships with a [default config](bonfire/resources/default_config.yaml) that
should be enough to get started for most internal Red Hat employees. An internal repository holds
application configurations for the cloud.redhat.com platform that are valid for use in ephemeral environments.

By default, the configuration file will be stored in `~/.config/bonfire/config.yaml`. You can reset the config to default at any time using `bonfire config write-default`.

### App config overrides

You can edit your local config file to override any app configurations to allow for "local tinkering". If you define an app under the
`apps` key of the config, it will take precedence over any app's configuration that was fetched/downloaded.

#### Deploy app template using changes you've made locally

As an example, if you wanted to test out some changes you're making to an app but you have not yet pushed these changes to a git repo, the local config could look similar to:

```
apps:
- name: my_app
  components:
    - name: service
      host: local
      repo: ~/dev/projects/my-app
      path: /clowdapp.yaml
```

- Where **host** set `local` indicates to look for the repo in a local directory
- Where **repo** indicates the path to your git repo folder
- Where **path** specifies the relative path to your ClowdApp template file in your git repo
- An `app` is similar to an application folder in app-interface. A `component` is similar to what app-interface would call a `resourceTemplate` within an app.

By default, bonfire will run `git rev-parse` to determine what IMAGE_TAG to set when the template is deployed. However, you can use `--set-image-tag` or `--set-parameter` to override this.

#### Deploy app template using changes you've made in a remote git branch

As an example, if you wanted to deploy changes to your app that you were working on which have been pushed to a PR/branch, the local config could look similar to:

```
apps:
- name: my_app
  components:
    - name: service
      host: github
      repo: MyOrg/MyRepo
      path: /clowdapp.yaml
```

- Where **host** set to `github` or `gitlab` indicates where the repo is hosted
- Where **repo** indicates the `OrganizationName/RepoName`
- Where **path** specifies the relative path to your ClowdApp template file in your git repo
- An `app` is similar to an application folder in app-interface. A `component` is similar to what app-interface would call a `resourceTemplate` within an app.

By default, bonfire will use the commit hash of `master` to determine what IMAGE_TAG to deploy.

NOTE: For this particular use case, if your changes are already present in a git repo, and your app already has appropriate ephemeral deployment configs set up, then using the `--set-template-ref` and `--set-image-tag` flags in bonfire may be simpler than editing your app config.

### Loading application configs

`bonfire process` relies on a few key pieces of info to process app configs:
1. The application name. This is typically the name of the listed in `app.yaml` in `app-interface`
1. *(applies to `--source=appsre` only)* a 'target env' -- the name of the `app-interface` environment that you want to pull application configs for. An app's config will only be processed if it has a deploy target set up that points to a namespace mapped to this environment (default: "ephemeral")
1. *(optional)* a 'ref env' -- the name of the `app-interface` environment that we want to use in order to set the applications `IMAGE_TAG` values and deploy template ref. This can be useful if you want to deploy applications using ephemeral template parameters, but you want to override the `IMAGE_TAG`/`ref` defined on all apps to use the values found in `prod` or `stage`.
1. Any template refs you wish to override -- in other words, if you want to download a different git hash of an application component's template.
1. Any image tags you wish to override -- in other words, if you want to use a different image tag for just a specific docker image.
1. Any parameters you wish to override -- if you want to set a different template parameter for a specific app.

By default, `bonfire` will dynamically load dependencies that all components of `app` relies on. This requires the `app` to be using the [Clowder](https://github.com/RedHatInsights/clowder) operator and to have the `dependencies` or `optionalDependencies` section of the ClowdApp set up.


### Example usage in a smoke test

The goal of a smoke test running against an `app` is to:
* deploy the PR's code for `app`
* deploy the production versions of `app`'s dependencies alongside it

Below we'll show how `bonfire deploy` will enable this:

Let's say that we are running a PR check against the `insights-puptoo` service. This service:
* is a member of the `ingress` application.
* has a kubernetes deploy manifest that resides in the same repo as the code
* has its CI/CD `pr_check.sh` set up such that if a PR is opened, a docker image is built and pushed to `quay.io/myorg/insights-puptoo` with the tag `pr-<git hash>`. The PR opened against the app has commit hash `abc1234`

If we intend to reserve a namespace and deploy the `ingress` application group into it, using the new template/image of the `insights-puptoo` PR, but using the production template/image for all other components, we could run:

```bash
APP_NAME=ingress
COMPONENT_NAME=insights-puptoo
GIT_COMMIT=pr-abc1234
IMAGE=quay.io/myorg/insights-puptoo
IMAGE_TAG=abc1234

NAMESPACE=$(bonfire deploy $APP_NAME \
    --ref-env insights-prod \
    --set-template-ref $COMPONENT_NAME=$GIT_COMMIT \
    --set-image-tag $IMAGE=$IMAGE_TAG)

echo "My environment is deployed into $NAMESPACE"
```

This is functionally equivalent to:
```bash
NAMESPACE=$(bonfire namespace reserve)

bonfire process $APP_NAME
    --ref-env insights-prod
    --set-template-ref $COMPONENT_NAME=$GIT_COMMIT
    --set-image-tag $IMAGE=$IMAGE_TAG
    --clowd-env env-$NAMESPACE

bonfire namespace wait-on-resources $NAMESPACE

echo "My environment is deployed into $NAMESPACE"
```

## Namespace management

`bonfire` is also used to reserve, release, and reconcile ephemeral namespaces running on our test OpenShift clusters. It interacts with the
[namespace reservation operator](https://github.com/RedHatInsights/ephemeral-namespace-operator) to reserve/release namespaces in a cluster
that has the operator installed.

When a tester is logged in using the proper account, namespace commands can be used such as:

`bonfire namespace reserve` -- find an available namespace and reserve it. By default the TTL is 1 hr.

`bonfire namespace release <namespace>` -- release a namespace reservation

Use `bonfire namespace -h` to see a list of all available namespace commands.

### Interactions with Clowder

* `bonfire` expects a Clowder `ClowdEnvironment` resource similar to [this template](bonfire/resources/ephemeral-cluster-clowdenvironment.yaml) to be created for a namespace before it can deploy into it. This `ClowdEnvironment` may have been created by the ephemeral namespace operator, or by a user manually running `bonfire deploy-env`

* When `bonfire deploy` is executed for a namespace, it will attempt to find the ClowdEnvironment associated with that namespace and set the `ENV_NAME` parameter accordingly for all templates it processes. All templates that define a `ClowdApp` resource should set the `environment` mapping in their spec using an `${ENV_NAME}` parameter.

* When `bonfire namespace wait-on-resources` is executed, it follows this logic:
1. Wait for all resources owned by a 'ClowdEnvironment' to appear in the namespace
2. Wait for all the deployments in the namespace to reach 'active' state.
3. Wait for resources owned by a 'ClowdApp' to appear in the namespace
4. Wait for all the deployments in the namespace to reach 'active' state (deployments we already waited on in step 2 are not waited on again)
5. Wait for other resources such as ClowdJobInvocations, CyndiPipelines, XJoinPipelines, etc. to reach a 'ready' state.

## Miscellaneous
### Running a local qontract-server

bonfire is configured to point to the app-sre team's internal GraphQL API by default, but by using env variables you can point to your your own instance of `qontract-server`:

```bash
export QONTRACT_BASE_URL="https://localhost:4000/graphql"
export QONTRACT_USERNAME=myUsername
export QONTRACT_PASSWORD=myPassword
```

For testing/debug purposes, instead of committing changes directly to app-interface, you can run your own local copy of the app-interface API server.

1. Clone https://github.com/app-sre/qontract-server
2. Clone the internal `app-interface` repo

In `qontract-server`, run:
```
npm install yarn
yarn install
yarn build
make bundle APP_INTERFACE_PATH=/path/to/app-interface
LOAD_METHOD=fs DATAFILES_FILE=bundle/bundle.json yarn run server
```

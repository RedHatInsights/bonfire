# bonfire

A CLI tool used to deploy ephemeral environments for testing cloud.redhat.com applications

`bonfire` interacts with a local configuration file or a running instance of [qontract-server](https://github.com/app-sre/qontract-server) (the component that powers the [AppSRE team](https://github.com/app-sre/)'s internal `app-interface` graphql API) to obtain applications' OpenShift templates, process them, and deploy them.

It also interacts with OpenShift to manage the reservation of ephemeral namespaces for testing.

It is meant to be partnered with the [Clowder](https://github.com/RedHatInsights/clowder) operator to spin up an ephemeral environment for testing on either a remote OpenShift cluster or a local k8s cluster.

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
if that cluster has been set up with bonfire's namespace reconciler.

The `bonfire deploy` command can be used as a helpful "1-liner" command to reserve a namespace,
process application configs, apply them into a desired namespace, and wait for them to come up successfully.

The `bonfire process-env` command can be used to print a processed ClowdEnvironment config to stdout.

The `bonfire deploy-env` command can be used as a helpful "1-liner" command to apply a ClowdEnvironment
configuration into a cluster and wait for environment resources to come up successfully.

### Using a local config

To get up and running without needing to contact app-interface's `qontract-server`, you can utilize
a local config file. `bonfire` ships with a [default config](resources/default_config.yaml) that
should be enough to get started for most internal Red Hat employees. An internal repository holds
application configurations for the cloud.redhat.com platform that are valid for use in ephemeral environments.

By default, the configuration file will be stored in `~/.config/bonfire/config.yaml`. You can reset the config to default at any time using `bonfire config write-default`.

You can edit this file to override any app configurations to allow for "local tinkering". If you define an app under the
`apps` key of the config, it will take precedence over that app's configuration that was fetched
using the `appsFile`

### Loading an app's ephemeral config from app-interface

You can also run `bonfire process`/`bonfire deploy` using `--source appsre` which will pull configurations from app-interface.

You'll first need to set proper env variables to interface with your instance of `qontract-server`:

```bash
export QONTRACT_BASE_URL="https://myserver/graphql"
export QONTRACT_USERNAME=myUsername
export QONTRACT_PASSWORD=myPassword
```

If these env vars are not specified, bonfire will attempt to access a local `qontract-server` (see "Setting up a local qontract-server" below)

`bonfire` will query the qontract GraphQL API and read the desired application's deploy configuration.

You can edit the local configuration file (discussed above) if you wish to override any app configurations to allow for "local tinkering". If you define an app under the `apps` key of the config, it will take precedence over that app's configuration that was fetched from app-interface.

### Loading application configs

`bonfire process` relies on a few key pieces of info to process app configs:
1. The application name. This is typically the name of the listed in `app.yaml` in `app-interface`
1. *(applies to `--source=appsre` only)* a 'target env' -- the name of the `app-interface` environment that you want to pull application configs for. An app's config will only be processed if it has a deploy target set up that points to a namespace mapped to this environment (default: "ephemeral")
1. *(optional)* a 'ref env' -- the name of the `app-interface` environment that we want to use in order to set the applications `IMAGE_TAG` values and deploy template ref. This can be useful if you want to deploy applications using ephemeral template parameters, but you want to override the `IMAGE_TAG`/`ref` defined on all apps to use the values found in `prod` or `stage`.
1. Any template refs you wish to override -- in other words, if you want to download a different git hash of an application component's template.
1. Any image tags you wish to override -- in other words, if you want to use a different image tag for just a specific docker image.
1. Any parameters you wish to override -- if you want to set a different template parameter for a specific app.

By default, `bonfire` will dynamically load dependencies that all components of `app` relies on. This requires the `app` to be using the [Clowder](https://github.com/RedHatInsights/clowder) operator and to have the `dependencies` section of the ClowdApp set up.


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

`bonfire` is also used to reserve, release, and reconcile ephemeral namespaces running on our test OpenShift clusters.

The list of ephemeral namespaces is stored in `app-interface`.

The service account that bonfire logs in to the cluster with has a custom role bound to it which allows it to edit namespace labels:

```
---
apiVersion: rbac.authorization.k8s.io/v1
kind: Role
metadata:
  name: namespace-editor
rules:
- apiGroups:
  - ""
  resources:
  - namespaces
  verbs:
  - get
  - list
  - patch
  - update
  - watch
```

This role is bound to the service account in each ephemeral namespace.

Bonfire uses labels to keep track of which namespaces are reserved AND ready. A "ready" namespace is one which has been "wiped clean" and then had a fresh set of base test configurations copied into it.

When a tester is logged in using the proper account, namespace commands can be used such as:

`bonfire namespace reserve` -- find an available namespace and reserve it. By default the TTL is 1 hr.

`bonfire namespace release <namespace>` -- release a namespace reservation

Use `bonfire namespace -h` to see a list of all available namespace commands.

### Namespace reconciler

A separate cron job runs the `bonfire namespace reconcile` command every 2 minutes. This command does the following:

* Checks for any namespaces that are released, but not ready, and "prepares" them by wiping them and copying base test resources into them. After being prepared, the namespace is marked "ready". A namespace is prepared by:
    1. creating an ephemeral `ClowdEnvironment` resource for it, and
    2. copying any secrets defined in the `ephemeral-base` namespace into it
* Checks for any namespaces that are reserved, but do not have an "expires" time set on them yet. This would be a newly-reserved namespace. The reconciler is responsible for applying the "expires time"
* Checks the "expires time" on all reserved namespaces. If any have expired, bonfire will release them and re-prepare them.

### Interactions with Clowder

* For every namespace that `bonfire` prepares, it creates a Clowder `ClowdEnvironment` resource following [this template](https://github.com/RedHatInsights/bonfire/blob/master/bonfire/resources/ephemeral-clowdenvironment.yaml). The name of the environment matches [this format](https://github.com/RedHatInsights/bonfire/blob/master/bonfire/config.py#L16). So, if bonfire prepared a namespace called `ephemeral-01`, then the name of the `ClowdEnvironment` would be `env-ephemeral-01`.

* When `bonfire deploy` is executed for a namespace, it will attempt to find the ClowdEnvironment associated with that namespace and set the `ENV_NAME` parameter accordingly for all templates it processes. All templates that define a `ClowdApp` resource should set the `environment` mapping in their spec using an `${ENV_NAME}` parameter.

* When `bonfire namespace wait-on-resources` is executed, it follows this logic:
1. Wait for all resources owned by a 'ClowdEnvironment' to appear in the namespace
2. Wait for all the deployments in the namespace to reach 'active' state.
3. Wait for resources owned by a 'ClowdApp' to appear in the namespace
4. Wait for all the deployments in the namespace to reach 'active' state (deployments we already waited on in step 2 are not waited on again)


## Miscellaneous
### Running a local qontract-server

For testing/debug purposes, instead of committing changes directly to app-interface, you can run
your own local copy of the app-interface API server.

1. Clone https://github.com/app-sre/qontract-server
2. Clone the internal `app-interface` repo

In `qontract-server`, run:
```
npm install yarn
make bundle APP_INTERFACE_PATH=/path/to/app-interface
LOAD_METHOD=fs DATAFILES_FILE=bundle/bundle.json yarn run server
```

# bonfire

A CLI tool used to deploy ephemeral environments for testing cloud.redhat.com applications

`bonfire` interacts with a running instance of [qontract-server](https://github.com/app-sre/qontract-server) to obtain namespace and application configurations defined in the [AppSRE team](https://github.com/app-sre/)'s internal `app-interface` repository.

It also interacts with OpenShift to manage the reservation of ephemeral namespaces for testing.

It is meant to be partnered with the [Clowder](https://github.com/RedHatInsights/clowder) operator to spin up an ephemeral environment for testing.

## Installation

```bash
pip install -r requirements.txt
pip install .
```

## Loading an app's ephemeral config

You'll first need to set proper env variables to interface with your instance of `qontract-server`:

```bash
export QONTRACT_BASE_URL="https://myserver/graphql"
export QONTRACT_USERNAME=myUsername
export QONTRACT_PASSWORD=myPassword
```

If these env vars are not specified, bonfire will attempt to access a local `qontract-server` (see "Setting up a local qontract-server" below)

You can then use the `bonfire config get` command to obtain the kubernetes configuration of an application defined according to the `app-interface` schema.

`bonfire` will query the qontract GraphQL API and read the desired application's deploy configuration.

`bonfire config get` relies on a few key pieces of info to process an app's config:
1. The application name. This is the name of the `app` in `app-interface`
2. a 'src env' -- the name of the `app-interface` environment that it should pull application configs for. An app's config will only be processed if it has a deploy target set up for this environment (default: "ephemeral")
3. a 'ref env' -- the name of the `app-interface` environment that we want the application's IMAGE_TAG and deploy template to come from. We will use the IMAGE_TAG/template defined on the app's deploy target that matches this environment name.
4. Any template refs you wish to override -- in other words, if you want to download a different git hash of an application component's template.
5. Any image tags you wish to override
6. Whether or not you want to dynamically load dependencies that all components of `app` relies on. This requires the `app` to be using the [Clowder](https://github.com/RedHatInsights/clowder) operator.
1. setting the IMAGE_TAG and git


For example, let's say that we are running a PR check against the `insights-puptoo` service. This service:
* is a member of the `ingress` application.
* the kubernetes deploy manifest for this service resides in the same repo as the code
* every time a PR is opened in this repo, a docker image is built and pushed to `quay.io/myorg/insights-puptoo` with the tag `pr-<git hash>`. The PR opened against the app has commit hash `abc1234`

If we intend to deploy the `ingress` application group into namespace `mynamespace`, using the new template/image of the `insights-puptoo` PR, but using the production template/image for all other components, we could run:

```bash
APP_NAME=ingress
COMPONENT_NAME=insights-puptoo
GIT_COMMIT=pr-abc1234
IMAGE=quay.io/myorg/insights-puptoo
IMAGE_TAG=abc1234
NAMESPACE=mynamespace

bonfire config get \
    --ref-env insights-prod \
    --app $APP_NAME \
    --set-template-ref $COMPONENT_NAME=$GIT_COMMIT \
    --set-image-tag $IMAGE=$IMAGE_TAG \
    --get-dependencies \
    --namespace $NAMESPACE \
    > k8s_resources.json

oc apply -f k8s_resources.json -n $NAMESPACE
```

## Running a local qontract-server

1. Clone https://github.com/app-sre/qontract-server
2. Clone the internal `app-interface` repo

In `qontract-server`, run:
```
npm install yarn
make bundle APP_INTERFACE_PATH=/path/to/app-interface
LOAD_METHOD=fs DATAFILES_FILE=bundle/bundle.json yarn run server
```

## Namespace reservation

`bonfire` is also used to reserve, release, and reconcile ephemeral namespaces running on our test OpenShift clusters.

The list of ephemeral namespaces is stored in `app-interface`.

The service account that bonfire logs in to the cluster has a custom role bound to it which allows it to edit namespace labels:

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

Bonfire uses labels to keep track of which namespaces are reserved AND ready. A "ready" namespace is one which has had a fresh set of base test configurations copied into it.

When a tester is logged in using the proper account, namespace commands can be used such as:

`bonfire namespace reserve` -- find an available namespace and reserve it. By default the TTL is 60min.

`bonfire namespace release <namespace>` -- release a namespace reservation

Use `bonfire namespace -h` to see a list of all available namespace commands.

## Namespace reconciler

A separate cron job runs the `bonfire namespace reconcile` command every 2 minutes. This command does the following:

* Checks for any namespaces that are released, but not ready, and "prepares" them by wiping them and copying base test resources into them. After being prepared, the namespace is marked "ready".
* Checks for any namespaces that are reserved, but do not have an "expires" time set on them yet. This would be a newly-reserved namespace. The reconciler is responsible for applying the "expires time"
* Checks the "expires time" on all reserved namespaces. If any have expired, bonfire will release them and re-prepare them.
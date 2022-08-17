# bonfire

A CLI tool used to deploy ephemeral environments for testing cloud.redhat.com applications

`bonfire` interacts with a running instance of [qontract-server](https://github.com/app-sre/qontract-server) (the component that powers the [AppSRE team](https://github.com/app-sre/)'s internal `app-interface` graphql API) or a local configuration file to obtain applications' OpenShift templates, process them, and deploy them.

`bonfire` interacts with a running instance of [qontract-server](https://github.com/app-sre/qontract-server) (the component that powers the [AppSRE team](https://github.com/app-sre/)'s internal `app-interface` graphql API) to obtain applications' OpenShift templates, process them, and deploy them. A local configuration file allows you to override an application config if you wish.

It also interacts with the [ephemeral namespace operator](https://github.com/RedHatInsights/ephemeral-namespace-operator) to manage the reservation of ephemeral namespaces for testing.

It has special functionality related to the [Clowder operator](https://github.com/RedHatInsights/clowder) and [Frontend operator](https://github.com/RedHatInsights/frontend-operator/) such as auto-deploying ClowdApp dependencies.

# Installation

We'd recommend setting up a virtual environment for bonfire:

```bash
VENV_DIR=~/bonfire_venv
mkdir -p $VENV_DIR
python3 -m venv $VENV_DIR
. $VENV_DIR/bin/activate
pip install crc-bonfire
bonfire --help
```

# Getting Started

One you have `bonfire` installed, the command you are most likely to use is `bonfire deploy`.

If you are on the Red Hat VPN, `bonfire` will communicate with an internal instance of the App-SRE team's `qontract-server` API. You need to use `oc login` to log in to the ephemeral cluster.

Once logged in, you should be able to type `bonfire deploy advisor`

This will cause `bonfire` to do the following:
1. reserve a namespace
2. fetch the templates for all components in the 'advisor' app and process them. By default, bonfire will look up the template and commit hash using the 'main'/'master' branch of each component defined in the app. It will look up the git commit hash for this branch and automatically set the `IMAGE_TAG` parameter passed to the templates. 
3. if ClowdApp resources are found, figure out which additional ClowdApps to fetch and process
4. apply all the processed template resources into your reserved namespace
5. wait for all the resources to reach a 'ready' state

Run `bonfire namespace list --mine` and you will see your namespace.

Switch into that namespace with `oc project <NAMESPACE>`

Run `oc get clowdapp` in your namespace and you should see several ClowdApps have been deployed.

If you want to to extend the time you have to work with your namespace, use `bonfire namespace extend <NAMESPACE>`

When you are done working with your namespace, type `bonfire namespace release <NAMESPACE>` to instruct the ephemeral namespace operator to delete your reservation.

The deploy command is an 'all-in-one' command that ties together 4 steps:
1. `bonfire namespace reserve` to reserve a namespace
2. `bonfire process` to fetch and process app templates
3. `oc apply` to apply the processed app templates into the namespace
4. `bonfire namespace wait-on-resources <NAMESPACE>` to wait on all resources in the namespace to reach 'ready' state

# Commonly Used CLI Options

As always, don't forget about `--help` -- there are several more options than what we will describe below -- remember that `--help` is there to help you!

## Reserving Namespaces

* `--duration <time>` -- by default the reservation duration is `1h` -- use this to increase the duration of your reservation.
* `--pool <pool>` -- different namespace pools are set up to provide different test environment configurations. Use this option to select a non-default pool.

## Deploying/Processing

* `--frontends=true` -- by default, bonfire will not deploy Frontend resources. Use this flag to enable the deployment of app frontends.
* `--set-image-tag <image uri>=<tag>` -- use this to change the image tag of a container image that appears in your templates. This does a search/replace for all occurences of `<image uri>` and sets the tag to be `<tag>`
* `--target-env` -- this changes which deploy target `bonfire` looks up to determine the parameters to apply when processing app templates. By default, the target env is set to `insights-ephemeral`
* `--ref-env` -- this changes which deploy target `bonfire` looks up to determine the git ref to fetch for your app configuration. For example, using `--ref-env insights-stage` would cause bonfire to deploy the stage git ref of your app and `--ref-env insights-production` would cause bonfire to deploy the production git ref of your app. If a target matching the environment is not found, `bonfire` defaults back to deploying the 'main'/'master' branch.
* `--set-template-ref <component>=<ref>` -- use this to change the git ref deployed for just a single component.
* `--set-parameter <component>/<name>=<value>` -- use this to set a parameter value on a specific component's template.
* `--optional-deps-method <hybrid|all|none>` -- change the way that bonfire processes ClowdApp optional dependencies (see "Dependency Processing" section below)


# Configuration Details 

When running `bonfire process`/`bonfire deploy`, by default the app-sre team's internal GraphQL API server is used. `bonfire` will query the GraphQL API and read the application's deploy configuration.

*NOTE*: You need to be on the internal VPN in order to access the default GraphQL API URL.

`bonfire` relies on a few key pieces of info to process app configs:

1. The application name. This is typically the name of the listed in `app.yaml` in `app-interface`
2. A 'target env' -- the name of the `app-interface` environment that bonfire looks at to determine the parameters to apply when processing app templates. An app's config will only be processed if it has a deploy target set up that is pointing to a namespace in this environment (default: "ephemeral")
3. A 'ref env' -- the name of the `app-interface` environment that we want to use in order to figure out which git ref of the components to deploy and which `IMAGE_TAG` value to set. By default, none is set which causes bonfire to use the 'main'/'master' git branch for all components.
4. Any template refs you wish to override (optional)
5. Any image tags you wish to override (optional)
6. Any parameters you wish to override (optional)

By default, if app components use `ClowdApp` resources in their templates, then `bonfire` will dynamically load dependencies (see "Dependency Processing" section below)

## Using a local config

`bonfire` ships with a [default config](bonfire/resources/default_config.yaml) that should be enough to get started for most internal Red Hat employees.

By default, the configuration file will be stored in `~/.config/bonfire/config.yaml`.

If you wish to override any app configurations, you can edit your local configuration file by typing `bonfire config edit`. If you define an app under the `apps` key of the config, it will take precedence over that app's configuration that was fetched from app-interface. Note that defining a local app configuration here will replace the configuration defined in app-interface for ALL components within that app.

You can reset the config to default at any time using `bonfire config write-default`.

## Local config examples

### Deploying local repo changes

If you wanted to test out some changes you're making to an app but you have not yet pushed these changes to a git repo, the local config could look similar to:

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

By default, `bonfire` will run `git rev-parse` to determine the current working commit hash in your repo folder, and this determines what IMAGE_TAG to set when the template is deployed. This means you would need to have a valid container image pushed for this commit hash. However, you can use `--set-image-tag` or `--set-parameter` to override the image you wish to use during the deployment.

### Deploying changes changes in a remote git branch

If you wanted to deploy changes to your app that you were working on which have been pushed to a PR/branch, the local config could look similar to:

```
apps:
- name: my_app
  components:
    - name: service
      host: github
      repo: MyOrg/MyRepo
      ref: my_branch
      path: /clowdapp.yaml
```

- Where **host** set to `github` or `gitlab` indicates where the repo is hosted
- Where **repo** indicates the `OrganizationName/RepoName`
- Where **path** specifies the relative path to your ClowdApp template file in your git repo
- Where **ref** specifies the branch or commit of the repo you want to deploy

By default, bonfire will use the latest commit hash found at the specified git ref to determine what IMAGE_TAG pass on to the deployment templates.

### Interactions with Clowder

* `bonfire` expects a Clowder `ClowdEnvironment` resource to be created for a namespace before it can deploy into it. This `ClowdEnvironment` is already created by the ephemeral namespace operator.

* When `bonfire deploy` is executed for a namespace, it will attempt to find the ClowdEnvironment associated with that namespace and set the `ENV_NAME` parameter accordingly for all templates it processes. All templates that define a `ClowdApp` resource should set the `environment` mapping in their spec using a parameter named `${ENV_NAME}`.

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

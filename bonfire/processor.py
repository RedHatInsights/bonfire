import copy
import json
import logging
import re
import traceback
from typing import Optional
import uuid
from pathlib import Path

import yaml
from cached_property import cached_property
from ocviapy import process_template
from sh import ErrorReturnCode

import bonfire.config as conf
from bonfire.openshift import whoami
from bonfire.utils import AppOrComponentSelector, FatalError, RepoFile
from bonfire.utils import get_clowdapp_dependencies
from bonfire.utils import get_dependencies as utils_get_dependencies


log = logging.getLogger(__name__)


def _process_template(*args, **kwargs):
    # run process_template with prettier error handling
    try:
        processed_template = process_template(*args, **kwargs)
    except ErrorReturnCode as err:
        raise FatalError(f"'oc process' command failed: {err.stderr}")
    return processed_template


def _get_trusted_config(data: dict, key1: str, key2: str, path: str, component_params: dict):
    """
    Check for presence of a trusted param being used for the value.

    A trusted parameter is defined as:
    1. matching the expected regex pattern
    2. the parameter value is set in the component's deploy config

    Returns True if we determine this is a trusted value
    """
    regex = conf.TRUSTED_RESOURCE_REGEX.get(key1, {}).get(key2)

    if not regex or not isinstance(regex, str):
        raise ValueError("not able to find conf.TRUSTED_RESOURCE_REGEX[{key1}][{key2}]")

    value = data.get(key1, {}).get(key2)
    if value:
        match = False
        in_params = False

        match = re.match(regex, str(value))
        if match and match.groups()[0] in component_params:
            in_params = True

        log.debug(
            "value '%s', regex r'%s', matches=%s, in params=%s",
            value,
            regex,
            bool(match),
            in_params,
        )

        if match and in_params:
            return value
        else:
            log.debug("deleted untrusted config at '%s.%s.%s'", path, key1, key2)
            return None


def _remove_untrusted_configs(
    data,
    params,
    path="",
    current_dict=None,
):
    """
    Locate configurations within 'data' and remove them if not trusted.

    Checks to see if resource configurations match the regex specified in
    conf.TRUSTED_RESOURCE_REGEX

    Also checks that if a request is defined, a corresponding limit is defined
    for the same resource and vice-versa.
    """
    if path.endswith(".resources"):
        resources = current_dict["resources"]
        cpu_request = _get_trusted_config(resources, "requests", "cpu", path, params)
        cpu_limit = _get_trusted_config(resources, "limits", "cpu", path, params)
        mem_request = _get_trusted_config(resources, "requests", "memory", path, params)
        mem_limit = _get_trusted_config(resources, "limits", "memory", path, params)

        if any([cpu_request, cpu_limit]) and not all([cpu_request, cpu_limit]):
            log.debug("'%s' cpu config needs both request and limit, removing cpu config", path)
            cpu_request = None
            cpu_limit = None
        if any([mem_request, mem_limit]) and not all([mem_request, mem_limit]):
            log.debug("'%s' mem config needs both request and limit, removing mem config", path)
            mem_request = None
            mem_limit = None

        # if val is null, omit it from final dict
        if not cpu_request:
            del resources["requests"]["cpu"]
        if not cpu_limit:
            del resources["limits"]["cpu"]
        if not mem_request:
            del resources["requests"]["memory"]
        if not mem_limit:
            del resources["limits"]["memory"]

    elif isinstance(data, dict):
        for key, value in copy.copy(data).items():
            _remove_untrusted_configs(value, params, path + f".{key}", current_dict=data)

    elif isinstance(data, list):
        for index, value in enumerate(copy.copy(data)):
            _remove_untrusted_configs(value, params, path + f"[{index}]")


def _remove_untrusted_configs_for_template(template, params):
    """
    Removes untrusted configurations within the template.

        A configuration is trusted if:
        1. the value is defined using a template parameter
        2. the parameter follows the proper syntax convention
        3. the parameter is defined on the component in its deployment config

    Checks template to see if any resources of kind listed in 'config.TRUSTED_CHECK_KINDS'
    are found. If so, analyzes the config on those resources to see if any need to be removed.
    """
    for obj in template.get("objects", []):
        kind = obj.get("kind")
        if kind not in conf.TRUSTED_CHECK_KINDS:
            continue

        name = obj.get("metadata", {}).get("name")
        log.debug("checking resources on %s '%s'", kind, name)
        _remove_untrusted_configs(obj, params)


def _remove_dependency_config(items):
    for i in items:
        if i["kind"] != "ClowdApp":
            continue

        if i["spec"].get("dependencies"):
            del i["spec"]["dependencies"]
            log.debug("removed dependencies from ClowdApp '%s'", i["metadata"]["name"])
        if i["spec"].get("optionalDependencies"):
            del i["spec"]["optionalDependencies"]
            log.debug("removed optionalDependencies from ClowdApp '%s'", i["metadata"]["name"])


def _set_replicas(items):
    for i in items:
        if i["kind"] != "ClowdApp":
            continue

        app_name = i.get("metadata", {}).get("name")
        # 'pods' is a legacy field in the ClowdApp spec
        deployments = i["spec"].get("deployments", []) or i["spec"].get("pods", [])
        for d in deployments:
            dep_name = d.get("name")
            # minReplicas is deprecated in this pr
            # https://github.com/RedHatInsights/clowder/pull/686/files
            if "minReplicas" in d and d["minReplicas"] > 1:
                d["minReplicas"] = 1
                log.debug(
                    "set minReplicas to '1' on ClowdApp '%s' deployment '%s'", app_name, dep_name
                )
            if "replicas" in d and d["replicas"] > 1:
                d["replicas"] = 1
                log.debug(
                    "set replicas to '1' on ClowdApp '%s' deployment '%s'", app_name, dep_name
                )


def _check_for_disabled(items):
    for item in items:
        kind = item.get("kind", "").lower()
        name = item.get("metadata", {}).get("name")
        if kind in ["clowdapp", "clowdenvironment"]:
            if item.get("spec", {}).get("disabled"):
                log.warning(
                    "%s/%s has 'disabled: true' configured, Clowder will ignore it",
                    kind,
                    name,
                )


def process_clowd_env(target_ns, quay_user, env_name, template_path, local=True):
    log.info("processing ClowdEnvironment")

    env_template_path = Path(template_path if template_path else conf.DEFAULT_CLOWDENV_TEMPLATE)

    if not env_template_path.exists():
        raise FatalError("ClowdEnvironment template file does not exist: %s", env_template_path)

    with env_template_path.open() as fp:
        template_data = yaml.safe_load(fp)

    params = dict()
    params["ENV_NAME"] = env_name
    # TODO: revisit need for below param once FEO has a more developed config management system
    params["FRONTEND_CONTEXT_NAME"] = env_name
    if quay_user:
        quay_user = quay_user.replace("_", "-")
        params["PULL_SECRET_NAME"] = f"{quay_user}-pull-secret"
    if target_ns:
        params["NAMESPACE"] = target_ns

    processed_template = _process_template(template_data, params=params, local=local)

    if not processed_template.get("items"):
        raise FatalError("Processed ClowdEnvironment template has no items")

    _check_for_disabled(processed_template["items"])

    return processed_template


def process_iqe_cji(
    clowd_app_name,
    debug=False,
    marker="",
    filter="",
    env="clowder_smoke",
    image_tag="",
    cji_name=None,
    template_path=None,
    requirements="",
    requirements_priority="",
    test_importance="",
    plugins="",
    local=True,
    selenium=False,
    parallel_enabled="",
    parallel_worker_count="",
    rp_args="",
    ibutsu_source="",
    custom_env_vars=None,
):
    log.info("processing IQE ClowdJobInvocation")

    template_path = Path(template_path if template_path else conf.DEFAULT_IQE_CJI_TEMPLATE)

    if not template_path.exists():
        raise FatalError("CJI template file does not exist: %s", template_path)

    with template_path.open() as fp:
        template_data = yaml.safe_load(fp)

    params = dict()
    params["DEBUG"] = json.dumps(debug)
    params["MARKER"] = marker
    params["FILTER"] = filter
    params["ENV_NAME"] = env
    params["IMAGE_TAG"] = image_tag
    params["PLUGINS"] = plugins
    params["NAME"] = cji_name or f"iqe-{str(uuid.uuid4()).split('-')[0]}"
    params["APP_NAME"] = clowd_app_name
    params["REQUIREMENTS"] = requirements
    params["REQUIREMENTS_PRIORITY"] = requirements_priority
    params["TEST_IMPORTANCE"] = test_importance
    params["DEPLOY_SELENIUM"] = json.dumps(selenium)
    params["PARALLEL_ENABLED"] = parallel_enabled
    params["PARALLEL_WORKER_COUNT"] = parallel_worker_count
    params["RP_ARGS"] = rp_args
    params["IBUTSU_SOURCE"] = ibutsu_source

    processed_template = _process_template(template_data, params=params, local=local)

    if not processed_template.get("items"):
        raise FatalError("Processed CJI template has no items")

    if custom_env_vars:
        for resource in processed_template["items"]:
            if resource.get("kind") == "ClowdJobInvocation":
                env = resource.get("spec", {}).get("testing", {}).get("iqe", {}).get("env", [])
                for var_name, var_value in custom_env_vars.items():
                    env.append({"name": str(var_name), "value": str(var_value)})

    return processed_template


def process_reservation(name, requester, duration, pool=None, template_path=None, local=True):
    log.info("processing namespace reservation")

    template_path = Path(template_path if template_path else conf.DEFAULT_RESERVATION_TEMPLATE)

    if not template_path.exists():
        raise FatalError("Reservation template file does not exist: %s", template_path)

    with template_path.open() as fp:
        template_data = yaml.safe_load(fp)

    params = dict()

    params["NAME"] = name if name else f"bonfire-reservation-{str(uuid.uuid4()).split('-')[0]}"
    params["DURATION"] = duration

    if requester is None:
        try:
            requester = whoami()
        except Exception:
            log.info("whoami returned an error - setting requester to 'bonfire'")  # minikube
            requester = "bonfire"

    params["REQUESTER"] = requester
    params["POOL"] = pool if pool else "default"

    processed_template = _process_template(template_data, params=params, local=local)

    if not processed_template.get("items"):
        raise FatalError("Processed Reservation template has no items")

    return processed_template


class ProcessedComponent:
    def __init__(self, name, items, deps_handled=False, optional_deps_handled=False):
        self.name = name
        self.items = items
        self.deps_handled = deps_handled
        self.optional_deps_handled = optional_deps_handled


def _should_remove(
    remove_option: AppOrComponentSelector,
    no_remove_option: AppOrComponentSelector,
    app_name: str,
    component_name: str,
    default: bool = True,
) -> bool:
    # 'should_remove' evaluates to true when:
    #   "--remove-option all" is set
    #   "--remove-option all --no-remove-option x" is set and app/component does NOT match 'x'
    #   "--no-remove-option all --remove-option x" is set and app/component matches 'x'
    #   "--no-remove-option x --remove-option y" and app/component matches 'y'
    #   "--remove-option x --no-remove-option y" and app/component matches 'x'
    #   none of the setting permutations are matched and default=True
    remove_for_all_no_exceptions = remove_option.select_all and no_remove_option.empty
    remove_for_none_no_exceptions = no_remove_option.select_all and remove_option.empty

    log.debug(
        "should_remove: app_name: %s, component_name: %s, remove_option: %s, no_remove_option: %s",
        app_name,
        component_name,
        remove_option,
        no_remove_option,
    )

    if remove_for_none_no_exceptions:
        return False
    if remove_for_all_no_exceptions:
        return True
    if remove_option.select_all:
        if app_name in no_remove_option.apps or component_name in no_remove_option.components:
            return False
        return True
    if no_remove_option.select_all:
        if app_name in remove_option.apps or component_name in remove_option.components:
            return True
        return False
    if component_name in no_remove_option.components:
        return False
    if component_name in remove_option.components:
        return True
    if app_name in no_remove_option.apps:
        return False
    if app_name in remove_option.apps:
        return True

    return default


class TemplateProcessor:
    @staticmethod
    def _parse_app_names(app_names):
        parsed_app_names = set()
        for app_name in app_names:
            # backward compatibility for specifying app names with comma,separated,values
            for entry in app_name.split(","):
                parsed_app_names.add(entry)
        return parsed_app_names

    @staticmethod
    def _parse_exclude_components(exclude_components):
        """Parse exclude_components which can be None, a string, or a list."""
        if exclude_components is None:
            return None

        if isinstance(exclude_components, str):
            # Handle comma-separated string
            return [
                component.strip()
                for component in exclude_components.split(",")
                if component.strip()
            ]

        # Assume it's already a list
        return list(exclude_components)

    @staticmethod
    def _find_dupe_components(components_for_app):
        """Make sure no component is listed more than once across all apps."""
        for app_name, components in components_for_app.items():
            components_for_other_apps = copy.copy(components_for_app)
            del components_for_other_apps[app_name]

            for component in components:
                found_in = [app_name]
                for other_app_name, other_components in components_for_other_apps.items():
                    if component in other_components:
                        found_in.append(other_app_name)
                if len(found_in) > 1:
                    raise FatalError(
                        f"component '{component}' is not unique, found in apps: {found_in}"
                    )

    @staticmethod
    def _validate_component_dict(all_components, data, name):
        # Translate deprecated "APP_NAME/COMPONENT_NAME" path syntax
        updated_data = {}

        # Max number of items we expect separated by '/' in the CLI option value
        max_len = 2
        if name == "--set-parameter":
            max_len = 3

        for path, value in data.items():
            split = path.split("/")
            if len(split) == max_len:
                # first item was an app name
                new_path = split[1:]
            elif len(split) == max_len - 1:
                # first item was a component name
                new_path = split[0:]
            else:
                raise FatalError(f"invalid format for {name}: {path}={value}")

            component_name = new_path[0]

            # Make sure component name actually exists in app config
            if component_name not in all_components:
                raise FatalError(
                    f"component given for {name} not found in app config: {component_name}"
                )

            key = "/".join(new_path)
            updated_data[key] = value

        # Update the paths
        data.clear()
        for key, val in updated_data.items():
            data[key] = val

    @staticmethod
    def _validate_component_list(all_components, data, name):
        for component_name in data:
            if component_name not in all_components:
                raise FatalError(
                    f"component given for {name} not found in app config: {component_name}"
                )

    @staticmethod
    def _validate_app_list(all_apps, app_list, name):
        for app_name in app_list:
            if app_name not in all_apps:
                raise FatalError(f"app given for {name} not found in app config: {app_name}")

    def _validate_selector_options(self, all_apps, all_components, data, name):
        if isinstance(data, AppOrComponentSelector):
            self._validate_app_list(all_apps, data.apps, name)
            self._validate_component_list(all_components, data.components, name)
        elif isinstance(data, dict):
            self._validate_component_dict(all_components, data, name)
        else:
            self._validate_component_list(all_components, data, name)

    @cached_property
    def _components_for_app(self):
        components_for_app = {}

        for app_name, app_cfg in self.apps_config.items():
            # Check that each app has required keys
            required_keys = ["name", "components"]
            missing_keys = [k for k in required_keys if k not in app_cfg]
            if missing_keys:
                raise FatalError(f"app '{app_name}' is missing required keys: {missing_keys}")

            # Check that each app name is unique
            app_name = app_cfg["name"]
            if app_name in components_for_app:
                raise FatalError(f"app with name '{app_name}' is not unique")
            components_for_app[app_name] = []

            for component in app_cfg.get("components", []):
                # Check that each component in an app has required keys
                required_keys = ["name", "host", "repo", "path"]
                missing_keys = [k for k in required_keys if k not in component]
                if missing_keys:
                    raise FatalError(
                        f"component on app {app_name} is missing required keys: {missing_keys}"
                    )
                comp_name = component["name"]
                components_for_app[app_name].append(comp_name)

        return components_for_app

    def _validate(self):
        """
        Validate app configurations and options passed to the TemplateProcessor

        1. Check that each app has required keys
        2. Check that each app name is unique
        3. Check that each component in an app has required keys
        4. Check that each component is a unique name across the whole config
        5. Check that CLI params requiring a component use a valid component name
        """
        # Check that each component name is unique across the whole config
        self._find_dupe_components(self._components_for_app)

        # Check that CLI params requiring a component use a valid component name or app name
        all_components = []
        for _, app_components in self._components_for_app.items():
            all_components.extend(app_components)

        all_apps = list(self._components_for_app.keys())

        self._validate_selector_options(
            all_apps, all_components, self.template_ref_overrides, "--set-template-ref"
        )
        self._validate_selector_options(
            all_apps, all_components, self.param_overrides, "--set-parameter"
        )

        self._validate_selector_options(
            all_apps, all_components, self.remove_resources, "--remove-resources"
        )
        self._validate_selector_options(
            all_apps, all_components, self.no_remove_resources, "--no-remove-resources"
        )
        self._validate_selector_options(
            all_apps, all_components, self.remove_dependencies, "--remove-dependencies"
        )
        self._validate_selector_options(
            all_apps, all_components, self.no_remove_dependencies, "--no-remove-dependencies"
        )

        # 'all' is a valid component keyword for this option below
        all_components.append("all")
        self._validate_selector_options(
            all_apps, all_components, self.component_filter, "--component"
        )

    def __init__(
        self,
        apps_config,
        app_names,
        get_dependencies,
        optional_deps_method,
        image_tag_overrides,
        template_ref_overrides,
        param_overrides,
        clowd_env,
        remove_resources: AppOrComponentSelector,
        no_remove_resources: AppOrComponentSelector,
        remove_dependencies: AppOrComponentSelector,
        no_remove_dependencies: AppOrComponentSelector,
        single_replicas,
        component_filter,
        local,
        frontends,
        namespace=None,
        exclude_components=None,
    ):
        self.apps_config = apps_config
        self.requested_app_names = self._parse_app_names(app_names)
        self.get_dependencies = get_dependencies
        self.optional_deps_method = optional_deps_method
        self.image_tag_overrides = image_tag_overrides
        self.template_ref_overrides = template_ref_overrides
        self.param_overrides = param_overrides
        self.clowd_env = clowd_env
        self.remove_resources = remove_resources
        self.no_remove_resources = no_remove_resources
        self.remove_dependencies = remove_dependencies
        self.no_remove_dependencies = no_remove_dependencies
        self.single_replicas = single_replicas
        self.component_filter = component_filter
        self.local = local
        self.frontends = frontends
        self.namespace = namespace
        self.exclude_components = self._parse_exclude_components(exclude_components)

        self._validate()

        self.k8s_list = {
            "kind": "List",
            "apiVersion": "v1",
            "metadata": {},
            "items": [],
        }

        self.processed_components = {}

        self.counter = {"image_tag_overrides": {}}
        for image in self.image_tag_overrides:
            self.counter["image_tag_overrides"][image] = 0

    def _get_app_config(self, app_name):
        if app_name not in self.apps_config:
            raise FatalError(f"app {app_name} not found in apps config")
        return self.apps_config[app_name]

    def _get_component_config(self, component_name):
        for _, app_cfg in self.apps_config.items():
            for component in app_cfg["components"]:
                if component["name"] == component_name:
                    return component
        else:
            raise FatalError(f"component with name '{component_name}' not found")

    def _sub_image_tags(self, items):
        content = json.dumps(items)
        for image, image_tag in self.image_tag_overrides.items():
            # easier to just re.sub on a whole string
            content, subs = re.subn(rf"{image}:[-\w\.]+", rf"{image}:{image_tag}", content)
            if subs:
                self.counter["image_tag_overrides"][image] += subs
                log.info("replaced %d occurence(s) of image tag for image '%s'", subs, image)
        return json.loads(content)

    def _sub_ref(self, current_component_name, repo_file):
        for component_name, value in self.template_ref_overrides.items():
            if current_component_name == component_name:
                log.info(
                    "component: '%s' overriding template ref to '%s'",
                    component_name,
                    value,
                )
                repo_file.ref = value

    def _sub_params(self, current_component_name, params):
        for path, value in self.param_overrides.items():
            split = path.split("/")
            if len(split) == 2:
                component_name, param_name = split
            else:
                raise FatalError(f"invalid format for --set-parameter: {path}={value}")

            if current_component_name == component_name:
                log.info(
                    "component: '%s' overriding param '%s' to '%s'",
                    component_name,
                    param_name,
                    value,
                )
                params[param_name] = value

    def _get_app_for_component(self, component_name):
        for app_name, components in self._components_for_app.items():
            if component_name in components:
                return app_name

    def _get_component_items(self, component_name):
        component = self._get_component_config(component_name)
        try:
            rf = RepoFile.from_config(component)
            # override template ref if requested
            self._sub_ref(component_name, rf)
            log.debug(
                "component: '%s' fetching template using git ref '%s'", component_name, rf.ref
            )
            commit, template_content = rf.fetch()
        except Exception as err:
            log.error("failed to fetch template file for %s", component_name)
            log.debug(traceback.format_exc())
            raise FatalError(err)

        try:
            template = yaml.safe_load(template_content)
        except Exception as err:
            log.exception("failed to parse template content to yaml for %s", component_name)
            raise FatalError(err)

        # fetch component parameters
        params = component.get("parameters", {})

        # set IMAGE_TAG on this component only if it is currently unset
        if "IMAGE_TAG" not in params:
            params["IMAGE_TAG"] = commit[:7]

        # set NAMESPACE on this component only if it is current unset
        if "NAMESPACE" not in params:
            params["NAMESPACE"] = self.namespace

        # always override ENV_NAME
        params["ENV_NAME"] = self.clowd_env
        # TODO: revisit need for below param once FEO has a more developed config management system
        params["FRONTEND_CONTEXT_NAME"] = self.clowd_env

        # override other specific parameters on this component if requested by user at runtime
        self._sub_params(component_name, params)
        log.debug("parameters for component '%s': %s", component_name, params)

        # evaluate --remove-resources/--no-remove-resources
        app_name = self._get_app_for_component(component_name)

        # if entire app or component is marked trusted, do not remove any resources
        should_remove_resources = False
        if app_name in conf.TRUSTED_APPS:
            log.debug("should_remove: app '%s' listed in trusted apps", app_name)
        elif component_name in conf.TRUSTED_COMPONENTS:
            log.debug("should_remove: component '%s' listed in trusted components", component_name)
        else:
            should_remove_resources = _should_remove(
                self.remove_resources,
                self.no_remove_resources,
                app_name,
                component_name,
                default=True,
            )
        log.debug("should_remove_resources evaluates to %s", should_remove_resources)
        if should_remove_resources:
            _remove_untrusted_configs_for_template(template, params)

        # process the template
        new_items = _process_template(template, params, self.local)["items"]

        # override the tags for all occurences of an image if requested
        new_items = self._sub_image_tags(new_items)

        # evaluate --remove-dependencies/--no-remove-dependencies
        should_remove_deps = _should_remove(
            self.remove_dependencies,
            self.no_remove_dependencies,
            app_name,
            component_name,
            default=False,
        )
        log.debug("should_remove_dependencies evaluates to %s", should_remove_deps)
        if should_remove_deps:
            _remove_dependency_config(new_items)

        if self.single_replicas:
            _set_replicas(new_items)

        _check_for_disabled(new_items)

        return new_items

    @staticmethod
    def _frontend_found(items):
        frontend_found = False
        for item in items:
            kind = item.get("kind").lower()
            ver = item.get("apiVersion").lower()
            if kind == "frontend" and ver.startswith("cloud.redhat.com"):
                frontend_found = True
                break
        return frontend_found

    def _should_fetch_optional_deps(self, app_name, component_name, in_recursion):
        fetch_optional_deps = False
        if self.optional_deps_method == "all":
            fetch_optional_deps = True
            log.debug("parsing optionalDependencies for component '%s'", component_name)
        if (
            self.optional_deps_method == "hybrid"
            and not in_recursion
            and app_name in self.requested_app_names
        ):
            # in hybrid mode, only fetch optionalDependencies on a ClowdApp if it was part of
            # an app group that the user specifically requested to deploy on the CLI
            #
            # 'in_recursion' is used to help us determine if we're currently parsing dependencies
            # for an app group the user requested on the CLI, or if we've arrived at this code path
            # via parsing of the original app's dependencies/optionalDependencies
            fetch_optional_deps = True
            log.debug(
                "parsing optionalDependencies for component '%s' (a member of app group '%s')",
                component_name,
                app_name,
            )

        if not fetch_optional_deps:
            log.debug(
                "ignoring optionalDependencies for component '%s'",
                component_name,
            )

        return fetch_optional_deps

    def _add_dependencies_to_config(self, app_name, processed_component, in_recursion):
        component_name = processed_component.name
        items = processed_component.items

        all_dependencies = set()

        if processed_component.deps_handled:
            log.debug("already handled dependencies for component '%s'", component_name)
        else:
            # check ClowdApp dependencies
            dependencies_for_app = get_clowdapp_dependencies(items)
            for _, deps in dependencies_for_app.items():
                all_dependencies = all_dependencies.union(deps)
            # check bonfire.dependencies annotations
            all_dependencies.update(utils_get_dependencies(items))
            processed_component.deps_handled = True

        if processed_component.optional_deps_handled:
            log.debug("already handled optionalDependencies for component '%s'", component_name)
        elif self._should_fetch_optional_deps(app_name, component_name, in_recursion):
            # check ClowdApp optionalDependencies
            dependencies_for_app = get_clowdapp_dependencies(items, optional=True)
            for _, deps in dependencies_for_app.items():
                all_dependencies = all_dependencies.union(deps)
            processed_component.optional_deps_handled = True

        for component_name in all_dependencies:
            self._process_component(component_name, app_name, in_recursion=True)

    def _handle_dependencies(self, app_name, processed_component, in_recursion):
        items = processed_component.items
        if self._frontend_found(items):
            for name in conf.AUTO_ADDED_FRONTEND_DEPENDENCIES:
                if name not in self.processed_components:
                    log.info("auto-adding %s as dependency for frontend resource", name)
                    self._process_component(name, app_name, in_recursion)
        self._add_dependencies_to_config(app_name, processed_component, in_recursion)

    def _process_component(self, component_name, app_name, in_recursion):
        if component_name in self.processed_components:
            log.debug("template already processed for component '%s'", component_name)
            processed_component = self.processed_components[component_name]
        else:
            log.info("--> processing component %s", component_name)
            items = self._get_component_items(component_name)

            # ignore frontends if we're not supposed to deploy them
            if self._frontend_found(items) and not self.frontends:
                log.info(
                    "ignoring component %s, user opted to disable frontend deployments",
                    component_name,
                )
                items = []

            processed_component = ProcessedComponent(component_name, items)
            self.processed_components[component_name] = processed_component
            reason = self._component_skip_check(component_name)
            if reason:
                log.info("skipping component '%s', %s", component_name, reason)
            else:
                self.k8s_list["items"].extend(items)

        if self.get_dependencies:
            # recursively process to add config for dependent apps to self.k8s_list
            self._handle_dependencies(app_name, processed_component, in_recursion)

    def _process_app(self, app_name):
        log.info("processing app '%s'", app_name)
        app_cfg = self._get_app_config(app_name)
        for component in app_cfg["components"]:
            component_name = component["name"]
            log.debug("app '%s' has component '%s'", app_name, component_name)
            self._process_component(component_name, app_name, in_recursion=False)

    def _component_skip_check(self, component_name) -> Optional[str]:
        skip_reasons = [
            (
                self.component_filter and component_name not in self.component_filter,
                "not found in --component filter",
            ),
            (
                self.exclude_components and component_name in self.exclude_components,
                "found in --exclude-components list",
            ),
        ]

        for condition, reason in skip_reasons:
            if condition:
                return reason
        return None

    def process(self, app_names=None):
        if not app_names:
            app_names = self.requested_app_names

        for app_name in app_names:
            self._process_app(app_name)

        images_with_no_subs = []
        for image, subs in self.counter["image_tag_overrides"].items():
            if subs == 0:
                images_with_no_subs.append(image)
        if images_with_no_subs:
            raise FatalError(
                f"""Could not find the following image names in any templates:
                {images_with_no_subs}. Check the arguments to --set-image-tag
                and try again."""
            )

        return self.k8s_list

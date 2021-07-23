import copy
import logging
import json
import yaml
import re
import uuid

from pathlib import Path

import bonfire.config as conf
from bonfire.openshift import process_template
from bonfire.utils import RepoFile

log = logging.getLogger(__name__)


def _remove_resource_config(items):
    for i in items:
        if i["kind"] != "ClowdApp":
            continue

        removed = False
        for d in i["spec"].get("deployments", []):
            if "resources" in d["podSpec"]:
                del d["podSpec"]["resources"]
                removed = True
        for p in i["spec"].get("pods", []):
            if "resources" in p:
                del p["resources"]
                removed = True

        if removed:
            log.debug("removed resources from ClowdApp '%s'", i["metadata"]["name"])


def _set_replicas(items):
    for i in items:
        if i["kind"] != "ClowdApp":
            continue

        updated = False
        for d in i["spec"].get("deployments", []):
            if "minReplicas" in d["podSpec"] and d["podSpec"]["minReplicas"] > 1:
                d["podSpec"]["minReplicas"] = 1
                updated = True
        for p in i["spec"].get("pods", []):
            if "minReplicas" in p and p["minReplicas"] > 1:
                p["minReplicas"] = 1
                updated = True

        if updated:
            log.debug("set replicas to '1' on ClowdApp '%s'", i["metadata"]["name"])


def process_clowd_env(target_ns, quay_user, env_name, template_path):
    log.info("processing ClowdEnvironment")

    env_template_path = Path(template_path if template_path else conf.DEFAULT_CLOWDENV_TEMPLATE)

    if not env_template_path.exists():
        raise ValueError("ClowdEnvironment template file does not exist: %s", env_template_path)

    with env_template_path.open() as fp:
        template_data = yaml.safe_load(fp)

    params = dict()
    params["ENV_NAME"] = env_name
    if quay_user:
        quay_user = quay_user.replace("_", "-")
        params["PULL_SECRET_NAME"] = f"{quay_user}-pull-secret"
    if target_ns:
        params["NAMESPACE"] = target_ns

    processed_template = process_template(template_data, params=params)

    if not processed_template.get("items"):
        raise ValueError("Processed ClowdEnvironment template has no items")

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
):
    log.info("processing IQE ClowdJobInvocation")

    template_path = Path(template_path if template_path else conf.DEFAULT_IQE_CJI_TEMPLATE)

    if not template_path.exists():
        raise ValueError("CJI template file does not exist: %s", template_path)

    with template_path.open() as fp:
        template_data = yaml.safe_load(fp)

    params = dict()
    params["DEBUG"] = str(debug).lower()
    params["MARKER"] = marker
    params["FILTER"] = filter
    params["ENV_NAME"] = env
    params["IMAGE_TAG"] = image_tag
    params["NAME"] = cji_name or f"iqe-{str(uuid.uuid4()).split('-')[0]}"
    params["APP_NAME"] = clowd_app_name

    processed_template = process_template(template_data, params=params)

    if not processed_template.get("items"):
        raise ValueError("Processed CJI template has no items")

    return processed_template


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
                    raise ValueError(
                        f"component '{component}' is not unique, found in apps: {found_in}"
                    )

    def _validate_app_config(self, apps_config):
        components_for_app = {}

        for app_name, app_cfg in apps_config.items():
            required_keys = ["name", "components"]
            missing_keys = [k for k in required_keys if k not in app_cfg]
            if missing_keys:
                raise ValueError(f"app '{app_name}' is missing required keys: {missing_keys}")

            app_name = app_cfg["name"]
            if app_name in components_for_app:
                raise ValueError(f"app with name '{app_name}' is not unique")
            components_for_app[app_name] = []

            for component in app_cfg.get("components", []):
                required_keys = ["name", "host", "repo", "path"]
                missing_keys = [k for k in required_keys if k not in component]
                if missing_keys:
                    raise ValueError(
                        f"component on app {app_name} is missing required keys: {missing_keys}"
                    )
                comp_name = component["name"]
                components_for_app[app_name].append(comp_name)

        self._find_dupe_components(components_for_app)

    def __init__(
        self,
        apps_config,
        app_names,
        get_dependencies,
        image_tag_overrides,
        template_ref_overrides,
        param_overrides,
        clowd_env,
        remove_resources,
        no_remove_resources,
        single_replicas,
        component_filter,
    ):
        self._validate_app_config(apps_config)

        self.apps_config = apps_config
        self.requested_app_names = self._parse_app_names(app_names)
        self.get_dependencies = get_dependencies
        self.image_tag_overrides = image_tag_overrides
        self.template_ref_overrides = template_ref_overrides
        self.param_overrides = param_overrides
        self.clowd_env = clowd_env
        self.remove_resources = remove_resources
        self.no_remove_resources = no_remove_resources
        self.single_replicas = single_replicas
        self.component_filter = component_filter

        self.k8s_list = {
            "kind": "List",
            "apiVersion": "v1",
            "metadata": {},
            "items": [],
        }

        self.processed_components = set()

    def _get_app_config(self, app_name):
        if app_name not in self.apps_config:
            raise ValueError(f"app {app_name} not found in apps config")
        return self.apps_config[app_name]

    def _get_component_config(self, component_name):
        for _, app_cfg in self.apps_config.items():
            for component in app_cfg["components"]:
                if component["name"] == component_name:
                    return component
        else:
            raise ValueError(f"component with name '{component_name}' not found")

    def _sub_image_tags(self, items):
        content = json.dumps(items)
        for image, image_tag in self.image_tag_overrides.items():
            # easier to just re.sub on a whole string
            content, subs = re.subn(rf"{image}:\w+", rf"{image}:{image_tag}", content)
            if subs:
                log.info("replaced %d occurence(s) of image tag for image '%s'", subs, image)
        return json.loads(content)

    def _sub_ref(self, current_component_name, repo_file):
        for app_component, value in self.template_ref_overrides.items():
            # TODO: remove split when app_name syntax is fully deprecated
            split = app_component.split("/")
            if len(split) == 2:
                _, component_name = split
            elif len(split) == 1:
                component_name = split[0]
            else:
                raise ValueError(
                    f"invalid format for template ref override: {app_component}={value}"
                )

            if current_component_name == component_name:
                log.info(
                    "component: '%s' overriding template ref to '%s'",
                    component_name,
                    value,
                )
                repo_file.ref = value

    def _sub_params(self, current_component_name, params):
        for param_path, value in self.param_overrides.items():
            # TODO: remove split when app_name syntax is fully deprecated
            split = param_path.split("/")
            if len(split) == 3:
                _, component_name, param_name = split
            elif len(split) == 2:
                component_name, param_name = split
            else:
                raise ValueError(f"invalid format for parameter override: {param_path}={value}")

            if current_component_name == component_name:
                log.info(
                    "component: '%s' overriding param '%s' to '%s'",
                    component_name,
                    param_name,
                    value,
                )
                params[param_name] = value

    def _get_component_items(self, component_name):
        component = self._get_component_config(component_name)
        try:
            rf = RepoFile.from_config(component)
            # override template ref if requested
            self._sub_ref(component_name, rf)
            commit, template_content = rf.fetch()
        except Exception:
            log.error("failed to fetch template file for %s", component_name)
            raise

        template = yaml.safe_load(template_content)

        params = {
            "IMAGE_TAG": commit[:7],
            "ENV_NAME": self.clowd_env,
        }

        params.update(component.get("parameters", {}))

        # override any specific parameters on this component if requested
        self._sub_params(component_name, params)

        new_items = process_template(template, params)["items"]

        # override the tags for all occurences of an image if requested
        new_items = self._sub_image_tags(new_items)

        if (
            "all" not in self.no_remove_resources
            and ("all" in self.remove_resources or component_name in self.remove_resources)
            and component_name not in self.no_remove_resources
        ):
            _remove_resource_config(new_items)
        if self.single_replicas:
            _set_replicas(new_items)

        return new_items

    def _process_component(self, component_name):
        if component_name not in self.processed_components:
            log.info("processing component %s", component_name)
            new_items = self._get_component_items(component_name)
            self.k8s_list["items"].extend(new_items)

            self.processed_components.add(component_name)

            if self.get_dependencies:
                # recursively process components to add config for dependent apps to self.k8s_list
                self._add_dependencies_to_config(component_name, new_items)
        else:
            log.debug("component %s already processed", component_name)

    def _add_dependencies_to_config(self, component_name, new_items):
        clowdapp_items = [item for item in new_items if item.get("kind").lower() == "clowdapp"]
        dependencies = {d for item in clowdapp_items for d in item["spec"].get("dependencies", [])}

        # also include optionalDependencies since we're interested in them for testing
        for item in clowdapp_items:
            for od in item["spec"].get("optionalDependencies", []):
                dependencies.add(od)

        if dependencies:
            log.debug("component '%s' has dependencies: %s", component_name, list(dependencies))

        dependencies = [d for d in dependencies if d not in self.processed_components]
        if dependencies:
            log.info("dependencies not previously processed: %s", dependencies)
            for component_name in dependencies:
                self._process_component(component_name)

    def _process_app(self, app_name):
        log.info("processing app '%s'", app_name)
        app_cfg = self._get_app_config(app_name)
        for component in app_cfg["components"]:
            component_name = component["name"]
            log.debug("app '%s' has component '%s'", app_name, component_name)
            if self.component_filter and component_name not in self.component_filter:
                log.debug(
                    "skipping component '%s', not found in --component filter", component_name
                )
                continue
            self._process_component(component_name)

    def process(self, app_names=None):
        if not app_names:
            app_names = self.requested_app_names

        for app_name in app_names:
            self._process_app(app_name)

        return self.k8s_list

import logging
import json
import yaml
import re

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


def process_clowd_env(target_ns, env_name, template_path):
    log.info("processing ClowdEnvironment")

    env_template_path = Path(template_path if template_path else conf.DEFAULT_CLOWDENV_TEMPLATE)

    if not env_template_path.exists():
        raise ValueError("ClowdEnvironment template file does not exist: %s", env_template_path)

    with env_template_path.open() as fp:
        template_data = yaml.safe_load(fp)

    params = dict()
    params["ENV_NAME"] = env_name
    if target_ns:
        params["NAMESPACE"] = target_ns

    processed_template = process_template(template_data, params=params)

    if not processed_template.get("items"):
        raise ValueError("Processed ClowdEnvironment template has no items")

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
        single_replicas,
    ):
        self.apps_config = apps_config
        self.requested_app_names = self._parse_app_names(app_names)
        self.get_dependencies = get_dependencies
        self.image_tag_overrides = image_tag_overrides
        self.template_ref_overrides = template_ref_overrides
        self.param_overrides = param_overrides
        self.clowd_env = clowd_env
        self.remove_resources = remove_resources
        self.single_replicas = single_replicas

        self.k8s_list = {
            "kind": "List",
            "apiVersion": "v1",
            "metadata": {},
            "items": [],
        }

        self.processed_apps = set()

    def _parse_app_config(self, app_name):
        if app_name not in self.apps_config:
            raise ValueError(f"app {app_name} not found in apps config")
        app_cfg = self.apps_config[app_name]
        required_keys = ["name", "components"]
        missing_keys = [k for k in required_keys if k not in app_cfg]
        if missing_keys:
            raise ValueError(f"app is missing required keys: {missing_keys}")

        return app_cfg

    def _sub_image_tags(self, items):
        content = json.dumps(items)
        for image, image_tag in self.image_tag_overrides.items():
            # easier to just re.sub on a whole string
            content, subs = re.subn(rf"{image}:\w+", rf"{image}:{image_tag}", content)
            if subs:
                log.info("replaced %d occurence(s) of image tag for image '%s'", subs, image)
        return json.loads(content)

    def _sub_ref(self, current_app_name, current_component_name, repo_file):
        for app_component, value in self.template_ref_overrides.items():
            app_name, component_name = app_component.split("/")
            if current_app_name == app_name and current_component_name == component_name:
                log.info(
                    "app: '%s' component: '%s' overriding template ref to '%s'",
                    app_name,
                    component_name,
                    value,
                )
                repo_file.ref = value

    def _sub_params(self, current_app_name, current_component_name, params):
        for param_path, value in self.param_overrides.items():
            try:
                app_name, component_name, param_name = param_path.split("/")
            except ValueError:
                raise ValueError(f"invalid format for parameter override: {param_path}={value}")
            if current_app_name == app_name and current_component_name == component_name:
                log.info(
                    "app: '%s' component: '%s' overriding param '%s' to '%s'",
                    app_name,
                    component_name,
                    param_name,
                    value,
                )
                params[param_name] = value

    def _process_component(self, app_name, component):
        required_keys = ["name", "host", "repo", "path"]
        missing_keys = [k for k in required_keys if k not in component]
        if missing_keys:
            raise ValueError("component is missing required keys: %s", ", ".join(missing_keys))

        component_name = component["name"]
        log.info("processing component %s", component_name)

        try:
            rf = RepoFile.from_config(component)
            # override template ref if requested
            self._sub_ref(app_name, component_name, rf)
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
        self._sub_params(app_name, component_name, params)

        new_items = process_template(template, params)["items"]

        # override the tags for all occurences of an image if requested
        self._sub_image_tags(new_items)

        if self.remove_resources:
            _remove_resource_config(new_items)
        if self.single_replicas:
            _set_replicas(new_items)

        return new_items

    def _add_dependencies_to_config(self, app_name, new_items):
        clowdapp_items = [item for item in new_items if item.get("kind").lower() == "clowdapp"]
        dependencies = {d for item in clowdapp_items for d in item["spec"].get("dependencies", [])}

        # also include optionalDependencies since we're interested in them for testing
        for item in clowdapp_items:
            for od in item["spec"].get("optionalDependencies", []):
                dependencies.add(od)

        if dependencies:
            log.debug("found dependencies for app '%s': %s", app_name, list(dependencies))

        dep_items = []
        dependencies = [d for d in dependencies if d not in self.processed_apps]
        if dependencies:
            log.info("app '%s' dependencies %s not previously processed", app_name, dependencies)
            items = self.process(app_names=dependencies)["items"]
            dep_items.extend(items)

        return dep_items

    def _process_app(self, app_name):
        log.info("processing app '%s'", app_name)
        app_cfg = self._parse_app_config(app_name)
        for component in app_cfg["components"]:
            new_items = self._process_component(app_name, component)
            self.k8s_list["items"].extend(new_items)

        self.processed_apps.add(app_name)

        if self.get_dependencies:
            # recursively call self.process to add config for dependent apps to self.k8s_list
            items = self._add_dependencies_to_config(app_name, new_items)
            self.k8s_list["items"].extend(items)

    def process(self, app_names=None):
        if not app_names:
            app_names = self.requested_app_names

        for app_name in app_names:
            self._process_app(app_name)

        return self.k8s_list

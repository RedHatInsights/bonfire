import pytest

from bonfire.processor import TemplateProcessor
from bonfire.utils import RepoFile


class MockRepoFile:
    templates = {}

    def __init__(self, name):
        self.name = name

    @classmethod
    def from_config(cls, data):
        return cls(data["name"])

    @classmethod
    def add_template(cls, name, template_commit, template_data):
        cls.templates[name] = {"commit": template_commit, "data": template_data}

    def fetch(self):
        return self.templates[self.name]["commit"], self.templates[self.name]["data"]


@pytest.fixture
def mock_repo_file(monkeypatch):
    MockRepoFile.templates = {}
    with monkeypatch.context() as m:
        m.setattr(RepoFile, "fetch", MockRepoFile.fetch)
        m.setattr(RepoFile, "from_config", MockRepoFile.from_config)
        yield MockRepoFile


SIMPLE_CLOWDAPP = """
---
apiVersion: v1
kind: Template
metadata:
  name: {name}-template
objects:
- apiVersion: cloud.redhat.com/v1alpha1
  kind: ClowdApp
  metadata:
    name: {name}
  spec:
    envName: ${{ENV_NAME}}
    dependencies: {deps}
    optionalDependencies: {optional_deps}
parameters:
- description: Image tag
  name: IMAGE_TAG
  required: true
- description: ClowdEnv Name
  name: ENV_NAME
  required: true
"""


def assert_clowdapps(items, app_list):
    found_apps = []
    for i in items:
        if i["kind"].lower() == "clowdapp":
            name = i["metadata"]["name"]
            found_apps.append(name)

    for app in app_list:
        if app not in found_apps:
            raise AssertionError(f"app {app} missing from processed output")

    for app in found_apps:
        if app not in app_list:
            raise AssertionError(f"app {app} should not be present in processed output")

    if len(set(found_apps)) != len(found_apps):
        raise AssertionError("apps present more than once in processed output")


def test_dependencies(mock_repo_file):
    apps_config = {
        "app1": {
            "name": "app1",
            "components": [
                {"name": "app1-component1", "host": "local", "repo": "test", "path": "test"},
                # {"name": "app1-component2", "host": "local", "repo": "test", "path": "test"},
                # {"name": "app1-component3", "host": "local", "repo": "test", "path": "test"},
            ],
        },
        "app2": {
            "name": "app2",
            "components": [
                {"name": "app2-component1", "host": "local", "repo": "test", "path": "test"},
                {"name": "app2-component2", "host": "local", "repo": "test", "path": "test"},
                {"name": "app2-component3", "host": "local", "repo": "test", "path": "test"},
            ],
        },
        "app3": {
            "name": "app3",
            "components": [
                {"name": "app3-component1", "host": "local", "repo": "test", "path": "test"},
                {"name": "app3-component2", "host": "local", "repo": "test", "path": "test"},
                {"name": "app3-component3", "host": "local", "repo": "test", "path": "test"},
            ],
        },
    }
    tp = TemplateProcessor(
        apps_config=apps_config,
        app_names=["app1"],
        get_dependencies=True,
        optional_deps_method="hybrid",
        image_tag_overrides={},
        template_ref_overrides={},
        param_overrides={},
        clowd_env="some_env",
        remove_resources=["all"],
        no_remove_resources=[],
        single_replicas=True,
        component_filter=[],
        local=True,
        frontends=False,
    )

    mock_repo_file.add_template(
        "app1-component1",
        "1234abc",
        SIMPLE_CLOWDAPP.format(name="app1-component1", deps=["app2-component2"], optional_deps=[]),
    )
    mock_repo_file.add_template(
        "app2-component2",
        "6789def",
        SIMPLE_CLOWDAPP.format(name="app2-component2", deps=["app2-component2"], optional_deps=[]),
    )

    processed = tp.process()
    assert_clowdapps(processed["items"], ["app1-component1", "app2-component2"])

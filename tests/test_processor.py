import uuid

import pytest

from bonfire.processor import TemplateProcessor
from bonfire.utils import RepoFile


class MockRepoFile:
    """
    mock of utils.RepoFile so that we do not literally fetch templates from github/gitlab/etc.
    """

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


def add_template(mock_repo_file, app_name, deps=[], optional_deps=[]):
    mock_repo_file.add_template(
        app_name,
        uuid.uuid4().hex[0:6],
        SIMPLE_CLOWDAPP.format(name=app_name, deps=deps, optional_deps=optional_deps),
    )


@pytest.fixture()
def processor():
    apps_config = {
        "app1": {
            "name": "app1",
            "components": [
                {"name": "app1-component1", "host": "local", "repo": "test", "path": "test"},
                {"name": "app1-component2", "host": "local", "repo": "test", "path": "test"},
            ],
        },
        "app2": {
            "name": "app2",
            "components": [
                {"name": "app2-component1", "host": "local", "repo": "test", "path": "test"},
                {"name": "app2-component2", "host": "local", "repo": "test", "path": "test"},
            ],
        },
        "app3": {
            "name": "app3",
            "components": [
                {"name": "app3-component1", "host": "local", "repo": "test", "path": "test"},
                {"name": "app3-component2", "host": "local", "repo": "test", "path": "test"},
            ],
        },
        "app4": {
            "name": "app4",
            "components": [
                {"name": "app4-component1", "host": "local", "repo": "test", "path": "test"},
                {"name": "app4-component2", "host": "local", "repo": "test", "path": "test"},
            ],
        },
    }
    tp = TemplateProcessor(
        apps_config=apps_config,
        app_names=[],
        get_dependencies=True,
        optional_deps_method="hybrid",
        image_tag_overrides={},
        template_ref_overrides={},
        param_overrides={},
        clowd_env="some_env",
        remove_resources=["all"],
        no_remove_resources=[],
        remove_dependencies=[],
        no_remove_dependencies=["all"],
        single_replicas=True,
        component_filter=[],
        local=True,
        frontends=False,
    )
    return tp


@pytest.mark.parametrize(
    "optional_deps_method,expected",
    [
        ("all", ["app1-component1", "app1-component2", "app2-component2", "app3-component2"]),
        ("hybrid", ["app1-component1", "app1-component2", "app2-component2", "app3-component2"]),
        ("none", ["app1-component1", "app1-component2", "app2-component2", "app3-component2"]),
    ],
)
def test_required_deps(mock_repo_file, processor, optional_deps_method, expected):
    """
    app1-component1 has 'app2-component2' listed under 'dependencies'
    app2-component2 has 'app3-component2' listed under 'dependencies'

    test that processing app1 results in expected ClowdApp dependencies being pulled in
    """
    add_template(mock_repo_file, "app1-component1", deps=["app2-component2"])
    add_template(mock_repo_file, "app1-component2")
    add_template(mock_repo_file, "app2-component2", deps=["app3-component2"])
    # template for app3-component2 will contain a dep we've already handled
    add_template(mock_repo_file, "app3-component2", deps=["app1-component1"])

    processor.optional_deps_method = optional_deps_method
    processor.requested_app_names = ["app1"]
    processed = processor.process()
    assert_clowdapps(processed["items"], expected)


@pytest.mark.parametrize(
    "optional_deps_method,expected",
    [
        ("all", ["app1-component1", "app1-component2", "app2-component2", "app3-component2"]),
        ("hybrid", ["app1-component1", "app1-component2", "app2-component2"]),
        ("none", ["app1-component1", "app1-component2"]),
    ],
)
def test_optional_deps(mock_repo_file, processor, optional_deps_method, expected):
    """
    app1-component1 has 'app2-component2' listed under 'optionalDependencies'
    app2-component2 has 'app3-component2' listed under 'optionalDependencies'

    test that processing app1 results in expected ClowdApp dependencies being pulled in depending
    on what 'optional dependencies mode' is selected
    """
    add_template(mock_repo_file, "app1-component1", optional_deps=["app2-component2"])
    add_template(mock_repo_file, "app1-component2")
    add_template(mock_repo_file, "app2-component2", optional_deps=["app3-component2"])
    # template for app3-component2 will contain a dep we've already handled
    add_template(mock_repo_file, "app3-component2", deps=["app1-component1"])

    processor.optional_deps_method = optional_deps_method
    processor.requested_app_names = ["app1"]
    processed = processor.process()
    assert_clowdapps(processed["items"], expected)


@pytest.mark.parametrize(
    "optional_deps_method,expected",
    [
        (
            "all",
            [
                "app1-component1",
                "app1-component2",
                "app2-component1",
                "app2-component2",
                "app3-component1",
                "app3-component2",
            ],
        ),
        (
            "hybrid",
            [
                "app1-component1",
                "app1-component2",
                "app2-component1",
                "app3-component1",
                "app3-component2",
            ],
        ),
        ("none", ["app1-component1", "app1-component2", "app3-component1"]),
    ],
)
def test_mixed_deps(mock_repo_file, processor, optional_deps_method, expected):
    """
    app1-component1 has 'app3-component1' listed under 'dependencies'
    app1-component1 has 'app2-component1' listed under 'optionalDependencies'

    app2-component1 has 'app3-component2' listed under 'dependencies'
    app2-component1 has 'app2-component2' listed under 'optionalDependencies'

    test that processing app1 results in expected ClowdApp dependencies being pulled in depending
    on what 'optional dependencies mode' is selected
    """
    add_template(
        mock_repo_file,
        "app1-component1",
        deps=["app3-component1"],
        optional_deps=["app2-component1"],
    )
    add_template(
        mock_repo_file,
        "app2-component1",
        deps=["app3-component2"],
        optional_deps=["app2-component2"],
    )
    add_template(mock_repo_file, "app1-component2")
    add_template(mock_repo_file, "app2-component2")
    add_template(mock_repo_file, "app3-component1")
    add_template(mock_repo_file, "app3-component2")

    processor.optional_deps_method = optional_deps_method
    processor.requested_app_names = ["app1"]
    processed = processor.process()
    assert_clowdapps(processed["items"], expected)


@pytest.mark.parametrize(
    "optional_deps_method,expected",
    [
        (
            "all",
            [
                "app1-component1",
                "app1-component2",
                "app2-component1",
                "app2-component2",
                "app3-component1",
                "app3-component2",
                "app4-component1",
                "app4-component2",
            ],
        ),
        (
            "hybrid",
            [
                "app1-component1",
                "app1-component2",
                "app2-component1",
                "app2-component2",
                "app3-component1",
                "app3-component2",
            ],
        ),
        (
            "none",
            [
                "app1-component1",
                "app1-component2",
                "app2-component1",
                "app3-component1",
                "app3-component2",
            ],
        ),
    ],
)
def test_mixed_deps_two_apps(mock_repo_file, processor, optional_deps_method, expected):
    """
    app1-component1 has 'app2-component1' listed under 'dependencies'
    app1-component1 has 'app3-component1' listed under 'optionalDependencies'

    app2-component1 has 'app4-component1' listed under 'optionalDependencies'
    app2-component2 has 'app4-component2' listed under 'optionalDependencies'

    app3-commponent1 has 'app2-component2' listed under 'optionalDependencies'

    test that processing app1 and app3 results in expected ClowdApp dependencies being pulled in
    depending on what 'optional dependencies mode' is selected
    """
    add_template(
        mock_repo_file,
        "app1-component1",
        deps=["app2-component1"],
        optional_deps=["app3-component1"],
    )
    add_template(mock_repo_file, "app1-component2")
    add_template(mock_repo_file, "app2-component1", optional_deps=["app4-component1"])
    add_template(mock_repo_file, "app2-component2", optional_deps=["app4-component2"])
    add_template(mock_repo_file, "app3-component1", optional_deps=["app2-component2"])
    add_template(mock_repo_file, "app3-component2")
    add_template(mock_repo_file, "app4-component1")
    add_template(mock_repo_file, "app4-component2")

    processor.optional_deps_method = optional_deps_method
    processor.requested_app_names = ["app1", "app3"]
    processed = processor.process()
    assert_clowdapps(processed["items"], expected)

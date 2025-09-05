import uuid

import click
import pytest

from bonfire.processor import (
    TemplateProcessor,
    _should_alter,
    _resolve_dependency_overrides,
    _alter_dependency_config,
)
from bonfire.utils import RepoFile, AppOrComponentSelector


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

    @property
    def ref(self):
        return self.templates[self.name]["commit"]

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
    deployments:
    - name: deployment1
      podSpec:
        resources:
          limits:
            cpu: ${{CPU_LIMIT_DEPLOYMENT1}}
            memory: ${{MEM_LIMIT_DEPLOYMENT1}}
          requests:
            cpu: ${{CPU_REQUEST_DEPLOYMENT1}}
            memory: ${{MEM_REQUEST_DEPLOYMENT1}}
    - name: deployment2
      podSpec:
        resources:
          limits:
            cpu: ${{DEPLOYMENT2_WRONG_NAME_CPU}}
            memory: ${{MEM_LIMIT_DEPLOYMENT2}}
          requests:
            cpu: ${{DEPLOYMENT2_WRONG_NAME_CPU}}
            memory: ${{MEMORY_REQUEST_DEPLOYMENT2}}
parameters:
- description: Image tag
  name: IMAGE_TAG
  required: true
- description: ClowdEnv Name
  name: ENV_NAME
  required: true
- name: CPU_LIMIT_DEPLOYMENT1
  value: 100m
- name: CPU_REQUEST_DEPLOYMENT1
  value: 1m
- name: MEM_REQUEST_DEPLOYMENT1
  value: 1Mi
- name: MEM_LIMIT_DEPLOYMENT1
  value: 100Mi
- name: DEPLOYMENT2_WRONG_NAME_CPU
  value: 2m
- name: MEMORY_REQUEST_DEPLOYMENT2
  value: 2Mi
- name: MEM_LIMIT_DEPLOYMENT2
  value: 200Mi
"""


CLOWDAPP_W_UNTRUSTED_PARAM = """
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
    deployments:
    - name: deployment1
      podSpec:
        resources:
          limits:
            cpu: ${{CPU_LIMIT_DEPLOYMENT1}}
            memory: ${{MEM_LIMIT_DEPLOYMENT1}}
          requests:
            cpu: ${{INVALID_PARAMETER_HERE}}
            memory: ${{MEM_REQUEST_DEPLOYMENT1}}
    - name: deployment2
      podSpec:
        resources:
          limits:
            cpu: ${{DEPLOYMENT2_WRONG_NAME_CPU}}
            memory: ${{MEM_LIMIT_DEPLOYMENT2}}
          requests:
            cpu: ${{DEPLOYMENT2_WRONG_NAME_CPU}}
            memory: ${{MEMORY_REQUEST_DEPLOYMENT2}}
parameters:
- description: Image tag
  name: IMAGE_TAG
  required: true
- description: ClowdEnv Name
  name: ENV_NAME
  required: true
- name: CPU_LIMIT_DEPLOYMENT1
  value: 100m
- name: CPU_REQUEST_DEPLOYMENT1
  value: 1m
- name: MEM_REQUEST_DEPLOYMENT1
  value: 1Mi
- name: MEM_LIMIT_DEPLOYMENT1
  value: 100Mi
- name: DEPLOYMENT2_WRONG_NAME_CPU
  value: 2m
- name: MEMORY_REQUEST_DEPLOYMENT2
  value: 2Mi
- name: MEM_LIMIT_DEPLOYMENT2
  value: 200Mi
"""


TEMPLATES = {
    "simple_clowdapp": SIMPLE_CLOWDAPP,
    "clowdapp_w_untrusted_param": CLOWDAPP_W_UNTRUSTED_PARAM,
}


def assert_clowdapps(items, app_list):
    found_apps = AppOrComponentSelector().apps
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


def add_template(
    mock_repo_file, template_name, deps=None, optional_deps=None, template_key="simple_clowdapp"
):
    deps = deps or []
    optional_deps = optional_deps or []
    template = TEMPLATES[template_key]
    mock_repo_file.add_template(
        template_name,
        uuid.uuid4().hex[0:6],
        template.format(name=template_name, deps=deps, optional_deps=optional_deps),
    )


def get_processor(apps_config):
    return TemplateProcessor(
        apps_config=apps_config,
        app_names=[],
        get_dependencies=True,
        optional_deps_method="hybrid",
        image_tag_overrides={},
        template_ref_overrides={},
        param_overrides={},
        clowd_env="some_env",
        remove_resources=AppOrComponentSelector(True, [], []),
        no_remove_resources=AppOrComponentSelector(False, [], []),
        remove_dependencies=AppOrComponentSelector(False, [], []),
        no_remove_dependencies=AppOrComponentSelector(True, [], []),
        single_replicas=True,
        component_filter=[],
        local=True,
        frontends=False,
    )


def get_apps_config():
    return {
        "app1": {
            "name": "app1",
            "components": [
                {
                    "name": "app1-component1",
                    "host": "local",
                    "repo": "test",
                    "path": "test",
                },
                {
                    "name": "app1-component2",
                    "host": "local",
                    "repo": "test",
                    "path": "test",
                },
            ],
        },
        "app2": {
            "name": "app2",
            "components": [
                {
                    "name": "app2-component1",
                    "host": "local",
                    "repo": "test",
                    "path": "test",
                },
                {
                    "name": "app2-component2",
                    "host": "local",
                    "repo": "test",
                    "path": "test",
                },
            ],
        },
        "app3": {
            "name": "app3",
            "components": [
                {
                    "name": "app3-component1",
                    "host": "local",
                    "repo": "test",
                    "path": "test",
                },
                {
                    "name": "app3-component2",
                    "host": "local",
                    "repo": "test",
                    "path": "test",
                },
            ],
        },
        "app4": {
            "name": "app4",
            "components": [
                {
                    "name": "app4-component1",
                    "host": "local",
                    "repo": "test",
                    "path": "test",
                },
                {
                    "name": "app4-component2",
                    "host": "local",
                    "repo": "test",
                    "path": "test",
                },
            ],
        },
        "app5": {
            "name": "app5",
            "components": [
                {
                    "name": "app5-component1",
                    "host": "local",
                    "repo": "test",
                    "path": "test",
                },
                {
                    "name": "app5-component2",
                    "host": "local",
                    "repo": "test",
                    "path": "test",
                },
                {
                    "name": "app5-component3",
                    "host": "local",
                    "repo": "test",
                    "path": "test",
                },
            ],
        },
    }


@pytest.mark.parametrize(
    "optional_deps_method,expected",
    [
        (
            "all",
            [
                "app1-component1",
                "app1-component2",
                "app2-component2",
                "app3-component2",
            ],
        ),
        (
            "hybrid",
            [
                "app1-component1",
                "app1-component2",
                "app2-component2",
                "app3-component2",
            ],
        ),
        (
            "none",
            [
                "app1-component1",
                "app1-component2",
                "app2-component2",
                "app3-component2",
            ],
        ),
    ],
)
def test_required_deps(mock_repo_file, optional_deps_method, expected):
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

    processor = get_processor(get_apps_config())
    processor.optional_deps_method = optional_deps_method
    processor.requested_app_names = ["app1"]
    processed = processor.process()
    assert_clowdapps(processed["items"], expected)


def test_transitive_dependency_resolution_with_components(mock_repo_file):
    add_template(mock_repo_file, "app1-component1", deps=["app2-component1"])
    add_template(mock_repo_file, "app2-component1", deps=["app3-component1"])
    add_template(mock_repo_file, "app3-component1")
    add_template(mock_repo_file, "app1-component2", deps=["app2-component2"])
    add_template(mock_repo_file, "app2-component2", deps=["app3-component2"])
    add_template(mock_repo_file, "app3-component2")

    processor = get_processor(get_apps_config())
    processor.optional_deps_method = "all"
    processor.requested_app_names = ["app1"]
    processor.component_filter = ("app1-component1",)
    processed = processor.process()
    expected = ["app1-component1", "app2-component1", "app3-component1"]
    assert_clowdapps(processed["items"], expected)


def test_reprocesses_dependency(mock_repo_file):
    add_template(mock_repo_file, "app1-component1")
    add_template(mock_repo_file, "app1-component2", deps=["app1-component1"])

    processor = get_processor(get_apps_config())
    processor.requested_app_names = ["app1"]
    processor.component_filter = ("app1-component2",)
    processed = processor.process()
    expected = ["app1-component2", "app1-component1"]
    assert_clowdapps(processed["items"], expected)


def test_unlisted_component_does_not_remove_dependency_from_listed_component(mock_repo_file):
    """
    The graph looks like
        a1-c1 -> a2-c2 -> a3-c2
        a1-c2 -> a2-c2 -> a3-c3
    And we request component a1-c2.  This test is meant to ensure that a2-c2 and its
    dependencies are included even though it is also a dependency of a component that doesn't
    match the filter (a1-c1).
    """
    add_template(mock_repo_file, "app1-component1", deps=["app2-component2"])
    add_template(mock_repo_file, "app2-component2", deps=["app3-component2"])
    add_template(mock_repo_file, "app3-component2")
    add_template(mock_repo_file, "app1-component2", deps=["app2-component2"])

    processor = get_processor(get_apps_config())
    processor.optional_deps_method = "all"
    processor.requested_app_names = ["app1"]
    processor.component_filter = ("app1-component2",)
    processed = processor.process()
    expected = ["app1-component2", "app2-component2", "app3-component2"]
    assert_clowdapps(processed["items"], expected)


@pytest.mark.parametrize(
    "optional_deps_method,expected",
    [
        (
            "all",
            [
                "app1-component1",
                "app1-component2",
                "app2-component2",
                "app3-component2",
            ],
        ),
        ("hybrid", ["app1-component1", "app1-component2", "app2-component2"]),
        ("none", ["app1-component1", "app1-component2"]),
    ],
)
def test_optional_deps(mock_repo_file, optional_deps_method, expected):
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

    processor = get_processor(get_apps_config())
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
def test_mixed_deps(mock_repo_file, optional_deps_method, expected):
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

    processor = get_processor(get_apps_config())
    processor.optional_deps_method = optional_deps_method
    processor.requested_app_names = ["app1"]
    processed = processor.process()
    assert_clowdapps(processed["items"], expected)


@pytest.mark.parametrize(
    "optional_deps_method,expected",
    [
        (
            "all",
            ["app5-component3", "app5-component2", "app1-component1"],
        ),
        (
            "hybrid",
            [
                "app5-component3",
                "app5-component2",
            ],
        ),
        ("none", ["app5-component3"]),
    ],
)
def test_mixed_deps_with_component_filter(mock_repo_file, optional_deps_method, expected):
    """
    app5-component1 has 'app5-component2' listed under 'dependencies'
    app5-component1 has 'app5-component3' listed under 'optionalDependencies'

    app5-component2 has 'app1-component1' listed under 'optionalDependencies'

    app5-component3 has 'app5-component2' listed under 'optionalDependencies'

    bonfire is run with '--component app5-component3'

    test that processing app1 results in expected ClowdApp dependencies being pulled in depending
    on what 'optional dependencies mode' is selected
    """
    add_template(
        mock_repo_file,
        "app1-component1",
    )
    add_template(
        mock_repo_file,
        "app5-component1",
        deps=["app5-component2"],
        optional_deps=["app5-component3"],
    )
    add_template(mock_repo_file, "app5-component2", optional_deps=["app1-component1"])
    add_template(
        mock_repo_file,
        "app5-component3",
        optional_deps=["app5-component2"],
    )

    processor = get_processor(get_apps_config())
    processor.optional_deps_method = optional_deps_method
    processor.requested_app_names = ["app5"]
    processor.component_filter = ("app5-component3",)
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
def test_mixed_deps_two_apps(mock_repo_file, optional_deps_method, expected):
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

    processor = get_processor(get_apps_config())
    processor.optional_deps_method = optional_deps_method
    processor.requested_app_names = ["app1", "app3"]
    processed = processor.process()
    assert_clowdapps(processed["items"], expected)


def test_filtered_deps(mock_repo_file):
    expected = ["app1-component1", "app2-component1", "app4-component1", "app1-component2"]
    add_template(
        mock_repo_file,
        "app1-component1",
        deps=["app2-component1", "app2-component2"],
        optional_deps=["app3-component1"],
    )
    add_template(mock_repo_file, "app1-component2")
    add_template(mock_repo_file, "app2-component1", optional_deps=["app4-component1"])
    add_template(mock_repo_file, "app2-component2", optional_deps=["app4-component2"])
    add_template(mock_repo_file, "app4-component1")
    add_template(mock_repo_file, "app4-component2")

    processor = get_processor(get_apps_config())
    processor.requested_app_names = ["app1"]
    processor.optional_deps_method = "all"
    processor.remove_dependencies = AppOrComponentSelector(False, "app1", ["app1-component1"])
    processor.no_remove_dependencies = AppOrComponentSelector(
        False, "app1", ["app1-component1/app2-component1"]
    )
    processed = processor.process()
    assert_clowdapps(processed["items"], expected)


# Testing --no-remove-resources/dependency "app:" syntax
def test_should_remove_remove_for_none_no_exceptions():
    # --no-remove-resources all --no-remove-resources component1 --no-remove-resources app:app1
    remove_resources = AppOrComponentSelector(select_all=False, components=[], apps=[])
    no_remove_resources = AppOrComponentSelector(
        select_all=True, components=["component1"], apps=["app1"]
    )

    mutually_exclusive = True
    assert (
        _should_alter(
            remove_resources, no_remove_resources, "app2", "component2", mutually_exclusive
        )
        is False
    )
    assert (
        _should_alter(
            remove_resources, no_remove_resources, "app2", "component1", mutually_exclusive
        )
        is False
    )
    assert (
        _should_alter(remove_resources, no_remove_resources, "app1", "whatever", mutually_exclusive)
        is False
    )


def test_should_remove_remove_for_all_no_exceptions():
    # --remove-resources all --remove-resources component1 --remove-resources app:app1
    remove_resources = AppOrComponentSelector(
        select_all=True, components=["component1"], apps=["app1"]
    )
    no_remove_resources = AppOrComponentSelector(select_all=False, components=[], apps=[])

    mutually_exclusive = True
    assert (
        _should_alter(
            remove_resources, no_remove_resources, "app2", "component2", mutually_exclusive
        )
        is True
    )
    assert (
        _should_alter(
            remove_resources, no_remove_resources, "app2", "component1", mutually_exclusive
        )
        is True
    )
    assert (
        _should_alter(remove_resources, no_remove_resources, "app1", "whatever", mutually_exclusive)
        is True
    )


def test_should_remove_remove_option_select_all():
    # --remove-resources all --no-remove-resources component1
    mutually_exclusive = True
    assert (
        _should_alter(
            AppOrComponentSelector(select_all=True, components=[], apps=[]),
            AppOrComponentSelector(select_all=False, components=["component1"], apps=[]),
            "app2",
            "component1",
            mutually_exclusive,
        )
        is False
    )

    # --remove-resources all --no-remove-resources app:app1
    assert (
        _should_alter(
            AppOrComponentSelector(select_all=True, components=[], apps=[]),
            AppOrComponentSelector(select_all=False, components=[], apps=["app1"]),
            "app1",
            "component1",
            mutually_exclusive,
        )
        is False
    )

    # --remove-resources all
    assert (
        _should_alter(
            AppOrComponentSelector(select_all=True, components=[], apps=[]),
            AppOrComponentSelector(select_all=False, components=[], apps=[]),
            "app1",
            "component2",
            mutually_exclusive,
        )
        is True
    )


def test_should_remove_no_remove_option_select_all():
    # --remove-resources component1 --no-remove-resources all
    mutually_exclusive = True
    assert (
        _should_alter(
            AppOrComponentSelector(select_all=False, components=["component1"], apps=[]),
            AppOrComponentSelector(select_all=True, components=[], apps=[]),
            "app1",
            "component1",
            mutually_exclusive,
        )
        is True
    )

    # --remove-resources app:app1 --no-remove-resources all
    assert (
        _should_alter(
            AppOrComponentSelector(select_all=False, components=[], apps=["app1"]),
            AppOrComponentSelector(select_all=True, components=[], apps=[]),
            "app1",
            "component1",
            mutually_exclusive,
        )
        is True
    )

    # --remove-resources component1 --remove-resources app:app1 --no-remove-resources all
    assert (
        _should_alter(
            AppOrComponentSelector(select_all=False, components=["component1"], apps=["app1"]),
            AppOrComponentSelector(select_all=True, components=[], apps=[]),
            "app1",
            "component1",
            mutually_exclusive,
        )
        is True
    )

    # --remove-resources component1 --remove-resources app:app2 --no-remove-resources all
    assert (
        _should_alter(
            AppOrComponentSelector(select_all=False, components=["component1"], apps=["app1"]),
            AppOrComponentSelector(select_all=True, components=[], apps=[]),
            "app2",
            "component1",
            mutually_exclusive,
        )
        is True
    )

    # --remove-resources component2 --remove-resources app:app1 --no-remove-resources all
    assert (
        _should_alter(
            AppOrComponentSelector(select_all=False, components=["component1"], apps=["app1"]),
            AppOrComponentSelector(select_all=True, components=[], apps=[]),
            "app1",
            "component2",
            mutually_exclusive,
        )
        is True
    )

    # --remove-resources component2 --remove-resources app:app2 --no-remove-resources all
    assert (
        _should_alter(
            AppOrComponentSelector(select_all=False, components=["component1"], apps=["app1"]),
            AppOrComponentSelector(select_all=True, components=[], apps=[]),
            "app2",
            "component2",
            mutually_exclusive,
        )
        is False
    )

    assert (
        # --no-remove-resources all
        _should_alter(
            AppOrComponentSelector(select_all=False, components=[], apps=[]),
            AppOrComponentSelector(select_all=True, components=[], apps=[]),
            "app1",
            "component1",
            mutually_exclusive,
        )
        is False
    )


@pytest.mark.parametrize("default", (True, False), ids=("default=True", "default=False"))
def test_should_remove_component_overrides_app(default):
    # --no-remove-resources app:app1 --remove-resources component1
    remove_resources = AppOrComponentSelector(select_all=False, components=["component2"], apps=[])
    no_remove_resources = AppOrComponentSelector(select_all=False, components=[], apps=["app1"])
    mutually_exclusive = True

    assert (
        _should_alter(
            remove_resources, no_remove_resources, "app1", "component1", mutually_exclusive, default
        )
        is False
    )
    assert (
        _should_alter(
            remove_resources, no_remove_resources, "app1", "component2", mutually_exclusive, default
        )
        is True
    )
    assert (
        _should_alter(
            remove_resources, no_remove_resources, "anything", "else", mutually_exclusive, default
        )
        is default
    )


@pytest.mark.parametrize("default", (True, False), ids=("default=True", "default=False"))
def test_should_remove_component_app_combos(default):
    # --no-remove-resources app:app2 --no-remove-resources component2 \
    #   --remove-resources component1 --remove-resources app:app1
    remove_resources = AppOrComponentSelector(
        select_all=False, components=["component1"], apps=["app1"]
    )
    no_remove_resources = AppOrComponentSelector(
        select_all=False, components=["component2"], apps=["app2"]
    )

    mutually_exclusive = True
    assert (
        _should_alter(
            remove_resources, no_remove_resources, "app2", "component1", mutually_exclusive, default
        )
        is True
    )
    assert (
        _should_alter(
            remove_resources, no_remove_resources, "app1", "anything", mutually_exclusive, default
        )
        is True
    )
    assert (
        _should_alter(
            remove_resources, no_remove_resources, "app1", "component2", mutually_exclusive, default
        )
        is False
    )
    assert (
        _should_alter(
            remove_resources, no_remove_resources, "app2", "anything", mutually_exclusive, default
        )
        is False
    )
    assert (
        _should_alter(
            remove_resources, no_remove_resources, "anything", "else", mutually_exclusive, default
        )
        is default
    )


def get_apps_config_with_params(parameters=None):
    return {
        "app1": {
            "name": "app1",
            "components": [
                {
                    "name": "app1-component1",
                    "host": "local",
                    "repo": "test",
                    "path": "test",
                    "parameters": parameters or {},
                },
            ],
        },
    }


def test_remove_resources_untrusted_params(mock_repo_file):
    """
    Test that resource configs are removed if template's parameter values are not explicitly set
    """
    add_template(mock_repo_file, "app1-component1")
    apps_config = get_apps_config_with_params(None)
    processor = get_processor(apps_config)
    processor.requested_app_names = ["app1"]
    result = processor.process()

    deployments = result["items"][0]["spec"]["deployments"]
    deployment1, deployment2 = deployments[0], deployments[1]

    assert deployment1["podSpec"]["resources"]["requests"] == {}
    assert deployment1["podSpec"]["resources"]["limits"] == {}
    assert deployment2["podSpec"]["resources"]["requests"] == {}
    assert deployment2["podSpec"]["resources"]["limits"] == {}


def test_preserve_resources_trusted_params(mock_repo_file):
    """
    Test that using trusted parameters causes cpu/mem configurations to be preserved.

    Ensures that a value set with an untrusted parameter name is still removed.
    """
    add_template(mock_repo_file, "app1-component1")
    apps_config = get_apps_config_with_params(
        parameters={
            "CPU_LIMIT_DEPLOYMENT1": "456m",
            "CPU_REQUEST_DEPLOYMENT1": "123m",
            "MEM_LIMIT_DEPLOYMENT1": "456Mi",
            "MEM_REQUEST_DEPLOYMENT1": "123Mi",
            "DEPLOYMENT2_WRONG_NAME_CPU": "1",
            "MEM_LIMIT_DEPLOYMENT2": "910Mi",
            "MEMORY_REQUEST_DEPLOYMENT2": "789Mi",
        }
    )
    processor = get_processor(apps_config)
    processor.requested_app_names = ["app1"]
    result = processor.process()

    deployments = result["items"][0]["spec"]["deployments"]
    deployment1, deployment2 = deployments[0], deployments[1]

    assert deployment1["podSpec"]["resources"]["requests"]["cpu"] == "123m"
    assert deployment1["podSpec"]["resources"]["requests"]["memory"] == "123Mi"
    assert deployment1["podSpec"]["resources"]["limits"]["cpu"] == "456m"
    assert deployment1["podSpec"]["resources"]["limits"]["memory"] == "456Mi"
    assert deployment2["podSpec"]["resources"]["requests"]["memory"] == "789Mi"
    assert deployment2["podSpec"]["resources"]["limits"]["memory"] == "910Mi"
    # deployment2 CPU param does not match trusted syntax for name
    assert "cpu" not in deployment2["podSpec"]["resources"]["requests"]
    assert "cpu" not in deployment2["podSpec"]["resources"]["limits"]


def test_remove_resources_without_corresponding_config(mock_repo_file):
    """
    Test that using trusted parameters causes cpu/mem configurations to be preserved.

    Ensures that a value set with an untrusted parameter name is still removed.
    """
    add_template(mock_repo_file, "app1-component1", template_key="clowdapp_w_untrusted_param")
    apps_config = get_apps_config_with_params(
        parameters={
            "CPU_LIMIT_DEPLOYMENT1": "456m",
            "CPU_REQUEST_DEPLOYMENT1": "123m",  # invalid param name present in template
            "MEM_LIMIT_DEPLOYMENT1": "456Mi",
            "MEM_REQUEST_DEPLOYMENT1": "123Mi",
            "DEPLOYMENT2_WRONG_NAME_CPU": "1",
            "MEM_LIMIT_DEPLOYMENT2": "910Mi",
            "MEMORY_REQUEST_DEPLOYMENT2": "789Mi",
        }
    )
    processor = get_processor(apps_config)
    processor.requested_app_names = ["app1"]
    result = processor.process()

    deployments = result["items"][0]["spec"]["deployments"]
    deployment1, deployment2 = deployments[0], deployments[1]

    assert "cpu" not in deployment1["podSpec"]["resources"]["requests"]
    assert deployment1["podSpec"]["resources"]["requests"]["memory"] == "123Mi"
    assert "cpu" not in deployment1["podSpec"]["resources"]["limits"]
    assert deployment1["podSpec"]["resources"]["limits"]["memory"] == "456Mi"
    assert deployment2["podSpec"]["resources"]["requests"]["memory"] == "789Mi"
    assert deployment2["podSpec"]["resources"]["limits"]["memory"] == "910Mi"
    # deployment2 CPU param does not match trusted syntax for name
    assert "cpu" not in deployment2["podSpec"]["resources"]["requests"]
    assert "cpu" not in deployment2["podSpec"]["resources"]["limits"]


@pytest.mark.parametrize(
    "no_remove_resources",
    (
        # --no-remove-resources all
        AppOrComponentSelector(select_all=True, components=[], apps=[]),
        # --no-remove-resources app:app1
        AppOrComponentSelector(select_all=False, components=[], apps=["app1"]),
        # --no-remove-resources app1-component1
        AppOrComponentSelector(select_all=False, components=["app1-component1"], apps=[]),
    ),
    ids=("all", "app", "component"),
)
def test_preserve_resources_cli_option(mock_repo_file, no_remove_resources):
    """
    Test that using "--no-remove-resources" causes cpu/mem configs to be preserved
    """
    add_template(mock_repo_file, "app1-component1")
    apps_config = get_apps_config_with_params(parameters=None)
    processor = get_processor(apps_config)
    processor.requested_app_names = ["app1"]
    processor.no_remove_resources = no_remove_resources
    processor.remove_resources = AppOrComponentSelector(False, [], [])
    result = processor.process()

    deployments = result["items"][0]["spec"]["deployments"]
    deployment1, deployment2 = deployments[0], deployments[1]

    assert deployment1["podSpec"]["resources"]["requests"]["cpu"] == "1m"
    assert deployment1["podSpec"]["resources"]["requests"]["memory"] == "1Mi"
    assert deployment1["podSpec"]["resources"]["limits"]["cpu"] == "100m"
    assert deployment1["podSpec"]["resources"]["limits"]["memory"] == "100Mi"
    assert deployment2["podSpec"]["resources"]["requests"]["memory"] == "2Mi"
    assert deployment2["podSpec"]["resources"]["requests"]["cpu"] == "2m"
    assert deployment2["podSpec"]["resources"]["limits"]["memory"] == "200Mi"
    assert deployment2["podSpec"]["resources"]["limits"]["cpu"] == "2m"


def test_exclude_components(mock_repo_file):
    """
    Test that components included in --exclude-components are skipped during processing
    """
    add_template(mock_repo_file, "app1-component1")
    add_template(mock_repo_file, "app1-component2")
    add_template(mock_repo_file, "app2-component1")
    add_template(mock_repo_file, "app2-component2")

    processor = get_processor(get_apps_config())
    processor.requested_app_names = ["app1", "app2"]
    processor.exclude_components = ["app1-component2", "app2-component1"]

    processed = processor.process()

    expected_components = ["app1-component1", "app2-component2"]
    assert_clowdapps(processed["items"], expected_components)


def test_exclude_components_empty_list(mock_repo_file):
    """
    Test that when exclude_components is None or empty, all components are processed
    """
    add_template(mock_repo_file, "app1-component1")
    add_template(mock_repo_file, "app1-component2")
    add_template(mock_repo_file, "app2-component1")
    add_template(mock_repo_file, "app2-component2")

    processor = get_processor(get_apps_config())
    processor.requested_app_names = ["app1", "app2"]
    processor.exclude_components = None

    processed = processor.process()

    expected_components = [
        "app1-component1",
        "app1-component2",
        "app2-component1",
        "app2-component2",
    ]
    assert_clowdapps(processed["items"], expected_components)


def test_exclude_components_comma_separated_string(mock_repo_file):
    """
    Test that exclude_components accepts a comma-separated string
    """
    add_template(mock_repo_file, "app1-component1")
    add_template(mock_repo_file, "app1-component2")
    add_template(mock_repo_file, "app2-component1")
    add_template(mock_repo_file, "app2-component2")

    processor = get_processor(get_apps_config())
    processor.requested_app_names = ["app1", "app2"]
    # Test comma-separated string (simulating CLI input)
    processor.exclude_components = "app1-component2,app2-component1"

    processed = processor.process()

    expected_components = ["app1-component1", "app2-component2"]
    assert_clowdapps(processed["items"], expected_components)


def test_exclude_components_comma_separated_with_spaces(mock_repo_file):
    """
    Test that exclude_components handles spaces around commas correctly
    """
    add_template(mock_repo_file, "app1-component1")
    add_template(mock_repo_file, "app1-component2")
    add_template(mock_repo_file, "app2-component1")
    add_template(mock_repo_file, "app2-component2")

    processor = get_processor(get_apps_config())
    processor.requested_app_names = ["app1", "app2"]
    # Test comma-separated string with spaces
    processor.exclude_components = "app1-component2, app2-component1 , "

    processed = processor.process()

    expected_components = ["app1-component1", "app2-component2"]
    assert_clowdapps(processed["items"], expected_components)


def test_parse_exclude_components():
    """
    Test the _parse_exclude_components static method with different input types
    """
    # Test None input
    result = TemplateProcessor._parse_exclude_components(None)
    assert result is None

    # Test empty string
    result = TemplateProcessor._parse_exclude_components("")
    assert result == []

    # Test single component string
    result = TemplateProcessor._parse_exclude_components("component1")
    assert result == ["component1"]

    # Test comma-separated string
    result = TemplateProcessor._parse_exclude_components("component1,component2,component3")
    assert result == ["component1", "component2", "component3"]

    # Test comma-separated string with spaces
    result = TemplateProcessor._parse_exclude_components("component1, component2 , component3")
    assert result == ["component1", "component2", "component3"]

    # Test string with trailing/leading commas and spaces
    result = TemplateProcessor._parse_exclude_components(" ,component1, component2, ")
    assert result == ["component1", "component2"]

    # Test list input (should return same list)
    input_list = ["component1", "component2"]
    result = TemplateProcessor._parse_exclude_components(input_list)
    assert result == ["component1", "component2"]

    # Test tuple input (should convert to list)
    input_tuple = ("component1", "component2")
    result = TemplateProcessor._parse_exclude_components(input_tuple)
    assert result == ["component1", "component2"]


@pytest.mark.parametrize(
    "keep,remove,expected",
    [
        ({"a"}, {"b"}, {"a", "c"}),
        ({"*"}, {"b"}, {"a", "c"}),
        ({None}, {"b"}, {"a", "c"}),
        ({"a"}, {None}, {"a", "b", "c"}),
        ({"*"}, {None}, {"a", "b", "c"}),
        ({None}, {None}, {"a", "b", "c"}),
        ({"a"}, {"*"}, {"a"}),
        # Combination ["*"] and ["*"] is an error and is tested elsewhere
        ({None}, {"*"}, set()),
    ],
)
def test_dependency_resolution(keep, remove, expected):
    dependencies = {"a", "b", "c"}
    result = _resolve_dependency_overrides(dependencies, keep, remove)
    # Thanks https://stackoverflow.com/a/61494686/6124862
    lacks = expected.difference(result)
    extra = result.difference(expected)
    message = f"Lacks elements {lacks} " if lacks else ""
    message += f"Extra elements {extra}" if extra else ""
    assert not message


def test_dependency_resolution_validates_no_common_items():
    dependencies = {"a", "b", "c"}
    keep = {"a"}
    remove = {"a"}
    with pytest.raises(click.ClickException) as e:
        _resolve_dependency_overrides(dependencies, keep, remove)
    assert "Cannot resolve dependency list" in e.value.message


def test_dependency_resolution_validates_no_wildcard():
    dependencies = {"a", "b", "c"}
    keep = {"*"}
    remove = {"*"}
    with pytest.raises(click.ClickException) as e:
        _resolve_dependency_overrides(dependencies, keep, remove)
    assert "Cannot resolve dependency list" in e.value.message


def test_dependency_resolution_validates_wildcard_only_item():
    dependencies = {"a", "b", "c"}
    keep = {"*", "b"}
    remove = {"a"}
    with pytest.raises(click.ClickException) as e:
        _resolve_dependency_overrides(dependencies, keep, remove)
    assert "Invalid dependency modification specifier" in e.value.message


def test_dependency_resolution_validates_not_none_not_empty():
    dependencies = {"a", "b", "c"}
    keep = set()
    remove = {"a"}
    with pytest.raises(click.ClickException) as e:
        _resolve_dependency_overrides(dependencies, keep, remove)
    assert "cannot be None or an empty list" in e.value.message

    keep = None
    with pytest.raises(click.ClickException) as e:
        _resolve_dependency_overrides(dependencies, keep, remove)
    assert "cannot be None or an empty list" in e.value.message


def test_dependency_resolution_validates_dependency_presence(mock_repo_file):
    items = [
        {
            "kind": "ClowdApp",
            "metadata": {"name": "hello"},
            "spec": {"dependencies": ["a", "b"], "optionalDependencies": ["c"]},
        }
    ]

    keep = {None}
    remove = {"x"}
    with pytest.raises(click.ClickException) as e:
        _alter_dependency_config(items, "hello", keep, remove)
    assert "not present in dependencies" in e.value.message

    keep = {"y"}
    remove = {None}
    with pytest.raises(click.ClickException) as e:
        _alter_dependency_config(items, "hello", keep, remove)
    assert "not present in dependencies" in e.value.message


def test_process_reservation_with_team(mocker):
    """
    Test that process_reservation correctly handles the team parameter
    """
    from bonfire.processor import process_reservation

    
    # Mock the template processing
    mock_process_template = mocker.patch("bonfire.processor._process_template")
    mock_process_template.return_value = {
        "items": [
            {
                "apiVersion": "cloud.redhat.com/v1alpha1",
                "kind": "NamespaceReservation",
                "metadata": {"name": "test-reservation"},
                "spec": {
                    "duration": "1h",
                    "requester": "test-user",
                    "team": "test-team",
                    "pool": "default",
                },
            }
        ]
    }
    
    # Mock file operations
    mock_path = mocker.patch("bonfire.processor.Path")
    mock_path.return_value.exists.return_value = True
    mock_path.return_value.open.return_value.__enter__.return_value.read.return_value = (
        "mock template"
    )

    
    # Mock yaml.safe_load
    mocker.patch("bonfire.processor.yaml.safe_load", return_value={"mock": "template"})
    
    # Test with team parameter
    result = process_reservation(
        name="test-reservation",
        requester="test-user",
        duration="1h",
        pool="default",
        team="test-team",
    )
    
    # Verify the template was processed with correct parameters
    mock_process_template.assert_called_once()
    call_args = mock_process_template.call_args
    params = call_args[1]["params"]

    
    assert params["NAME"] == "test-reservation"
    assert params["REQUESTER"] == "test-user"
    assert params["DURATION"] == "1h"
    assert params["POOL"] == "default"
    assert params["TEAM"] == "test-team"
    

    assert result == mock_process_template.return_value


def test_process_reservation_without_team(mocker):
    """
    Test that process_reservation correctly handles None team parameter
    """
    from bonfire.processor import process_reservation
    

    # Mock the template processing
    mock_process_template = mocker.patch("bonfire.processor._process_template")
    mock_process_template.return_value = {
        "items": [
            {
                "apiVersion": "cloud.redhat.com/v1alpha1",
                "kind": "NamespaceReservation",
                "metadata": {"name": "test-reservation"},
                "spec": {
                    "duration": "1h",
                    "requester": "test-user",
                    "team": None,
                    "pool": "default",
                },
            }
        ]
    }
    
    # Mock file operations
    mock_path = mocker.patch("bonfire.processor.Path")
    mock_path.return_value.exists.return_value = True
    mock_path.return_value.open.return_value.__enter__.return_value.read.return_value = (
        "mock template"
    )

    
    # Mock yaml.safe_load
    mocker.patch("bonfire.processor.yaml.safe_load", return_value={"mock": "template"})
    
    # Test without team parameter (should default to None)
    result = process_reservation(
        name="test-reservation", requester="test-user", duration="1h", pool="default"
    )
    
    # Verify the template was processed with correct parameters
    mock_process_template.assert_called_once()
    call_args = mock_process_template.call_args
    params = call_args[1]["params"]
    

    assert params["NAME"] == "test-reservation"
    assert params["REQUESTER"] == "test-user"
    assert params["DURATION"] == "1h"
    assert params["POOL"] == "default"
    assert params["TEAM"] is None
    

    assert result == mock_process_template.return_value

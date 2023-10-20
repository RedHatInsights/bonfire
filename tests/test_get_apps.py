import bonfire
from bonfire.qontract import get_apps_for_env, sub_refs, ENVS_QUERY, APPS_QUERY


def _mock_envs_gql_resp():
    return {
        "envs": [
            {
                "name": "env_with_no_apps",
            },
            {
                "name": "ephemeral",
                "parameters": '{"PARAM_1":"ephemeral1","PARAM_2":"ephemeral2","PARAM_3":100}',
                "namespaces": [
                    {"name": "ephemeral-base", "path": "/path/to/ephemeral-base.yml"},
                ],
            },
            {
                "name": "stage",
                "parameters": '{"PARAM_1":"stage1","PARAM_2":"stage2","PARAM_3":200}',
                "namespaces": [
                    {"name": "stage-namespace-1", "path": "/path/to/stage-namespace-1.yml"},
                    {"name": "stage-namespace-2", "path": "/path/to/stage-namespace-2.yml"},
                    {"name": "stage-namespace-3", "path": "/path/to/stage-namespace-3.yml"},
                ],
            },
            {
                "name": "prod",
                "parameters": '{"PARAM_1":"prod1","PARAM_2":"prod2","PARAM_3":300}',
                "namespaces": [
                    {"name": "prod-namespace-1", "path": "/path/to/prod-namespace-1.yml"},
                    {"name": "prod-namespace-2", "path": "/path/to/prod-namespace-2.yml"},
                ],
            },
        ]
    }


def _mock_apps_gql_resp():
    return {
        "apps": [
            {
                "name": "app1",
                "parentApp": {"name": "insights"},
                "saasFiles": [
                    {
                        "path": "/path/to/deploy.yml",
                        "name": "app1",
                        "parameters": None,
                        "resourceTemplates": [
                            {
                                "name": "component1",
                                "path": "/deploy/template.yml",
                                "url": "https://github.test/Org/Repo",
                                "parameters": None,
                                "targets": [
                                    {
                                        "namespace": {
                                            "name": "app1-stage-ns-1",
                                            "path": "/path/to/stage-namespace-1.yml",
                                            "cluster": {"name": "test_cluster"},
                                        },
                                        "ref": "master",
                                        "parameters": None,
                                    },
                                    {
                                        "namespace": {
                                            "name": "app1-stage-ns-2",
                                            "path": "/path/to/stage-namespace-2.yml",
                                            "cluster": {"name": "test_cluster"},
                                        },
                                        "ref": "abc1234",
                                        "parameters": '{"FAVORED_PARAM":"favored.value"}',
                                    },
                                    {
                                        "namespace": {
                                            "name": "app1-stage-ns-3",
                                            "path": "/path/to/stage-namespace-3.yml",
                                            "cluster": {"name": "test_cluster"},
                                        },
                                        "ref": "xyz6789",
                                        "parameters": '{"FAVORED_PARAM":"unfavored.value"}',
                                    },
                                    {
                                        "namespace": {
                                            "name": "app1-prod-ns-1",
                                            "path": "/path/to/prod-namespace-2.yml",
                                            "cluster": {"name": "test_cluster"},
                                        },
                                        "ref": "prod1ref",
                                        "parameters": '{"REPLICAS":1,"FAVORED_PARAM":"favored"}',
                                    },
                                    {
                                        "namespace": {
                                            "name": "app1-prod-ns-2",
                                            "path": "/path/to/prod-namespace-2.yml",
                                            "cluster": {"name": "test_cluster"},
                                        },
                                        "ref": "prod2ref",
                                        "parameters": '{"REPLICAS":0,"FAVORED_PARAM":"favored"}',
                                    },
                                    {
                                        "namespace": {
                                            "name": "ephemeral-base",
                                            "path": "/path/to/ephemeral-base.yml",
                                            "cluster": {"name": "test_cluster"},
                                        },
                                        "ref": "internal",
                                        "parameters": None,
                                    },
                                ],
                            },
                        ],
                    }
                ],
            },
        ]
    }


class MockGQLClient:
    def execute(self, query):
        if query == ENVS_QUERY:
            return _mock_envs_gql_resp()
        elif query == APPS_QUERY:
            return _mock_apps_gql_resp()
        else:
            raise ValueError("invalid query for MockGQLClient")


class MockAppInterfaceClient(bonfire.qontract.Client):
    def __init__(self):
        self.client = MockGQLClient()


def _mock_get_client():
    return MockAppInterfaceClient()


def test_no_pref(monkeypatch):
    """
    Test that with no preference, git ref from first stage target is chosen
    """
    monkeypatch.setattr(bonfire.qontract, "get_client", _mock_get_client)
    expected_apps = {
        "app1": {
            "name": "app1",
            "components": [
                {
                    "name": "component1",
                    "path": "/deploy/template.yml",
                    "host": "github",
                    "repo": "Org/Repo",
                    "ref": "master",
                    "parameters": {
                        "PARAM_1": "ephemeral1",
                        "PARAM_2": "ephemeral2",
                        "PARAM_3": 100,
                    },
                }
            ],
        }
    }
    ephemeral_apps = get_apps_for_env(env_name="ephemeral", preferred_params={})
    final_apps = sub_refs(ephemeral_apps, "stage", None, preferred_params={})

    assert final_apps == expected_apps


def test_preferred_ref(monkeypatch):
    """
    Test that git ref from stage target with FAVORED_PARAM=favored.value is chosen
    """
    monkeypatch.setattr(bonfire.qontract, "get_client", _mock_get_client)
    expected_apps = {
        "app1": {
            "name": "app1",
            "components": [
                {
                    "name": "component1",
                    "path": "/deploy/template.yml",
                    "host": "github",
                    "repo": "Org/Repo",
                    "ref": "abc1234",
                    "parameters": {
                        "PARAM_1": "ephemeral1",
                        "PARAM_2": "ephemeral2",
                        "PARAM_3": 100,
                    },
                }
            ],
        }
    }
    prefer = {"FAVORED_PARAM": "favored.value"}
    ephemeral_apps = get_apps_for_env(env_name="ephemeral", preferred_params=prefer)
    final_apps = sub_refs(ephemeral_apps, "stage", None, preferred_params=prefer)

    assert final_apps == expected_apps


def test_prefer_replicas(monkeypatch):
    """
    Test that git ref from prod target with REPLICAS=1 is chosen
    """
    monkeypatch.setattr(bonfire.qontract, "get_client", _mock_get_client)
    expected_apps = {
        "app1": {
            "name": "app1",
            "components": [
                {
                    "name": "component1",
                    "path": "/deploy/template.yml",
                    "host": "github",
                    "repo": "Org/Repo",
                    "ref": "prod1ref",
                    "parameters": {
                        "PARAM_1": "ephemeral1",
                        "PARAM_2": "ephemeral2",
                        "PARAM_3": 100,
                    },
                }
            ],
        }
    }
    prefer = {"FAVORED_PARAM": "favored"}
    ephemeral_apps = get_apps_for_env(env_name="ephemeral", preferred_params=prefer)
    final_apps = sub_refs(ephemeral_apps, "prod", None, preferred_params=prefer)

    assert final_apps == expected_apps


def test_fallback_with_preference(monkeypatch):
    """
    Test that git ref from stage target with FAVORED_PARAM=favored.value is chosen when
    ref env is set to 'prod' but no deploy config is present for the component in 'prod'
    """
    monkeypatch.setattr(bonfire.qontract, "get_client", _mock_get_client)
    expected_apps = {
        "app1": {
            "name": "app1",
            "components": [
                {
                    "name": "component1",
                    "path": "/deploy/template.yml",
                    "host": "github",
                    "repo": "Org/Repo",
                    "ref": "abc1234",
                    "parameters": {
                        "PARAM_1": "ephemeral1",
                        "PARAM_2": "ephemeral2",
                        "PARAM_3": 100,
                    },
                }
            ],
        }
    }
    prefer = {"FAVORED_PARAM": "favored.value"}
    ephemeral_apps = get_apps_for_env(env_name="ephemeral", preferred_params=prefer)
    final_apps = sub_refs(ephemeral_apps, "env_with_no_apps", "stage", preferred_params=prefer)

    assert final_apps == expected_apps

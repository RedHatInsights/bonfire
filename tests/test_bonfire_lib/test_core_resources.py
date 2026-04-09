from bonfire_lib.core_resources import render_reservation, render_clowdenv, render_cji


class TestRenderReservation:
    def test_required_params(self):
        result = render_reservation("test-res", "1h", "user@redhat.com")
        assert result["apiVersion"] == "cloud.redhat.com/v1alpha1"
        assert result["kind"] == "NamespaceReservation"
        assert result["metadata"]["name"] == "test-res"
        assert result["metadata"]["labels"]["requester"] == "user@redhat.com"
        assert result["spec"]["duration"] == "1h"
        assert result["spec"]["requester"] == "user@redhat.com"
        assert result["spec"]["pool"] == "default"

    def test_no_optional_keys_when_not_provided(self):
        result = render_reservation("test-res", "1h", "user")
        assert "team" not in result["spec"]
        assert "secretSourceNamespace" not in result["spec"]

    def test_with_team(self):
        result = render_reservation("test-res", "1h", "user", team="myteam")
        assert result["spec"]["team"] == "myteam"

    def test_with_secrets_src_namespace(self):
        result = render_reservation(
            "test-res", "1h", "user", secrets_src_namespace="custom-base"
        )
        assert result["spec"]["secretSourceNamespace"] == "custom-base"

    def test_custom_pool(self):
        result = render_reservation("test-res", "1h", "user", pool="minimal")
        assert result["spec"]["pool"] == "minimal"

    def test_all_params(self):
        result = render_reservation(
            "test-res",
            "2h30m",
            "user@redhat.com",
            pool="large",
            team="platform",
            secrets_src_namespace="my-base",
        )
        assert result["spec"]["duration"] == "2h30m"
        assert result["spec"]["pool"] == "large"
        assert result["spec"]["team"] == "platform"
        assert result["spec"]["secretSourceNamespace"] == "my-base"


class TestRenderClowdenv:
    def test_basic_render(self):
        result = render_clowdenv("env-test", "test-ns")
        assert result["apiVersion"] == "cloud.redhat.com/v1alpha1"
        assert result["kind"] == "ClowdEnvironment"
        assert result["metadata"]["name"] == "env-test"
        assert result["spec"]["targetNamespace"] == "test-ns"

    def test_default_pull_secret(self):
        result = render_clowdenv("env-test", "test-ns")
        pull_secrets = result["spec"]["providers"]["pullSecrets"]
        assert pull_secrets[0]["name"] == "quay-cloudservices-pull"

    def test_custom_pull_secret(self):
        result = render_clowdenv("env-test", "test-ns", pull_secret_name="custom-pull")
        pull_secrets = result["spec"]["providers"]["pullSecrets"]
        assert pull_secrets[0]["name"] == "custom-pull"

    def test_has_provider_sections(self):
        result = render_clowdenv("env-test", "test-ns")
        providers = result["spec"]["providers"]
        assert "web" in providers
        assert "kafka" in providers
        assert "db" in providers
        assert "logging" in providers
        assert "objectStore" in providers
        assert "inMemoryDb" in providers
        assert "metrics" in providers
        assert "featureFlags" in providers
        assert "testing" in providers


class TestRenderCji:
    def test_basic_render(self):
        result = render_cji("test-cji", "my-app")
        assert result["apiVersion"] == "cloud.redhat.com/v1alpha1"
        assert result["kind"] == "ClowdJobInvocation"
        assert result["metadata"]["name"] == "test-cji"
        assert result["spec"]["appName"] == "my-app"

    def test_defaults(self):
        result = render_cji("test-cji", "my-app")
        spec = result["spec"]
        iqe = spec["testing"]["iqe"]
        assert iqe["debug"] is False
        assert iqe["imageTag"] == ""
        assert iqe["ui"]["selenium"]["deploy"] is False

    def test_env_vars_present(self):
        result = render_cji("test-cji", "my-app")
        env_list = result["spec"]["testing"]["iqe"]["env"]
        env_dict = {e["name"]: e["value"] for e in env_list}
        assert "IQE_MARKER_EXPRESSION" in env_dict
        assert "IQE_FILTER_EXPRESSION" in env_dict
        assert "IQE_PLUGINS" in env_dict
        assert "ENV_FOR_DYNACONF" in env_dict
        assert env_dict["ENV_FOR_DYNACONF"] == "clowder_smoke"
        assert env_dict["IQE_PARALLEL_ENABLED"] == "true"
        assert env_dict["IQE_PARALLEL_WORKER_COUNT"] == "2"
        assert env_dict["IQE_ENABLE_MINIO"] == "true"

    def test_custom_values(self):
        result = render_cji(
            "test-cji",
            "my-app",
            env_name="custom_env",
            debug=True,
            marker="smoke",
            filter="test_login",
            plugins="my_plugin",
            deploy_selenium=True,
            parallel_enabled="false",
            parallel_worker_count="4",
        )
        spec = result["spec"]
        iqe = spec["testing"]["iqe"]
        assert iqe["debug"] is True
        assert iqe["ui"]["selenium"]["deploy"] is True

        env_dict = {e["name"]: e["value"] for e in iqe["env"]}
        assert env_dict["ENV_FOR_DYNACONF"] == "custom_env"
        assert env_dict["IQE_MARKER_EXPRESSION"] == "smoke"
        assert env_dict["IQE_FILTER_EXPRESSION"] == "test_login"
        assert env_dict["IQE_PLUGINS"] == "my_plugin"
        assert env_dict["IQE_PARALLEL_ENABLED"] == "false"
        assert env_dict["IQE_PARALLEL_WORKER_COUNT"] == "4"

from bonfire_lib.config import Settings


class TestSettingsDefaults:
    def test_default_pool(self, settings):
        assert settings.default_namespace_pool == "default"

    def test_default_duration(self, settings):
        assert settings.default_reservation_duration == "1h"

    def test_default_requester(self, settings):
        assert settings.default_requester == ""

    def test_default_env_name(self, settings):
        assert settings.ephemeral_env_name == "insights-ephemeral"

    def test_default_base_namespace(self, settings):
        assert settings.default_base_namespace == "ephemeral-base"

    def test_default_is_bot(self, settings):
        assert settings.is_bot is False


class TestSettingsFromEnv:
    def test_reads_env_vars(self, monkeypatch):
        monkeypatch.setenv("BONFIRE_DEFAULT_NAMESPACE_POOL", "custom-pool")
        monkeypatch.setenv("BONFIRE_DEFAULT_DURATION", "2h")
        monkeypatch.setenv("BONFIRE_NS_REQUESTER", "ci-bot")
        monkeypatch.setenv("EPHEMERAL_ENV_NAME", "custom-env")
        monkeypatch.setenv("DEFAULT_BASE_NAMESPACE", "custom-base")
        monkeypatch.setenv("BONFIRE_BOT", "true")

        s = Settings.from_env()
        assert s.default_namespace_pool == "custom-pool"
        assert s.default_reservation_duration == "2h"
        assert s.default_requester == "ci-bot"
        assert s.ephemeral_env_name == "custom-env"
        assert s.default_base_namespace == "custom-base"
        assert s.is_bot is True

    def test_uses_defaults_when_unset(self, monkeypatch):
        for var in (
            "BONFIRE_DEFAULT_NAMESPACE_POOL",
            "BONFIRE_DEFAULT_DURATION",
            "BONFIRE_NS_REQUESTER",
            "EPHEMERAL_ENV_NAME",
            "DEFAULT_BASE_NAMESPACE",
            "BONFIRE_BOT",
        ):
            monkeypatch.delenv(var, raising=False)

        s = Settings.from_env()
        assert s.default_namespace_pool == "default"
        assert s.default_reservation_duration == "1h"
        assert s.default_requester == ""
        assert s.ephemeral_env_name == "insights-ephemeral"
        assert s.default_base_namespace == "ephemeral-base"
        assert s.is_bot is False

    def test_bot_case_insensitive(self, monkeypatch):
        monkeypatch.setenv("BONFIRE_BOT", "True")
        assert Settings.from_env().is_bot is True

        monkeypatch.setenv("BONFIRE_BOT", "TRUE")
        assert Settings.from_env().is_bot is True

        monkeypatch.setenv("BONFIRE_BOT", "false")
        assert Settings.from_env().is_bot is False

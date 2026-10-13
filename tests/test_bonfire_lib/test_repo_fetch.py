"""Tests for bonfire_lib.repo_fetch module."""

from pathlib import Path

import pytest
from unittest.mock import MagicMock, patch

import bonfire_lib.repo_fetch as repo_fetch
from bonfire_lib import config
from bonfire_lib.repo_fetch import RepoFile, _get_gl_ca_cert
from bonfire_lib.utils import FatalError


@pytest.fixture(autouse=True)
def _reset_ca_cert_cache():
    """The resolved CA cert path is cached in a module global; reset it per-test."""
    repo_fetch._gl_ca_cert_path = None
    yield
    repo_fetch._gl_ca_cert_path = None


class TestGetGlCaCert:
    # config.GL_CA_CERT is read from the env at import time, so patch the
    # constant directly rather than setting the env var (see AGENTS.md #6).
    def test_defaults_to_bundled_cert(self, monkeypatch):
        monkeypatch.setattr(config, "GL_CA_CERT", None)
        path = _get_gl_ca_cert()
        assert path == str(repo_fetch._BUNDLED_GL_CA_CERT)
        assert repo_fetch._BUNDLED_GL_CA_CERT.is_file()

    def test_env_override_existing_file(self, tmp_path, monkeypatch):
        cert = tmp_path / "mounted.pem"
        cert.write_text("x")
        monkeypatch.setattr(config, "GL_CA_CERT", str(cert))
        assert _get_gl_ca_cert() == str(cert)

    def test_env_override_missing_file_raises_actionable(self, monkeypatch):
        monkeypatch.setattr(config, "GL_CA_CERT", "/no/such/cert.pem")
        with pytest.raises(FatalError, match=r"BONFIRE_GL_CA_CERT.*no file exists"):
            _get_gl_ca_cert()

    def test_missing_bundle_raises_actionable(self, monkeypatch):
        monkeypatch.setattr(config, "GL_CA_CERT", None)
        monkeypatch.setattr(repo_fetch, "_BUNDLED_GL_CA_CERT", Path("/no/such/bundle.pem"))
        with pytest.raises(FatalError, match=r"bundled GitLab CA certificate is missing"):
            _get_gl_ca_cert()


class TestRepoFileInit:
    def test_valid_github(self):
        rf = RepoFile("github", "org", "repo", "/template.yaml", "main")
        assert rf.host == "github"
        assert rf.org == "org"
        assert rf.repo == "repo"
        assert rf.path == "/template.yaml"
        assert rf.ref == "main"

    def test_path_gets_slash_prefix(self):
        rf = RepoFile("github", "org", "repo", "template.yaml")
        assert rf.path == "/template.yaml"

    def test_unsupported_host_raises(self):
        with pytest.raises(FatalError, match="unsupported"):
            RepoFile("local", "org", "repo", "/t.yaml")


class TestFromComponent:
    def test_github_component(self):
        component = {
            "name": "rosa-ephemeral-cluster",
            "host": "github",
            "repo": "RedHatInsights/ephemeral-cluster-operator",
            "path": "/deploy/template.yaml",
            "ref": "abc123",
        }
        rf = RepoFile.from_component(component)
        assert rf.host == "github"
        assert rf.org == "RedHatInsights"
        assert rf.repo == "ephemeral-cluster-operator"
        assert rf.path == "/deploy/template.yaml"
        assert rf.ref == "abc123"

    def test_gitlab_with_subgroups(self):
        component = {
            "name": "comp",
            "host": "gitlab",
            "repo": "group/subgroup/my-repo",
            "path": "/t.yaml",
            "ref": "main",
        }
        rf = RepoFile.from_component(component)
        assert rf.org == "group/subgroup"
        assert rf.repo == "my-repo"

    def test_missing_keys_raises(self):
        with pytest.raises(FatalError, match="missing keys"):
            RepoFile.from_component({"name": "comp"})

    def test_no_slash_in_repo_raises(self):
        with pytest.raises(FatalError, match="invalid repo"):
            RepoFile.from_component(
                {
                    "host": "github",
                    "repo": "noslash",
                    "path": "/t.yaml",
                }
            )

    def test_default_ref(self):
        component = {
            "host": "github",
            "repo": "org/repo",
            "path": "/t.yaml",
        }
        rf = RepoFile.from_component(component)
        assert rf.ref == "master"


class TestFetchGithub:
    @patch.object(
        RepoFile, "_get_gh_commit_hash", return_value="abc1234567890abcdef1234567890abcdef123456"
    )
    @patch.object(RepoFile, "_get")
    def test_branch_ref_resolves_commit(self, mock_get, mock_hash):
        rf = RepoFile("github", "org", "repo", "/template.yaml", "main")
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"kind: Template"
        mock_get.return_value = mock_response

        commit, content = rf._fetch_github()

        assert commit == "abc1234567890abcdef1234567890abcdef123456"
        assert content == b"kind: Template"
        mock_hash.assert_called_once()

    @patch.object(RepoFile, "_get")
    def test_sha_ref_skips_resolution(self, mock_get):
        sha = "a" * 40
        rf = RepoFile("github", "org", "repo", "/template.yaml", sha)
        mock_response = MagicMock()
        mock_response.status_code = 200
        mock_response.content = b"kind: Template"
        mock_get.return_value = mock_response

        commit, content = rf._fetch_github()
        assert commit == sha

    @patch.object(RepoFile, "_get_gh_commit_hash", return_value="a" * 40)
    @patch.object(RepoFile, "_get")
    def test_404_raises_fatal(self, mock_get, mock_hash):
        rf = RepoFile("github", "org", "repo", "/missing.yaml", "main")
        mock_response = MagicMock()
        mock_response.status_code = 404
        mock_get.return_value = mock_response

        with pytest.raises(FatalError, match="not found"):
            rf._fetch_github()


class TestRateLimitRetry:
    def test_rate_limit_retries(self):
        rf = RepoFile("github", "org", "repo", "/t.yaml")

        rate_limited = MagicMock()
        rate_limited.status_code = 429
        rate_limited.request = MagicMock(url="https://example.com")
        rate_limited.headers = {"retry-after": "0"}
        rate_limited.text = ""

        ok = MagicMock()
        ok.status_code = 200
        ok.request = MagicMock(url="https://example.com")

        rf._session = MagicMock()
        rf._session.get.side_effect = [rate_limited, ok]

        with patch("bonfire_lib.repo_fetch.time.sleep"):
            result = rf._get("https://example.com")

        assert result.status_code == 200
        assert rf._session.get.call_count == 2

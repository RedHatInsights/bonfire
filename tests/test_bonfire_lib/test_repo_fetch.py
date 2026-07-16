"""Tests for bonfire_lib.repo_fetch module."""

import pytest
from unittest.mock import MagicMock, patch

from bonfire_lib.repo_fetch import RepoFile, GH_RAW_URL
from bonfire_lib.utils import FatalError


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
            RepoFile.from_component({
                "host": "github",
                "repo": "noslash",
                "path": "/t.yaml",
            })

    def test_default_ref(self):
        component = {
            "host": "github",
            "repo": "org/repo",
            "path": "/t.yaml",
        }
        rf = RepoFile.from_component(component)
        assert rf.ref == "master"


class TestFetchGithub:
    @patch.object(RepoFile, "_get_gh_commit_hash", return_value="abc1234567890abcdef1234567890abcdef123456")
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

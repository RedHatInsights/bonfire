"""Fetch template files from GitHub/GitLab over HTTP.

Simplified extraction of bonfire/utils.py RepoFile — uses raw HTTP
fetches only (no git clone, no sh dependency). Supports GitHub and
GitLab hosts with rate-limit retry, alternate ref fallback, and
commit SHA resolution.
"""

import logging
import os
import re
import time
from pathlib import Path
from urllib.parse import quote

import requests
from cached_property import cached_property

from bonfire_lib import config
from bonfire_lib.utils import FatalError

log = logging.getLogger(__name__)

GH_RAW_URL = "https://raw.githubusercontent.com/{org}/{repo}/{ref}{path}"
GH_BRANCH_URL = config.GH_API_URL.rstrip("/") + "/repos/{org}/{repo}/git/refs/heads/{branch}"

GL_RAW_URL = "https://gitlab.cee.redhat.com/{group}/{project}/-/raw/{ref}{path}"
GL_PROJECTS_URL = "https://gitlab.cee.redhat.com/api/v4/{type}/{group}/projects?search={name}"
GL_BRANCH_URL = "https://gitlab.cee.redhat.com/api/v4/projects/{id}/repository/branches/{branch}"

# CA cert bundled with the package: the long-lived Red Hat IT Root CA (valid
# until 2055) that gitlab.cee.redhat.com chains to. Bundling it avoids fetching a
# cert from certs.corp.redhat.com at runtime, which is not reliably reachable
# from CI/Tekton runtimes (DNS lookups for that host fail intermittently).
# Override via $BONFIRE_GL_CA_CERT (parsed in bonfire_lib.config).
_BUNDLED_GL_CA_CERT = Path(__file__).parent / "certs" / "2022-IT-Root-CA.pem"

GIT_SHA_RE = re.compile(r"[a-f0-9]{40}")

_gl_ca_cert_path = None


def _get_gl_ca_cert():
    """Resolve the GitLab CA certificate file path.

    The bundled Red Hat IT Root CA is used by default; set ``$BONFIRE_GL_CA_CERT``
    to override with a mounted / pre-installed CA bundle. Nothing is fetched at
    runtime. The resolved path is cached for subsequent calls.
    """
    global _gl_ca_cert_path
    if _gl_ca_cert_path is not None:
        return _gl_ca_cert_path

    override = config.GL_CA_CERT
    if override:
        if not os.path.isfile(override):
            raise FatalError(
                f"{config.GL_CA_CERT_ENV} is set to '{override}' but no file exists there"
            )
        log.debug("using GitLab CA certificate from %s=%s", config.GL_CA_CERT_ENV, override)
        _gl_ca_cert_path = override
    elif _BUNDLED_GL_CA_CERT.is_file():
        log.debug("using bundled GitLab CA certificate at %s", _BUNDLED_GL_CA_CERT)
        _gl_ca_cert_path = str(_BUNDLED_GL_CA_CERT)
    else:
        raise FatalError(
            f"bundled GitLab CA certificate is missing at {_BUNDLED_GL_CA_CERT}; "
            f"set {config.GL_CA_CERT_ENV} to a locally-available CA bundle path"
        )

    return _gl_ca_cert_path


class RepoFile:
    """Fetch a file from a GitHub or GitLab repository via HTTP."""

    def __init__(self, host, org, repo, path, ref="master"):
        if host not in ("github", "gitlab"):
            raise FatalError(f"unsupported repo host type: {host}")

        if not path.startswith("/"):
            path = f"/{path}"

        self.host = host
        self.org = org
        self.repo = repo
        self.path = path
        self.ref = ref
        self._alternate_refs = {
            "master": ["main", "stable"],
        }
        self._session = requests.Session()

    @classmethod
    def from_component(cls, component: dict) -> "RepoFile":
        """Create from a component config dict returned by qontract.

        Expected keys: host, repo (as "org/repo"), path, ref.
        """
        required_keys = ["host", "repo", "path"]
        missing = [k for k in required_keys if k not in component]
        if missing:
            raise FatalError(f"component config missing keys: {', '.join(missing)}")

        repo_str = component["repo"]
        host = component["host"]

        if host in ("github", "gitlab"):
            if "/" not in repo_str:
                raise FatalError(f"invalid repo '{repo_str}', expected format: <org>/<repo>")
            last_slash = repo_str.rindex("/")
            org = repo_str[:last_slash]
            repo = repo_str[last_slash + 1 :]
        else:
            raise FatalError(f"unsupported host '{host}'")

        return cls(host, org, repo, component["path"], component.get("ref", "master"))

    def fetch(self) -> tuple[str, bytes]:
        """Fetch the template file content.

        Returns:
            (commit_hash, file_content_bytes) tuple
        """
        try:
            if self.host == "github":
                return self._fetch_github()
            else:
                return self._fetch_gitlab()
        finally:
            self._session.close()

    @cached_property
    def _gl_certfile(self):
        return _get_gl_ca_cert()

    @cached_property
    def _gh_auth_headers(self):
        if config.GH_TOKEN:
            return {"Authorization": f"token {config.GH_TOKEN}"}
        return None

    def _get_ref(self, get_ref_func):
        """Try fetching a git ref, falling back to alternates if needed."""
        refs_to_try = [self.ref]
        if self.ref in self._alternate_refs:
            refs_to_try += self._alternate_refs[self.ref]

        response = None
        for idx, ref in enumerate(refs_to_try):
            log.debug("attempting ref '%s'", ref)
            response = get_ref_func(ref)
            if response.status_code == 200:
                log.info("fetch succeeded for ref '%s'", ref)
                break
            else:
                log.info(
                    "failed to fetch ref '%s' (http %d)",
                    ref,
                    response.status_code,
                )
                if idx + 1 < len(refs_to_try):
                    continue
                alts_txt = ""
                if self.ref in self._alternate_refs:
                    alts = ", ".join(self._alternate_refs[self.ref])
                    alts_txt = f" and alternates: {alts}"
                raise FatalError(f"git ref fetch failed for '{self.ref}'{alts_txt}")

        return response

    def _get(self, *args, **kwargs):
        """GET with rate-limit retry handling."""
        attempt = kwargs.pop("_attempt", 1)

        response = self._session.get(*args, **kwargs)
        status_code = response.status_code
        url = response.request.url

        if status_code == 429 or (
            status_code == 403 and "api rate limit exceeded" in response.text.lower()
        ):
            if attempt == 3:
                raise FatalError(f"GET {url} continues to hit rate limit after 3 attempts")

            if "retry-after" in response.headers:
                sleep_seconds = int(response.headers["retry-after"])
            elif response.headers.get("x-ratelimit-remaining") == "0":
                reset_time = int(response.headers["x-ratelimit-reset"]) or time.time() + 60
                sleep_seconds = reset_time - time.time()
            else:
                sleep_seconds = 60

            log.warning("GET %s rate limited, retrying after %ds", url, sleep_seconds)
            time.sleep(sleep_seconds)
            kwargs["_attempt"] = attempt + 1
            return self._get(*args, **kwargs)

        return response

    def _get_gh_commit_hash(self):
        def get_ref_func(ref):
            url = GH_BRANCH_URL.format(org=self.org, repo=self.repo, branch=ref)
            return self._get(url, headers=self._gh_auth_headers)

        response = self._get_ref(get_ref_func)
        response_json = response.json()
        if isinstance(response_json, list):
            return response_json[0]["object"]["sha"]
        return response_json["object"]["sha"]

    def _fetch_github(self):
        commit = self.ref
        if not GIT_SHA_RE.match(commit):
            commit = self._get_gh_commit_hash()

        url = GH_RAW_URL.format(org=self.org, repo=self.repo, ref=commit, path=self.path)
        response = self._get(url, headers=self._gh_auth_headers)
        if response.status_code == 404:
            raise FatalError(f"template not found at {url} (http 404)")
        response.raise_for_status()
        return commit, response.content

    def _get_gl_commit_hash(self):
        group, project = quote(self.org, safe=""), self.repo
        url = GL_PROJECTS_URL.format(type="groups", group=group, name=project)
        response = self._get(url, verify=self._gl_certfile)
        if response.status_code == 404:
            response = self._get(
                GL_PROJECTS_URL.format(type="users", group=group, name=project),
                verify=self._gl_certfile,
            )
        response.raise_for_status()
        projects = response.json()

        project_id = 0
        for p in projects:
            if p["path"] == project:
                project_id = p["id"]

        if not project_id:
            raise FatalError(f"gitlab project ID not found for {self.org}/{self.repo}")

        def get_ref_func(ref):
            return self._get(
                GL_BRANCH_URL.format(id=project_id, branch=ref),
                verify=self._gl_certfile,
            )

        response = self._get_ref(get_ref_func)
        return response.json()["commit"]["id"]

    def _fetch_gitlab(self):
        commit = self.ref
        if not GIT_SHA_RE.match(commit):
            commit = self._get_gl_commit_hash()

        url = GL_RAW_URL.format(group=self.org, project=self.repo, ref=commit, path=self.path)
        response = self._get(url, verify=self._gl_certfile)
        if response.status_code == 404:
            raise FatalError(f"template not found at {url} (http 404)")
        response.raise_for_status()
        return commit, response.content

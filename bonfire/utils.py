import atexit
import logging
import os
import re
import requests
import shlex
import subprocess
import tempfile

from cached_property import cached_property

GH_RAW_URL = "https://raw.githubusercontent.com/{org}/{repo}/{ref}{path}"
GL_RAW_URL = "https://gitlab.cee.redhat.com/{group}/{project}/-/raw/{ref}{path}"
GH_BRANCH_URL = "https://api.github.com/repos/{org}/{repo}/git/refs/heads/{branch}"
GL_PROJECTS_URL = "https://gitlab.cee.redhat.com/api/v4/{type}/{group}/projects/?per_page=100"
GL_BRANCH_URL = "https://gitlab.cee.redhat.com/api/v4/projects/{id}/repository/branches/{branch}"

GIT_SHA_RE = re.compile(r"[a-f0-9]{40}")

GL_CA_CERT = """
-----BEGIN CERTIFICATE-----
MIIENDCCAxygAwIBAgIJANunI0D662cnMA0GCSqGSIb3DQEBCwUAMIGlMQswCQYD
VQQGEwJVUzEXMBUGA1UECAwOTm9ydGggQ2Fyb2xpbmExEDAOBgNVBAcMB1JhbGVp
Z2gxFjAUBgNVBAoMDVJlZCBIYXQsIEluYy4xEzARBgNVBAsMClJlZCBIYXQgSVQx
GzAZBgNVBAMMElJlZCBIYXQgSVQgUm9vdCBDQTEhMB8GCSqGSIb3DQEJARYSaW5m
b3NlY0ByZWRoYXQuY29tMCAXDTE1MDcwNjE3MzgxMVoYDzIwNTUwNjI2MTczODEx
WjCBpTELMAkGA1UEBhMCVVMxFzAVBgNVBAgMDk5vcnRoIENhcm9saW5hMRAwDgYD
VQQHDAdSYWxlaWdoMRYwFAYDVQQKDA1SZWQgSGF0LCBJbmMuMRMwEQYDVQQLDApS
ZWQgSGF0IElUMRswGQYDVQQDDBJSZWQgSGF0IElUIFJvb3QgQ0ExITAfBgkqhkiG
9w0BCQEWEmluZm9zZWNAcmVkaGF0LmNvbTCCASIwDQYJKoZIhvcNAQEBBQADggEP
ADCCAQoCggEBALQt9OJQh6GC5LT1g80qNh0u50BQ4sZ/yZ8aETxt+5lnPVX6MHKz
bfwI6nO1aMG6j9bSw+6UUyPBHP796+FT/pTS+K0wsDV7c9XvHoxJBJJU38cdLkI2
c/i7lDqTfTcfLL2nyUBd2fQDk1B0fxrskhGIIZ3ifP1Ps4ltTkv8hRSob3VtNqSo
GxkKfvD2PKjTPxDPWYyruy9irLZioMffi3i/gCut0ZWtAyO3MVH5qWF/enKwgPES
X9po+TdCvRB/RUObBaM761EcrLSM1GqHNueSfqnho3AjLQ6dBnPWlo638Zm1VebK
BELyhkLWMSFkKwDmne0jQ02Y4g075vCKvCsCAwEAAaNjMGEwHQYDVR0OBBYEFH7R
4yC+UehIIPeuL8Zqw3PzbgcZMB8GA1UdIwQYMBaAFH7R4yC+UehIIPeuL8Zqw3Pz
bgcZMA8GA1UdEwEB/wQFMAMBAf8wDgYDVR0PAQH/BAQDAgGGMA0GCSqGSIb3DQEB
CwUAA4IBAQBDNvD2Vm9sA5A9AlOJR8+en5Xz9hXcxJB5phxcZQ8jFoG04Vshvd0e
LEnUrMcfFgIZ4njMKTQCM4ZFUPAieyLx4f52HuDopp3e5JyIMfW+KFcNIpKwCsak
oSoKtIUOsUJK7qBVZxcrIyeQV2qcYOeZhtS5wBqIwOAhFwlCET7Ze58QHmS48slj
S9K0JAcps2xdnGu0fkzhSQxY8GPQNFTlr6rYld5+ID/hHeS76gq0YG3q6RLWRkHf
4eTkRjivAlExrFzKcljC4axKQlnOvVAzz+Gm32U0xPBF4ByePVxCJUHw1TsyTmel
RxNEp7yHoXcwn+fXna+t5JWh1gxUZty3
-----END CERTIFICATE-----
"""

log = logging.getLogger(__name__)


def get_dupes(iterable):
    count_for = {}
    for item in iterable:
        if item not in count_for:
            count_for[item] = 0
        count_for[item] += 1

    dupes = []
    for item, count in count_for.items():
        if count > 1:
            dupes.append(item)

    return dupes


def split_equals(list_of_str, allow_null=False):
    """
    parse multiple key=val string arguments into a single dictionary
    """
    if not list_of_str:
        return {}

    if allow_null:
        equals_regex = re.compile(r"^(\S+=\S+|\S+=)$")
    else:
        equals_regex = re.compile(r"^\S+=\S+$")

    output = {}

    for item in list_of_str:
        item = str(item)
        if not equals_regex.match(item):
            raise ValueError(
                f"invalid format for value '{item}', must match: r'{equals_regex.pattern}'"
            )
        key, val = item.split("=")
        output[key] = val

    return output


class RepoFile:
    def __init__(self, host, org, repo, path, ref="master"):
        if host not in ["local", "github", "gitlab"]:
            raise ValueError(f"invalid repo host type: {host}")

        if not path.startswith("/"):
            path = f"/{path}"

        self.host = host
        self.org = org
        self.repo = repo
        self.path = path
        self.ref = ref

    @classmethod
    def from_config(cls, d):
        required_keys = ["host", "repo", "path"]
        missing_keys = [k for k in required_keys if k not in d.keys()]
        if missing_keys:
            raise ValueError(f"repo config missing keys: {', '.join(missing_keys)}")

        repo = d["repo"]
        if d["host"] in ["github", "gitlab"]:
            if "/" not in repo:
                raise ValueError(
                    f"invalid value for repo '{repo}', required format: <org>/<repo name>"
                )
            org, repo = repo.split("/")
        elif d["host"] == "local":
            org = "local"

        return cls(d["host"], org, repo, d["path"], d.get("ref", "master"))

    def fetch(self):
        if self.host == "local":
            return self._fetch_local()
        if self.host == "github":
            return self._fetch_github()
        if self.host == "gitlab":
            return self._fetch_gitlab()

    @cached_property
    def _gl_certfile(self):
        with tempfile.NamedTemporaryFile(delete=False) as fp:
            cert_fname = fp.name
            fp.write(GL_CA_CERT.encode("ascii"))

        atexit.register(os.unlink, cert_fname)

        return cert_fname

    def _get_gl_commit_hash(self):
        group, project = self.org, self.repo
        response = requests.get(
            GL_PROJECTS_URL.format(type="groups", group=group), verify=self._gl_certfile
        )
        if response.status_code == 404:
            # Weird quirk in gitlab API. If it's a user instead of a group, need to
            # use a different path
            response = requests.get(
                GL_PROJECTS_URL.format(type="users", group=group), verify=self._gl_certfile
            )
        response.raise_for_status()
        projects = response.json()
        project_id = 0

        for p in projects:
            if p["path"] == project:
                project_id = p["id"]

        if not project_id:
            raise ValueError("gitlab project ID not found for {self.org}/{self.repo}")

        response = requests.get(
            GL_BRANCH_URL.format(id=project_id, branch=self.ref), verify=self._gl_certfile
        )
        response.raise_for_status()
        return response.json()["commit"]["id"]

    def _fetch_gitlab(self):
        commit = self.ref
        if not GIT_SHA_RE.match(commit):
            # look up the commit hash for this branch
            commit = self._get_gl_commit_hash()

        url = GL_RAW_URL.format(group=self.org, project=self.repo, ref=commit, path=self.path)
        response = requests.get(url, verify=self._gl_certfile)
        response.raise_for_status()

        return commit, response.content

    def _get_gh_commit_hash(self):
        response = requests.get(GH_BRANCH_URL.format(org=self.org, repo=self.repo, branch=self.ref))
        response.raise_for_status()
        return response.json()["object"]["sha"]

    def _fetch_github(self):
        commit = self.ref
        if not GIT_SHA_RE.match(commit):
            # look up the commit hash for this branch
            commit = self._get_gh_commit_hash()

        response = requests.get(
            GH_RAW_URL.format(org=self.org, repo=self.repo, ref=commit, path=self.path)
        )
        response.raise_for_status()
        return commit, response.content

    def _fetch_local(self):
        repodir = os.path.expanduser(self.repo)
        cmd = f"git -C {repodir} rev-parse HEAD"
        commit = subprocess.check_output(shlex.split(cmd)).decode("ascii")
        p = os.path.join(repodir, self.path.lstrip("/"))
        with open(p) as fp:
            return commit, fp.read()

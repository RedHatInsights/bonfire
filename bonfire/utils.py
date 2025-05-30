import atexit
import copy
import difflib
from functools import lru_cache
import json
import logging
import os
import pprint
import re
import shlex
import socket
import subprocess
import tempfile
import time
from urllib.request import urlretrieve
import sys

if sys.version_info >= (3, 8):
    import importlib.metadata as importlib_metadata
else:
    import importlib_metadata

from packaging import version
from pathlib import Path
from urllib.parse import urlparse

from typing import List

import sys

import requests
import yaml
from cached_property import cached_property


class FatalError(Exception):
    """An exception that will cause the CLI to exit"""

    pass


def get_config_path():
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        config_home = Path(xdg_config_home)
    else:
        config_home = Path.home().joinpath(".config")

    return config_home.joinpath("bonfire")


PKG_NAME = "crc-bonfire"
PYPI_URL = f"https://pypi.python.org/pypi/{PKG_NAME}/json"

VER_CHECK_PATH = get_config_path().joinpath("lastvercheck")
VER_CHECK_TIME = 3600  # check every 1hr

GH_RAW_URL = "https://raw.githubusercontent.com/{org}/{repo}/{ref}{path}"
GL_RAW_URL = "https://gitlab.cee.redhat.com/{group}/{project}/-/raw/{ref}{path}"
GH_API_URL = os.getenv("GITHUB_API_URL", "https://api.github.com")
GH_BRANCH_URL = GH_API_URL.rstrip("/") + "/repos/{org}/{repo}/git/refs/heads/{branch}"
GL_PROJECTS_URL = "https://gitlab.cee.redhat.com/api/v4/{type}/{group}/projects?search={name}"
GL_BRANCH_URL = "https://gitlab.cee.redhat.com/api/v4/projects/{id}/repository/branches/{branch}"
SYNTAX_ERR = "configuration syntax error"


GIT_SHA_RE = re.compile(r"[a-f0-9]{40}")
GL_CA_CERT_URL = "https://certs.corp.redhat.com/certs/2022-IT-Root-CA.pem"
_PARAM_REGEX = re.compile(r"\${(\S+)}")

log = logging.getLogger(__name__)


class AppOrComponentSelector:
    def __init__(
        self, select_all: bool = False, apps: List[str] = None, components: List[str] = None
    ):
        self.select_all = select_all
        self.apps = apps or []
        self.components = components or []

    @property
    def empty(self):
        return not self.select_all and not self.apps and not self.components

    def __str__(self):
        return (
            f"{self.__class__.__name__}"
            f"(select_all={self.select_all}, apps={self.apps}, components={self.components})"
        )

    def __len__(self):
        return len(self.apps)


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
        equals_regex = re.compile(r"^(\S+=[\S ]+|\S+=)$")
    else:
        equals_regex = re.compile(r"^\S+=[\S ]+$")

    output = {}

    for item in list_of_str:
        item = str(item)
        if not equals_regex.match(item):
            raise ValueError(
                f"invalid format for value '{item}', must match: r'{equals_regex.pattern}'"
            )
        key, val = item.split("=", 1)
        output[key] = val

    return output


def validate_time_string(time):
    valid_time = re.compile(r"^((\d+)h)?((\d+)m)?((\d+)s)?$")
    if not valid_time.match(time):
        raise ValueError(
            f"invalid format for duration '{time}', expecting h/m/s string. Ex: '1h30m'"
        )
    seconds = hms_to_seconds(time)
    if seconds > 1209600:  # 14 days
        raise ValueError(f"invalid duration '{time}', must be less than 14 days")
    elif seconds < 1800:  # 30 mins
        raise ValueError(f"invalid duration '{time}', must be more than 30 mins")
    return time


class RepoFile:
    def __init__(self, host, org, repo, path, ref="master"):
        if host not in ["local", "github", "gitlab"]:
            raise FatalError(f"{SYNTAX_ERR}, invalid repo host type: {host}")

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
    def from_config(cls, d):
        required_keys = ["host", "repo", "path"]
        missing_keys = [k for k in required_keys if k not in d.keys()]
        if missing_keys:
            raise FatalError(f"{SYNTAX_ERR}, repo config missing keys: {', '.join(missing_keys)}")

        repo = d["repo"]
        if d["host"] in ["github", "gitlab"]:
            if "/" not in repo:
                raise FatalError(
                    f"{SYNTAX_ERR}, invalid value for repo '{repo}', required format: "
                    "<org>/<repo name>"
                )
            org, repo = repo.split("/")
        elif d["host"] == "local":
            org = "local"

        return cls(d["host"], org, repo, d["path"], d.get("ref", "master"))

    def fetch(self):
        if self.host == "local":
            result = self._fetch_local()
        if self.host == "github":
            result = self._fetch_github()
        if self.host == "gitlab":
            result = self._fetch_gitlab()

        self._session.close()

        return result

    @cached_property
    def _gl_certfile(self):
        with tempfile.NamedTemporaryFile(delete=False) as fp:
            urlretrieve(GL_CA_CERT_URL, fp.name)

        atexit.register(os.unlink, fp.name)
        return fp.name

    @cached_property
    def _gh_auth_headers(self):
        log_msg = f"using GITHUB_API_URL '{GH_API_URL}' with no authorization"
        headers = None

        gh_token = os.getenv("GITHUB_TOKEN")
        if gh_token:
            log_msg = f"using GITHUB_API_URL '{GH_API_URL}' with GITHUB_TOKEN"
            headers = {"Authorization": f"token {gh_token}"}

        log.debug(log_msg)
        return headers

    def _get_ref(self, get_ref_func):
        """
        Wrapper to attempt fetching a git ref and trying alternate refs if needed

        Calls get_ref_func(ref) for each ref to attempt fetching.

        get_ref_func is a function defined by the caller which should return a requests.Response
        """
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
                    "failed to fetch git ref '%s' (http code: %d, response txt: %s)",
                    ref,
                    response.status_code,
                    response.text,
                )
                if idx + 1 < len(refs_to_try):
                    # more alternates to try...
                    log.info("trying alternate: %s", refs_to_try[idx + 1])
                    continue
                else:
                    alts_txt = ""
                    if self.ref in self._alternate_refs:
                        alts = ", ".join(self._alternate_refs[self.ref])
                        alts_txt = f" and its alternates: {alts}"
                    raise Exception(
                        f"git ref fetch failed for '{self.ref}'{alts_txt}, see logs for details"
                    )

        return response

    def _get_gl_commit_hash(self):
        group, project = self.org, self.repo
        url = GL_PROJECTS_URL.format(type="groups", group=group, name=project)
        check_url_connection(url)
        response = self._get(url, verify=self._gl_certfile)
        if response.status_code == 404:
            # Weird quirk in gitlab API. If it's a user instead of a group, need to
            # use a different path
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
            raise FatalError(
                f"gitlab project ID not found for {self.org}/{self.repo}."
                " If you are sure it is correct, check the repository's read permissions."
            )

        def get_ref_func(ref):
            return self._get(
                GL_BRANCH_URL.format(id=project_id, branch=ref), verify=self._gl_certfile
            )

        response = self._get_ref(get_ref_func)
        return response.json()["commit"]["id"]

    def _fetch_gitlab(self):
        commit = self.ref
        if not GIT_SHA_RE.match(commit):
            # look up the commit hash for this branch
            commit = self._get_gl_commit_hash()

        url = GL_RAW_URL.format(group=self.org, project=self.repo, ref=commit, path=self.path)
        check_url_connection(url)
        response = self._get(url, verify=self._gl_certfile)
        if response.status_code == 404:
            log.warning(
                "http response 404 for url %s, checking for template in current working dir...", url
            )
            return self._fetch_local(os.getcwd())
        else:
            response.raise_for_status()

        return commit, response.content

    def _get(self, *args, **kwargs):
        """Send a GET with handler for 403/429 rate limit errors."""
        attempt = kwargs.pop("_attempt", 1)

        response = self._session.get(*args, **kwargs)
        status = response.status_code
        url = response.request.url

        if status == 429 or (status == 403 and "api rate limit exceeded" in response.text.lower()):
            if attempt == 3:
                raise Exception(f"GET {url} continues to hit rate limit after 3 attempts")

            if "retry-after" in response.headers:
                sleep_seconds = int(response.headers["retry-after"])

            elif response.headers.get("x-ratelimit-remaining") == "0":
                reset_time = int(response.headers["x-ratelimit-reset"]) or time.time() + 60
                sleep_seconds = reset_time - time.time()

            else:
                sleep_seconds = 60

            log.warning("GET %s exceeded rate limit, retrying after %d sec", url, sleep_seconds)

            time.sleep(sleep_seconds)
            kwargs["_attempt"] = attempt + 1
            return self._get(*args, **kwargs)

        return response

    def _get_gh_commit_hash(self):
        def get_ref_func(ref):
            url = GH_BRANCH_URL.format(org=self.org, repo=self.repo, branch=ref)
            check_url_connection(url)
            return self._get(url, headers=self._gh_auth_headers)

        response = self._get_ref(get_ref_func)
        response_json = response.json()
        if isinstance(response_json, list):
            return response_json[0]["object"]["sha"]
        return response_json["object"]["sha"]

    def _fetch_github(self):
        commit = self.ref
        if not GIT_SHA_RE.match(commit):
            # look up the commit hash for this branch
            commit = self._get_gh_commit_hash()

        url = GH_RAW_URL.format(org=self.org, repo=self.repo, ref=commit, path=self.path)
        check_url_connection(url)
        response = self._get(url, headers=self._gh_auth_headers)
        if response.status_code == 404:
            log.warning(
                "http response 404 for url %s, checking for template in current working dir...", url
            )
            return self._fetch_local(os.getcwd())
        else:
            response.raise_for_status()

        return commit, response.content

    def _fetch_local(self, repo_dir=None):
        if not repo_dir:
            repo_dir = os.path.expanduser(self.repo)
        cmd = "git rev-parse HEAD"
        commit = subprocess.check_output(shlex.split(cmd), cwd=repo_dir).decode("ascii")
        p = os.path.join(repo_dir, self.path.lstrip("/"))
        with open(p) as fp:
            return commit, fp.read()


def get_clowdapp_dependencies(items, optional=False):
    """
    Returns dict of clowdapp_name: set of dependencies found for any ClowdApps in 'items'

    if optional=True, returns set of optionalDependencies

    'items' is a list of k8s resources found in a template
    """
    key = "optionalDependencies" if optional else "dependencies"
    clowdapp_items = [item for item in items if item.get("kind").lower() == "clowdapp"]

    deps_for_app = dict()

    for clowdapp in clowdapp_items:
        name = clowdapp["metadata"]["name"]
        dependencies = {d for d in clowdapp["spec"].get(key, [])}
        log.debug("clowdapp '%s' has %s: %s", name, key, list(dependencies))
        deps_for_app[name] = dependencies

    return deps_for_app


def get_dependencies(items):
    """
    Returns set of dependencies found when looking at 'bonfire.dependencies' annotation on resources
    """
    deps = set()

    for item in items:
        kind = item.get("kind", "")
        metadata = item.get("metadata", {})
        name = metadata.get("name")
        annotations = metadata.get("annotations") or {}
        bonfire_deps = annotations.get("bonfire.dependencies", "").split(",")
        filtered_bonfire_deps = [dep for dep in bonfire_deps if dep]
        if name and filtered_bonfire_deps:
            log.debug(
                "resource %s/%s has bonfire.dependencies: %s",
                kind.lower(),
                name,
                list(filtered_bonfire_deps),
            )
            deps.update(filtered_bonfire_deps)

    return deps


def find_what_depends_on(apps_config, clowdapp_name):
    found = set()
    sorted_keys = sorted(apps_config.keys())
    for app_name in sorted_keys:
        app_config = apps_config[app_name]
        for component in app_config.get("components", []):
            component_name = component.get("name")
            try:
                rf = RepoFile.from_config(component)
                _, template_content = rf.fetch()
            except Exception as err:
                log.error("failed to fetch template file for %s: %s", component_name, err)

            template = yaml.safe_load(template_content)
            items = template.get("objects", [])

            dependencies = get_clowdapp_dependencies(items)
            optional_dependencies = get_clowdapp_dependencies(items, optional=True)

            all_dependencies = {}
            all_keys = dependencies.keys() | optional_dependencies.keys()
            for name in all_keys:
                all_dependencies[name] = dependencies.get(name, set()).union(
                    optional_dependencies.get(name, set())
                )

            for name, deps in all_dependencies.items():
                # check if the name of the ClowdApp is set with a parameter
                parameter_name = _PARAM_REGEX.findall(name)
                if parameter_name:
                    # replace 'name' with parameter's default value if found
                    for p in template.get("parameters", {}):
                        if p["name"] == parameter_name[0]:
                            name = p.get("value", name)

                # if this ClowdApp depends on the one we're interested in, add it to the list
                if clowdapp_name.strip().lower() in [d.strip().lower() for d in deps]:
                    found.add(name)

    return found


def load_file(path):
    """Load a .json/.yml/.yaml file."""
    if not os.path.isfile(path):
        raise FatalError("Path '{}' is not a file or does not exist".format(path))

    _, file_ext = os.path.splitext(path)

    with open(path, "rb") as f:
        if file_ext == ".yaml" or file_ext == ".yml":
            content = yaml.safe_load(f)
        elif file_ext == ".json":
            content = json.load(f)
        else:
            raise FatalError("File '{}' must be a YAML or JSON file".format(path))

    if not content:
        raise FatalError("File '{}' is empty!".format(path))

    return content


def get_version():
    try:
        return importlib_metadata.version(PKG_NAME)
    except importlib_metadata.PackageNotFoundError:
        return "0.0.0"


def _compare_version(pypi_version):
    pypi_version = version.parse(pypi_version)

    local_version = get_version()
    try:
        my_version = version.parse(local_version)
    except ValueError:
        log.info(f"version {local_version} seems to be a dev version, assuming up-to-date")
        return

    if my_version < pypi_version:
        log.info(
            "new release found"
            "\n\n"
            "there is a new bonfire version available! "
            f"(yours: {my_version}, available: {pypi_version})"
            "\n\n"
            "upgrade with:\n"
            f"    pip install --upgrade {PKG_NAME}"
            "\n"
        )
    else:
        log.info("up-to-date!")


def _update_ver_check_file():
    ver_check_file = Path(VER_CHECK_PATH)
    try:
        with ver_check_file.open(mode="w") as fp:
            fp.write(str(time.time()))
    except OSError:
        log.error("failed to update version check file at path: %s", ver_check_file.resolve())


def _ver_check_needed():
    ver_check_file = Path(VER_CHECK_PATH)
    if not ver_check_file.exists():
        _update_ver_check_file()
        return True

    last_check_time = 0
    try:
        with ver_check_file.open() as fp:
            last_check_time = float(fp.read().strip())
    except (OSError, ValueError):
        log.exception("failed to read version check file at path: %s", ver_check_file.resolve())

    if time.time() > last_check_time + VER_CHECK_TIME:
        _update_ver_check_file()
        return True

    return False


def check_pypi():
    if not _ver_check_needed():
        return

    log.info("checking pypi for latest release...")

    pkg_data = {}
    try:
        response = requests.get(PYPI_URL, timeout=5)
        response.raise_for_status()
        pkg_data = response.json()
    except requests.exceptions.RequestException as err:
        log.error("error fetching version from pypi: %s", err)
        return
    except ValueError:
        log.error("response was not valid json")

    try:
        pypi_version = pkg_data["info"]["version"]
    except KeyError:
        log.error("unable to parse version info from pypi")
    else:
        _compare_version(pypi_version)


def hms_to_seconds(s):
    fmt = r"^(\d+h)?(\d+m)?(\d+s)?$"

    split = re.split(fmt, s)

    seconds = 0

    for group in split:
        if group:  # to ignore 'None' groups when all units aren't present
            if "h" in group:
                seconds += int(group.split("h")[0]) * 3600
            elif "m" in group:
                seconds += int(group.split("m")[0]) * 60
            elif "s" in group:
                seconds += int(group.split("s")[0])

    return seconds


@lru_cache(maxsize=None)
def _check_connection(hostname, port=443, timeout=5):
    """
    Check connection makes sure a connection is available to a given hostname.

    Function is cached so that we only check a hostname once.
    """
    log.debug("checking connection to '%s', port %d, timeout %ssec", hostname, port, timeout)

    try:
        with socket.socket(socket.AF_INET, socket.SOCK_STREAM) as test_connection_socket:
            test_connection_socket.settimeout(timeout)
            test_connection_socket.connect((hostname, port))
    except socket.gaierror:
        raise FatalError(
            f"DNS lookup failed for '{hostname}' -- check network connection (is VPN needed?)"
        )
    except (OSError, TimeoutError):
        raise FatalError(
            f"Unable to connect to '{hostname}' on port {port} after {timeout} "
            f"seconds -- check network connection (is VPN needed?)"
        )


def check_url_connection(url, timeout=5):
    parsed_url = urlparse(url)
    scheme = parsed_url.scheme
    hostname = parsed_url.hostname
    port = parsed_url.port
    if scheme not in ("http", "https") or not hostname:
        raise ValueError(f"Invalid URL: '{url}'")
    if not port:
        port = 443 if scheme == "https" else 80
    _check_connection(hostname=hostname, port=port, timeout=timeout)


def object_merge(old, new, merge_lists=True):
    """
    Recursively merge two data structures
    Thanks rsnyman :)
    https://github.com/rochacbruno/dynaconf/commit/458ffa6012f1de62fc4f68077f382ab420b43cfc#diff-c1b434836019ae32dc57d00dd1ae2eb9R15
    """
    if isinstance(old, list) and isinstance(new, list) and merge_lists:
        for item in old[::-1]:
            new.insert(0, item)
    if isinstance(old, dict) and isinstance(new, dict):
        for key, value in old.items():
            if key not in new:
                new[key] = value
            else:
                object_merge(value, new[key])
    return new


def _log_diff(old_apps_config, new_apps_config):
    old_lines = pprint.pformat(old_apps_config).splitlines()
    new_lines = pprint.pformat(new_apps_config).splitlines()
    compare_result = difflib.unified_diff(old_lines, new_lines)
    diff = "\n".join(compare_result)
    log.info("diff in apps config after merging local config into remote config:\n%s", diff)


def merge_app_configs(apps_config, new_apps, method="merge"):
    """
    Merge configurations found in new_apps into apps_config
    """
    old_apps_config = copy.deepcopy(apps_config)

    if method == "override":
        # with this method, any app defined in 'new_apps' completely overrides
        # the config in 'apps_config'
        apps_config.update(new_apps)
        _log_diff(old_apps_config, apps_config)
        return apps_config

    for app_name, new_app_cfg in new_apps.items():
        # if the newly defined app is not present in remote apps, add the whole app config
        if app_name not in apps_config:
            apps_config[app_name] = new_app_cfg
            continue

        # 'components' key should be present but we'll initialize it as [] if it is absent
        apps_config[app_name]["components"] = apps_config[app_name].get("components") or []
        app_components = apps_config[app_name]["components"]
        new_apps[app_name]["components"] = new_apps[app_name].get("components") or []
        new_app_components = new_apps[app_name]["components"]

        # if the newly defined app is present in existing apps, merge the components config
        app_components_orig = copy.deepcopy(app_components)

        for new_component in new_app_components:
            component_name = new_component["name"]

            # find all components in existing config with matching name
            matched_components = [
                (idx, c) for idx, c in enumerate(app_components_orig) if c["name"] == component_name
            ]

            if len(matched_components) < 1:
                # this component doesn't exist in the existing apps config, just append it
                app_components.append(new_component)
            elif len(matched_components) == 1:
                # a component with matching name was found, merge their config together
                idx, component = matched_components[0]
                app_components[idx] = object_merge(component, new_component)
            else:
                # this scenario is probably rare but if there is more than one match
                # we won't know which component to merge config with
                raise ValueError(
                    f"config error: component '{component_name}' is defined "
                    f"more than once in app '{app_name}'"
                )

    _log_diff(old_apps_config, apps_config)
    return apps_config

import logging
import os
from pathlib import Path
from pkg_resources import resource_filename
import re

from dotenv import load_dotenv


log = logging.getLogger(__name__)


def _get_config_path():
    xdg_config_home = os.environ.get("XDG_CONFIG_HOME")
    if xdg_config_home:
        config_home = Path(xdg_config_home)
    else:
        config_home = Path.home().joinpath(".config")

    return config_home.joinpath("bonfire")


DEFAULT_CONFIG_PATH = _get_config_path().joinpath("config.yaml")
DEFAULT_ENV_PATH = _get_config_path().joinpath("env")
DEFAULT_CLOWDENV_TEMPLATE = resource_filename(
    "bonfire", "resources/ephemeral-clowdenvironment.yaml"
)
DEFAULT_LOCAL_CONFIG = resource_filename("bonfire", "resources/default_local_config.yaml")

ENV_FILE = str(DEFAULT_ENV_PATH.absolute()) if DEFAULT_ENV_PATH.exists() else ""
load_dotenv(ENV_FILE)

# for compatibility with app-sre team env vars
APP_INTERFACE_BASE_URL = os.getenv("APP_INTERFACE_BASE_URL")
APP_INTERFACE_USERNAME = os.getenv("APP_INTERFACE_USERNAME")
APP_INTERFACE_PASSWORD = os.getenv("APP_INTERFACE_PASSWORD")

LOCAL_GRAPHQL_URL = "http://localhost:4000/graphql"

QONTRACT_BASE_URL = os.getenv(
    "QONTRACT_BASE_URL",
    f"https://{APP_INTERFACE_BASE_URL}/graphql" if APP_INTERFACE_BASE_URL else LOCAL_GRAPHQL_URL,
)
QONTRACT_USERNAME = os.getenv("QONTRACT_USERNAME", APP_INTERFACE_USERNAME or None)
QONTRACT_PASSWORD = os.getenv("QONTRACT_PASSWORD", APP_INTERFACE_PASSWORD or None)
QONTRACT_TOKEN = os.getenv("QONTRACT_TOKEN")

RAW_GITHUB_URL = "https://raw.githubusercontent.com/{org}/{repo}/{ref}{path}"
RAW_GITLAB_URL = "https://gitlab.cee.redhat.com/{org}/{repo}/-/raw/{ref}{path}"

BASE_NAMESPACE_NAME = os.getenv("BASE_NAMESPACE_NAME", "ephemeral-base")
RESERVABLE_NAMESPACE_REGEX = re.compile(r"ephemeral-\d+")
EPHEMERAL_ENV_NAME = os.getenv("EPHEMERAL_ENV_NAME", "insights-ephemeral")
PROD_ENV_NAME = os.getenv("PROD_ENV_NAME", "insights-production")

ENV_NAME_FORMAT = "env-{namespace}"

RECONCILE_TIMEOUT = os.getenv("RECONCILE_TIMEOUT", 180)

OC_LOGIN_TOKEN = os.getenv("OC_LOGIN_TOKEN")
OC_LOGIN_SERVER = os.getenv("OC_LOGIN_SERVER")

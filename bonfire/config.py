import logging
import os
from pathlib import Path
from pkg_resources import resource_filename
import re
import shutil
import yaml

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
DEFAULT_CONFIG_DATA = resource_filename("bonfire", "resources/default_config.yaml")

LOCAL_GRAPHQL_URL = "http://localhost:4000/graphql"

ENV_FILE = str(DEFAULT_ENV_PATH.absolute()) if DEFAULT_ENV_PATH.exists() else ""
load_dotenv(ENV_FILE)

# used in app-sre jenkins jobs
APP_INTERFACE_BASE_URL = os.getenv("APP_INTERFACE_BASE_URL")
APP_INTERFACE_USERNAME = os.getenv("APP_INTERFACE_USERNAME")
APP_INTERFACE_PASSWORD = os.getenv("APP_INTERFACE_PASSWORD")
QONTRACT_BASE_URL = os.getenv(
    "QONTRACT_BASE_URL",
    f"https://{APP_INTERFACE_BASE_URL}/graphql" if APP_INTERFACE_BASE_URL else LOCAL_GRAPHQL_URL,
)
QONTRACT_USERNAME = os.getenv("QONTRACT_USERNAME", APP_INTERFACE_USERNAME or None)
QONTRACT_PASSWORD = os.getenv("QONTRACT_PASSWORD", APP_INTERFACE_PASSWORD or None)
QONTRACT_TOKEN = os.getenv("QONTRACT_TOKEN")
OC_LOGIN_TOKEN = os.getenv("OC_LOGIN_TOKEN")
OC_LOGIN_SERVER = os.getenv("OC_LOGIN_SERVER")

# env vars that could modify behavior of the jenkins reconciler job
BASE_NAMESPACE_NAME = os.getenv("BASE_NAMESPACE_NAME", "ephemeral-base")
RESERVABLE_NAMESPACE_REGEX = os.getenv("RESERVABLE_NAMESPACE_REGEX", re.compile(r"ephemeral-\d+"))
EPHEMERAL_ENV_NAME = os.getenv("EPHEMERAL_ENV_NAME", "insights-ephemeral")
RECONCILE_TIMEOUT = os.getenv("RECONCILE_TIMEOUT", 180)
ENV_NAME_FORMAT = os.getenv("ENV_NAME_FORMAT", "env-{namespace}")


def _load_file(path):
    with path.open() as fp:
        return yaml.safe_load(fp)


def write_default_config(outpath=None):
    outpath = Path(outpath) if outpath else DEFAULT_CONFIG_PATH
    outpath.parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    inpath = Path(DEFAULT_CONFIG_DATA)
    shutil.copy(inpath, outpath)
    outpath.chmod(0o600)
    log.info("saved config to: %s", outpath.absolute())


def load_config(config_path=None):
    if config_path:
        log.debug("user provided explicit config path: %s", config_path)
        config_path = Path(config_path)
        if not config_path.exists():
            raise ValueError(f"provided config file path '{str(config_path)}' does not exist")
    else:
        # no user-provided path, check default locations
        config_path = Path("config.yaml")
        if not config_path.exists():
            log.debug("./config.yaml not found, using default path: %s", DEFAULT_CONFIG_PATH)
            config_path = DEFAULT_CONFIG_PATH
            if not config_path.exists():
                write_default_config()
                log.info("default config not found, creating")

    log.debug("using local config file: %s", str(config_path.absolute()))
    local_config_data = _load_file(config_path)

    return local_config_data

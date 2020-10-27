import os


QONTRACT_BASE_URL = os.getenv("QONTRACT_BASE_URL", "http://localhost:4000/graphql")
QONTRACT_USERNAME = os.getenv("QONTRACT_USERNAME")
QONTRACT_PASSWORD = os.getenv("QONTRACT_PASSWORD")
QONTRACT_TOKEN = os.getenv("QONTRACT_TOKEN")

RAW_GITHUB_URL = "https://raw.githubusercontent.com/{org}/{repo}/{ref}{path}"
RAW_GITLAB_URL = "https://gitlab.cee.redhat.com/{org}/{repo}/-/raw/{ref}{path}"

BASE_NAMESPACE_NAME = os.getenv("BASE_NAMESPACE_NAME", "ephemeral-base")
EPHEMERAL_ENV_NAME = os.getenv("EPHEMERAL_ENV_NAME", "insights-ephemeral")
PROD_ENV_NAME = os.getenv("PROD_ENV_NAME", "insights-production")

ENV_NAME_FORMAT = "env-{namespace}"

RECONCILE_TIMEOUT = os.getenv("RECONCILE_TIMEOUT", 120)

OC_LOGIN_TOKEN = os.getenv("OC_LOGIN_TOKEN")
OC_LOGIN_SERVER = os.getenv("OC_LOGIN_SERVER")

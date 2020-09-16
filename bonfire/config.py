import os


APP_INTERFACE_BASE_URL = os.getenv("APP_INTERFACE_BASE_URL", "http://localhost:4000/graphql")
APP_INTERFACE_USERNAME = os.getenv("APP_INTERFACE_USERNAME")
APP_INTERFACE_PASSWORD = os.getenv("APP_INTERFACE_PASSWORD")
APP_INTERFACE_TOKEN = os.getenv("APP_INTERFACE_TOKEN")

RAW_GITHUB_URL = "https://raw.githubusercontent.com/{org}/{repo}/{ref}{path}"
RAW_GITLAB_URL = "https://gitlab.cee.redhat.com/{org}/{repo}/-/raw/{ref}{path}"

BASE_NAMESPACE = os.getenv("BASE_NAMESPACE_NAME", "ephemeral-base")
EPHEMERAL_ENV_NAME = os.getenv("EPHEMERAL_ENV_NAME", "insights-ephemeral")
PROD_ENV_NAME = os.getenv("PROD_ENV_NAME", "insights-production")

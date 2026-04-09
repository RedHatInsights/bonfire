"""Core resource template rendering.

Renders NamespaceReservation, ClowdEnvironment, and ClowdJobInvocation CRs
from Jinja2 YAML templates. Replaces the OpenShift Template YAML files in
bonfire/resources/ and the oc process calls in bonfire/processor.py.
"""

from pathlib import Path

import yaml
from jinja2 import Environment, FileSystemLoader

_TEMPLATE_DIR = Path(__file__).parent / "templates"
_env = Environment(loader=FileSystemLoader(_TEMPLATE_DIR), keep_trailing_newline=True)


def render_reservation(
    name: str,
    duration: str,
    requester: str,
    pool: str = "default",
    team: str | None = None,
    secrets_src_namespace: str | None = None,
) -> dict:
    """Render a NamespaceReservation CR as a Python dict."""
    template = _env.get_template("reservation.yaml.j2")
    rendered = template.render(
        name=name,
        duration=duration,
        requester=requester,
        pool=pool,
        team=team,
        secrets_src_namespace=secrets_src_namespace,
    )
    return yaml.safe_load(rendered)


def render_clowdenv(
    env_name: str,
    namespace: str,
    pull_secret_name: str = "quay-cloudservices-pull",
) -> dict:
    """Render a ClowdEnvironment CR as a Python dict."""
    template = _env.get_template("clowdenvironment.yaml.j2")
    rendered = template.render(
        env_name=env_name,
        namespace=namespace,
        pull_secret_name=pull_secret_name,
    )
    return yaml.safe_load(rendered)


def render_cji(
    name: str,
    app_name: str,
    env_name: str = "clowder_smoke",
    debug: bool = False,
    image_tag: str = "",
    marker: str = "",
    filter: str = "",
    plugins: str = "",
    requirements: str = "",
    requirements_priority: str = "",
    test_importance: str = "",
    deploy_selenium: bool = False,
    parallel_enabled: str = "true",
    parallel_worker_count: str = "2",
    rp_args: str = "",
    ibutsu_source: str = "",
) -> dict:
    """Render a ClowdJobInvocation CR as a Python dict."""
    template = _env.get_template("clowdjobinvocation.yaml.j2")
    rendered = template.render(
        name=name,
        app_name=app_name,
        env_name=env_name,
        debug=debug,
        image_tag=image_tag,
        marker=marker,
        filter=filter,
        plugins=plugins,
        requirements=requirements,
        requirements_priority=requirements_priority,
        test_importance=test_importance,
        deploy_selenium=deploy_selenium,
        parallel_enabled=parallel_enabled,
        parallel_worker_count=parallel_worker_count,
        rp_args=rp_args,
        ibutsu_source=ibutsu_source,
    )
    return yaml.safe_load(rendered)

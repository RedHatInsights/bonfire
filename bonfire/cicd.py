import os
import click
from pkg_resources import resource_filename
from jinja2 import Template

PR_CHECK_FRONTEND = resource_filename(__name__, "resources/pr_check_template.sh")
BUILD_DEPLOY_FRONTEND = resource_filename(__name__, "resources/pr_check_template.sh")
PR_CHECK_BACKEND = resource_filename(__name__, "resources/pr_check_template.sh")
BUILD_DEPLOY_BACKEND = resource_filename(__name__, "resources/pr_check_template.sh")

PR_CHECK = "pr_check.sh"
BUILD_DEPLOY = "build_deploy.sh"


class CICDTemplate:

    def __init__(self, app_name, component, project_type):
        self.app_name = app_name if app_name else get_app_name()
        self.component = component if component else self.app_name
        self.project_type = project_type if project_type else find_project_type()
        self.project_path = get_project_path()
        self.image_name = self.setup_image_name()
        self.template_vars = {
            "app_name": self.app_name,
            "image_name": self.image_name,
            "component": self.component
        }

    def init(self):
        self.create_pr_check()
        self.create_build_deploy()

    def setup_image_name(self):
        image_name = f"quay.io/cloudservices/{self.app_name}"
        if self.project_type == "frontend":
            image_name += "-frontend"
        return image_name

    def create_pr_check(self):
        if self.project_type == "frontend":
            click.echo("Creating pr_check.sh for frontend app " + self.app_name)
            self.render_template(PR_CHECK_FRONTEND, PR_CHECK)
        else:
            click.echo("Creating pr_check.sh for backend app " + self.app_name)
            self.render_template(PR_CHECK_BACKEND, PR_CHECK)
        click.echo("Created pr_check.sh in top level of " + self.project_path)

    def create_build_deploy(self):
        if self.project_type == "frontend":
            click.echo("Creating build_deploy.sh for frontend app " + self.app_name)
            self.render_template(BUILD_DEPLOY_FRONTEND, BUILD_DEPLOY)
        else:
            click.echo("Creating build_deploy.sh for backend app " + self.app_name)
            self.render_template(BUILD_DEPLOY_BACKEND, BUILD_DEPLOY)
        click.echo("Created build_deploy.sh in top level of " + self.project_path)

    def render_template(self, template_name, target_file):
        with open(template_name, "r") as f:
            template = Template(f.read())
        rendered_template = template.render(component=self.component, image_name=self.image_name)

        with open(os.path.join(os.getcwd(), target_file), 'w') as pr:
            for line in rendered_template:
                pr.write(line)
        # Chmod must use an octal number beginning with `0o`
        os.chmod(os.path.join(os.getcwd(), target_file), 0o755)


def get_project_path():
    return os.getcwd()


def get_app_name():
    return get_project_path().split("/")[-1]


def find_project_type():
    for dirpath, dirname, filename in os.walk(os.getcwd()):
        if "package.json" in filename:
            click.echo("Located package.json; Project type set to frontend. \
                If this is incorrect, please use bonfire cicd init <name> --backend true.")
            return "frontend"
    click.echo("No package.json in " + get_project_path() + ". Project type set to backend.")
    return "backend"


def init_cicd_files(app_name, component, project_type):
    template = CICDTemplate(app_name, component, project_type)
    template.init()

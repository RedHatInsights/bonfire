import os
import stat
import click
from pkg_resources import resource_filename

PR_CHECK_TEMPLATE = resource_filename(__name__, "resources/pr_check_template.sh")
BUILD_DEPLOY_TEMPLATE = resource_filename(__name__, "resources/pr_check_template.sh")

def get_project_name():
    return os.getcwd()

def create_pr_check():
    render_template(PR_CHECK_TEMPLATE)
    click.echo("Created pr_check.sh in top level of " + get_project_name())

def create_build_deploy():
    render_template(BUILD_DEPLOY_TEMPLATE)
    click.echo("Created build_deploy.sh in top level of " + get_project_name())

def find_project_type():
    for dirpath, dirname, filename in os.walk(os.getcwd()):
        if "package.json" in filename:
            click.echo("Located package.json; Project type set to frontend. If this is incorrect, please use bonfire cicd init backend.")
            return "frontend"
    click.echo("No package.json in " + get_project_name() + ". Project type set to backend.")
    return "backend"

def init_cicd_files(project_type):
    create_pr_check()
    create_build_deploy()

def render_template(filename):
    rendered_template = []
    with open(filename, "r") as f:
        lines = f.readlines()
        for l in lines:
            rendered_template.append(process_template_line(l))

    with open(os.path.join(os.getcwd(), "pr_check.sh"), 'w') as pr:
        for line in rendered_template:
            pr.write(line)
    # Chmod must use an octal number 0o
    os.chmod(os.path.join(os.getcwd(), "pr_check.sh"), 0o755)

def process_template_line(line):
    if "%" in line:
        processed = process_inline_var(line)
        return processed
    else:
        return line

def process_inline_var(line):
    VAR_INDEX=1
    app_name = "test"
    image_name = "quay.io/cloudservices/test"
    var_name = line.split("%")
    var_name[VAR_INDEX] = '"' + eval(var_name[VAR_INDEX]) + '"'
    return ''.join(var_name)

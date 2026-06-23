# Contributing

Thank you for your interest in contributing! This document outlines the process and guidelines for
contributing to this project.

## Getting Started

- Fork the repository
- Read the [project README][readme] and any additional documentation files for guidance on setting
  up the project locally
- Create a feature branch off the default branch with a descriptive name

## Environment Setup

Local development works best with a virtual environment. Not only will it keep your local dev python
environment separate from your system config, it will also make it easy to integrate with Visual
Studio Code for debugging.

```sh
# Get the code
git clone git@github.com:RedHatInsights/bonfire.git
cd bonfire
# Create the virtual environment
python3 -m venv .venv
# Activate the virtual environment
. .venv/bin/activate
# Install and update packages required by setuptools
pip install --upgrade pip setuptools wheel
# Build and install bonfire in editable mode
pip install -e .
```

> **Note:** When you want to launch VSCode make sure you are in the activated virtual environment
> and then run `code .` in the bonfire code directory.

## Visual Studio Code Config

Ensure you've set up the environment as shown above, as this VSCode launch config requires the steps
above to be completed first. With the environment set up, open your `launch.json` and add the
following config:

```json
{
    "version": "0.2.0",
    "configurations": [
        {
            "name": "Bonfire",
            "type": "python",
            "request": "launch",
            "program": "${cwd}/.venv/bin/bonfire",
            "console": "integratedTerminal",
            "justMyCode": true
        }
    ]
}
```

This will use the locally installed bonfire binary to launch your code. When you want to debug your
code, simply run the Bonfire launch task in VSCode.

## Opening a Pull Request

- Ensure your PR title is descriptive and summarizes the change
- Include a clear description of what the PR does and why the change is needed
- If your work is based on or co-authored with another contributor, credit them using the git
  co-author trailer format:

  ```text
  Co-authored-by: Name <email@example.com>
  ```

  This trailer should be added to the commit message itself, not the PR description

## Commit Messages

Write clear, descriptive commit messages that follow these guidelines:

- Use the imperative mood in the subject line (e.g., "Add feature" instead of "Added feature")
- Keep the subject line to 72 characters or less
- Separate the subject from the body with a blank line
- In the commit body, explain *what* changed and *why* it changed (not how)
- Reference relevant issues or discussions when applicable

**Example:**

```text
Fix authentication flow for token refresh

The previous implementation did not properly handle token expiration
during long-running operations. This change ensures tokens are
refreshed transparently without interrupting the user workflow.

Fixes #123
```

## Signing Commits

All commits must be signed with a GPG or SSH key to verify your identity and ensure commit
integrity.

To enable signing for all commits on your machine:

```sh
git config --global commit.gpgSign true
```

For detailed setup instructions, refer to the
[git-commit signing documentation][git-commit-signing].

## AI-Assisted Commit Messages

If you use an AI agent or tool to generate or refine your commit message, the following rules apply:

1. **Author responsibility:** You must read, understand, and edit the AI-generated message before
   committing. The final commit message is your responsibility, and you must ensure it accurately
   describes your changes.

1. **Disclose the tool:** Add a `Co-authored-by:` trailer to the commit to credit the AI tool used.
   Example:

   ```text
   Co-authored-by: Claude Sonnet 4.6 <noreply@anthropic.com>
   ```

   This makes it transparent to the project maintainers and other contributors that AI assistance
   was used in crafting the message.

## Optional: Conventional Commits

This project does not require a specific commit message format by default. However, if you
prefer structured commit messages with standardized prefixes, you may optionally adopt the
[Conventional Commits specification][conventional-commits-spec]. Under this convention, commits are
prefixed with types such as `feat:`, `fix:`, `docs:`, `refactor:`, etc. Using Conventional Commits
can make it easier to generate changelogs and track semantic versioning.

## Code Review

All contributions go through code review. Be prepared to:

- Respond to feedback promptly
- Make requested changes in new commits (avoid force-pushing unless asked)
- Discuss design decisions and tradeoffs openly

Thank you for contributing!

[readme]: ./README.md
[conventional-commits-spec]: https://www.conventionalcommits.org/
[git-commit-signing]: https://git-scm.com/docs/git-commit#Documentation/git-commit.txt--S

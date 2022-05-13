# Alternative to 'sed' to search/replace within a file using regex

import os
import re
import sys

import click


def _do_lines(search_regex, replace_regex, file_path):
    new_lines = []
    with open(file_path, "r") as fp:
        for line in fp:
            new_lines.append(re.sub(search_regex, replace_regex, line))
    return "".join(new_lines)  # \n already included in the re.sub return data


def _do_file(search_regex, replace_regex, file_path):
    with open(file_path, "r") as fp:
        data = fp.read()
    return re.sub(search_regex, replace_regex, data, flags=re.DOTALL)


def _error(msg):
    click.error(msg)
    sys.exit(1)


@click.command(context_settings=dict(help_option_names=["-h", "--help"]))
@click.argument("search_regex", required=True, type=str)
@click.argument("replace_regex", required=True, type=str)
@click.argument("file_path", required=True, type=str)
@click.option(
    "--in-place",
    "-i",
    is_flag=True,
    default=False,
    help="Overwrite file once replace is completed",
)
@click.option(
    "--lines",
    "-l",
    is_flag=True,
    default=False,
    help="Find re match on each line, not the entire file at once",
)
def main(search_regex, replace_regex, file_path, in_place, lines):
    if not os.path.exists(file_path):
        _error(f"file does not exist: {file_path}")
    if not os.path.isfile(file_path):
        _error(f"path is not a file: {file_path}")
    if not os.access(file_path, os.R_OK):
        _error(f"unable to file for reading: {file_path}")

    if lines:
        new_data = _do_lines(search_regex, replace_regex, file_path)
    else:
        new_data = _do_file(search_regex, replace_regex, file_path)

    if in_place:
        if not os.access(file_path, os.W_OK):
            _error(f"unable to file for writing: {file_path}")
        with open(file_path, "w") as fp:
            fp.write(new_data)
    else:
        print(new_data)


if __name__ == "__main__":
    main()

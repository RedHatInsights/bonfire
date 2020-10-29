import re


def split_equals(list_of_str, allow_null=False):
    """
    parse multiple key=val string arguments into a single dictionary
    """
    if not list_of_str:
        return {}

    if allow_null:
        equals_regex = re.compile(r"^(\S+=\S+|\S+=)$")
    else:
        equals_regex = re.compile(r"^\S+=\S+$")

    output = {}

    for item in list_of_str:
        item = str(item)
        if not equals_regex.match(item):
            raise ValueError(
                f"invalid format for value '{item}', must match: r'{equals_regex.pattern}'"
            )
        key, val = item.split("=")
        output[key] = val

    return output

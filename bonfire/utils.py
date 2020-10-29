import re


EQUALS_REGEX = re.compile(r"^\S+=\S+$")


def split_equals(list_of_str):
    """
    parse multiple key=val string arguments into a single dictionary
    """
    if not list_of_str:
        return {}

    output = {}

    for item in list_of_str:
        item = str(item)
        if not EQUALS_REGEX.match(item):
            raise ValueError(
                f"invalid format for value '{item}', must match: r'{EQUALS_REGEX.pattern}'"
            )
        key, val = item.split("=")
        output[key] = val

    return output
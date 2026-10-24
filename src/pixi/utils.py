from typing import Sequence

# helpers


def exists(value, allow_empty_string=False):
    if value is None:
        return False

    if isinstance(value, bool):
        return value

    if isinstance(value, (int, float)):
        return value != 0

    if isinstance(value, str):
        return value != "" or (value == "" and allow_empty_string)

    if isinstance(value, (list, tuple, dict)):
        return len(value) != 0

    return True



# modified from https://stackoverflow.com/a/76636817
def format_time(delta: float, min_count: int = 3, max_lenght: int = 2) -> str:
    """Return time difference as human-readable string"""

    periods = (
        ("year", 31536000),
        ("month", 2592000),
        ("week", 604800),
        ("day", 86400),
        ("hour", 3600),
        ("minute", 60),
        ("second", 1),
    )

    fmt_list = []
    for period, seconds_each in periods:
        if delta >= seconds_each:
            how_many = int(delta / seconds_each)
            if how_many >= min_count:
                fmt_list.append(f"{how_many} {period}{'s' if how_many >= 2 else ''}")
                if len(fmt_list) >= max_lenght:
                    break

                delta -= seconds_each * how_many

    if fmt_list:
        return " and ".join(fmt_list)

    return "just now"  # less than a second ago


def format_time_ago(delta: float, min_count: int = 3, max_lenght: int = 2) -> str:
    if delta >= min_count:
        return format_time(delta, min_count, max_lenght) + " ago"

    return "just now"  # less than a second ago


def format_time_later(delta: float, min_count: int = 3, max_lenght: int = 2) -> str:
    if delta >= min_count:
        return format_time(delta, min_count, max_lenght) + " later"

    return "just now"  # less than a second ago


def clean_dict(d: dict):
    final_dict = {}
    for k, v in d.items():
        if v is None:
            continue
        elif isinstance(v, dict):
            if len(v) == 0:
                continue
            v = clean_dict(v)
        elif isinstance(v, Sequence):
            if len(v) == 0:
                continue
            if not isinstance(v, str):  # other than strings, we every other sequence is a nested dynamic type
                v = [(clean_dict(e) if isinstance(e, dict) else e) for e in v]
        final_dict[k] = v
    return final_dict

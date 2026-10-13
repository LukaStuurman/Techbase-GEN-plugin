"""Recognize BAG residential use without inventing an electrical capacity."""
import re


def is_bag_object(doorlaat):
    return str(doorlaat).strip().casefold() == "verblijfsobject"


def has_residential_usage(usage):
    # OAPIF providers may expose multi-use values as lists or serialized lists.
    if isinstance(usage, (list, tuple, set)):
        return any(has_residential_usage(item) for item in usage)
    return re.search(r"(?<!\w)woonfunctie(?!\w)", str(usage).casefold()) is not None

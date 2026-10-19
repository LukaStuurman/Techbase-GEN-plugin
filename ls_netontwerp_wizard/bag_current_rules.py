"""Recognize BAG residential use without inventing an electrical capacity."""
import re

# A BAG object added via "Nieuwbouw" keeps its design assumption independent of the
# construction year stored on the physical BAG pand.
NEW_BUILD_FIELD = "Nieuwbouw"
NEW_BUILD_TYPE_FIELD = "OntwerpstroomType"
NEW_BUILD_TYPE_3 = (
    "Type 3: Laagbouw huishoudens vanaf bouwjaar 2022 met een individuele "
    "warmtepomp en tapwaterbuffer"
)


def is_new_build_flag(value):
    return str(value).strip().casefold() in ("1", "true", "ja", "yes", "nieuwbouw")



def is_bag_object(doorlaat):
    return str(doorlaat).strip().casefold() == "verblijfsobject"


def has_residential_usage(usage):
    # OAPIF providers may expose multi-use values as lists or serialized lists.
    if isinstance(usage, (list, tuple, set)):
        return any(has_residential_usage(item) for item in usage)
    return re.search(r"(?<!\w)woonfunctie(?!\w)", str(usage).casefold()) is not None

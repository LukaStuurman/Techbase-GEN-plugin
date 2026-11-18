"""Keep editor choices in the project and retain them in recalculated output."""
import json
import math

from .current_presets import unit_connection_from_choice

PROPERTY = "LSNetontwerp/current_editor_choices"
CHOICE_FIELDS = (
    "HerstelCat", "HerstelType", "HerstelHandmatig",
    "HerstelKeuze", "HerstelAansluitwaarde", "HerstelKader",
)


def _choice_text(value):
    text = str(value).strip() if value is not None else ""
    return "" if text.casefold() in ("null", "none") else text


def _choices(layer):
    if layer is None:
        return {}
    try:
        value = json.loads(str(layer.customProperty(PROPERTY, "{}")))
        return value if isinstance(value, dict) else {}
    except (TypeError, ValueError):
        return {}


def current_choice(layer, feature, name):
    row = _choices(layer).get(str(feature.id()), {})
    if isinstance(row, dict) and name in row:
        return _choice_text(row[name])
    # Read older projects without creating or extending their legacy fields.
    index = feature.fields().lookupField(name)
    return _choice_text(feature[index]) if index >= 0 else ""


def current_choice_values(layer, feature, snapshot=None):
    """Read one complete choice, preferring current project edits over fields."""
    stored = _choices(layer) if snapshot is None else snapshot
    row = stored.get(str(feature.id()), {})
    if not isinstance(row, dict):
        row = {}
    result = {}
    for name in CHOICE_FIELDS:
        if name in row:
            result[name] = _choice_text(row[name])
        else:
            index = feature.fields().lookupField(name)
            result[name] = _choice_text(feature[index]) if index >= 0 else ""
    if result.get("HerstelCat") and not result.get("HerstelKader"):
        # Preserve the old result's framework BEFORE the new calculation
        # overwrites KaderVersie. Old 2.0 preset labels also said "Huidige",
        # so that label alone cannot distinguish current from future service.
        index = feature.fields().lookupField("KaderVersie")
        result["HerstelKader"] = _choice_text(feature[index]) if index >= 0 else ""
    if result.get("HerstelHandmatig") != "1" and not result.get("HerstelAansluitwaarde"):
        result["HerstelAansluitwaarde"] = unit_connection_from_choice(
            result.get("HerstelCat"), result.get("HerstelKeuze"),
            result.get("HerstelType"),
        ) or ""
    return result


def current_choices_snapshot(layer):
    """Read the layer-wide property once for a whole processing run."""
    return _choices(layer)


def has_current_choices(layer):
    return bool(_choices(layer))


def business_choice_connection(choices, framework):
    """Return a saved business preset only in its original meaning.

    In 2.0 it describes FUTURE supply; in 3.0/3.1/3.2 it describes CURRENT
    supply. Neither kind of selection may silently become the other.
    """
    if choices.get("HerstelCat") != "Zakelijk":
        return None
    origin = _choice_text(choices.get("HerstelKader"))
    target = str(framework)
    compatible = (origin == target == "2.0") or (
        origin in ("3.0", "3.1", "3.2")
        and target in ("3.0", "3.1", "3.2")
    )
    if not compatible:
        return None
    return choices.get("HerstelAansluitwaarde") or unit_connection_from_choice(
        "Zakelijk", choices.get("HerstelKeuze"), choices.get("HerstelType")
    )


def manual_current_override(choices, component_values):
    """Return the four deliberate currents, never freeze an automatic preset."""
    if choices.get("HerstelHandmatig") != "1":
        return None
    try:
        values = tuple(float(value) for value in component_values)
    except (TypeError, ValueError):
        raise ValueError("De opgeslagen handmatige ontwerpstromen zijn ongeldig.") from None
    if len(values) != 4 or any(not math.isfinite(value) or value < 0 for value in values):
        raise ValueError("De opgeslagen handmatige ontwerpstromen zijn ongeldig.")
    return values


def restored_design_inputs(choices, framework, doorlaat, usage, housing):
    """Apply deliberate classifications/presets without changing GEN source fields.

    Kader 2.0 business gas advice must keep the actual current electricity
    service. Its separate future value is handled by the calculator itself.
    Street/charging presets are used only when explicitly stored; no missing
    or unsupported connection is automatically rounded into another tariff.
    """
    category = choices.get("HerstelCat")
    if category == "Huishoudelijk":
        usage = "woonfunctie"
        housing = choices.get("HerstelType") or housing
    elif category in ("Zakelijk", "Oplaadpunt", "Straatmeubilair"):
        usage = {
            "Zakelijk": "bedrijf", "Oplaadpunt": "oplaadpunt",
            "Straatmeubilair": "straatmeubilair",
        }[category]
        selected_service = (
            business_choice_connection(choices, framework)
            if category == "Zakelijk" else choices.get("HerstelAansluitwaarde")
        )
        if selected_service and (category != "Zakelijk" or str(framework) != "2.0"):
            doorlaat = selected_service
    return doorlaat, usage, housing


def save_current_choices(layer, feature_ids, values):
    choices = _choices(layer)
    for feature_id in feature_ids:
        choices[str(feature_id)] = dict(values)
    layer.setCustomProperty(PROPERTY, json.dumps(choices, ensure_ascii=False))


def clear_current_choices(layer, feature_ids):
    save_current_choices(layer, feature_ids, {
        "HerstelCat": "", "HerstelType": "", "HerstelHandmatig": "0",
        "HerstelKeuze": "", "HerstelAansluitwaarde": "", "HerstelKader": "",
    })


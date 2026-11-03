"""Keep editor choices in the project rather than adding attribute columns."""
import json

PROPERTY = "LSNetontwerp/current_editor_choices"


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
    if name in row:
        return str(row[name])
    # Read older projects without creating or extending their legacy fields.
    index = feature.fields().lookupField(name)
    return str(feature[index]).strip() if index >= 0 else ""


def save_current_choices(layer, feature_ids, values):
    choices = _choices(layer)
    for feature_id in feature_ids:
        choices[str(feature_id)] = dict(values)
    layer.setCustomProperty(PROPERTY, json.dumps(choices, ensure_ascii=False))


def clear_current_choices(layer, feature_ids):
    save_current_choices(layer, feature_ids, {
        "HerstelCat": "", "HerstelType": "", "HerstelHandmatig": "0",
    })

"""Named unit choices from Eea-0205.K 3.2, column Type wooneenheid.

Labels follow Transformator and cable direction (1). Values use the active
wizard matrices, including the separate transformer/cable gas tables.
"""
from qgis.PyQt.QtCore import Qt
from qgis.PyQt.QtGui import QColor

HOUSEHOLD_UNIT_CHOICES = (
    ("Vrijstaand", "vrijstaande woning"),
    ("Twee onder een kap", "twee-onder-een-kap"),
    ("Appartement incl. publiek laden", "appartement"),
    ("Rijtjeswoning (woonboten, woonwagens, chalets en vakantiehuisjes)", "tussenwoning/geschakeld"),
    ("Hoekwoning (rijtjeswoning)", "hoekwoning"),
    ("Onbekend", "onbekend"),
)
UNIT_CHOICES = {
    "Zakelijk": (
        ("Huidige aansluitwaarde: < 3x35A", "lt35", "3 x 25 A"),
        ("Huidige aansluitwaarde: 3x35A t/m 3x40A", "35_40", "3 x 40 A"),
        ("Huidige aansluitwaarde: 3x50A", "50", "3 x 50 A"),
        ("Huidige aansluitwaarde: 3x63A", "63", "3 x 63 A"),
        ("Huidige aansluitwaarde: 3x80A", "80", "3 x 80 A"),
        ("Huidige aansluitwaarde: 3x100A", "100", "3 x 100 A"),
        ("Huidige aansluitwaarde: 3x125A", "125", "3 x 125 A"),
        ("Huidige aansluitwaarde: 3x160A", "160", "3 x 160 A"),
        ("Huidige aansluitwaarde: 3x200A", "200", "3 x 200 A"),
        ("Huidige aansluitwaarde: 3x250A", "250", "3 x 250 A"),
    ),
    "Oplaadpunt": (("Aansluiting 3x25A", "laad25", "3 x 25 A"),),
    "Straatmeubilair": (
        ("Aansluiting 1x6A", "straat6", "1 x 6 A"),
        ("Aansluiting 1x10A", "straat10", "1 x 10 A"),
        ("Aansluiting 3x25A", "straat25", "3 x 25 A"),
        ("Aansluiting 3x40A t/m 3x50A", "straat40_50", "3 x 50 A"),
        ("Aansluiting 3x63A t/m 3x80A", "straat63_80", "3 x 80 A"),
    ),
}
GAS_CHOICES = (
    ("G4, G6, geen of ander gas", "G4/G6/Geen", "#FFFF00"),
    ("G10 t/m G25", "G10-G25", "#FF0000"),
    ("> G25", ">G25", "#C00000"),
)


def fill_gas_combo(combo):
    background = Qt.ItemDataRole.BackgroundRole if hasattr(Qt, "ItemDataRole") else Qt.BackgroundRole
    foreground = Qt.ItemDataRole.ForegroundRole if hasattr(Qt, "ItemDataRole") else Qt.ForegroundRole
    for label, stored, color in GAS_CHOICES:
        combo.addItem(label, stored)
        index = combo.count() - 1
        combo.setItemData(index, QColor(color), background)
        combo.setItemData(index, QColor("black" if color == "#FFFF00" else "white"), foreground)


def fill_unit_combo(combo, category, framework_version=None):
    combo.blockSignals(True)
    combo.clear()
    for label, key, _doorlaat in UNIT_CHOICES.get(category, ()):
        if category == "Zakelijk" and str(framework_version) == "2.0":
            label = label.replace("Huidige aansluitwaarde:", "Toekomstige aansluitwaarde:")
            if key in {"100", "125", "200"}:
                label += " — overig, kaderwaarde ontbreekt"
        combo.addItem(label, key)
    combo.addItem("Zelf invullen", None)
    default = {"Zakelijk": "lt35", "Straatmeubilair": "straat25", "Oplaadpunt": "laad25"}.get(category)
    index = combo.findData(default)
    combo.setCurrentIndex(index if index >= 0 else 0)
    combo.blockSignals(False)


def unit_description(category, key):
    return next((label for label, stored, _ in UNIT_CHOICES.get(category, ()) if stored == key), "Zelf invullen")


def current_context(host):
    from .algorithms.woningtype_selectie_herberekenen_tool import _configurations, _load_design_module
    module = _load_design_module()
    values = host._workflow_field_defaults()
    return module, values, *_configurations(values, module)


def unit_currents(context, category, key, gas_category="G4/G6/Geen"):
    choice = next((row for row in UNIT_CHOICES.get(category, ()) if row[1] == key), None)
    if choice is None:
        return None
    module, values, standard, cable, opwek, opwek_cable = context
    doorlaat = choice[2]
    usage = {"Zakelijk": "bedrijf", "Oplaadpunt": "oplaadpunt", "Straatmeubilair": "straatmeubilair"}[category]
    gas = gas_category if category == "Zakelijk" else "G4/G6/Geen"
    one_phase = bool(values.get("one_phase_exception", True))
    normal = module.calculate_ontwerpstroom(doorlaat, usage, "", 0, gas, standard, 0, None, one_phase)
    cable_current = module.calculate_ontwerpstroom(doorlaat, usage, "", 0, gas, cable, 0, None, one_phase)
    generation = module.calculate_opwek_ontwerpstroom(doorlaat, usage, "", gas, opwek, standard, normal, one_phase)
    generation_cable = module.calculate_opwek_ontwerpstroom(doorlaat, usage, "", gas, opwek_cable, cable, cable_current, one_phase)
    return normal, cable_current, generation, generation_cable


def category_note(category, key):
    if category == "Zakelijk":
        if key in {"100", "125", "160", "200", "250"}:
            return "Type 9: Grootverbruik LS (eigen richting >3x80A)"
        return "Type 8: Kleinzakelijk (niet-huishoudelijk t/m 3x80A)"
    return {"Oplaadpunt": "Type 10: Netbewust publiek laden", "Straatmeubilair": "Type 11: Straatmeubilair"}.get(category, "")

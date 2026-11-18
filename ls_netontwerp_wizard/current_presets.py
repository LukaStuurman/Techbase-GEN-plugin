"""Named unit choices from Eea-0205.K 3.2, column Type wooneenheid.

Labels follow Transformator and cable direction (1). Values use the active
wizard matrices, including the separate transformer/cable gas tables.
"""

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
        ("Aansluiting 3x35A", "straat35", "3 x 35 A"),
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
    from qgis.PyQt.QtCore import Qt
    from qgis.PyQt.QtGui import QColor

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
                label += " — aanvulling Kader 3.2"
        elif category == "Straatmeubilair" and str(framework_version) == "2.0":
            if key in {"straat6", "straat10", "straat25"}:
                label += " — laagste profiel (5,8 A)"
            elif key == "straat35":
                label += " — profiel 3x40–50 A (22 A)"
        combo.addItem(label, key)
    combo.addItem("Zelf invullen", None)
    default = {"Zakelijk": "lt35", "Straatmeubilair": "straat25", "Oplaadpunt": "laad25"}.get(category)
    index = combo.findData(default)
    combo.setCurrentIndex(index if index >= 0 else 0)
    combo.blockSignals(False)


def unit_description(category, key):
    return next((label for label, stored, _ in UNIT_CHOICES.get(category, ()) if stored == key), "Zelf invullen")


def unit_future_connection(category, key):
    """A deliberate Type 6/7 choice is a FUTURE rating, not GEN current."""
    return next(
        (doorlaat for _label, stored, doorlaat in UNIT_CHOICES.get(category, ())
         if stored == key),
        None,
    )


def unit_connection_from_choice(category, key=None, label=None):
    """Recover only an explicitly stored preset, including old label-only edits.

    Current GEN values are not inputs here: unknown connections are never
    rounded or promoted into a preset. Both display prefixes were emitted
    by the editor for the same named choices in different Kader versions.
    """
    text = " ".join(str(label or "").split()).casefold()
    for original, stored_key, doorlaat in UNIT_CHOICES.get(category, ()):
        if key is not None and str(key) == stored_key:
            return doorlaat
        labels = (
            original,
            original.replace("Huidige aansluitwaarde:", "Toekomstige aansluitwaarde:"),
        )
        if text and any(text == " ".join(value.split()).casefold() for value in labels):
            return doorlaat
    return None


def current_context(host):
    from .algorithms.woningtype_selectie_herberekenen_tool import _configurations, _load_design_module
    module = _load_design_module()
    values = host._workflow_field_defaults()
    return module, values, *_configurations(values, module)


def unit_currents(context, category, key, gas_category="G4/G6/Geen", current_service=None):
    choice = next((row for row in UNIT_CHOICES.get(category, ()) if row[1] == key), None)
    if choice is None:
        return None
    module, values, standard, cable, opwek, opwek_cable = context
    doorlaat = choice[2]
    if (
        category == "Zakelijk"
        and str(values.get("design_framework")) == "2.0"
        and current_service
    ):
        # The future rating remains the selected preset. The gas advice
        # instead uses the actual, separate CURRENT GEN connection.
        doorlaat = current_service
    usage = {"Zakelijk": "bedrijf", "Oplaadpunt": "oplaadpunt", "Straatmeubilair": "straatmeubilair"}[category]
    gas = gas_category if category == "Zakelijk" else "G4/G6/Geen"
    one_phase = bool(values.get("one_phase_exception", True))
    # Selecting a named business preset in Kader 2.0 is an explicit choice
    # of the FUTURE connection. Pass it as such to the shared calculator;
    # using it only as current GEN 'doorlaat' would lose that deliberate
    # future choice when the current source connection changes later.
    future = (
        choice[2] if category == "Zakelijk"
        and str(values.get("design_framework")) == "2.0" else None
    )
    kwargs = {"kader20_future": future} if future else {}
    normal = module.calculate_ontwerpstroom(
        doorlaat, usage, "", 0, gas, standard, 0, None, one_phase, **kwargs
    )
    cable_current = module.calculate_ontwerpstroom(
        doorlaat, usage, "", 0, gas, cable, 0, None, one_phase, **kwargs
    )
    generation = module.calculate_opwek_ontwerpstroom(
        doorlaat, usage, "", gas, opwek, standard, normal, one_phase, **kwargs
    )
    generation_cable = module.calculate_opwek_ontwerpstroom(
        doorlaat, usage, "", gas, opwek_cable, cable, cable_current,
        one_phase, **kwargs
    )
    return normal, cable_current, generation, generation_cable


def category_note(category, key, framework=None):
    if category == "Zakelijk" and str(framework) == "2.0":
        if key in {"100", "125", "200"}:
            return "Kader 2.0 Type 7: ontbrekende 2.0-waarde aangevuld met de staffels/formule van Kader 3.2, met apart huidig gasadvies per trafo/kabel"
        if key in {"160", "250"}:
            return "Kader 2.0 Type 7: grootverbruik LS op toekomstige aansluitwaarde, met apart huidig gasadvies per trafo/kabel"
        return "Kader 2.0 Type 6: kleinzakelijk op toekomstige aansluitwaarde, met apart huidig gasadvies per trafo/kabel"
    if category == "Straatmeubilair" and str(framework) == "2.0":
        if key in {"straat6", "straat10", "straat25"}:
            return "Kader 2.0 Type 9: laagste 3x25 A-profiel, 5,8 A trafo/kabel en 0 A opwek; ook voor bekende eenfaseaansluitingen. Bij ontbrekende doorlaat of ampèrewaarde geldt dit profiel als standaardaanname; de bronwaarde blijft ongewijzigd."
        if key == "straat35":
            return "Kader 2.0 Type 9: 3x35 A gebruikt het profiel 3x40–50 A, 22 A trafo/kabel en 0 A opwek"
        return "Kader 2.0 Type 9: straatmeubilair, 0 A opwek; ontbrekende driefasewaarden boven 3x80 A worden aangevuld met Kader 3.2"
    if category == "Oplaadpunt" and str(framework) == "2.0":
        return "Kader 2.0 Type 8: netbewust publiek laden, 0 A opwek; ontbrekende driefasewaarden boven 3x80 A worden aangevuld met Kader 3.2"
    if category == "Zakelijk":
        if key in {"100", "125", "160", "200", "250"}:
            return "Type 9: Grootverbruik LS (eigen richting >3x80A)"
        return "Type 8: Kleinzakelijk (niet-huishoudelijk t/m 3x80A)"
    return {"Oplaadpunt": "Type 10: Netbewust publiek laden", "Straatmeubilair": "Type 11: Straatmeubilair"}.get(category, "")


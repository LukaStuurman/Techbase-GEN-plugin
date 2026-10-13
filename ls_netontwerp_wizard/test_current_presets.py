"""QGIS regression tests for named current choices and business gas categories."""
import os
from pathlib import Path
import sys

from qgis.PyQt.QtCore import QVariant
from qgis.core import QgsApplication, QgsFeature, QgsField, QgsGeometry, QgsProject, QgsVectorLayer


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    app = QgsApplication([], False)
    app.initQgis()
    from ls_netontwerp_wizard.current_presets import GAS_CHOICES, UNIT_CHOICES, current_context, unit_currents
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    from ls_netontwerp_wizard.dialog import FRAMEWORK_31_STREET_MATRIX
    from ls_netontwerp_wizard.connection_sources import CURRENT_FIELDS

    layer = QgsVectorLayer("Point?crs=EPSG:28992", "LS-aansluitingen ontwerpstroom", "memory")
    layer.dataProvider().addAttributes([QgsField(n, QVariant.Double) for n in CURRENT_FIELDS] +
                                     [QgsField(n, QVariant.String) for n in ("Gevonden_Woningtype", "Gebruiksdoel", "G_Type", "service_connection_type_type")])
    layer.updateFields()
    f = QgsFeature(layer.fields())
    f.setGeometry(QgsGeometry.fromWkt("POINT(156000 381000)"))
    f["Gebruiksdoel"] = "bedrijf"
    f["G_Type"] = "G4"
    for name in CURRENT_FIELDS:
        f[name] = 0.0
    assert layer.dataProvider().addFeature(f)
    layer.selectAll()
    layer.setCustomProperty("LSNetontwerp/review_current_layer", True)
    QgsProject.instance().addMapLayer(layer)
    dialog = LSNetontwerpDashboardDialog(None)
    dialog.prepared_state = {"values": {"matrix_straat": FRAMEWORK_31_STREET_MATRIX}}
    context = current_context(dialog)
    # Independently copied from workbook Transformator and (1), F/G rows 36-69.
    expected_trafo = [
        [8.7, 44, 210], [32, 65, 210], [44, 65, 210], [51, 138, 210], [65, 138, 210],
        [85, 210, 210], [106, 210, 210], [138, 210, 210], [210, 210, 210], [210, 210, 210],
    ]
    expected_cable = [
        [8.7, 44, 65], [32, 65, 65], [44, 65, 65], [51, 65, 65], [65, 65, 65],
        [85, 210, 210], [106, 210, 210], [138, 210, 210], [210, 210, 210], [210, 210, 210],
    ]
    for row, (_, key, _) in enumerate(UNIT_CHOICES["Zakelijk"]):
        for gas_index, (_, gas, _) in enumerate(GAS_CHOICES):
            actual = unit_currents(context, "Zakelijk", key, gas)
            assert actual == (expected_trafo[row][gas_index], expected_cable[row][gas_index],
                              expected_trafo[row][gas_index], expected_cable[row][gas_index]), (key, gas, actual)
    for (_, key, _), expected in zip(UNIT_CHOICES["Straatmeubilair"], (4.3, 8.7, 5.8, 22, 36)):
        assert unit_currents(context, "Straatmeubilair", key) == (expected, expected, 0, 0)
    assert unit_currents(context, "Oplaadpunt", "laad25") == (3.7, 4.8, 0, 0)
    assert unit_currents(context, "Zakelijk", None) is None

    dialog.show_value_page()
    assert dialog.value_unit_combo.count() == 11
    assert dialog.value_gas_combo.count() == 3
    assert not dialog.value_gas_combo.isHidden()
    dialog.value_unit_combo.setCurrentIndex(dialog.value_unit_combo.findData("63"))
    dialog.value_gas_combo.setCurrentIndex(dialog.value_gas_combo.findData("G10-G25"))
    assert (dialog.value_trafo.value(), dialog.value_cable.value()) == (138, 65)
    dialog.run_value_edit()
    saved = next(layer.getFeatures())
    assert [saved[name] for name in CURRENT_FIELDS] == [138, 65, 138, 65, 138, 65]
    assert saved["G_Type"] == "G10-G25"
    assert saved["HerstelType"] == "Huidige aansluitwaarde: 3x63A"
    dialog.show_home_page()
    dialog.show_value_page()
    assert dialog.value_unit_combo.currentData() == "63"
    assert dialog.value_gas_combo.currentData() == "G10-G25"
    assert dialog.value_trafo.value() == 138
    # The named choices still allow explicit manual current overrides.
    dialog.value_unit_combo.setCurrentIndex(dialog.value_unit_combo.findData(None))
    dialog.value_trafo.setValue(123)
    dialog.value_cable.setValue(124)
    dialog.value_generation_trafo.setValue(125)
    dialog.value_generation_cable.setValue(126)
    dialog.run_value_edit()
    saved = next(layer.getFeatures())
    assert [saved[name] for name in CURRENT_FIELDS] == [123, 124, 125, 126, 125, 126]
    assert saved["HerstelType"] == "Zelf invullen"
    # Same presets in the zero-current repair page, with a different gas choice.
    zero = dialog.zero_current_page
    zero.category_combo.setCurrentIndex(zero.category_combo.findData("Zakelijk"))
    zero.unit_combo.setCurrentIndex(zero.unit_combo.findData("lt35"))
    zero.gas_combo.setCurrentIndex(zero.gas_combo.findData(">G25"))
    assert (zero.trafo_spin.value(), zero.cable_spin.value()) == (210, 65)
    zero.apply_values_to_layer(layer, [saved.id()], "Zakelijk", {
        "consumption_trafo": zero.trafo_spin.value(), "consumption_cable": zero.cable_spin.value(),
        "generation_trafo": zero.generation_trafo_spin.value(), "generation_cable": zero.generation_cable_spin.value(),
    }, unit_name=zero.unit_combo.currentText(), gas_category=zero.gas_combo.currentData())
    saved = next(layer.getFeatures())
    assert saved["G_Type"] == ">G25" and saved["Hoogste Kabel"] == 65
    dialog.value_category_combo.setCurrentIndex(dialog.value_category_combo.findData("Oplaadpunt"))
    assert dialog.value_gas_combo.isHidden()
    assert dialog.value_unit_combo.itemText(0) == "Aansluiting 3x25A"
    assert (dialog.value_trafo.value(), dialog.value_cable.value()) == (3.7, 4.8)
    dialog.value_category_combo.setCurrentIndex(dialog.value_category_combo.findData("Straatmeubilair"))
    dialog.value_unit_combo.setCurrentIndex(dialog.value_unit_combo.findData("straat6"))
    assert dialog.value_trafo.value() == 4.3
    dialog.value_category_combo.setCurrentIndex(dialog.value_category_combo.findData("Huishoudelijk"))
    assert dialog.value_unit_group.isHidden()
    assert dialog.value_housing_combo.itemText(0) == "Vrijstaand"
    if "--preview" in sys.argv:
        dialog.value_category_combo.setCurrentIndex(dialog.value_category_combo.findData("Zakelijk"))
        dialog.resize(1100, 820)
        dialog.show()
        app.processEvents()
        assert dialog.grab().save(sys.argv[sys.argv.index("--preview") + 1])
    print("CURRENT_PRESETS_TEST_OK (30 business/gas pairs, 5 street choices, charging, UI, persistence)", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()

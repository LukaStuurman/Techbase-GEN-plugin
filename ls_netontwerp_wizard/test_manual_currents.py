"""Exercise typing, preset reset and saved household overrides in QGIS."""
import os
from pathlib import Path
import sys

from qgis.PyQt.QtCore import Qt, QVariant
from qgis.PyQt.QtTest import QTest
from qgis.PyQt.QtGui import QFont, QFontDatabase
from qgis.PyQt.QtWidgets import QScrollArea
from qgis.core import QgsApplication, QgsFeature, QgsField, QgsGeometry, QgsProject, QgsVectorLayer


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    app = QgsApplication([], False)
    app.initQgis()
    for name in ("segoeui.ttf", "segoeuib.ttf"):
        QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / name))
    app.setFont(QFont("Segoe UI", 10))
    from ls_netontwerp_wizard.current_edit_metadata import current_choice
    from ls_netontwerp_wizard.connection_sources import CURRENT_FIELDS
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog

    layer = QgsVectorLayer("Point?crs=EPSG:28992", "LS-aansluitingen ontwerpstroom", "memory")
    layer.dataProvider().addAttributes([QgsField(n, QVariant.Double) for n in CURRENT_FIELDS] +
        [QgsField(n, QVariant.String) for n in ("Gevonden_Woningtype", "Gevonden_Bouwjaar", "Gebruiksdoel", "G_Type")])
    layer.updateFields()
    for year in (2000, 2025):
        feature = QgsFeature(layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt(f"POINT({year} 0)"))
        for name in CURRENT_FIELDS:
            feature[name] = 0
        feature["Gevonden_Woningtype"] = "vrijstaande woning"
        feature["Gevonden_Bouwjaar"] = str(year)
        feature["Gebruiksdoel"] = "woonhuis"
        layer.dataProvider().addFeature(feature)
    layer.setCustomProperty("LSNetontwerp/review_current_layer", True)
    QgsProject.instance().addMapLayer(layer)
    original_fields = [f.name() for f in layer.fields()]
    layer.selectAll()
    dialog = LSNetontwerpDashboardDialog(None)
    dialog.show_value_page()
    dialog.show()
    app.processEvents()
    assert dialog.value_manual_group.isVisible()
    assert not dialog.value_manual_checkbox.isChecked()
    dialog.run_value_edit()
    automatic = [[f[n] for n in CURRENT_FIELDS] for f in layer.getFeatures()]
    assert automatic[0] != automatic[1], automatic

    def type_value(spin, text):
        spin.lineEdit().selectAll()
        QTest.keyClicks(spin.lineEdit(), text.replace(".", spin.locale().decimalPoint()))
        QTest.keyClick(spin.lineEdit(), Qt.Key.Key_Return if hasattr(Qt, "Key") else Qt.Key_Return)

    for spin, text in zip(dialog._value_current_spins(), ("11.125", "12.5", "0", "14.75")):
        type_value(spin, text)
    assert dialog.value_manual_checkbox.isChecked()
    assert dialog.page_stack.currentWidget() is dialog.value_page
    assert "14.750" in dialog.value_highest_preview.text(), ([s.value() for s in dialog._value_current_spins()], dialog.value_highest_preview.text())
    dialog.run_value_edit()
    expected = [11.125, 12.5, 0, 14.75, 11.125, 14.75]
    assert all([f[n] for n in CURRENT_FIELDS] == expected for f in layer.getFeatures())
    assert all(current_choice(layer, f, "HerstelHandmatig") == "1" for f in layer.getFeatures())
    dialog.show_home_page()
    dialog.show_value_page()
    assert dialog.value_manual_checkbox.isChecked()
    assert [s.value() for s in dialog._value_current_spins()] == expected[:4]
    dialog.value_manual_checkbox.setChecked(False)
    dialog.run_value_edit()
    assert [[f[n] for n in CURRENT_FIELDS] for f in layer.getFeatures()] == automatic
    assert all(current_choice(layer, f, "HerstelHandmatig") == "0" for f in layer.getFeatures())

    # Zero is a deliberate, valid manual value, including for the whole selection.
    dialog.value_manual_checkbox.setChecked(True)
    for spin in dialog._value_current_spins():
        type_value(spin, "0")
    dialog.run_value_edit()
    dialog.show_zero_current_page(select_first=False)
    zero = dialog.zero_current_page
    zero.table.selectAll()
    zero.category_combo.setCurrentIndex(zero.category_combo.findData("Zakelijk"))
    app.processEvents()
    assert len(zero.findChildren(QScrollArea)) == 1
    assert zero.unit_group.isVisible() and zero.unit_combo.isVisible() and zero.gas_combo.isVisible()
    zero.unit_combo.setCurrentIndex(zero.unit_combo.findData("63"))
    zero.gas_combo.setCurrentIndex(zero.gas_combo.findData("G10-G25"))
    assert [s.value() for s in zero._current_spins()] == [138, 65, 138, 65]
    assert not zero.manual_checkbox.isChecked()
    zero.apply_category()
    assert all([f[n] for n in CURRENT_FIELDS] == [138, 65, 138, 65, 138, 65] for f in layer.getFeatures())
    assert all(f["G_Type"] == "G10-G25" for f in layer.getFeatures())

    # Repair household nulls through the actual table action with typed overrides.
    provider = layer.dataProvider()
    provider.changeAttributeValues({f.id(): {layer.fields().lookupField(n): 0 for n in CURRENT_FIELDS} for f in layer.getFeatures()})
    zero.refresh()
    zero.table.selectAll()
    zero.category_combo.setCurrentIndex(zero.category_combo.findData("Huishoudelijk"))
    assert zero.current_values_group.isVisible()
    for spin, text in zip(zero._current_spins(), ("7.25", "8.5", "9.75", "0")):
        type_value(spin, text)
    assert zero.manual_checkbox.isChecked()
    assert dialog.page_stack.currentWidget() is zero
    zero.apply_category()
    assert all([f[n] for n in CURRENT_FIELDS] == [7.25, 8.5, 9.75, 0, 9.75, 8.5] for f in layer.getFeatures())
    # A fresh category/preset selection returns to automatic values in every category.
    for category in ("Zakelijk", "Oplaadpunt", "Straatmeubilair", "Huishoudelijk"):
        zero.category_combo.setCurrentIndex(zero.category_combo.findData(category))
        assert not zero.current_values_group.isHidden()
        assert not zero.manual_checkbox.isChecked()
        type_value(zero.trafo_spin, "123.125")
        assert zero.manual_checkbox.isChecked()

    if "--preview" in sys.argv:
        zero.category_combo.setCurrentIndex(zero.category_combo.findData("Zakelijk"))
        dialog.resize(1100, 950)
        app.processEvents()
        scroll = zero.findChild(QScrollArea)
        scroll.ensureWidgetVisible(zero.unit_combo)
        app.processEvents()
        assert dialog.grab().save(sys.argv[sys.argv.index("--preview") + 1])
    assert [f.name() for f in layer.fields()] == original_fields
    assert not any(f.name().startswith("Herstel") for f in layer.fields())
    print("MANUAL_CURRENTS_TEST_OK (actual typing, four categories, old/new household, saved overrides, preset reset, business zero repair)", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()

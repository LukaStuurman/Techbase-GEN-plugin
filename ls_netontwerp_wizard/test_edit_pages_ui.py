"""Exercise the integrated current- and housing-edit pages in one dialog."""

from __future__ import annotations

import os
from pathlib import Path
import sys

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsApplication,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsProcessingContext,
    QgsProject,
    QgsVectorLayer,
)


def main():
    plugin_dir = Path(__file__).resolve().parent
    sys.path.insert(0, str(plugin_dir.parent))
    app = QgsApplication([], False)
    app.initQgis()
    project = QgsProject.instance()

    housing = QgsVectorLayer(
        "Polygon?crs=EPSG:28992", "Woningtypen BAG/3DBAG", "memory"
    )
    housing.dataProvider().addAttributes(
        [
            QgsField("Woningtype", QVariant.String),
            QgsField("bouwjaar", QVariant.Int),
        ]
    )
    housing.updateFields()
    building = QgsFeature(housing.fields())
    building.setAttributes(["vrijstaande woning", 2000])
    building.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0,20 0,20 20,0 20,0 0))"))
    housing.dataProvider().addFeature(building)
    housing.selectAll()

    points = QgsVectorLayer(
        "Point?crs=EPSG:28992", "LS-aansluitingen ontwerpstroom", "memory"
    )
    fields = [
        QgsField("service_connection_type_type", QVariant.String),
        QgsField("Gebruiksdoel", QVariant.String),
        QgsField("G_Type", QVariant.String),
    ]
    fields.extend(
        QgsField(name, QVariant.Double)
        for name in (
            "Ontwerpstroom",
            "Ontwerpstroom kabel",
            "Opwek ontwerpstroom",
            "Kabel opwek ontwerpstroom",
            "Hoogste Trafo",
            "Hoogste Kabel",
        )
    )
    fields.extend(
        [
            QgsField("Gevonden_Woningtype", QVariant.String),
            QgsField("Gevonden_Bouwjaar", QVariant.String),
        ]
    )
    points.dataProvider().addAttributes(fields)
    points.updateFields()
    connection = QgsFeature(points.fields())
    connection.setAttributes(["3 x 25 A", "woonhuis", ""] + [1.0] * 6 + ["", ""])
    connection.setGeometry(QgsGeometry.fromWkt("POINT(10 10)"))
    points.dataProvider().addFeature(connection)
    points.selectAll()
    points.setCustomProperty("LSNetontwerp/review_current_layer", True)
    stations = QgsVectorLayer(
        "Point?crs=EPSG:28992", "Bestaande stations (bron)", "memory"
    )
    stations.dataProvider().addAttributes(
        [
            QgsField("Station", QVariant.String),
            QgsField("trafo_power", QVariant.String),
            QgsField("Max_A", QVariant.Double),
        ]
    )
    stations.updateFields()
    station_features = []
    for name, x in (("079.1010", 30), ("079.222", 40)):
        station = QgsFeature(stations.fields())
        station.setAttributes([name, "400", 400.0 / 0.23 / 3.0])
        station.setGeometry(QgsGeometry.fromWkt(f"POINT({x} 10)"))
        station_features.append(station)
    stations.dataProvider().addFeatures(station_features)
    first_station_id = next(stations.getFeatures()).id()
    stations.selectByIds([first_station_id])
    stations.setCustomProperty("LSNetontwerp/review_station_layer", True)
    stations.setCustomProperty("LSNetontwerp/station_name_field", "Station")
    stations.setCustomProperty(
        "LSNetontwerp/station_capacity_field", "trafo_power"
    )
    stations.setCustomProperty("LSNetontwerp/station_max_field", "Max_A")
    project.addMapLayer(housing)
    project.addMapLayer(points)
    project.addMapLayer(stations)

    import ls_netontwerp_wizard.dialog as dialog_module
    from ls_netontwerp_wizard.algorithms.hoogste_waarden_selectie_tool import (
        HoogsteWaardenSelectieAlgorithm,
    )
    from ls_netontwerp_wizard.algorithms.woningtype_selectie_herberekenen_tool import (
        WoningtypeSelectieHerberekenenAlgorithm,
    )
    from ls_netontwerp_wizard.algorithms.stations_selectie_tool import (
        StationsSelectieAlgorithm,
    )
    from ls_netontwerp_wizard.dialog import LSNetontwerpDialog

    def dispatch(algorithm_id, parameters, feedback=None, **_kwargs):
        if algorithm_id.endswith("hoogste_trafo_kabel_selectie"):
            algorithm = HoogsteWaardenSelectieAlgorithm()
        elif algorithm_id.endswith("bestaande_stations_selectie"):
            algorithm = StationsSelectieAlgorithm()
        else:
            algorithm = WoningtypeSelectieHerberekenenAlgorithm()
        algorithm.initAlgorithm()
        return algorithm.processAlgorithm(
            parameters, QgsProcessingContext(), feedback
        )

    dialog_module.processing.run = dispatch
    dialog = LSNetontwerpDialog()

    dialog.show_value_page()
    assert dialog.page_stack.currentWidget() is dialog.value_page
    assert "1" in dialog.value_selection_label.text()
    dialog.value_trafo.setValue(12.3)
    dialog.value_cable.setValue(14.5)
    dialog.run_value_edit()
    changed = next(points.getFeatures())
    assert abs(float(changed["Hoogste Trafo"]) - 12.3) < 1e-9
    assert abs(float(changed["Hoogste Kabel"]) - 14.5) < 1e-9
    assert dialog.value_status_label.text().startswith("Gereed:")

    dialog.show_home_page()
    assert dialog.page_stack.currentWidget() is dialog.main_page

    dialog.show_station_page()
    assert dialog.page_stack.currentWidget() is dialog.station_page
    assert "1" in dialog.station_selection_label.text()
    dialog.station_capacity.setValue(630.0)
    dialog.run_station_edit()
    changed_station = next(
        feature
        for feature in stations.getFeatures()
        if feature.id() == first_station_id
    )
    assert str(changed_station["trafo_power"]) == "630"
    assert abs(float(changed_station["Max_A"]) - (630.0 / 0.23 / 3.0)) < 1e-9
    assert dialog.station_status_label.text().startswith("Gereed:")

    remaining_id = next(
        feature.id()
        for feature in stations.getFeatures()
        if feature.id() != first_station_id
    )
    stations.selectByIds([remaining_id])
    original_question = dialog_module.QMessageBox.question
    try:
        dialog_module.QMessageBox.question = lambda *_args, **_kwargs: (
            dialog_module.QMessageBox.StandardButton.Yes
        )
        dialog.run_station_delete()
    finally:
        dialog_module.QMessageBox.question = original_question
    assert stations.featureCount() == 1
    assert dialog.station_status_label.text().startswith("Gereed:")
    dialog.show_home_page()
    assert dialog.page_stack.currentWidget() is dialog.main_page

    dialog.show_housing_page()
    assert dialog.page_stack.currentWidget() is dialog.housing_page
    assert "1" in dialog.housing_selection_label.text()
    dialog.housing_type_combo.setCurrentIndex(2)  # Appartement
    dialog.run_housing_edit()
    changed_building = next(housing.getFeatures())
    changed_point = next(points.getFeatures())
    assert changed_building["Woningtype"] == "appartement"
    assert changed_point["Gevonden_Woningtype"] == "appartement"
    assert abs(float(changed_point["Hoogste Trafo"]) - 4.5) < 1e-9
    assert dialog.housing_status_label.text().startswith("Gereed:")
    dialog.show_home_page()
    assert dialog.page_stack.currentWidget() is dialog.main_page

    print("EDIT_PAGES_UI_TEST_OK", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()

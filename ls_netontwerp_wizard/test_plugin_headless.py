"""Kleine lokale laadtest; wordt niet door QGIS zelf uitgevoerd."""

from pathlib import Path
import sys

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    Qgis,
    QgsApplication,
    QgsFeature,
    QgsField,
    QgsGeometry,
    QgsProcessingContext,
    QgsProcessingFeedback,
    QgsProject,
    QgsVectorLayer,
)


def main():
    plugin_parent = Path(__file__).resolve().parent.parent
    sys.path.insert(0, str(plugin_parent))
    app = QgsApplication([], False)
    app.initQgis()
    try:
        from ls_netontwerp_wizard.dialog import LSNetontwerpDialog
        from ls_netontwerp_wizard.workflow import WorkflowRunner

        dialog = LSNetontwerpDialog()
        assert dialog.edit_cluster_button.text() == "4. Clustering aanpassen"
        assert dialog.free_cluster_button.text() == "4b. Vrij aanpassen"
        assert dialog.free_cluster_button.isHidden()
        assert dialog.network_button.text() == "5. Sleuven/routes"
        assert dialog.areas_button.text() == "6. Mooie clustergebieden"
        dialog.show_areas_page()
        assert dialog.page_stack.currentWidget() is dialog.areas_page
        assert dialog.areas_create_button.text() == "Vereenvoudigde gebieden maken"
        assert dialog.areas_draw_button.text() == "Grens van 2 gebieden verleggen"
        assert dialog.areas_right_angles.isChecked()
        assert dialog.areas_min_width.value() == 20.0
        assert dialog.areas_junction_tolerance.value() == 12.0
        assert dialog.areas_advanced_container.isHidden()
        dialog.show_home_page()
        dialog.show_network_page()
        assert dialog.page_stack.currentWidget() is dialog.network_page
        assert dialog.network_advanced_container.isHidden()
        assert dialog.network_selected_refresh_button.text() == "Geselecteerde routes verversen"
        dialog.open_cluster_editor()
        assert dialog.page_stack.currentWidget() is dialog.manual_page
        assert dialog.manual_advanced_container.isHidden()
        dialog.manual_advanced_toggle.setChecked(True)
        assert not dialog.manual_advanced_container.isHidden()
        dialog.show_home_page()
        assert dialog.page_stack.currentWidget() is dialog.main_page
        assert dialog.info_button.text().startswith("ⓘ")
        query_text = dialog._gen_query_text()
        assert "|LS Kabel [LS Kaart]|" in query_text
        assert "interacts trail" in query_text
        assert "|MS/LS Transformator|" in query_text
        progress_update = dialog._make_progress("Clustering voorbereiden…")
        long_progress_message = "Kabelverbonden clustering: " + "detail " * 40
        progress_update(55, long_progress_message)
        assert not dialog.progress_group.isHidden()
        assert dialog.progress_bar.value() == 55
        assert len(dialog.progress_summary.text()) <= 105
        assert long_progress_message.strip() in dialog.progress_details.toPlainText()
        dialog._finish_progress(100)
        assert dialog.progress_bar.value() == 100
        assert dialog.progress_cancel_button.isHidden()
        assert dialog.advanced_container.isHidden()
        dialog.advanced_toggle.setChecked(True)
        assert not dialog.advanced_container.isHidden()
        dialog.no_plan.setChecked(False)
        dialog.plan_edit.setText("C:/test/plangebied.gpkg")
        assert dialog.values()["plan"] == "C:/test/plangebied.gpkg"
        dialog.no_plan.setChecked(True)
        assert not dialog.plan_edit.isEnabled()
        assert not dialog.plan_button.isEnabled()
        assert dialog.values()["plan"] == ""
        assert dialog.values()["only_plan"] is False
        dialog.no_plan.setChecked(False)
        assert dialog.plan_edit.isEnabled()
        assert dialog.values()["plan"] == "C:/test/plangebied.gpkg"
        values = dialog.values()
        assert values["field_design_current"] == "Hoogste Trafo"
        assert values["default_apartment"] is True
        assert values["automatic_stations"] is True
        assert values["matrix_woonhuis"][:4] == [
            "hoekwoning",
            "5.5",
            "tussen/geschakeld",
            "5.5",
        ]
        assert values["matrix_type"][:6] == [
            "0",
            "Overig",
            "0.0",
            "1",
            "0",
            "0",
        ]
        assert values["opwek_zero_ids"] == "4, 8, 9"
        assert values["fallback_laad"] == 3.7
        matrix = dialog.widgets["matrix_woonhuis"]
        original_rows = matrix.rowCount()
        matrix.selectRow(0)
        dialog._duplicate_matrix_row(matrix)
        assert matrix.rowCount() == original_rows + 1
        assert matrix.item(1, 0).text() == matrix.item(0, 0).text()
        dialog._move_matrix_row(matrix, 1)
        assert dialog._selected_matrix_row(matrix) == 2
        dialog._copy_matrix(matrix)
        dialog._remove_matrix_rows(matrix)
        assert matrix.rowCount() == original_rows
        dialog._paste_matrix(matrix)
        assert matrix.rowCount() == original_rows + 1
        runner = WorkflowRunner(values, lambda _percent, _message: None)
        plan_layer = QgsVectorLayer("Polygon?crs=EPSG:28992", "Plangebied", "memory")
        runner._style_plan_area(plan_layer)
        plan_properties = (
            plan_layer.renderer().symbol().symbolLayer(0).properties()
        )
        assert plan_properties["style"] == "no"
        assert plan_properties["outline_color"].startswith("255,0,0")
        assert float(plan_properties["outline_width"]) == 1.0
        assert bool(plan_layer.customProperty("LSNetontwerp/plan_layer"))

        cable_layer = QgsVectorLayer(
            "LineString?crs=EPSG:28992", "Laagspanningskabels", "memory"
        )
        cable_layer.dataProvider().addAttributes([QgsField("function", QVariant.String)])
        cable_layer.updateFields()
        ls_feature = QgsFeature(cable_layer.fields())
        ls_feature["function"] = "LS hoofdnet"
        ms_feature = QgsFeature(cable_layer.fields())
        ms_feature["function"] = "MS"
        cable_layer.dataProvider().addFeatures([ls_feature, ms_feature])
        runner._style_function_cables(cable_layer, "function", "LS")
        cable_categories = cable_layer.renderer().categories()
        states = {str(category.value()): category.renderState() for category in cable_categories}
        assert states == {"LS hoofdnet": True, "MS": False}
        assert cable_layer.hasScaleBasedVisibility() is False

        housing_layer = QgsVectorLayer(
            "Polygon?crs=EPSG:28992", "Woningtypen", "memory"
        )
        housing_layer.dataProvider().addAttributes([QgsField("Woningtype", QVariant.String)])
        housing_layer.updateFields()
        runner._style_woningtypes(housing_layer, "Woningtype")
        assert len(housing_layer.renderer().categories()) == 6
        assert housing_layer.hasScaleBasedVisibility() is False

        review_layer = QgsVectorLayer(
            "Point?crs=EPSG:28992", "LS-aansluitingen ontwerpstroom", "memory"
        )
        review_layer.dataProvider().addAttributes(
            [QgsField("Hoogste Trafo", QVariant.Double)]
        )
        review_layer.updateFields()
        runner._style_review_connections(review_layer)
        review_symbol = review_layer.renderer().symbol()
        assert review_symbol.sizeUnit() == Qgis.RenderUnit.Pixels
        assert review_symbol.symbolLayer(0).sizeUnit() == Qgis.RenderUnit.Pixels
        assert review_symbol.symbolLayer(0).strokeWidthUnit() == Qgis.RenderUnit.Pixels
        assert (
            review_layer.labeling().settings().format().sizeUnit()
            == Qgis.RenderUnit.Pixels
        )

        station_layer = QgsVectorLayer(
            "Point?crs=EPSG:28992", "Bestaande stations (bron)", "memory"
        )
        station_layer.dataProvider().addAttributes(
            [
                QgsField("Station", QVariant.String),
                QgsField("trafo_power", QVariant.String),
            ]
        )
        station_layer.updateFields()
        station = QgsFeature(station_layer.fields())
        station.setAttributes(["079.1010", "630"])
        station.setGeometry(QgsGeometry.fromWkt("POINT(5 5)"))
        station_layer.dataProvider().addFeature(station)
        max_field = runner._ensure_station_max_current(
            station_layer, "trafo_power"
        )
        runner._style_review_stations(
            station_layer, "Station", "trafo_power", max_field
        )
        styled_station = next(station_layer.getFeatures())
        assert abs(float(styled_station["Max_A"]) - (630.0 / 0.23 / 3.0)) < 1e-9
        station_symbol = station_layer.renderer().rootRule().children()[0].symbol()
        assert station_symbol.symbolLayer(0).properties()["name"] == "square"
        assert station_symbol.color().getRgb()[:3] == (
            227,
            26,
            28,
        )
        station_labels = station_layer.labeling().settings()
        assert "Station" in station_labels.fieldName
        assert "Max_A" in station_labels.fieldName
        assert station_labels.priority == 10
        assert station_labels.placementSettings().allowDegradedPlacement()
        assert (
            station_labels.placementSettings().overlapHandling()
            == Qgis.LabelOverlapHandling.AllowOverlapAtNoCost
        )
        assert bool(
            station_layer.customProperty("LSNetontwerp/review_station_layer")
        )

        project = QgsProject.instance()
        project.clear()
        osm_test = QgsVectorLayer("Polygon?crs=EPSG:28992", "OSM", "memory")
        middle_test = QgsVectorLayer("LineString?crs=EPSG:28992", "Midden", "memory")
        front_test = QgsVectorLayer("Point?crs=EPSG:28992", "Voorgrond", "memory")
        project.addMapLayer(osm_test)
        project.addMapLayer(middle_test)
        project.addMapLayer(front_test)
        runner._set_step_one_render_order((front_test,), osm_test)
        assert project.layerTreeRoot().customLayerOrder()[0].id() == front_test.id()
        assert project.layerTreeRoot().customLayerOrder()[-1].id() == osm_test.id()
        for key in ("import", "housing", "current", "clustering"):
            assert runner._algorithm(key) is not None
        from ls_netontwerp_wizard.provider import LSNetontwerpProvider

        provider = LSNetontwerpProvider()
        provider.loadAlgorithms()
        assert len(provider.algorithms()) == 6
        assert {
            algorithm.name() for algorithm in provider.algorithms()
        } == {
            "hoogste_trafo_kabel_selectie",
            "bestaande_stations_selectie",
            "woningtype_selectie_herberekenen",
            "handmatige_clustercorrectie_selectie",
            "sleufroute_toevoegen_en_noden",
            "clustergebieden_topologisch_vereenvoudigen",
        }

        from ls_netontwerp_wizard.algorithms.woningtype_selectie_herberekenen_tool import (
            WoningtypeSelectieHerberekenenAlgorithm,
        )

        edit_housing = QgsVectorLayer(
            "Polygon?crs=EPSG:28992", "Woningtypen BAG/3DBAG", "memory"
        )
        edit_housing.dataProvider().addAttributes(
            [
                QgsField("Woningtype", QVariant.String),
                QgsField("bouwjaar", QVariant.Int),
            ]
        )
        edit_housing.updateFields()
        building = QgsFeature(edit_housing.fields())
        building.setAttributes(["vrijstaande woning", 2000])
        building.setGeometry(
            QgsGeometry.fromWkt("POLYGON((0 0,20 0,20 20,0 20,0 0))")
        )
        edit_housing.dataProvider().addFeature(building)
        edit_housing.selectAll()

        edit_points = QgsVectorLayer(
            "Point?crs=EPSG:28992", "LS-aansluitingen ontwerpstroom", "memory"
        )
        point_fields = [
            QgsField("service_connection_type_type", QVariant.String),
            QgsField("Gebruiksdoel", QVariant.String),
            QgsField("G_Type", QVariant.String),
        ]
        point_fields.extend(
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
        point_fields.extend(
            [
                QgsField("Gevonden_Woningtype", QVariant.String),
                QgsField("Gevonden_Bouwjaar", QVariant.String),
            ]
        )
        edit_points.dataProvider().addAttributes(point_fields)
        edit_points.updateFields()
        connection = QgsFeature(edit_points.fields())
        connection.setAttributes(
            ["3 x 25 A", "woonhuis", ""] + [0.0] * 6 + ["", ""]
        )
        connection.setGeometry(QgsGeometry.fromWkt("POINT(10 10)"))
        edit_points.dataProvider().addFeature(connection)

        housing_algorithm = WoningtypeSelectieHerberekenenAlgorithm()
        housing_algorithm.initAlgorithm()
        housing_result = housing_algorithm.processAlgorithm(
            {
                "WONINGEN": edit_housing,
                "AANSLUITINGEN": edit_points,
                "VELD_WONINGTYPE": "Woningtype",
                "VELD_BOUWJAAR": "bouwjaar",
                "VELD_DOORLAAT": "service_connection_type_type",
                "VELD_GEBRUIK": "Gebruiksdoel",
                "VELD_GAS": "G_Type",
                "NIEUW_WONINGTYPE": 2,
            },
            QgsProcessingContext(),
            QgsProcessingFeedback(),
        )
        assert housing_result["AANTAL_WONINGEN"] == 1
        assert housing_result["AANTAL_AANSLUITINGEN"] == 1
        changed_building = next(edit_housing.getFeatures())
        changed_connection = next(edit_points.getFeatures())
        assert changed_building["Woningtype"] == "appartement"
        assert changed_connection["Gevonden_Woningtype"] == "appartement"
        assert float(changed_connection["Hoogste Trafo"]) == 4.5

        from ls_netontwerp_wizard.algorithms.laagspanning_clustering_lib import (
            maak_clustering_engine as clustering_engine,
        )

        clustering_engine._AUTO_TOPOLOGY_MINIMUM_NEW = 16
        retry_counts = clustering_engine.automatic_new_station_count_options(
            total_load=9000.0,
            existing_capacity=3500.0,
            new_station_capacity=913.0,
        )
        assert 17 in retry_counts
        assert max(retry_counts) >= 26
        clustering_engine._AUTO_TOPOLOGY_MINIMUM_NEW = 0
        print("PLUGIN_HEADLESS_TEST_OK")
    finally:
        app.exitQgis()


if __name__ == "__main__":
    main()

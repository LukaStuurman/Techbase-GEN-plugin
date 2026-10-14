"""Station colors, separate input routes and persistent native layer-list behavior."""
import json
import os
from pathlib import Path
import sys
import tempfile

from qgis.PyQt.QtCore import Qt, QVariant, QSize
from qgis.core import (QgsApplication, QgsFeature, QgsField, QgsGeometry, QgsLayerTreeModel,
                       QgsProject, QgsVectorFileWriter, QgsVectorLayer, QgsFillSymbol,
                       QgsLineSymbol, QgsMapSettings, QgsMapRendererParallelJob, QgsRectangle, QgsRenderContext)
from qgis.PyQt.QtWidgets import QPushButton, QMainWindow


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    app = QgsApplication([], False)
    app.initQgis()
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    from ls_netontwerp_wizard.workflow import WorkflowRunner
    from ls_netontwerp_wizard.connection_sources import assign_station
    from ls_netontwerp_wizard.project_presentation import place_layer_before
    from ls_netontwerp_wizard.plugin import LSNetontwerpPlugin

    project = QgsProject.instance()
    project.clear()
    dialog = LSNetontwerpDashboardDialog(None)
    card1 = next(
        child for child in dialog.main_page.findChildren(QPushButton) if child.text() == "1.1. Ontwerpstroom maken"
    ).parentWidget()
    actions = card1.findChildren(QPushButton)
    assert [button.text() for button in actions] == ["1.1. Ontwerpstroom maken", "1.2. Stationskoppeling", "1.3. Nieuwbouw"]
    dialog.station_names_button.setEnabled(True)
    dialog.new_buildings_button.setEnabled(True)
    actions[1].click()
    assert dialog.page_stack.currentWidget() is dialog.station_link_page
    assert not dialog.station_link_page.station_group.isHidden() and dialog.station_link_page.bag_group.isHidden()
    dialog.show_home_page()
    actions[2].click()
    assert dialog.page_stack.currentWidget() is dialog.connection_sources_page
    assert dialog.connection_sources_page.station_group.isHidden() and not dialog.connection_sources_page.bag_group.isHidden()
    assert dialog.connection_sources_page.station_combo.parentWidget() is dialog.connection_sources_page.bag_group

    source = QgsVectorLayer("Point?crs=EPSG:28992", "temporary", "memory")
    source.dataProvider().addAttributes([QgsField(name, QVariant.String) for name in ("Master Asset ID", "Station")] + [QgsField("Hoogste Trafo", QVariant.Double)])
    source.updateFields()
    for i, station in enumerate((None, None, "999.009", None), 1):
        feature = QgsFeature(source.fields())
        feature.setGeometry(QgsGeometry.fromWkt(f"POINT({i} {i})"))
        feature.setAttributes([str(i), station, 5.5])
        source.dataProvider().addFeature(feature)
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        path = Path(directory)
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "connections"
        assert QgsVectorFileWriter.writeAsVectorFormatV3(source, str(path / "connections.gpkg"), project.transformContext(), options)[0] == QgsVectorFileWriter.NoError
        layer = QgsVectorLayer(str(path / "connections.gpkg") + "|layername=connections", "LS-aansluitingen ontwerpstroom", "ogr")
        assert layer.isValid()
        project.addMapLayer(layer)
        WorkflowRunner._style_review_connections(layer)
        node = project.layerTreeRoot().findLayer(layer.id())
        model = QgsLayerTreeModel(project.layerTreeRoot())
        model.setFlag(QgsLayerTreeModel.ShowLegend, True)
        display = Qt.ItemDataRole.DisplayRole if hasattr(Qt, "ItemDataRole") else Qt.DisplayRole
        decoration = Qt.ItemDataRole.DecorationRole if hasattr(Qt, "ItemDataRole") else Qt.DecorationRole
        assert node.isExpanded()
        legends = model.layerLegendNodes(node)
        assert [legend.data(display) for legend in legends] == ["Aansluitingen"]
        assert not legends[0].data(decoration).isNull()
        csv = path / "stations.csv"
        csv.write_text('"Master Asset ID","SourceFile"\n"1","001.025"\n"2","001.030"\n', encoding="utf-8-sig")
        summary = WorkflowRunner._apply_station_names_from_csv(layer, {"station_names_csv": str(csv), "station_name_csv_field": "SourceFile"})
        assert summary["matched"] == 2
        assert layer.renderer().type() == "categorizedSymbol" and layer.renderer().classAttribute() == "Station"
        colors = json.loads(layer.customProperty("LSNetontwerp/station_colors"))
        assert set(colors) == {"001.025", "001.030", "999.009"}
        assert len(set(colors.values())) == 3
        context = QgsRenderContext()
        layer.renderer().startRender(context, layer.fields())
        unknown = next(f for f in layer.getFeatures() if f["Master Asset ID"] == "4")
        assert layer.renderer().symbolForFeature(unknown, context).color().name() == "#94a3b8"
        layer.renderer().stopRender(context)
        assert layer.labelsEnabled() and "Hoogste Trafo" in layer.labeling().settings().fieldName
        model.refreshLayerLegend(node)
        legends = model.layerLegendNodes(node)
        assert len(legends) == 4
        assert {legend.data(display) for legend in legends} == {"001.025", "001.030", "999.009", "Geen station gekoppeld"}
        assert all(not legend.data(decoration).isNull() for legend in legends)
        WorkflowRunner._apply_station_names_from_csv(layer, {"station_names_csv": str(csv), "station_name_csv_field": "SourceFile"})
        assert json.loads(layer.customProperty("LSNetontwerp/station_colors")) == colors
        layer.selectByIds([next(f.id() for f in layer.getFeatures() if f["Master Asset ID"] == "1")])
        assign_station(layer, "001.040")
        assert "001.040" in json.loads(layer.customProperty("LSNetontwerp/station_colors"))
        assert json.loads(layer.customProperty("LSNetontwerp/station_colors"))["001.030"] == colors["001.030"]
        expected_colors = json.loads(layer.customProperty("LSNetontwerp/station_colors"))

        osm = QgsVectorLayer("Polygon?crs=EPSG:28992", "OpenStreetMap", "memory")
        project.addMapLayer(osm)
        manual = QgsVectorLayer("LineString?crs=EPSG:28992", "Eigen CAD", "memory")
        project.addMapLayer(manual)
        root = project.layerTreeRoot()
        root.setCustomLayerOrder([layer, osm, manual])
        root.setHasCustomLayerOrder(True)
        project.writeEntry("LSNetontwerp", "presentation_version", 146)
        project_path = str(path / "work.qgz")
        assert project.write(project_path)
        class Iface:
            window = QMainWindow()
            def mainWindow(self):
                return self.window
            def addPluginToVectorMenu(self, *_args):
                pass
            def addToolBarIcon(self, *_args):
                pass
            def removePluginVectorMenu(self, *_args):
                pass
            def removeToolBarIcon(self, *_args):
                pass
        plugin = LSNetontwerpPlugin(Iface())
        plugin.initGui()  # repairs an already-open generated project
        assert not root.hasCustomLayerOrder()
        assert root.layerOrder()[-1].id() == osm.id()
        assert root.findLayer(manual.id()).isVisible()
        WorkflowRunner._set_step_one_layer_visibility((layer, osm))
        assert root.findLayer(manual.id()).isVisible()  # user layers are not hidden
        root.setCustomLayerOrder([layer, osm, manual])
        root.setHasCustomLayerOrder(True)
        project.writeEntry("LSNetontwerp", "presentation_version", 146)
        assert project.write()
        layer_id = layer.id()
        del legends, model
        assert project.read(project_path)
        # The real readProject signal repairs legacy state during reopening.
        root = project.layerTreeRoot()
        layer = project.mapLayer(layer_id)
        assert layer.isValid() and layer.featureCount() == 4
        assert layer.renderer().type() == "categorizedSymbol"
        assert json.loads(layer.customProperty("LSNetontwerp/station_colors")) == expected_colors
        assert root.findLayer(layer.id()).isExpanded()
        assert not root.hasCustomLayerOrder()
        new_layer = QgsVectorLayer("LineString?crs=EPSG:28992", "Handmatig toegevoegd", "memory")
        project.addMapLayer(new_layer)
        order = root.layerOrder()
        assert order[0].id() == new_layer.id()
        assert root.findLayer(new_layer.id()).isVisible()
        assert order[-1].name() == "OpenStreetMap"
        # Confirm map output: the newly added line draws over an opaque background.
        background = project.mapLayersByName("OpenStreetMap")[0]
        feature = QgsFeature(background.fields())
        feature.setGeometry(QgsGeometry.fromWkt("POLYGON((0 0,6 0,6 6,0 6,0 0))"))
        background.dataProvider().addFeature(feature)
        background.renderer().setSymbol(QgsFillSymbol.createSimple({"color": "255,255,255,255"}))
        feature = QgsFeature(new_layer.fields())
        feature.setGeometry(QgsGeometry.fromWkt("LINESTRING(0.5 3,5.5 3)"))
        new_layer.dataProvider().addFeature(feature)
        new_layer.renderer().setSymbol(QgsLineSymbol.createSimple({"line_color": "255,0,0,255", "line_width": "2"}))
        settings = QgsMapSettings()
        settings.setDestinationCrs(new_layer.crs())
        settings.setLayers([item for item in root.layerOrder() if root.findLayer(item.id()).isVisible()])
        settings.setExtent(QgsRectangle(0, 0, 6, 6))
        settings.setOutputSize(QSize(240, 240))
        job = QgsMapRendererParallelJob(settings)
        job.start()
        job.waitForFinished()
        pixel = job.renderedImage().pixelColor(100, 120)
        assert pixel.red() > 180 and pixel.green() < 90, pixel.name()
        # A subsequent area operation also keeps native order and group membership.
        group = root.addGroup("Eigen groep")
        anchor = QgsVectorLayer("Polygon?crs=EPSG:28992", "Gebieden", "memory")
        project.addMapLayer(anchor, False)
        group.addLayer(anchor)
        replacement = QgsVectorLayer("Polygon?crs=EPSG:28992", "Vereenvoudigd", "memory")
        project.addMapLayer(replacement)
        place_layer_before(replacement, anchor, project)
        assert root.findLayer(replacement.id()).parent() is group
        assert group.children()[0].layer() is replacement
        assert not root.hasCustomLayerOrder() and project.mapLayer(replacement.id()) is replacement
        plugin.unload()
    print("STATION_PRESENTATION_TEST_OK (separate routes, random colors, native legend icons, reassignment, QGZ/GPKG persistence, manual additions, group-preserving order)", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()

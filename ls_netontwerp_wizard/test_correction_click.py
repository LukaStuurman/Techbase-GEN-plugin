"""Exercise real Qt clicked(bool), session resets and recovered virtual fields."""
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace
from qgis.core import QgsApplication, QgsFeature, QgsField, QgsFields, QgsGeometry, QgsProcessingContext, QgsProcessingFeedback, QgsProject, QgsVectorFileWriter, QgsVectorLayer, QgsVariantUtils
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtWidgets import QLabel, QPushButton


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    app = QgsApplication([], False)
    app.initQgis()
    from ls_netontwerp_wizard.repeated_correction_fix import _install_manual_page_reset, _install_visual_editor_reset
    from ls_netontwerp_wizard.algorithms.handmatige_cluster_correctie_tool import HandmatigeClusterCorrectieAlgorithm as Algorithm
    from ls_netontwerp_wizard.algorithms.laagspanning_clustering_tool import LaagspanningClusteringAlgorithm
    errors = []
    original_hook = sys.excepthook
    sys.excepthook = lambda *args: errors.append(args)
    calls = []
    class Manual:
        manual_status_label = QLabel("Ready")
        def run_manual_correction(self): calls.append("manual")
    class Visual:
        status_label = QLabel("Ready")
        def apply_change(self): calls.append("visual")
    _install_manual_page_reset(SimpleNamespace(LSNetontwerpDialog=Manual))
    _install_visual_editor_reset(SimpleNamespace(VisueleClusterEditorDialog=Visual))
    for instance, method in ((Manual(), "run_manual_correction"), (Visual(), "apply_change")):
        button = QPushButton()
        button.clicked.connect(getattr(instance, method))
        button.click()
        button.click()
    assert calls == ["manual", "manual", "visual", "visual"] and not errors, errors
    sys.excepthook = original_hook
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        source = QgsVectorLayer("Point?crs=EPSG:28992&field=Cluster:string", "Stations ontwerp", "memory")
        feature = QgsFeature(source.fields())
        feature.setAttributes(["S1"])
        feature.setGeometry(QgsGeometry.fromWkt("POINT(155000 463000)"))
        source.dataProvider().addFeatures([feature])
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName, options.layerName = "GPKG", "stations"
        path = Path(tmp) / "stations.gpkg"
        assert QgsVectorFileWriter.writeAsVectorFormatV3(source, str(path), QgsProject.instance().transformContext(), options)[0] == 0
        layer = QgsVectorLayer(f"{path}|layername=stations", "Stations ontwerp", "ogr")
        layer.addExpressionField("1", QgsField("Volgnummer", QVariant.Int))
        Algorithm._ensure_integer_field(layer, "Volgnummer")
        index = layer.fields().lookupField("Volgnummer")
        assert layer.fields().fieldOrigin(index) == QgsFields.OriginProvider
        assert layer.dataProvider().changeAttributeValues({next(layer.getFeatures()).id(): {index: 2}})
        layer.dataProvider().forceReload()
        assert next(layer.getFeatures())["Volgnummer"] == 2
        del layer
        original = QgsVectorLayer("Point?crs=EPSG:28992&field=Station:string&field=master_asset_id:string", "original", "memory")
        rows = []
        for station, asset in (("159.503", "asset-1"), (None, "asset-2")):
            row = QgsFeature(original.fields())
            row.setGeometry(QgsGeometry.fromWkt("POINT(155000 463000)"))
            row.setAttributes([station, asset])
            rows.append(row)
        original.dataProvider().addFeatures(rows)
        cleaned_path = Path(tmp) / "cleaned.gpkg"
        LaagspanningClusteringAlgorithm()._write_clean_source(original, cleaned_path, "points",
            [("GebiedLabel", 0, QVariant.String), ("Station", 0, QVariant.String)],
            QgsProcessingContext(), QgsProcessingFeedback(), 0, 100)
        cleaned = QgsVectorLayer(f"{cleaned_path}|layername=points", "cleaned", "ogr")
        cleaned_rows = list(cleaned.getFeatures())
        assert cleaned_rows[0]["Station"] == "159.503" and cleaned_rows[0]["GebiedLabel"] == "159.503"
        assert cleaned_rows[0]["master_asset_id"] == "asset-1"
        assert QgsVariantUtils.isNull(cleaned_rows[1]["Station"]) or cleaned_rows[1]["Station"] == ""
    print("CORRECTION_CLICK_TEST_OK (Qt clicks in both editors, repeated clicks, writable recovered numbering)", flush=True)
    app.exitQgis()


if __name__ == "__main__":
    main()

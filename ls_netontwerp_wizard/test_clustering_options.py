"""Late plan snapshots, configurable algorithm parameters and BAG boundary routes."""
import json
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch

from qgis.core import (QgsApplication, QgsFeature, QgsField, QgsGeometry, QgsProject,
    QgsVectorFileWriter, QgsVectorLayer)
from qgis.PyQt.QtCore import QVariant


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    app = QgsApplication([], False)
    app.initQgis()
    if "--preview" in sys.argv:
        from qgis.PyQt.QtGui import QFont, QFontDatabase
        for name in ("segoeui.ttf", "segoeuib.ttf"):
            QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / name))
        app.setFont(QFont("Segoe UI", 10))
    from ls_netontwerp_wizard.clustering_options import ClusteringOptionsDialog, save_options
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    from ls_netontwerp_wizard.workflow import WorkflowRunner
    project = QgsProject.instance()
    project.clear()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        project.setFileName(str(root / "work.qgz"))
        points = QgsVectorLayer("Point?crs=EPSG:28992", "points", "memory")
        points.dataProvider().addAttributes([QgsField("Hoogste Trafo", QVariant.Double),
            QgsField("Kabelstroom", QVariant.String)])
        points.updateFields()
        feature = QgsFeature(points.fields())
        feature.setAttributes([100, "7,5"])
        feature.setGeometry(QgsGeometry.fromWkt("POINT(156390 380742)"))
        points.dataProvider().addFeatures([feature])
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName, options.layerName = "GPKG", "points"
        source_path = root / "points.gpkg"
        assert QgsVectorFileWriter.writeAsVectorFormatV3(points, str(source_path), project.transformContext(), options)[0] == QgsVectorFileWriter.NoError
        points = QgsVectorLayer(str(source_path) + "|layername=points", "LS-aansluitingen ontwerpstroom", "ogr")
        project.addMapLayer(points)
        points.setCustomProperty("LSNetontwerp/review_current_layer", True)
        host = LSNetontwerpDashboardDialog(None)
        values = host.values()
        values.update(open_project=False, auto_cpu_threads=False, cpu_threads=1, field_design_current="Kabelstroom", max_route=700)
        state = {"status": "ontwerpstroom_controleren", "version": 1, "values": values,
            "result_dir": str(root), "work_project": str(root / "work.qgz"), "import_gpkg": str(root / "import.gpkg"),
            "points_gpkg": str(source_path), "points_layer": "points", "plan_gpkg": "", "clustering_dir": str(root / "clusters")}
        WorkflowRunner._write_state(state)
        host._restore_prepared_state()
        assert host.widgets["field_design_current"].text() == "Kabelstroom"
        host.widgets["max_route"].setValue(777)
        plan = QgsVectorLayer("Polygon?crs=EPSG:4326", "Later toegevoegd plangebied", "memory")
        plan.dataProvider().addAttributes([QgsField("name", QVariant.String)])
        plan.updateFields()
        for x in (5.40, 5.45):
            feature = QgsFeature(plan.fields())
            feature.setAttributes([str(x)])
            feature.setGeometry(QgsGeometry.fromWkt(f"POLYGON(({x} 51.4,{x+.01} 51.4,{x+.01} 51.41,{x} 51.41,{x} 51.4))"))
            plan.dataProvider().addFeatures([feature])
        project.addMapLayer(plan)
        plan.selectByIds([next(plan.getFeatures()).id()])
        dialog = ClusteringOptionsDialog(host)
        assert dialog.numbers["max_route"].value() == 777
        assert dialog.current_field.currentText() == "Kabelstroom"
        dialog.plan_combo.setCurrentIndex(dialog.plan_combo.findData(plan.id()))
        dialog.selected_only.setChecked(True)
        assert dialog.only_plan.isChecked()
        dialog.numbers["max_route"].setValue(555)
        dialog.numbers["new_station_kva"].setValue(400)
        dialog.numbers["target_utilization"].setValue(75)
        dialog.flat.setChecked(False)
        assert dialog.save(), dialog.status.text()
        saved = host.prepared_state
        assert saved["values"]["field_design_current"] == "Kabelstroom"
        assert saved["values"]["max_route"] == 555 and saved["values"]["only_plan"]
        assert not host.no_plan.isChecked()
        uri = WorkflowRunner._layer(saved["plan_gpkg"], "plangebied")
        copied = QgsVectorLayer(uri, "copied", "ogr")
        assert copied.isValid() and copied.featureCount() == 1
        assert copied.crs().authid() == "EPSG:28992"
        assert saved == json.loads(Path(saved["state_file"]).read_text(encoding="utf-8"))
        plan.startEditing()
        assert not dialog.save() and "bewerkingen" in dialog.status.text()
        plan.rollBack()
        # Capture the real staged workflow parameters without replacing its
        # configuration handling or touching a real user's input files.
        captured = {}
        final_project = root / "result.qgz"
        final_project.write_text("test", encoding="utf-8")

        class CaptureRunner(WorkflowRunner):
            def _validate_layer(self, uri, label):
                return uri

            def _run_algorithm(self, key, parameters, *args):
                captured.update(parameters)
                return {"QGIS_PROJECT": str(final_project)}

        CaptureRunner(saved["values"], lambda *_: None).cluster(saved)
        assert captured["ONTWERPSTROOM_VELD"] == "Kabelstroom"
        assert captured["MAX_ROUTE_M"] == 555 and captured["NIEUW_KVA"] == 400
        assert captured["VOORKEUR_BENUTTING"] == 75
        assert captured["PLANGEBIED"] == uri and captured["ALLEEN_BINNEN_PLANGEBIED"]
        assert captured["FLATKASTEN"] is None
        host.prepared_state = None
        host._restore_prepared_state()
        assert host.prepared_state["status"] == "gereed", "completed projects can be configured again"
        # No plan clears the stored binding, not just its screen text.
        cleared = save_options(host.prepared_state, saved["values"], None)
        assert cleared["plan_gpkg"] == "" and not cleared["values"]["only_plan"]
        assert not any(layer.customProperty("LSNetontwerp/plan_layer", False) for layer in project.mapLayers().values())
        # Step 3 opens the options dialog before running the algorithm.
        fake = ClusteringOptionsDialog(host)
        with patch("ls_netontwerp_wizard.clustering_options.ClusteringOptionsDialog", return_value=fake), patch.object(fake, "exec"), patch.object(host, "run_clustering") as run:
            host.cluster_button.click()
            run.assert_not_called()
        engine = WorkflowRunner(values, lambda *_: None)._algorithm("clustering")._load_engine()
        from shapely.geometry import Point, Polygon
        footprint = Polygon([(0, 0), (10, 0), (10, 10), (0, 10)])
        line = engine.line_inside_building(Point(-.195, 3), Point(-.299, 5), footprint)
        assert footprint.buffer(.35).covers(line)
        try:
            engine.line_inside_building(Point(-.4, 3), Point(5, 5), footprint)
        except RuntimeError:
            pass
        else:
            raise AssertionError("Outside the accepted BAG tolerance")
        courtyard = Polygon([(0,0),(20,0),(20,20),(0,20)], [[(5,5),(15,5),(15,15),(5,15)]])
        line = engine.line_inside_building(Point(2,10), Point(18,10), courtyard)
        assert courtyard.buffer(.35).covers(line) and line.length > 16
        if "--preview" in sys.argv:
            dialog.show()
            app.processEvents()
            assert dialog.grab().save(sys.argv[sys.argv.index("--preview") + 1])
        host.close()
        dialog.close()
        fake.close()
        project.clear()
    print("CLUSTERING_OPTIONS_TEST_OK (late selected plan, CRS, saved settings, Advanced edits, actual algorithm parameters, repeat runs, boundary tolerance, courtyard routing)", flush=True)
    app.exitQgis()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc(file=sys.__stderr__)
        raise

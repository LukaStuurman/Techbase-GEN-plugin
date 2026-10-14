"""Guided Qt controls, real correction worker and source preparation in a plan."""
from pathlib import Path
import sys
import tempfile
from unittest.mock import patch
from qgis.core import (QgsApplication, QgsFeature, QgsField, QgsGeometry,
    QgsProcessingContext, QgsProject, QgsVectorFileWriter, QgsVectorLayer)
from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QFont, QFontDatabase
from qgis.PyQt.QtWidgets import QMessageBox, QPushButton


def memory(name, kind, fields, rows):
    layer = QgsVectorLayer(kind + "?crs=EPSG:28992", name, "memory")
    layer.dataProvider().addAttributes([QgsField(key, typ) for key, typ in fields])
    layer.updateFields()
    features = []
    for values, wkt in rows:
        feature = QgsFeature(layer.fields())
        feature.setAttributes([values.get(field.name()) for field in layer.fields()])
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        features.append(feature)
    assert layer.dataProvider().addFeatures(features)[0]
    return layer


def save(layer, path, name, first=True):
    options = QgsVectorFileWriter.SaveVectorOptions()
    options.driverName, options.layerName = "GPKG", name
    if not first:
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteLayer
    assert QgsVectorFileWriter.writeAsVectorFormatV3(layer, str(path), QgsProject.instance().transformContext(), options)[0] == 0
    result = QgsVectorLayer(f"{path}|layername={name}", layer.name(), "ogr")
    assert result.isValid()
    return result


def fixture(root):
    project = QgsProject.instance()
    project.clear()
    project.setFileName(str(root / "project.qgz"))
    strings = ["Cluster", "Type"]
    numeric = ["KVA", "Max_A", "Belast_A", "Benut_pct", "Aantal", "Gem_route", "Max_route", "Route_km", "Volgnummer", "Net_X", "Net_Y"]
    summary_fields = [(s, QVariant.String) for s in strings] + [(s, QVariant.Double) for s in numeric]
    def summary(cluster, load, maximum, nr):
        return dict(Cluster=cluster, Type="Bestaand", KVA=maximum*.69, Max_A=maximum, Belast_A=load,
            Benut_pct=load/maximum*100, Aantal=4 if cluster=="S1" else 2, Gem_route=20, Max_route=30,
            Route_km=.03, Volgnummer=nr, Net_X=0 if nr==1 else 100, Net_Y=0)
    summaries = [summary("S1",75,100,1),summary("S2",45,80,2)]
    points_fields = [("Cluster",QVariant.String),("Ontwerp_A",QVariant.Double),("Stat_type",QVariant.String),
        ("Stat_KVA",QVariant.Double),("Max_A",QVariant.Double),("Clust_A",QVariant.Double),("Benut_pct",QVariant.Double),
        ("Route_m",QVariant.Double),("Snap_m",QVariant.Double),("Oud_gebied",QVariant.String)]
    points = []
    for x, load, cluster in ((5,0,"S1"),(10,20,"S1"),(20,30,"S1"),(30,25,"S1"),(80,20,"S2"),(90,25,"S2")):
        points.append((dict(Cluster=cluster,Ontwerp_A=load,Stat_type="Bestaand",Stat_KVA=69 if cluster=="S1" else 55.2,
            Max_A=100 if cluster=="S1" else 80,Clust_A=75 if cluster=="S1" else 45,Benut_pct=75,
            Route_m=x if cluster=="S1" else 100-x,Snap_m=0,Oud_gebied=""),f"POINT({x} 0)"))
    layers = [memory("Aansluitingen geclusterd","Point",points_fields,points),
        memory("Stations ontwerp","Point",summary_fields,[(summaries[0],"POINT(0 0)"),(summaries[1],"POINT(100 0)")]),
        memory("Clustergebieden","Polygon",summary_fields,[(summaries[0],"POLYGON((-5 -5,40 -5,40 5,-5 5,-5 -5))"),
            (summaries[1],"POLYGON((40 -5,105 -5,105 5,40 5,40 -5))")]),
        memory("Kabelroutes per cluster","LineString",summary_fields,[(summaries[0],"LINESTRING(0 0,30 0)"),(summaries[1],"LINESTRING(80 0,100 0)")]),
        memory("Sleuven geknipt/genood","LineString",[("Rekenfactor",QVariant.Double)],[(dict(Rekenfactor=1),"LINESTRING(0 0,5 0,10 0,20 0,30 0,50 0,80 0,90 0,100 0)")])]
    path = root / "result.gpkg"
    result = []
    for index, layer in enumerate(layers):
        result.append(save(layer,path,("aansluitingen_geclusterd","stations_ontwerp","clustergebieden","cluster_kabelroutes","sleuven_genood")[index],index==0))
        project.addMapLayer(result[-1])
    return result


def main():
    import faulthandler
    faulthandler.dump_traceback_later(45, exit=True)
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    app=QgsApplication([],False);app.initQgis()
    for font in ("segoeui.ttf","segoeuib.ttf"):
        QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts")/font))
    app.setFont(QFont("Segoe UI",10))
    from ls_netontwerp_wizard.repeated_correction_fix import install
    install()
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    from ls_netontwerp_wizard.cluster_paint_dialog import VisueleClusterEditorDialog
    from ls_netontwerp_wizard.algorithms.handmatige_cluster_correctie_tool import HandmatigeClusterCorrectieAlgorithm
    from ls_netontwerp_wizard.workflow import WorkflowRunner
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root=Path(tmp)
        points,stations,*_=fixture(root)
        host=LSNetontwerpDashboardDialog(None)
        errors=[]; oldhook=sys.excepthook;sys.excepthook=lambda *a:(errors.append(a),oldhook(*a))
        next(b for b in host.findChildren(QPushButton) if b.text().startswith("4a.")).click()
        editor=host._dashboard_visual_cluster_dialog;guide=editor.guide
        assert guide.action=="move" and editor.mode=="result" and not guide.advanced.isChecked()
        points.selectByIds([4]);guide.target_combo.setCurrentIndex(guide.target_combo.findData(2))
        assert guide.commit.isEnabled() and "70.0 / 80.0" in editor.preview_label.text(), (points.selectedFeatureIds(),stations.selectedFeatureIds(),guide._target_searching,editor.preview_label.text())
        guide.target_combo.setEditText("station dat niet bestaat")
        guide.target_combo.lineEdit().textEdited.emit("station dat niet bestaat")
        assert not guide.commit.isEnabled() and guide.target_combo.currentText()=="station dat niet bestaat"
        guide.target_combo.setCurrentIndex(0);guide.target_combo.setCurrentIndex(guide.target_combo.findData(2))
        assert guide.commit.isEnabled()
        guide.choose_action("merge")
        assert not guide.commit.isEnabled() and "4 aansluitingen" in editor.preview_label.text() and "120.0 / 80.0" in editor.preview_label.text()
        guide.choose_action("move")
        guide.cluster_combo.setCurrentIndex(guide.cluster_combo.findData("S1"));guide.select_cluster.click()
        assert len(points.selectedFeatureIds())==4
        points.selectByIds([4])
        captured={}
        def dispatch(_name,params,feedback=None):
            captured.update(params)
            assert not guide.action_combo.isEnabled() and feedback is not None
            feedback.setProgress(50);assert guide.cancel.isEnabled()
            feedback.setProgress(88);assert not guide.cancel.isEnabled()
            return {"VERPLAATST_AANTAL":1,"DOELSTATION":"S2"}
        with patch("ls_netontwerp_wizard.cluster_paint_dialog.processing.run",side_effect=dispatch):guide.commit.click()
        assert captured["CONTROLE_MAX_ONTWERPSTROOM"] and captured["CONTROLE_MAX_KABELLENGTE"] and captured["CONTROLE_ROUTES_ANDERE_CLUSTERS"] and captured["CONTROLE_GEDEELDE_ROUTES_VERTAKKINGEN"]
        assert not captured["HELE_BRONCLUSTER_VERWIJDEREN"] and not points.selectedFeatureIds() and not stations.selectedFeatureIds()
        guide.restore_selection.click();assert points.selectedFeatureIds()==[4]
        # Cancellation reaches the worker, leaves the choice intact and
        # restores controls; a failure is shown inline rather than as success.
        guide.target_combo.setCurrentIndex(guide.target_combo.findData(2))
        def cancelled(_name,params,feedback=None):
            assert guide.cancel.isEnabled()
            guide.cancel.click();assert feedback.isCanceled()
            raise RuntimeError("Geannuleerd")
        with patch("ls_netontwerp_wizard.cluster_paint_dialog.processing.run",side_effect=cancelled):guide.commit.click()
        assert guide.failed and "Geannuleerd" in editor.status_label.text() and guide.action_combo.isEnabled()
        assert points.selectedFeatureIds()==[4]
        next(b for b in host.findChildren(QPushButton) if b.text().startswith("4b.")).click()
        assert guide.action=="new" and editor.new_cluster_kva.value()==630 and guide.location_mode.currentData()=="auto"
        assert not errors,errors
        sys.excepthook=oldhook
        host.close()

        # Real worker through the new primary action; source data and routes update.
        editor=VisueleClusterEditorDialog(None);guide=editor.guide
        editor.backup_edit.setText(str(root/"backups"))
        def real_dispatch(_name,params,feedback=None):
            algorithm=HandmatigeClusterCorrectieAlgorithm();algorithm.initAlgorithm()
            return algorithm.processAlgorithm(params,QgsProcessingContext(),feedback)
        points.selectByIds([4]);guide.target_combo.setCurrentIndex(guide.target_combo.findData(2))
        with patch("ls_netontwerp_wizard.cluster_paint_dialog.processing.run",side_effect=real_dispatch):guide.commit.click()
        assert not guide.failed,editor.status_label.text()
        assert points.getFeature(4)["Cluster"]=="S2"
        assert stations.getFeature(2)["Belast_A"]==70
        guide.choose_action("new");points.selectByIds([2,3])
        with patch("ls_netontwerp_wizard.cluster_paint_dialog.processing.run",side_effect=real_dispatch):guide.commit.click()
        assert not guide.failed,editor.status_label.text()
        assert points.getFeature(2)["Cluster"]=="H-01" and points.getFeature(3)["Cluster"]=="H-01"
        assert next(f for f in stations.getFeatures() if f["Cluster"]=="H-01")["KVA"]==630
        editor.close()

        # Explicit 3b restores editable source layers even with result layers loaded.
        original=memory("LS-aansluitingen ontwerpstroom","Point",[("Teststroom",QVariant.Double),("Hoogste Trafo",QVariant.Double)],
            [({"Teststroom":i,"Hoogste Trafo":99},f"POINT({x} 0)") for i,x in enumerate((5,10,20,30,80,90))])
        save(original,root/"points.gpkg","points")
        source_stations=memory("Bestaande stations (bron)","Point",[("Station",QVariant.String),("trafo_power",QVariant.Double)],
            [(dict(Station="S1",trafo_power=69),"POINT(0 0)"),(dict(Station="S2",trafo_power=55.2),"POINT(100 0)")])
        save(source_stations,root/"import.gpkg","stations")
        main_cable=memory("Laagspanningskabels (bron)","LineString",[],[({},"LINESTRING(0 0,100 0)")])
        save(main_cable,root/"import.gpkg","main",False)
        plan=memory("Plangebied","Polygon",[],[({},"POLYGON((-1 -2,16 -2,16 2,-1 2,-1 -2))")])
        save(plan,root/"plan.gpkg","plangebied")
        host=LSNetontwerpDashboardDialog(None)
        values=host.values();values.update(layer_stations="stations",layer_main_cables="main",field_station_capacity="trafo_power",field_design_current="Teststroom",only_plan=True)
        host.prepared_state={"values":values,"result_dir":str(root),"points_gpkg":str(root/"points.gpkg"),"points_layer":"points",
            "import_gpkg":str(root/"import.gpkg"),"plan_gpkg":str(root/"plan.gpkg"),"status":"gereed"}
        host._open_visual_cluster_editor("prepare","new");editor=host._dashboard_visual_cluster_dialog;guide=editor.guide
        assert editor.mode=="prepare" and not editor.source_connections.readOnly()
        editor.backup_edit.setText(str(root/"pre-backups"))
        editor.source_connections.selectAll()
        assert "4 buiten het plangebied" in editor.selection_label.text()
        guide.commit.click();assert not guide.failed,editor.status_label.text()
        source=editor.source_connections
        assert all(f["GebiedLabel"]=="H-02" for f in guide.relevant_features(source,list(source.getFeatures())))
        assert host._manual_coverage(editor)==(2,2)
        assert editor.dashboard_manual_cluster_button.isEnabled() and not editor.dashboard_manual_cluster_button.isHidden()
        assert editor.dashboard_manual_cluster_button.parentWidget() is guide.commit.parentWidget()
        assert "2 van 2" in editor.pre_coverage_label.text()
        if "--preview" in sys.argv:
            host.resize(1180,820);host.show();app.processEvents()
            folder=Path(sys.argv[sys.argv.index("--preview")+1]);folder.mkdir(exist_ok=True)
            assert editor.dashboard_manual_cluster_button.isVisible()
            assert host.grab().save(str(folder/"prepare.png"))
        guide.restore_selection.click();editor.new_cluster_name.setText("H-02")
        assert not guide.commit.isEnabled()
        count=editor.source_stations.featureCount()
        try:editor._create_prepared_cluster("H-02",630)
        except RuntimeError:pass
        else:raise AssertionError("Duplicate must be rejected before deleting an existing station")
        assert editor.source_stations.featureCount()==count
        guide.choose_action("clear");source.selectByIds([2]);guide.commit.click()
        assert not guide.failed and host._manual_coverage(editor)==(1,2)
        assert not editor.dashboard_manual_cluster_button.isEnabled()
        guide.choose_action("assign");source.selectByIds([2]);guide.commit.click()
        assert not guide.failed and host._manual_coverage(editor)==(2,2)
        # Project-building failures return to preparation with usable controls.
        with patch.object(WorkflowRunner,"cluster",side_effect=RuntimeError("Project opbouwen geweigerd")),patch.object(QMessageBox,"critical") as critical_error:
            host._run_manual_clustering_from_editor()
            critical_error.assert_called_once()
        assert editor.mode=="prepare" and host.run_button.isEnabled() and host.cluster_button.isEnabled()
        # The actual full-manual dispatcher honors plan coverage, switches
        # back to result mode and keeps the workflow for later edits.
        def completed_workflow(_runner,state):
            assert state["values"]["automatic_stations"] is False and state["values"]["manual_station_count"]==0
            state["status"]="gereed"
            return {"result_dir":str(root),"project":str(root/"project.qgz")}
        def enforced():
            assert editor.mode=="result"
            editor._set_status("Gereed: handmatige indeling toegepast")
        def critical(_parent,title,message):
            raise AssertionError(f"{title}: {message}")
        def failed_enforcement():
            editor._error("Route is geweigerd")
        with patch.object(WorkflowRunner,"cluster",completed_workflow),patch.object(editor,"enforce_prepared_clusters",side_effect=failed_enforcement),patch.object(QMessageBox,"information") as success,patch.object(QMessageBox,"warning") as warning:
            host._run_manual_clustering_from_editor()
            success.assert_not_called();warning.assert_called_once()
        assert guide.failed and host.edit_values_button.isEnabled() and host.run_button.isEnabled()
        host._open_visual_cluster_editor("prepare","new")
        with patch.object(WorkflowRunner,"cluster",completed_workflow),patch.object(editor,"enforce_prepared_clusters",side_effect=enforced),patch.object(QMessageBox,"information"),patch.object(QMessageBox,"critical",side_effect=critical),patch.object(QMessageBox,"warning") as warning:
            host._run_manual_clustering_from_editor()
            warning.assert_not_called()
        assert editor.mode=="result" and host.prepared_state["status"]=="gereed"
        if "--preview" in sys.argv:
            host.resize(1180,820);host.show();app.processEvents()
            host._open_visual_cluster_editor("result","move");points.selectByIds([4]);guide.target_combo.setCurrentIndex(guide.target_combo.findData(3));app.processEvents()
            assert host.grab().save(str(folder/"redistribute.png"))
            guide.choose_action("new");app.processEvents();assert host.grab().save(str(folder/"new.png"))
        host._open_visual_cluster_editor("result","merge")
        points.selectByIds([2]);guide.target_combo.setCurrentIndex(guide.target_combo.findData(1))
        assert guide.commit.isEnabled() and "2 aansluitingen" in editor.preview_label.text()
        with patch("ls_netontwerp_wizard.cluster_paint_dialog.processing.run",side_effect=real_dispatch):guide.commit.click()
        assert not guide.failed,editor.status_label.text()
        assert points.getFeature(2)["Cluster"]=="S1" and points.getFeature(3)["Cluster"]=="S1"
        assert all(f["Cluster"]!="H-01" for f in stations.getFeatures())
        host.close();QgsProject.instance().clear()
    print("GUIDED_CLUSTER_EDITING_TEST_OK (actual Qt dashboard, search, merge totals, safety, progress, real move/new workers, plan-scoped source preparation, 630 kVA, duplicates)",flush=True)
    faulthandler.cancel_dump_traceback_later()
    app.exitQgis()


if __name__=="__main__":
    main()

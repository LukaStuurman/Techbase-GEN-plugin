"""Real isolated project generation, recovery and live station-overview labels."""
from pathlib import Path
import shutil
import sys
import tempfile

from qgis.core import QgsApplication, QgsExpression, QgsLayoutExporter, QgsProject
from qgis.PyQt.QtCore import QRectF, QSize


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    app = QgsApplication([], False)
    app.initQgis()
    from qgis.PyQt.QtGui import QFontDatabase
    for font in ("arial.ttf", "arialbd.ttf"):
        QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / font))
    from ls_netontwerp_wizard.workflow import WorkflowRunner
    project = QgsProject.instance()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        root = Path(tmp)
        project.setFileName(str(root / "work.qgz"))
        if "--input" in sys.argv:
            source = Path(sys.argv[sys.argv.index("--input") + 1])
            for name in ("clustering_ontwerp.gpkg", "cluster_overzicht.csv"):
                shutil.copy2(source / name, root / name)
        else:
            import geopandas as gpd
            from shapely.geometry import LineString, Point, Polygon
            import pandas as pd
            rows = [dict(Volgnummer=i, Cluster=f"S{i}", Type="Bestaand", KVA=630,
                Max_A=913.0, Belast_A=10.0 * i, Benut_pct=i, Aantal=i,
                geometry=Point(155000 + i * 10, 463000)) for i in (1, 2)]
            path = root / "clustering_ontwerp.gpkg"
            stations = gpd.GeoDataFrame(rows, geometry="geometry", crs="EPSG:28992")
            stations.drop(columns="Volgnummer").to_file(path, layer="stations_ontwerp", driver="GPKG")
            connections = stations.copy()
            connections["Station"] = ["S2", "S1"]
            connections["Master_asset_id"] = ["asset-1", "asset-2"]
            connections["Ontwerp_A"] = [10.0, 20.0]
            connections.to_file(path, layer="aansluitingen_geclusterd", driver="GPKG")
            gpd.GeoDataFrame([{**row, "geometry": Polygon([(155000,462990),(155030,462990),(155030,463010),(155000,463010)])} for row in rows], crs=stations.crs).to_file(path, layer="clustergebieden", driver="GPKG")
            cables = gpd.GeoDataFrame([{**row, "geometry": LineString([(155000,463000),(155030,463000)])} for row in rows], crs=stations.crs)
            cables.to_file(path, layer="sleuven_genood", driver="GPKG")
            cables.to_file(path, layer="cluster_kabelroutes", driver="GPKG")
            pd.DataFrame(rows).drop(columns="geometry").to_csv(root / "cluster_overzicht.csv", sep=";", decimal=",", index=False)
        state = {"values": {"open_project": False}, "result_dir": str(root), "clustering_dir": str(root), "status": "clustering_bezig"}
        runner = WorkflowRunner(state["values"], lambda *_: None)
        # Repeat independent worker starts because the original failure was a
        # native heap crash, masked intermittently by worker timing.
        for _round in range(3):
            project_path = runner.recover_project(state)
            assert runner._algorithm("clustering")._project_artifacts_valid(project_path, root / "clustering_overzicht.qpt")
            assert state["status"] == "gereed" and "Poging 1: code 0" in (root / "qgis_project_creation.log").read_text(encoding="utf-8")
        assert project.read(str(project_path))
        layout = project.layoutManager().layoutByName("Clustering overzicht")
        assert "Clustergebieden" not in [node.layer().name() for node in layout.itemById("legenda").model().rootGroup().findLayers()]
        scope = project.layoutManager().layoutByName("Scope")
        assert scope is not None and (root / "scope.qpt").exists()
        scope_layers = scope.itemById("scopekaart").layers()
        assert not any(layer.name() in ("Clustergebieden", "Kabelroutes per cluster", "Stations ontwerp") for layer in scope_layers)
        snapshot = next(layer for layer in scope_layers if layer.name() == "Aansluitingen bestaande stations (Scope)")
        scope_before = [(f["Station"], f["Master_asset_id"]) for f in snapshot.getFeatures()]
        assert snapshot.readOnly() and not scope.itemById("scopekaart").layerStyleOverrides()
        scope_table = scope.itemById("scope_stationsoverzicht")
        scope_rendered = QgsExpression.replaceExpressionText(scope_table.text(), scope.createExpressionContext())
        assert "[%" not in scope_rendered
        if "--input" not in sys.argv:
            assert scope_before == [("S2", "asset-1"), ("S1", "asset-2")], scope_before
            clustered = project.mapLayersByName("Aansluitingen geclusterd")[0]
            clustered.startEditing()
            clustered.changeAttributeValue(next(clustered.getFeatures()).id(), clustered.fields().lookupField("Cluster"), "S2")
            assert scope_before == [(f["Station"], f["Master_asset_id"]) for f in snapshot.getFeatures()]
            clustered.rollBack()
        table = layout.itemById("stationsoverzicht")
        assert table is not None and "aggregate(" in table.text()
        context = layout.createExpressionContext()
        rendered = QgsExpression.replaceExpressionText(table.text(), context)
        assert "[%" not in rendered and rendered.count("<td>") >= 12, rendered
        stations = next(layer for layer in project.mapLayers().values() if layer.name() == "Stations ontwerp")
        feature = next(stations.getFeatures())
        stations.startEditing()
        assert stations.changeAttributeValue(feature.id(), stations.fields().lookupField("Belast_A"), 123.4)
        changed = QgsExpression.replaceExpressionText(table.text(), layout.createExpressionContext())
        assert changed != rendered and ("123.4" in changed or "123,4" in changed)
        stations.rollBack()
        if "--preview" in sys.argv:
            map_item = layout.itemById("clusterkaart")
            map_item.setLayers([layer for layer in project.mapLayers().values() if layer.providerType() != "wms"])
            image = QgsLayoutExporter(layout).renderRegionToImage(QRectF(320, 15, 96, 155), QSize(1056, 1705))
            assert not image.isNull() and image.save(sys.argv[sys.argv.index("--preview") + 1])
        project.clear()
    print("PROJECT_RECOVERY_TEST_OK (3 native worker runs, no recalculation, valid QGZ/QPT, live station values and colors)", flush=True)
    app.exitQgis()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc(file=sys.__stderr__)
        raise

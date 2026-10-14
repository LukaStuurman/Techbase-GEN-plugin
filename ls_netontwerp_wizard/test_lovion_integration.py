"""Controlled LOVION integration: no desktop input, OCR or clipboard actions."""
import json
from pathlib import Path
import sys
import tempfile
import time

from qgis.PyQt.QtCore import QVariant
from qgis.core import (QgsApplication, QgsCoordinateTransform, QgsCoordinateReferenceSystem,
    QgsFeature, QgsField, QgsGeometry, QgsProject, QgsVectorLayer, QgsVectorFileWriter)


def layer(name, geometry, fields, records, crs="EPSG:28992"):
    result = QgsVectorLayer(f"{geometry}?crs={crs}", name, "memory")
    result.dataProvider().addAttributes([QgsField(field, QVariant.String) for field in fields])
    result.updateFields()
    features = []
    for values, wkt in records:
        feature = QgsFeature(result.fields())
        feature.setAttributes(values)
        feature.setGeometry(QgsGeometry.fromWkt(wkt))
        features.append(feature)
    result.dataProvider().addFeatures(features)
    result.updateExtents()
    QgsProject.instance().addMapLayer(result)
    return result


def wait(app, worker, timeout=45):
    deadline = time.monotonic() + timeout
    while not worker.finished and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.02)
    assert worker.finished, "worker timeout"
    app.processEvents()


def rejects(callback):
    try:
        callback()
    except ValueError:
        return
    raise AssertionError("Expected validation failure")


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    app = QgsApplication([], False)
    app.initQgis()
    from ls_netontwerp_wizard.lovion_session import (LovionSession, STATE_KEY, station_numbers,
        selected_station_numbers, stations_in_plan, verified_report)
    from ls_netontwerp_wizard.lovion_panel import LovionWorker
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    project = QgsProject.instance()
    project.clear()
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
        folder = Path(tmp)
        project.setFileName(str(folder / "project.qgz"))
        stations = layer("stations", "Point", ["Station"], [(["A"], "POINT(0 0)"),
            (["B"], "POINT(10 10)"), (["C"], "POINT(5 5)"), (["D"], "POINT(20 20)")])
        stations.setCustomProperty("LSNetontwerp/review_station_layer", True)
        areas = layer("plangebied", "Polygon", ["name"], [(["first"], "POLYGON((0 0,10 0,0 10,0 0))"),
            (["second"], "POLYGON((19 19,21 19,21 21,19 21,19 19))")])
        areas.selectByIds([next(areas.getFeatures()).id()])
        assert set(stations_in_plan(stations, "Station", areas)) == {"A", "C"}, "exact intersection and boundary"
        areas.removeSelection()
        assert set(stations_in_plan(stations, "Station", areas)) == {"A", "C", "D"}
        transformed = QgsGeometry.fromWkt("POLYGON((0 0,10 0,0 10,0 0))")
        transformed.transform(QgsCoordinateTransform(stations.crs(), QgsCoordinateReferenceSystem("EPSG:4326"), project))
        geographic = layer("geographic", "Polygon", ["name"], [(["geo"], transformed.asWkt())], "EPSG:4326")
        assert "C" in stations_in_plan(stations, "Station", geographic), "CRS transform"
        stations.removeSelection()
        rejects(lambda: selected_station_numbers(stations, "Station"))
        assert station_numbers("A;B\nA,c") == ["A", "B", "c"]
        rejects(lambda: station_numbers("bad/name"))
        target = layer("LS-aansluitingen ontwerpstroom", "Point", ["Master Asset ID", "Station", "Hoogste Trafo"],
            [(["123456789012345678", "original", "1"], "POINT(1 1)"),
             (["second", None, "1"], "POINT(2 2)"), (["third", "manual", "1"], "POINT(3 3)")])
        target.setCustomProperty("LSNetontwerp/review_current_layer", True)
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName, options.layerName = "GPKG", "connections"
        QgsVectorFileWriter.writeAsVectorFormatV3(target, str(folder / "connections.gpkg"), project.transformContext(), options)
        project.removeMapLayer(target.id())
        target = QgsVectorLayer(str(folder / "connections.gpkg"), "LS-aansluitingen ontwerpstroom", "ogr")
        target.setCustomProperty("LSNetontwerp/review_current_layer", True)
        project.addMapLayer(target)
        fixture = folder / "fixture.json"
        fixture.write_text(json.dumps({
            "A": [{"Status": "in bedrijf", "Assets": ["123456789012345678"]}, {"Status": "gepland"}],
            "B": [{"Status": "in bedrijf", "Assets": ["second"]}],
            "C": [{"Status": "in bedrijf", "Assets": ["third"]}, {"Error": "controlled failure"}],
            "D": [{"Status": "in bedrijf", "Manual": True}],
            "E": [{"Status": "in bedrijf", "Assets": ["outside-project"]}],
            "P": [{"Status": "gepland"}],
            "slow": [{"Status": "in bedrijf", "Assets": ["third"], "Delay": 1500}]
        }), encoding="utf-8")
        session = LovionSession(target)
        assert session.add(["A", "a", "B", "C", "D"]) == 4
        worker = LovionWorker(session, session.pending(), fixture)
        messages = []
        worker.completed.connect(messages.append)
        worker.start()
        wait(app, worker)
        assert session.data["stations"]["A"]["status"] == "done", messages
        assert session.data["stations"]["A"]["planned"] == 1
        assert session.data["stations"]["B"]["matched"] == 1
        assert session.data["stations"]["C"]["assets"] == [], "partial trafo set discarded"
        assert set(session.pending()) == {"C", "D"}
        values = {f["Master Asset ID"]: f["Station"] for f in target.getFeatures()}
        assert values == {"123456789012345678": "A", "second": "B", "third": "manual"}
        assert target.renderer().type() == "categorizedSymbol"
        assert len({c.symbol().color().name() for c in target.renderer().categories() if c.value() in {"A", "B"}}) == 2
        report = json.loads(worker.report.read_text(encoding="utf-8"))
        bad = folder / "bad.json"
        bad.write_text(json.dumps(dict(report, ImportedRows=999)), encoding="utf-8")
        rejects(lambda: verified_report(bad, worker.numbers))
        rejects(lambda: verified_report(worker.report, ["other-round"]))
        # Conflicting verified asset ownership must not partially write the layer.
        conflict_fixture = folder / "conflict.json"
        conflict_fixture.write_text(json.dumps({"conflict": [{"Status": "in bedrijf", "Assets": ["second"]}]}), encoding="utf-8")
        session.add(["conflict"])
        conflicting = LovionWorker(session, ["conflict"], conflict_fixture)
        conflict_messages = []
        conflicting.completed.connect(conflict_messages.append)
        conflicting.start()
        wait(app, conflicting)
        assert "Resultaat niet toegepast" in conflict_messages[0]
        assert session.data["stations"]["conflict"]["assets"] == []
        assert next(f for f in target.getFeatures() if f["Master Asset ID"] == "second")["Station"] == "B"
        session.remove(["conflict"])
        # Incremental run: only requested remaining stations, preserve earlier colors/results.
        session.remove(["C"])
        session.add(["E", "P"])
        second = LovionWorker(session, session.pending(), fixture)
        second.start()
        wait(app, second)
        assert second.numbers == ["D", "E", "P"]
        assert session.data["stations"]["D"]["status"] == "manual"
        assert session.data["stations"]["E"]["matched"] == 0
        assert session.data["stations"]["P"]["status"] == "planned"
        assert session.data["stations"]["A"]["matched"] == 1
        assert LovionSession(target).data == session.data
        # Failed explicit retry keeps the previously verified asset mappings.
        failed_fixture = folder / "failed.json"
        failed_fixture.write_text(json.dumps({"A": [{"Error": "retry failure"}]}), encoding="utf-8")
        session.retry(["A"])
        retry_worker = LovionWorker(session, ["A"], failed_fixture)
        retry_worker.start()
        wait(app, retry_worker)
        assert session.data["stations"]["A"]["assets"] == ["123456789012345678"]
        assert next(f for f in target.getFeatures() if f["Master Asset ID"] == "123456789012345678")["Station"] == "A"
        project.write()
        layer_id = target.id()
        project.clear()
        assert project.read(str(folder / "project.qgz"))
        target = project.mapLayer(layer_id)
        session = LovionSession(target)
        assert session.data["stations"]["A"]["matched"] == 1, "QGZ/GPKG persistence"
        # A user edit is preserved when removing the extractor's ownership.
        fid = next(f.id() for f in target.getFeatures() if f["Master Asset ID"] == "second")
        target.startEditing()
        rejects(lambda: session.remove(["B"]))
        target.changeAttributeValue(fid, target.fields().lookupField("Station"), "user-change")
        target.commitChanges()
        session.remove(["D"])
        assert target.getFeature(fid)["Station"] == "user-change", "unrelated removal preserves manual edits"
        session.remove(["B"])
        assert target.getFeature(fid)["Station"] == "user-change"
        session.reset()
        assert not session.data["stations"]
        assert next(f for f in target.getFeatures() if f["Master Asset ID"] == "123456789012345678")["Station"] == "original"
        # Cooperative stop uses a file; fixture mode never sends real input.
        session.add(["slow"])
        third = LovionWorker(session, ["slow"], fixture)
        third.event_received.connect(lambda event: third.stop() if event.get("type") == "station_started" else None)
        third.start()
        wait(app, third)
        assert session.data["stations"]["slow"]["status"] == "error"
        assert session.data["stations"]["slow"]["assets"] == []
        dialog = LSNetontwerpDashboardDialog(None)
        page = dialog.station_link_page
        page.refresh()
        panel = page.lovion_panel
        panel.manual.setPlainText("A;B")
        panel.add_manual()
        assert panel.table.rowCount() == 3
        panel.start(fixture)
        assert not page.target_combo.isEnabled()
        fourth = panel.worker
        wait(app, fourth)
        assert page.target_combo.isEnabled()
        assert panel.worker is None
        assert "A" in LovionSession(target).data["stations"]
        dialog.close()
        # Switching projects cancels extraction and never applies to a new layer.
        switched = LovionWorker(LovionSession(target), ["slow"], fixture)
        switched.event_received.connect(lambda event: project.clear() if event.get("type") == "station_started" else None)
        switched.start()
        wait(app, switched)
        fresh = layer("fresh", "Point", ["Master Asset ID", "Station"], [(["third", "untouched"], "POINT(1 1)")])
        assert next(fresh.getFeatures())["Station"] == "untouched"
        project.clear()
    print("LOVION_INTEGRATION_TEST_OK (exact/CRS intersection, multi-trafo, partial failure, incremental runs, manual review, cancellation, asset precision, colors, undo, persistence, UI worker)")
    app.exitQgis()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc(file=sys.__stderr__)
        raise

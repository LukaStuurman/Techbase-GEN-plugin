"""Offline BAG snapshots, API pagination and optional existing-object checks."""
import json
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import sys
import tempfile
import threading
import time
from urllib.parse import parse_qs, urlparse
from unittest.mock import patch

from qgis.core import QgsApplication, QgsCoordinateReferenceSystem, QgsProject, QgsRectangle
from qgis.gui import QgsMapCanvas
from qgis.PyQt.QtCore import QVariant


def wait(app, condition):
    deadline = time.monotonic() + 20
    while not condition() and time.monotonic() < deadline:
        app.processEvents()
        time.sleep(.01)
    assert condition(), "BAG download timeout"


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    app = QgsApplication([], False)
    app.initQgis()
    from ls_netontwerp_wizard.bag_download import (download_objects, local_objects_layer,
        map_bbox, BagDownloadTask, DownloadCancelled)
    from ls_netontwerp_wizard.connection_sources import add_selected_objects, CURRENT_FIELDS
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    from ls_netontwerp_wizard.test_connection_sources import make_layer, add
    project = QgsProject.instance()
    project.clear()
    objects = [{"type": "Feature", "id": f"object-{i}", "geometry": {
        "type": "Point", "coordinates": [5.425 + i * .0001, 51.415]}, "properties": {
        "identificatie": f"086101000000000{i}", "huisnummer": 10 + i, "huisletter": "A",
        "postcode": "5502HC", "toevoeging": "", "bronhouder_naam": "Veldhoven",
        "woonplaats_naam": "Zeelst", "gebruiksdoel": ["woonfunctie"]}}
        for i in range(1, 4)]
    requests = []

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            parsed = urlparse(self.path)
            query = parse_qs(parsed.query)
            requests.append((parsed.path, query))
            if parsed.path == "/broken":
                self.send_error(503)
                return
            second = query.get("page") == ["2"]
            links = [] if second else [{"rel": "next", "href": "?" + parsed.query + "&page=2"}]
            if parsed.path.startswith("/failed"):
                links = [{"rel": "next", "href": "/broken"}]
            if parsed.path.startswith("/repeat"):
                links = [{"rel": "next", "href": self.path}]
            data = {"type": "FeatureCollection", "features": objects[2:] if second else objects[:2], "links": links}
            raw = json.dumps(data).encode("utf-8")
            self.send_response(200)
            self.send_header("Content-Type", "application/geo+json")
            self.send_header("Content-Length", str(len(raw)))
            self.end_headers()
            self.wfile.write(raw)

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    url = f"http://127.0.0.1:{server.server_port}"
    bbox = (5.425, 51.414, 5.427, 51.416)
    try:
        with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as tmp:
            root = Path(tmp)
            project.setFileName(str(root / "project.qgz"))
            path = root / "snapshot.geojson"
            assert download_objects(url, bbox, path, page_size=2) == 3
            assert json.loads(path.read_text(encoding="utf-8"))["features"] == objects
            assert requests[0][1]["bbox"] == ["5.425,51.414,5.427,51.416"]
            assert requests[1][1]["page"] == ["2"]
            for mode in ("failed", "repeat"):
                failed_path = root / f"{mode}.geojson"
                try:
                    download_objects(url + "/" + mode, bbox, failed_path)
                except Exception:
                    pass
                else:
                    raise AssertionError("Incomplete download was accepted")
                assert not failed_path.exists() and not failed_path.with_suffix(".part").exists()
            stopped = [False]
            try:
                download_objects(url, bbox, root / "cancel.geojson", lambda: stopped[0],
                    lambda _count: stopped.__setitem__(0, True))
            except DownloadCancelled:
                pass
            else:
                raise AssertionError("Cancellation was ignored")
            assert not (root / "cancel.geojson").exists()
            source = local_objects_layer(path, bbox)
            assert source.providerType() == "ogr" and source.featureCount() == 3
            assert source.getFeature(next(source.getFeatures()).id())["identificatie"] == "0861010000000001"
            project.addMapLayer(source)
            target = make_layer("Point", "LS-aansluitingen ontwerpstroom", [
                ("BAG_VBO_ID", QVariant.String), ("zip_code", QVariant.String), ("housenumber", QVariant.String),
                ("toevoeging", QVariant.String), ("huisnummertoevoeging", QVariant.String)
            ] + [(name, QVariant.Double) for name in CURRENT_FIELDS])
            target.setCustomProperty("LSNetontwerp/review_current_layer", True)
            add(target, "POINT(156000 381000)", {"BAG_VBO_ID": "0861010000000001"})
            add(target, "POINT(156001 381001)", {"zip_code": "5502HC", "housenumber": "12", "toevoeging": "A"})
            before = set(target.allFeatureIds())
            dialog = LSNetontwerpDashboardDialog(None)
            zero = dialog.zero_current_page
            source.selectAll()
            protected = make_layer("Point", "protected", [(field.name(), field.type()) for field in target.fields()])
            add(protected, "POINT(156000 381000)", {"BAG_VBO_ID": "0861010000000001"})
            add(protected, "POINT(156001 381001)", {"zip_code": "5502HC", "housenumber": "12", "toevoeging": "A"})
            guarded = add_selected_objects(source, protected, None, zero, skip_existing=True)
            assert guarded["added"] == 1 and guarded["skipped"] == 2, "opt-in checks both BAG ID and address"
            result = add_selected_objects(source, target, None, zero, manual_currents=[10, 11, 12, 13])
            assert result == {"added": 3, "skipped": 0, "missing": 0}, result
            assert target.selectedFeatureCount() == 3 and not (before & set(target.selectedFeatureIds()))
            added = list(target.selectedFeatures())
            assert all(f["Ontwerpstroom"] == 10 and f["service_connection_type_type"] == "verblijfsobject" for f in added)
            assert added[0]["city"] == "Veldhoven" and added[0]["parish"] == "Zeelst"
            assert add_selected_objects(source, target, None, zero, skip_existing=True)["added"] == 0
            source.selectByIds([next(source.getFeatures()).id()])
            assert add_selected_objects(source, target, None, zero, manual_currents=[1, 2, 3, 4])["added"] == 1
            assert target.selectedFeatureCount() == 1
            # Actual asynchronous task fetches the same pages to a local file.
            completed = []
            task = BagDownloadTask(url, bbox, root / "background.geojson", lambda task, ok: completed.append((task.count, ok)))
            QgsApplication.taskManager().addTask(task)
            wait(app, lambda: bool(completed))
            assert completed == [(3, True)]
            canvas = QgsMapCanvas()
            canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:28992"))
            canvas.setExtent(QgsRectangle(156650, 381600, 156800, 381800))
            converted = map_bbox(canvas)
            assert 5 < converted[0] < 6 and 51 < converted[1] < 52
            canvas.setDestinationCrs(QgsCoordinateReferenceSystem("EPSG:4326"))
            canvas.setExtent(QgsRectangle(*bbox))

            class Iface:
                def mapCanvas(self):
                    return canvas

                def setActiveLayer(self, layer):
                    self.active = layer

            dialog.iface = Iface()
            page = dialog.connection_sources_page
            dialog.show_connection_sources_page()
            assert not page.skip_existing.isChecked()
            # Both choices really occupy the same row.
            form = page.bag_group.layout()
            # The buttons are children of the same nested horizontal layout.
            button_rows = [form.itemAt(i).layout() for i in range(form.count()) if form.itemAt(i).layout()]
            assert any(row.indexOf(page.bag_server_button) >= 0 and row.indexOf(page.bag_download_button) >= 0 for row in button_rows)
            assert page.bag_server_button.text() == "BAG-serververbinding"
            with patch.object(dialog, "_workflow_field_defaults", return_value={"bag_api_url": url}):
                page.bag_download_button.click()
                assert page._bag_download and not page.bag_server_button.isEnabled()
                wait(app, lambda: page._bag_download is None)
            offline = page.layer(page.source_combo)
            assert offline.providerType() == "ogr" and offline.featureCount() == 3, page.status.text()
            assert offline.id() == dialog.iface.active.id()
            assert "lokaal opgeslagen" in page.status.text()
            layer_id = offline.id()
            project.write()
            project.clear()
            assert project.read(str(root / "project.qgz"))
            reopened = project.mapLayer(layer_id)
            assert reopened.providerType() == "ogr" and reopened.featureCount() == 3
            # Offline feature access never touches the HTTP server.
            with patch("urllib.request.urlopen", side_effect=AssertionError("unexpected network")):
                assert len(list(reopened.getFeatures())) == 3
            if "--live-pdok" in sys.argv:
                live_path = root / "pdok.geojson"
                count = download_objects("https://api.pdok.nl/kadaster/bag/ogc/v2", bbox, live_path, page_size=2)
                live = local_objects_layer(live_path, bbox)
                assert count > 2 and live.featureCount() == count
                assert live.fields().lookupField("bronhouder_naam") >= 0
                assert live.fields().lookupField("gebruiksdoel") >= 0
                print(f"LIVE_PDOK_DOWNLOAD_OK ({count} objects, multiple pages, offline OGR layer)", flush=True)
            # A project switch cannot insert a download into the next project.
            with patch.object(dialog, "_workflow_field_defaults", return_value={"bag_api_url": url}):
                page.download_bag()
                assert page._bag_download is not None
                project.clear()
                wait(app, lambda: page._bag_download is None)
                assert not project.mapLayers()
                assert "Project gewijzigd" in page.status.text()
            if "--preview" in sys.argv:
                from qgis.PyQt.QtGui import QFont, QFontDatabase
                for font in ("segoeui.ttf", "segoeuib.ttf"):
                    QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / font))
                app.setFont(QFont("Segoe UI", 10))
                dialog.show_connection_sources_page()
                dialog.resize(1200, 960)
                dialog.show()
                app.processEvents()
                assert dialog.grab().save(sys.argv[sys.argv.index("--preview") + 1])
            dialog.close()
            canvas.close()
            project.clear()
    finally:
        server.shutdown()
        server.server_close()
    print("NEWBOUW_DOWNLOAD_TEST_OK (optional dedup, only new selection, all API pages, failure/cancel cleanup, CRS extent, background task, two-button UI, offline project reopen)", flush=True)
    app.exitQgis()


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import traceback
        traceback.print_exc(file=sys.__stderr__)
        raise

"""Download one fixed map extent to an offline GeoJSON layer."""
import json
import math
from pathlib import Path
import uuid
from urllib.parse import urlencode, urljoin
from urllib.request import Request, urlopen

from qgis.PyQt.QtCore import QStandardPaths, pyqtSignal
from qgis.core import QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsProject, QgsTask, QgsVectorLayer


class DownloadCancelled(Exception):
    pass


def map_bbox(canvas):
    extent = canvas.extent()
    if extent.isEmpty() or not canvas.mapSettings().destinationCrs().isValid():
        raise ValueError("Zoom eerst naar het gebied waarvoor je verblijfsobjecten wilt downloaden.")
    transform = QgsCoordinateTransform(canvas.mapSettings().destinationCrs(),
        QgsCoordinateReferenceSystem("EPSG:4326"), QgsProject.instance())
    bounds = transform.transformBoundingBox(extent)
    bbox = (bounds.xMinimum(), bounds.yMinimum(), bounds.xMaximum(), bounds.yMaximum())
    if (not all(math.isfinite(v) for v in bbox) or bbox[0] >= bbox[2] or bbox[1] >= bbox[3]
            or bbox[0] < -180 or bbox[2] > 180 or bbox[1] < -90 or bbox[3] > 90):
        raise ValueError("De kaartuitsnede kan niet naar een geldig BAG-downloadgebied worden omgezet.")
    return bbox


def download_path():
    name = f"bag_vbo_{uuid.uuid4().hex[:12]}.geojson"
    project = QgsProject.instance()
    base = Path(project.homePath()) if project.fileName() else None
    if base is None or len(str(base / name)) > 230:
        base = Path(QStandardPaths.writableLocation(QStandardPaths.StandardLocation.GenericDataLocation)) / "TechBase" / "BAG"
    base.mkdir(parents=True, exist_ok=True)
    return base / name


def download_objects(api_url, bbox, path, cancelled=lambda: False, progress=lambda count: None, page_size=1000):
    """Stream all API pages; publish only a fully completed local file."""
    path = Path(path)
    partial = path.with_suffix(".part")
    params = urlencode({"f": "json", "bbox": ",".join(format(v, ".12g") for v in bbox), "limit": page_size})
    url = str(api_url).rstrip("/") + "/collections/verblijfsobject/items?" + params
    visited, count = set(), 0
    try:
        with partial.open("w", encoding="utf-8", newline="\n") as handle:
            handle.write('{"type":"FeatureCollection","features":[')
            while url:
                if cancelled():
                    raise DownloadCancelled()
                if url in visited:
                    raise ValueError("De BAG-service herhaalt een downloadpagina; de download is niet compleet.")
                visited.add(url)
                request = Request(url, headers={"Accept": "application/geo+json", "User-Agent": "TechBase-QGIS"})
                with urlopen(request, timeout=30) as response:
                    page = json.load(response)
                if page.get("type") != "FeatureCollection" or not isinstance(page.get("features"), list):
                    raise ValueError("De BAG-service leverde geen geldige verblijfsobjectenpagina.")
                if "numberReturned" in page and int(page["numberReturned"]) != len(page["features"]):
                    raise ValueError("De BAG-service leverde een onvolledige downloadpagina.")
                for feature in page["features"]:
                    if cancelled():
                        raise DownloadCancelled()
                    if feature.get("type") != "Feature" or not isinstance(feature.get("properties"), dict):
                        raise ValueError("Een BAG-object in de download is ongeldig.")
                    if count:
                        handle.write(",")
                    json.dump(feature, handle, ensure_ascii=False)
                    count += 1
                progress(count)
                next_links = [link["href"] for link in page.get("links", []) if link.get("rel") == "next"]
                if len(next_links) > 1:
                    raise ValueError("De BAG-service gaf meerdere vervolgpagina's.")
                url = urljoin(url, next_links[0]) if next_links else None
            if cancelled():
                raise DownloadCancelled()
            handle.write("]}")
        partial.replace(path)
        return count
    finally:
        if partial.exists():
            partial.unlink()


def local_objects_layer(path, bbox):
    layer = QgsVectorLayer(str(path), "BAG verblijfsobjecten (lokaal)", "ogr")
    if not layer.isValid():
        raise ValueError("De gedownloade BAG-laag kon niet worden geopend.")
    layer.setCustomProperty("LSNetontwerp/bag_objects", True)
    layer.setCustomProperty("LSNetontwerp/bag_download_bbox", json.dumps(bbox))
    return layer


class BagDownloadTask(QgsTask):
    countChanged = pyqtSignal(int)

    def __init__(self, api_url, bbox, path, on_finished):
        super().__init__("BAG-verblijfsobjecten downloaden", QgsTask.Flag.CanCancel)
        self.api_url, self.bbox, self.path = api_url, bbox, Path(path)
        self.callback, self.count, self.error = on_finished, 0, ""

    def run(self):
        try:
            self.count = download_objects(self.api_url, self.bbox, self.path, self.isCanceled, self.countChanged.emit)
            return True
        except DownloadCancelled:
            self.error = "BAG-download gestopt. Er is geen onvolledige laag toegevoegd."
        except Exception as exc:
            self.error = f"BAG-download mislukt: {exc}"
        return False

    def finished(self, result):
        if not result and not self.error:
            self.error = "BAG-download gestopt. Er is geen onvolledige laag toegevoegd."
        self.callback(self, result)

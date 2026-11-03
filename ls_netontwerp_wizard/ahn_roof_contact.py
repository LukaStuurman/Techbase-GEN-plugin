"""Compacte AHN-dakcontactcontrole voor woningtypering.

Vervangt geen volledige 3DBAG-reconstructie: bepaal uitsluitend of de hoge
dakdelen van twee BAG-buurpanden doorlopen. Alleen 128m DSM-tegels met
aangrenzende woonpanden worden opgehaald; zij blijven lokaal gecachet.
"""
from __future__ import annotations

from collections import OrderedDict
from math import ceil, floor, hypot, isfinite
from pathlib import Path
from statistics import median
from urllib.parse import urlencode
from urllib.request import Request, urlopen

from qgis.PyQt.QtCore import QStandardPaths
from qgis.core import (
    QgsFeature, QgsFeatureRequest, QgsGeometry, QgsPointXY,
    QgsRasterLayer, QgsRectangle, QgsSpatialIndex,
)


AHN_WCS_URL = "https://service.pdok.nl/rws/ahn/wcs/v1_0"
AHN_COVERAGE = "dsm_05m"
GRID_METERS = 128
CACHE_VERSION = "dsm05_v1"
MAX_DOWNLOAD_BYTES = 10 * 1024 * 1024


def _percentile(values, fraction):
    values = sorted(v for v in values if v is not None and isfinite(v))
    if not values:
        return None
    return values[min(len(values) - 1, int((len(values) - 1) * fraction))]


def roof_connection_decision(seam_a, seam_b, inside_a, inside_b):
    """True=doorlopend hoog dak, False=duidelijke lage/andere verbinding, None=onzeker.

    Alleen sterke aanwijzingen wijzigen de BAG-classificatie. Onzekere AHN
    profielen mogen nooit stilzwijgend als 'losse daken' worden beschouwd.
    """
    if min(len(seam_a), len(seam_b)) < 3:
        return None
    edge_a, edge_b = median(seam_a), median(seam_b)
    peak_a, peak_b = _percentile(inside_a, 0.85), _percentile(inside_b, 0.85)
    if peak_a is None or peak_b is None:
        return None

    height_difference = abs(edge_a - edge_b)
    low_connection = max(peak_a - edge_a, peak_b - edge_b)

    # Een lage carport/aanbouw naast een aanzienlijk hoger hoofddak.
    if low_connection >= 3.7 or height_difference >= 3.0:
        return False
    # Alleen aantoonbaar vergelijkbare, hooggelegen dakdelen verbinden.
    if height_difference <= 1.25 and low_connection <= 2.8:
        return True
    return None


def _line_segments(geometry):
    """Geef segmenten van een (multi)lijn, ook in geometrieverzamelingen."""
    if geometry is None or geometry.isEmpty():
        return
    if geometry.isMultipart():
        for part in geometry.asGeometryCollection():
            yield from _line_segments(part)
        return
    try:
        points = geometry.asPolyline()
    except (TypeError, ValueError):
        return
    for before, after in zip(points, points[1:]):
        length = hypot(after.x() - before.x(), after.y() - before.y())
        if length >= 0.4:
            yield before, after, length


def _contact_samples(geom_a, geom_b):
    # De BAG kan een gevelverschil van enkele decimeters hebben.
    shared = geom_a.boundary().intersection(geom_b.buffer(0.65, 4))
    segments = sorted(_line_segments(shared), key=lambda value: -value[2])
    result = []
    for start, end, length in segments:
        count = max(1, min(10, int(ceil(length / 3.0))))
        dx, dy = (end.x() - start.x()) / length, (end.y() - start.y()) / length
        nx, ny = -dy, dx
        for index in range(count):
            if len(result) >= 12:
                return result
            f = (index + 0.5) / count
            x, y = start.x() + f * (end.x() - start.x()), start.y() + f * (end.y() - start.y())
            for sign in (1, -1):
                a = QgsPointXY(x + sign * nx * 1.6, y + sign * ny * 1.6)
                b = QgsPointXY(x - sign * nx * 1.6, y - sign * ny * 1.6)
                if (geom_a.contains(QgsGeometry.fromPointXY(a))
                        and geom_b.contains(QgsGeometry.fromPointXY(b))):
                    result.append((x, y, nx * sign, ny * sign, dx, dy))
                    break
    return result


class AhnRoofContact:
    """Bereken dakcontact uit lokale AHN DSM-hoogtes, zonder 3DBAG-server."""

    def __init__(self, feedback, cache_dir=None, offline_only=False, refresh=False):
        self.feedback = feedback
        self.offline_only = bool(offline_only)
        self.refresh = bool(refresh)
        if cache_dir is None:
            cache_dir = (Path(QStandardPaths.writableLocation(
                QStandardPaths.StandardLocation.GenericDataLocation
            )) / "TechBase" / "AHN_dakprofielen" / CACHE_VERSION)
        self.cache_dir = Path(cache_dir)
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self._rasters = OrderedDict()
        self._failed = set()
        self._refreshed = set()
        self._errors = 0
        self._downloads = 0
        self._warned = False

    def _tile_path(self, key):
        return self.cache_dir / ("dsm_%d_%d.tif" % key)

    def _download(self, key, path):
        if self.offline_only or self._errors >= 3:
            return False
        x0, y0 = key[0] * GRID_METERS, key[1] * GRID_METERS
        padding = 2
        args = [
            ("SERVICE", "WCS"), ("VERSION", "2.0.1"),
            ("REQUEST", "GetCoverage"), ("COVERAGEID", AHN_COVERAGE),
            ("FORMAT", "image/tiff"),
            ("SUBSET", "x(%.1f,%.1f)" % (x0-padding, x0+GRID_METERS+padding)),
            ("SUBSET", "y(%.1f,%.1f)" % (y0-padding, y0+GRID_METERS+padding)),
        ]
        url = AHN_WCS_URL + "?" + urlencode(args)
        part = path.with_suffix(".part")
        try:
            request = Request(url, headers={
                "Accept": "image/tiff", "User-Agent": "TechBase-QGIS-AHN-roof/1.0"
            })
            with urlopen(request, timeout=20) as response, part.open("wb") as output:
                size = 0
                while True:
                    if self.feedback.isCanceled():
                        return False
                    chunk = response.read(65536)
                    if not chunk:
                        break
                    size += len(chunk)
                    if size > MAX_DOWNLOAD_BYTES:
                        raise ValueError("AHN-uitsnede onverwacht groot")
                    output.write(chunk)
            with part.open("rb") as f:
                signature = f.read(4)
            if signature not in (b"II*\x00", b"MM\x00*", b"II+\x00", b"MM\x00+"):
                raise ValueError("De AHN WCS gaf geen TIFF terug")
            part.replace(path)
            self._downloads += 1
            if self._downloads == 1 or self._downloads % 20 == 0:
                self.feedback.pushInfo(
                    "AHN: %d compacte DSM-tegels lokaal opgeslagen in %s"
                    % (self._downloads, self.cache_dir)
                )
            return True
        except Exception as exc:
            self._errors += 1
            if not self._warned:
                self.feedback.reportError(
                    "AHN DSM tijdelijk niet beschikbaar (%s). Ongeteste daken "
                    "behouden de BAG-classificatie en krijgen een waarschuwing in de attributen."
                    % exc
                )
                self._warned = True
            return False
        finally:
            if part.exists():
                part.unlink()

    def _raster(self, x, y):
        key = (floor(x / GRID_METERS), floor(y / GRID_METERS))
        if key in self._failed:
            return None
        if key in self._rasters:
            self._rasters.move_to_end(key)
            return self._rasters[key]
        path = self._tile_path(key)
        if (self.refresh and key not in self._refreshed) or not path.is_file():
            if not self._download(key, path):
                self._failed.add(key)
                return None
            self._refreshed.add(key)
        raster = QgsRasterLayer(str(path), "AHN lokale DSM", "gdal")
        if not raster.isValid():
            self._failed.add(key)
            return None
        self._rasters[key] = raster
        if len(self._rasters) > 8:
            self._rasters.popitem(last=False)
        return raster

    def height(self, x, y):
        raster = self._raster(x, y)
        if raster is None:
            return None
        height, valid = raster.dataProvider().sample(QgsPointXY(x, y), 1)
        if not valid or not isfinite(height) or height < -100 or height > 1000:
            return None
        return float(height)

    def check_pair(self, geom_a, geom_b):
        contacts = _contact_samples(geom_a, geom_b)
        if len(contacts) < 2:
            return None
        seam_a, seam_b, inside_a, inside_b = [], [], [], []
        for x, y, nx, ny, tx, ty in contacts:
            if self.feedback.isCanceled():
                return None
            # Meet de hoogte net binnen beide pandcontouren.
            za = self.height(x + nx*1.6, y + ny*1.6)
            zb = self.height(x - nx*1.6, y - ny*1.6)
            if za is None or zb is None:
                continue
            seam_a.append(za)
            seam_b.append(zb)
            inside_a.append(za)
            inside_b.append(zb)
            # Verder naar binnen: detecteer lage carports en aanbouwen.
            for depth in (3.5, 6.0, 9.0, 12.0):
                pa = QgsPointXY(x + nx*depth, y + ny*depth)
                pb = QgsPointXY(x - nx*depth, y - ny*depth)
                if geom_a.contains(QgsGeometry.fromPointXY(pa)):
                    inside_a.append(self.height(pa.x(), pa.y()))
                if geom_b.contains(QgsGeometry.fromPointXY(pb)):
                    inside_b.append(self.height(pb.x(), pb.y()))
        return roof_connection_decision(
            [v for v in seam_a if v is not None],
            [v for v in seam_b if v is not None],
            [v for v in inside_a if v is not None],
            [v for v in inside_b if v is not None],
        )

    def populate_tile(self, tile_data, tolerance=0.2):
        """Check uitsluitend BAG-buurparen met een woonfunctie."""
        candidates = []
        spatial = QgsSpatialIndex()
        local = {}
        for index, item in enumerate(tile_data):
            item["ahn_roof_links"] = {}
            item["ahn_unknown_count"] = 0
            if item["has_woon"] and not item["is_app"] and not item["ignore_neighbor"]:
                feature = QgsFeature(index)
                feature.setGeometry(item["geom"])
                candidates.append(feature)
                local[index] = item
        if not candidates:
            return
        spatial.addFeatures(candidates)
        for index, item in local.items():
            if self.feedback.isCanceled():
                return
            bbox = QgsRectangle(item["geom"].boundingBox())
            bbox.grow(tolerance)
            for other_id in spatial.intersects(bbox):
                if other_id <= index:
                    continue
                other = local.get(other_id)
                if other is None:
                    continue
                geom_a, geom_b = item["geom"], other["geom"]
                if not (geom_a.intersects(geom_b) or geom_a.distance(geom_b) <= tolerance):
                    continue
                verdict = self.check_pair(geom_a, geom_b)
                if verdict is None:
                    item["ahn_unknown_count"] += 1
                    other["ahn_unknown_count"] += 1
                else:
                    item["ahn_roof_links"][other_id] = verdict
                    other["ahn_roof_links"][index] = verdict

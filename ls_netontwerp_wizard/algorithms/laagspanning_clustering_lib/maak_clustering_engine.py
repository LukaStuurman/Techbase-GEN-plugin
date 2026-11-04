from __future__ import annotations

import io
import json
import math
import os
import re
import shutil
import subprocess
import sys
import tempfile
import time
import warnings
from concurrent.futures import ThreadPoolExecutor, as_completed
from collections import Counter, defaultdict
from pathlib import Path
from threading import Lock
from urllib.error import HTTPError, URLError
from urllib.parse import urlencode
from urllib.request import Request, urlopen

import geopandas as gpd
import matplotlib.pyplot as plt
import networkx as nx
import numpy as np
import pandas as pd
import matplotlib.patheffects as patheffects
from matplotlib.lines import Line2D
from matplotlib.patches import Rectangle
from osgeo import ogr
from pyproj import Transformer
from scipy.optimize import Bounds, LinearConstraint, milp
from scipy.sparse import coo_matrix, csr_matrix, diags, hstack, identity, kron, vstack
from scipy.sparse.csgraph import dijkstra
from scipy.spatial import cKDTree
from shapely import points as shapely_points, voronoi_polygons
from shapely.geometry import LineString, MultiPoint, Point, shape
from shapely.ops import linemerge, nearest_points, substring, unary_union
from shapely.strtree import STRtree


warnings.filterwarnings(
    "ignore",
    message=r"Unrecognized options detected:.*threads.*",
    category=RuntimeWarning,
)


ROOT = Path(__file__).resolve().parent
POINTS_PATH = ROOT / "Ls Aansluitingen.shp"
CABLES_PATH = ROOT / "kabels_civiele sleuf.shp"
CONNECTION_CABLES_PATH: Path | None = None
FLAT_CABINETS_PATH: Path | None = None
STATIONS_PATH = ROOT / "stations.shp"
STATION_ENCLOSURES_PATH: Path | None = None
DISTRIBUTION_CABINETS_PATH: Path | None = None
PLANGEBIED_PATH: Path | None = None
BAG_API_BASE_URL = "https://api.pdok.nl/kadaster/bag/ogc/v2"
BAG_BUILDINGS_PATH: Path | None = None  # Prefer the previously calculated BAG housing layer.
ONLY_WITHIN_PLAN_AREA = True
ALLOW_EXTERNAL_ROUTES = True
LS_FUNCTION_TERMS: tuple[str, ...] = ("LS",)
CONNECTION_FUNCTION_TERMS: tuple[str, ...] = ("LS",)
LS_FUNCTION_FILTER_ENABLED = False
CONNECTION_FUNCTION_FILTER_ENABLED = False
OUT = ROOT / "resultaat_clustering"
CRS_RD = "EPSG:28992"
N_NEW = 0  # Filled automatically unless AUTO_NEW_STATIONS is disabled.
NEW_KVA = 630.0
AUTO_NEW_STATIONS = True
CREATE_QGIS_PROJECT = True
TARGET_UTILIZATION = 0.90
TARGET_UTILIZATION_PENALTY = 10_000.0
MAP_OUTPUT_DPI = 600
LAYOUT_EXPORT_DPI = 600
LAYOUT_CONNECTION_SCALE = 0.40
LAYOUT_STATION_SYMBOL_SCALE = 0.67
LAYOUT_STATION_LABEL_SCALE = 0.50
LAYOUT_STATION_LABEL_DISTANCE_MM = 3.0
LAYOUT_FLAT_CABINET_SCALE = 0.20
LAYOUT_ROUTE_WIDTH_SCALE = 0.20
OSM_MAX_ZOOM = 19
OSM_MAXIMUM_TILES = 384
MAX_ROUTE_M = 850.0
NEW_STATION_POINT_CLEARANCE_M = 1.50
NEW_STATION_FALLBACK_OFFSET_M = 2.00
NEW_STATION_CONNECTION_CABLE_CLEARANCE_M = 0.25
WRITE_SHAPEFILES = False
AUTO_NODE_CABLES = True
NODE_TOLERANCE_M = 1.0
CPU_THREADS = max(
    1,
    min(
        64,
        int(os.environ.get("LS_NETONTWERP_THREADS", "0") or 0)
        or max(1, (os.cpu_count() or 1) - 1),
    ),
)
MAX_AUTOMATIC_TOPOLOGY_RETRIES = 10
_AUTO_COUNTS_TRIED: set[int] = set()
_AUTO_TOPOLOGY_MINIMUM_NEW = 0
MIN_UTILIZATION = (0.80, 0.75, 0.70, 0.60, 0.50, 0.0)
LEGACY_CHANGE_PENALTY_M = 65.0
CONTIGUITY_CHANGE_PENALTY_M = 90.0


def log(message: str) -> None:
    print(message, flush=True)


def milp_options(time_limit: float, mip_rel_gap: float) -> dict:
    """HiGHS options shared by all integer optimizations."""
    return {
        "time_limit": time_limit,
        "mip_rel_gap": mip_rel_gap,
        "presolve": True,
        # SciPy forwards this native HiGHS option even when it warns that the
        # key is not part of SciPy's small documented option subset.
        "threads": int(CPU_THREADS),
        "parallel": CPU_THREADS > 1,
    }


def extract_design_current(path: Path) -> tuple[np.ndarray, int, str]:
    """Read the populated Ontwerpstroom field by DBF field index.

    The source shapefile contains six field names that DBF truncates to the same
    ten characters. GeoPandas therefore cannot reliably distinguish them. OGR
    can read them by index; the populated candidate is selected automatically.
    """
    ogr.UseExceptions()
    ds = ogr.Open(str(path))
    if ds is None:
        raise RuntimeError(f"Kan {path.name} niet openen")
    layer = ds.GetLayer(0)
    definition = layer.GetLayerDefn()
    candidates = [
        i
        for i in range(definition.GetFieldCount())
        if definition.GetFieldDefn(i).GetName().lower().startswith("ontwerpstro")
    ]
    if not candidates:
        raise RuntimeError("Geen veld Ontwerpstroom gevonden")

    best_index = -1
    best_values: list[float] = []
    best_count = -1
    for index in candidates:
        values: list[float] = []
        count = 0
        layer.ResetReading()
        for feature in layer:
            if feature.IsFieldSetAndNotNull(index):
                values.append(float(feature.GetField(index)))
                count += 1
            else:
                values.append(0.0)
        if count > best_count:
            best_count = count
            best_index = index
            best_values = values
    name = definition.GetFieldDefn(best_index).GetName()
    return np.asarray(best_values, dtype=float), best_index, name


def parse_design_kva(status: str) -> float:
    """Use the last capacity value; a literal KVA suffix is optional."""
    text = str(status).strip()
    values = re.findall(r"[-+]?\d+(?:[.,]\d+)?", text)
    if not values:
        raise ValueError(f"Geen numerieke trafocapaciteit gevonden: {status!r}")
    value = float(values[-1].replace(",", "."))
    if value <= 0.0:
        raise ValueError(f"Trafocapaciteit moet positief zijn: {status!r}")
    return value


def weighted_geometric_median(xy: np.ndarray, weights: np.ndarray) -> np.ndarray:
    weights = np.asarray(weights, dtype=float)
    if not np.any(weights > 0):
        weights = np.ones(len(xy), dtype=float)
    y = np.average(xy, axis=0, weights=weights)
    for _ in range(100):
        distances = np.linalg.norm(xy - y, axis=1)
        if np.any(distances < 1e-8):
            return xy[np.argmin(distances)].copy()
        new_y = np.sum(xy * (weights / distances)[:, None], axis=0) / np.sum(
            weights / distances
        )
        if np.linalg.norm(new_y - y) < 0.01:
            return new_y
        y = new_y
    return y


def line_parts(geometry):
    """Yield every usable LineString part in an arbitrary geometry."""
    if geometry is None or geometry.is_empty:
        return
    if geometry.geom_type in ("LineString", "LinearRing"):
        if geometry.length > 1e-7:
            yield LineString(geometry.coords)
        return
    if hasattr(geometry, "geoms"):
        for child in geometry.geoms:
            yield from line_parts(child)


def merge_linework(geometries):
    """Merge one or more line geometries, including the one-line edge case."""
    usable_parts = [
        part for geometry in geometries for part in line_parts(geometry)
    ]
    if not usable_parts:
        return LineString()
    merged = unary_union(usable_parts)
    if merged.geom_type == "LineString":
        return merged
    return linemerge(merged)


def normalize_link_id(value) -> str:
    """Normalize spreadsheet/DBF identifiers without losing textual IDs."""
    if value is None or pd.isna(value):
        return ""
    text = str(value).strip()
    if re.fullmatch(r"[-+]?\d+\.0+", text):
        text = text.split(".", 1)[0]
    return text.casefold()


def equipment_line_parts(geometry):
    """Yield network linework for line/polygon equipment geometries."""
    if geometry is None or geometry.is_empty or geometry.geom_type == "Point":
        return
    source = geometry.boundary if geometry.geom_type in ("Polygon", "MultiPolygon") else geometry
    yield from line_parts(source)


def make_equipment_network_links(
    cables: gpd.GeoDataFrame,
    stations: gpd.GeoDataFrame,
    station_enclosures: gpd.GeoDataFrame | None,
    distribution_cabinets: gpd.GeoDataFrame | None,
    tolerance_m: float,
) -> gpd.GeoDataFrame:
    """Make zero-cost conductors through station outlines and cabinets."""
    records: list[dict] = []
    tolerance_m = max(0.0, float(tolerance_m))
    cable_endpoints: list[Point] = []
    for cable_geometry in cables.geometry:
        for part in line_parts(cable_geometry):
            cable_endpoints.extend((Point(part.coords[0]), Point(part.coords[-1])))
    endpoint_tree = STRtree(cable_endpoints) if cable_endpoints else None

    if station_enclosures is not None and not station_enclosures.empty:
        enclosure_by_name: dict[str, list[object]] = defaultdict(list)
        for _index, row in station_enclosures.iterrows():
            normalized_name = normalize_link_id(row.get("Stationsnaa", ""))
            if normalized_name:
                enclosure_by_name[normalized_name].append(row.geometry)
            for part in equipment_line_parts(row.geometry):
                records.append(
                    {
                        "Element": "Stationomtrek",
                        "Stationsnaam": str(row.get("Stationsnaa", "")),
                        "Lengte_m": float(part.length),
                        "Reken_m": 0.0,
                        "geometry": part,
                    }
                )
            if endpoint_tree is not None:
                contact_geometry = (
                    row.geometry.boundary
                    if row.geometry.geom_type in ("Polygon", "MultiPolygon")
                    else row.geometry
                )
                for raw_endpoint_index in endpoint_tree.query(
                    row.geometry.buffer(tolerance_m)
                ):
                    endpoint = cable_endpoints[int(raw_endpoint_index)]
                    if endpoint.distance(contact_geometry) > tolerance_m + 1e-9:
                        continue
                    target = nearest_points(endpoint, contact_geometry)[1]
                    connector = LineString([endpoint, target])
                    if connector.length <= 1e-7:
                        continue
                    records.append(
                        {
                            "Element": "Kabel-stationomtrek",
                            "Stationsnaam": str(row.get("Stationsnaa", "")),
                            "Lengte_m": float(connector.length),
                            "Reken_m": 0.0,
                            "geometry": connector,
                        }
                    )
        linked_station_count = 0
        for _station_index, station in stations.iterrows():
            station_name = str(station.get("Stationsnaa", ""))
            geometries = enclosure_by_name.get(normalize_link_id(station_name), [])
            if not geometries:
                continue
            enclosure_geometry = unary_union(geometries)
            perimeter = (
                enclosure_geometry.boundary
                if enclosure_geometry.geom_type in ("Polygon", "MultiPolygon")
                else enclosure_geometry
            )
            target = nearest_points(station.geometry, perimeter)[1]
            connector = LineString([station.geometry, target])
            if connector.length > 1e-7:
                records.append(
                    {
                        "Element": "Stationpunt-omtrek",
                        "Stationsnaam": station_name,
                        "Lengte_m": float(connector.length),
                        "Reken_m": 0.0,
                        "geometry": connector,
                    }
                )
            linked_station_count += 1
        log(
            f"Stationomtrekken: {linked_station_count} stationpunt(en) via "
            "de gekozen stationsnaam aan hun vierkant/omtrek gekoppeld."
        )

    if distribution_cabinets is not None and not distribution_cabinets.empty:
        cabinet_connector_count = 0
        for cabinet_number, cabinet in enumerate(
            distribution_cabinets.geometry, start=1
        ):
            for part in equipment_line_parts(cabinet):
                records.append(
                    {
                        "Element": "Verdeelkast",
                        "Stationsnaam": "",
                        "Lengte_m": float(part.length),
                        "Reken_m": 0.0,
                        "geometry": part,
                    }
                )
            if endpoint_tree is None:
                continue
            contact_geometry = (
                cabinet.boundary
                if cabinet.geom_type in ("Polygon", "MultiPolygon")
                else cabinet
            )
            search_geometry = cabinet.buffer(tolerance_m)
            for raw_endpoint_index in endpoint_tree.query(search_geometry):
                endpoint = cable_endpoints[int(raw_endpoint_index)]
                if endpoint.distance(contact_geometry) > tolerance_m + 1e-9:
                    continue
                target = nearest_points(endpoint, contact_geometry)[1]
                connector = LineString([endpoint, target])
                if connector.length <= 1e-7:
                    continue
                records.append(
                    {
                        "Element": f"Kabel-verdeelkast {cabinet_number}",
                        "Stationsnaam": "",
                        "Lengte_m": float(connector.length),
                        "Reken_m": 0.0,
                        "geometry": connector,
                    }
                )
                cabinet_connector_count += 1
        log(
            f"Verdeelkasten: {len(distribution_cabinets)} object(en) als "
            f"netwerkknooppunt toegevoegd; {cabinet_connector_count} kleine "
            "kabeleindkoppeling(en) binnen de knooptolerantie gemaakt."
        )

    if not records:
        return gpd.GeoDataFrame(
            columns=["Element", "Stationsnaam", "Lengte_m", "Reken_m", "geometry"],
            geometry="geometry",
            crs=CRS_RD,
        )
    return gpd.GeoDataFrame(records, geometry="geometry", crs=CRS_RD)


def _load_local_bag_buildings(
    bounds: tuple[float, float, float, float],
) -> gpd.GeoDataFrame:
    """Reuse the complete BAG footprints already saved by the housing-type step.

    This avoids fetching a second, potentially inconsistent BAG snapshot from PDOK.
    Incomplete or invalid local data must fail visibly rather than silently dropping
    apartment connections.
    """
    try:
        buildings = gpd.read_file(BAG_BUILDINGS_PATH)
        if buildings.crs is None:
            raise ValueError("De lokale BAG-pandenlaag heeft geen CRS")
        buildings = buildings.to_crs(CRS_RD)
        if "BAG_ID" not in buildings.columns:
            raise ValueError("De lokale BAG-pandenlaag mist de identificatiekolom BAG_ID")
        if "Status" not in buildings.columns:
            buildings["Status"] = ""
        buildings = buildings.cx[bounds[0]:bounds[2], bounds[1]:bounds[3]].copy()
        buildings = buildings.loc[
            buildings.geometry.notna()
            & ~buildings.geometry.is_empty
            & ~buildings["Status"].fillna("").astype(str).str.casefold().str.contains("gesloopt", regex=False)
        ].copy()
        if buildings.empty:
            raise ValueError("Geen BAG-pandcontouren in het benodigde appartementgebied")
        buildings["BAG_ID"] = buildings["BAG_ID"].fillna("").astype(str)
        buildings = buildings.loc[buildings["BAG_ID"].str.strip().ne("")].copy()
        if buildings.empty:
            raise ValueError("Geen geldige BAG-pandidentificaties in de lokale laag")
        buildings = buildings.drop_duplicates(subset=["BAG_ID"]).reset_index(drop=True)
    except Exception as exc:
        raise RuntimeError(
            "De lokale woningtypenlaag kon niet als BAG-pandgeometrie worden "
            f"gebruikt: {exc}. Controleer de laag 'Woningtypen BAG/3DBAG'."
        ) from exc
    log(
        f"BAG woningtypenlaag: {len(buildings):,} lokale pandgeometrieën "
        "hergebruikt; geen nieuwe PDOK-aanvraag nodig."
    )
    return buildings


def _fetch_bag_page(url: str, max_attempts: int = 3) -> dict:
    """Retry transient OGC/network failures; never add records from a failed page."""
    request = Request(
        url,
        headers={
            "Accept": "application/geo+json, application/json",
            "User-Agent": "QGIS-Laagspanning-Clustering/1.0",
        },
    )
    for attempt in range(1, max_attempts + 1):
        try:
            with urlopen(request, timeout=45) as response:
                payload = json.loads(response.read().decode("utf-8"))
            if not isinstance(payload, dict) or not isinstance(payload.get("features"), list):
                raise ValueError("BAG OGC API stuurde geen geldige FeatureCollection")
            return payload
        except Exception as exc:
            retryable = (
                exc.code in (429, 500, 502, 503, 504)
                if isinstance(exc, HTTPError)
                else isinstance(exc, (TimeoutError, ConnectionError, URLError, OSError))
            )
            if not retryable or attempt == max_attempts:
                raise RuntimeError(
                    "De BAG-pandgeometrie kon niet via de ingestelde OGC API "
                    f"worden opgehaald (poging {attempt}/{max_attempts}): {exc}"
                ) from exc
            pause = min(2 ** (attempt - 1), 4)
            log(
                f"BAG OGC API reageert niet (poging {attempt}/{max_attempts}): "
                f"{exc}; opnieuw proberen over {pause} s."
            )
            time.sleep(pause)
    raise AssertionError("Onbereikbaar: BAG-opvraag zonder resultaat")


def fetch_bag_buildings(bounds: tuple[float, float, float, float]) -> gpd.GeoDataFrame:
    """Fetch RD New BAG footprints, preferring the existing local housing layer."""
    if BAG_BUILDINGS_PATH is not None:
        return _load_local_bag_buildings(bounds)
    crs_uri = "http://www.opengis.net/def/crs/EPSG/0/28992"
    parameters = {
        "f": "json",
        "bbox": ",".join(f"{coordinate:.3f}" for coordinate in bounds),
        "bbox-crs": crs_uri,
        "crs": crs_uri,
        "limit": "1000",
    }
    next_url = (
        BAG_API_BASE_URL.rstrip("/")
        + "/collections/pand/items?"
        + urlencode(parameters)
    )
    records: list[dict] = []
    page_count = 0
    visited_urls: set[str] = set()
    while next_url:
        page_count += 1
        if page_count > 100 or next_url in visited_urls:
            raise RuntimeError("BAG OGC API gaf een ongeldige of cyclische paginering")
        visited_urls.add(next_url)
        payload = _fetch_bag_page(next_url)
        for feature in payload.get("features", []):
            geometry_payload = feature.get("geometry")
            if not geometry_payload:
                continue
            geometry = shape(geometry_payload)
            if geometry.is_empty:
                continue
            if not geometry.is_valid:
                geometry = geometry.buffer(0)
            if geometry.is_empty:
                continue
            properties = feature.get("properties") or {}
            status = str(properties.get("status") or "")
            if "gesloopt" in status.casefold():
                continue
            records.append(
                {
                    "BAG_ID": str(
                        properties.get("identificatie")
                        or feature.get("id")
                        or ""
                    ),
                    "Status": status,
                    "geometry": geometry,
                }
            )
        next_url = next(
            (
                str(link.get("href"))
                for link in payload.get("links", [])
                if str(link.get("rel", "")).casefold() == "next"
                and link.get("href")
            ),
            "",
        )
    buildings = gpd.GeoDataFrame(records, geometry="geometry", crs=CRS_RD)
    if buildings.empty:
        raise RuntimeError("De BAG OGC API gaf geen panden in het invoergebied terug")
    buildings = buildings.drop_duplicates(subset=["BAG_ID"]).reset_index(drop=True)
    log(f"BAG OGC API: {len(buildings):,} actuele pandgeometrieën opgehaald.")
    return buildings

BAG_POINT_TOLERANCE_M = 0.35


def point_building_index(
    point: Point,
    buildings: gpd.GeoDataFrame,
    building_tree: STRtree,
    tolerance_m: float = BAG_POINT_TOLERANCE_M,
) -> int | None:
    """Return the smallest BAG building covering a point (boundary tolerant)."""
    candidate_indices = building_tree.query(point.buffer(tolerance_m))
    covered = [
        int(raw_index)
        for raw_index in candidate_indices
        if buildings.geometry.iloc[int(raw_index)].buffer(tolerance_m).covers(point)
    ]
    if not covered:
        return None
    return min(covered, key=lambda index: buildings.geometry.iloc[index].area)


def line_inside_building(start: Point, end: Point, building) -> LineString:
    """Shortest straight/visibility path that remains in a BAG footprint."""
    direct = LineString([start, end])
    # Points accepted by point_building_index must also be reachable by the
    # indoor path. GEN positions can sit just outside the BAG footprint.
    permitted = building.buffer(BAG_POINT_TOLERANCE_M)
    if permitted.covers(direct):
        return direct

    vertices: list[Point] = [start, end]
    polygon_parts = (
        list(building.geoms) if building.geom_type == "MultiPolygon" else [building]
    )
    for polygon in polygon_parts:
        vertices.extend(Point(coordinate) for coordinate in polygon.exterior.coords[:-1])
        for ring in polygon.interiors:
            vertices.extend(Point(coordinate) for coordinate in ring.coords[:-1])
    # BAG footprints can be highly detailed. Keep visibility construction
    # bounded while retaining the corners most useful for a short indoor path.
    if len(vertices) > 302:
        boundary_vertices = vertices[2:]
        step = max(1, math.ceil(len(boundary_vertices) / 300))
        vertices = vertices[:2] + boundary_vertices[::step]
    visibility = nx.Graph()
    for index, vertex in enumerate(vertices):
        visibility.add_node(index, point=vertex)
    for first in range(len(vertices)):
        for second in range(first + 1, len(vertices)):
            segment = LineString([vertices[first], vertices[second]])
            if permitted.covers(segment):
                visibility.add_edge(first, second, weight=float(segment.length))
    try:
        path_indices = nx.shortest_path(visibility, 0, 1, weight="weight")
    except (nx.NetworkXNoPath, nx.NodeNotFound) as exc:
        raise RuntimeError(
            "Binnen een BAG-pand kon geen geldige sleuf naar de flatkast/kabel "
            "worden geconstrueerd"
        ) from exc
    coordinates = [vertices[index].coords[0] for index in path_indices]
    return LineString(coordinates)


def nearest_cable_target(point: Point, cables: gpd.GeoDataFrame, building=None):
    """Find nearest cable position, preferring cable geometry inside a building."""
    if building is not None:
        inside_parts = []
        for geometry in cables.geometry:
            if geometry is None or geometry.is_empty:
                continue
            if not geometry.intersects(building):
                continue
            inside_parts.extend(line_parts(geometry.intersection(building.buffer(0.02))))
        if inside_parts:
            inside_tree = STRtree(inside_parts)
            line = inside_parts[int(inside_tree.nearest(point))]
            return line.interpolate(line.project(point)), True
    cable_parts = [
        part for geometry in cables.geometry for part in line_parts(geometry)
    ]
    if not cable_parts:
        raise RuntimeError("Geen kabel beschikbaar voor de appartementaansluiting")
    cable_tree = STRtree(cable_parts)
    line = cable_parts[int(cable_tree.nearest(point))]
    return line.interpolate(line.project(point)), False


def make_apartment_trenches(
    points: gpd.GeoDataFrame,
    flat_cabinets: gpd.GeoDataFrame,
    cables: gpd.GeoDataFrame,
) -> tuple[gpd.GeoDataFrame, gpd.GeoDataFrame]:
    """Connect multistory points to a matched cabinet or nearest BAG cable."""
    if "Multistory" not in points.columns or "Flatkast_ID" not in flat_cabinets.columns:
        raise RuntimeError("Voor appartementen ontbreken Multistory/Flatkast_ID")
    apartment_mask = points["Multistory"].map(normalize_link_id).ne("")
    apartment_points = points.loc[apartment_mask].copy()
    if apartment_points.empty:
        log("Flatkastenlaag gekozen, maar geen gevulde multistory-ID's gevonden.")
        empty_lines = gpd.GeoDataFrame(
            columns=["Multistory", "Flatkast_ID", "BAG_ID", "Koppeling", "Lengte_m", "Reken_m", "geometry"],
            geometry="geometry",
            crs=CRS_RD,
        )
        return empty_lines, gpd.GeoDataFrame(
            columns=["BAG_ID", "Status", "geometry"], geometry="geometry", crs=CRS_RD
        )

    requested_ids = {
        normalize_link_id(value) for value in apartment_points["Multistory"]
    }
    relevant_cabinet_geometries = [
        geometry
        for value, geometry in zip(
            flat_cabinets["Flatkast_ID"], flat_cabinets.geometry
        )
        if normalize_link_id(value) in requested_ids
    ]
    query_geometries = list(apartment_points.geometry) + relevant_cabinet_geometries
    minx = min(geometry.x for geometry in query_geometries) - 5.0
    miny = min(geometry.y for geometry in query_geometries) - 5.0
    maxx = max(geometry.x for geometry in query_geometries) + 5.0
    maxy = max(geometry.y for geometry in query_geometries) + 5.0
    buildings = fetch_bag_buildings((minx, miny, maxx, maxy))
    building_tree = STRtree(list(buildings.geometry))

    cabinet_by_id: dict[str, list[int]] = defaultdict(list)
    for index, value in enumerate(flat_cabinets["Flatkast_ID"]):
        normalized = normalize_link_id(value)
        if normalized:
            cabinet_by_id[normalized].append(index)
    cabinet_buildings = [
        point_building_index(geometry, buildings, building_tree)
        for geometry in flat_cabinets.geometry
    ]

    records: list[dict] = []
    connected_cabinets: set[int] = set()
    matched_count = 0
    fallback_inside_count = 0
    fallback_outside_count = 0
    used_building_indices: set[int] = set()
    for _point_index, point_row in apartment_points.iterrows():
        point = point_row.geometry
        link_value = point_row["Multistory"]
        link_id = normalize_link_id(link_value)
        building_index = point_building_index(point, buildings, building_tree)
        if building_index is not None:
            used_building_indices.add(building_index)
        building = (
            buildings.geometry.iloc[building_index]
            if building_index is not None
            else None
        )
        candidates = cabinet_by_id.get(link_id, [])
        same_building = [
            index
            for index in candidates
            if building_index is not None and cabinet_buildings[index] == building_index
        ]
        cabinet_index = None
        if same_building:
            cabinet_index = min(
                same_building,
                key=lambda index: point.distance(flat_cabinets.geometry.iloc[index]),
            )

        if cabinet_index is not None:
            cabinet = flat_cabinets.geometry.iloc[cabinet_index]
            geometry = line_inside_building(point, cabinet, building)
            records.append(
                {
                    "Multistory": str(link_value),
                    "Flatkast_ID": str(flat_cabinets.iloc[cabinet_index]["Flatkast_ID"]),
                    "BAG_ID": buildings.iloc[building_index]["BAG_ID"],
                    "Koppeling": "Aansluiting-flatkast",
                    "Lengte_m": float(geometry.length),
                    "Reken_m": 0.0,
                    "geometry": geometry,
                }
            )
            matched_count += 1
            if cabinet_index not in connected_cabinets:
                target, target_inside = nearest_cable_target(cabinet, cables, building)
                connector = (
                    line_inside_building(cabinet, target, building)
                    if target_inside
                    else LineString([cabinet, target])
                )
                if connector.length > 1e-6:
                    records.append(
                        {
                            "Multistory": str(link_value),
                            "Flatkast_ID": str(flat_cabinets.iloc[cabinet_index]["Flatkast_ID"]),
                            "BAG_ID": buildings.iloc[building_index]["BAG_ID"],
                            "Koppeling": "Flatkast-kabel",
                            "Lengte_m": float(connector.length),
                            "Reken_m": 0.0,
                            "geometry": connector,
                        }
                    )
                connected_cabinets.add(cabinet_index)
            continue

        target, target_inside = nearest_cable_target(point, cables, building)
        geometry = (
            line_inside_building(point, target, building)
            if target_inside and building is not None
            else LineString([point, target])
        )
        fallback_inside_count += int(target_inside)
        fallback_outside_count += int(not target_inside)
        records.append(
            {
                "Multistory": str(link_value),
                "Flatkast_ID": "",
                "BAG_ID": (
                    str(buildings.iloc[building_index]["BAG_ID"])
                    if building_index is not None
                    else ""
                ),
                "Koppeling": (
                    "Dichtstbijzijnde kabel in BAG-pand"
                    if target_inside
                    else "Dichtstbijzijnde kabel buiten BAG-pand"
                ),
                "Lengte_m": float(geometry.length),
                "Reken_m": 0.0,
                "geometry": geometry,
            }
        )

    trenches = gpd.GeoDataFrame(records, geometry="geometry", crs=CRS_RD)
    used_buildings = buildings.iloc[sorted(used_building_indices)].copy()
    log(
        "Appartementverbindingen: "
        f"{matched_count} aansluiting(en) via een flatkast in hetzelfde BAG-pand; "
        f"{fallback_inside_count} via dichtstbijzijnde kabel binnen het pand; "
        f"{fallback_outside_count} via de algemene dichtstbijzijnde kabel. "
        f"Deze sleuven tellen voor 0 m mee in de {MAX_ROUTE_M:g}-metercontrole."
    )
    return trenches, used_buildings


def make_missing_connection_links(
    points: gpd.GeoDataFrame,
    regular_cables: gpd.GeoDataFrame,
    already_connected_lines: list[object],
    connection_tolerance_m: float = 0.02,
) -> gpd.GeoDataFrame:
    """Create counted cable links for every LS point lacking real line contact."""
    cable_parts = [
        part for geometry in regular_cables.geometry for part in line_parts(geometry)
    ]
    if not cable_parts:
        raise RuntimeError("Geen reguliere kabel beschikbaar voor LS-aansluitingen")
    cable_tree = STRtree(cable_parts)
    contact_lines = [*cable_parts]
    contact_lines.extend(
        geometry
        for geometry in already_connected_lines
        if geometry is not None and not geometry.is_empty
    )
    contact_tree = STRtree(contact_lines)
    records: list[dict] = []
    for point_index, point_row in points.iterrows():
        point = point_row.geometry
        nearest_contact = contact_lines[int(contact_tree.nearest(point))]
        if point.distance(nearest_contact) <= connection_tolerance_m + 1e-9:
            continue
        cable = cable_parts[int(cable_tree.nearest(point))]
        target = cable.interpolate(cable.project(point))
        connector = LineString([point, target])
        if connector.length <= 1e-7:
            continue
        records.append(
            {
                "Aansl_ID": str(point_row.get("ID", point_index)),
                "Multistory": str(point_row.get("Multistory", "")),
                "Koppeling": "Ontbrekende aansluiting naar dichtstbijzijnde kabel",
                "Lengte_m": float(connector.length),
                "Reken_m": float(connector.length),
                "geometry": connector,
            }
        )
    if not records:
        return gpd.GeoDataFrame(
            columns=[
                "Aansl_ID",
                "Multistory",
                "Koppeling",
                "Lengte_m",
                "Reken_m",
                "geometry",
            ],
            geometry="geometry",
            crs=CRS_RD,
        )
    links = gpd.GeoDataFrame(records, geometry="geometry", crs=CRS_RD)
    log(
        f"Ontbrekende aansluitkabels: {len(links)} LS-aansluiting(en) "
        "expliciet met de dichtstbijzijnde reguliere kabel verbonden. Deze "
        "lengte telt mee voor de maximale route."
    )
    return links


def node_cable_network(
    cables: gpd.GeoDataFrame,
    points: gpd.GeoDataFrame,
    stations: gpd.GeoDataFrame,
    tolerance_m: float,
    zero_cost_geometry=None,
) -> gpd.GeoDataFrame:
    """Node linework at crossings, near T-junctions and projected terminals."""
    if zero_cost_geometry is None:
        zero_geometries = []
        if "Rekenfactor" in cables.columns:
            zero_geometries.extend(
                cables.loc[
                    pd.to_numeric(cables["Rekenfactor"], errors="coerce").fillna(1.0)
                    <= 1e-9,
                    "geometry",
                ].tolist()
            )
        elif "Reken_m" in cables.columns and "Lengte_m" in cables.columns:
            zero_geometries.extend(
                cables.loc[
                    pd.to_numeric(cables["Reken_m"], errors="coerce").fillna(1.0)
                    <= 1e-9,
                    "geometry",
                ].tolist()
            )
        if zero_geometries:
            zero_cost_geometry = unary_union(zero_geometries)
    input_parts = [
        part for geometry in cables.geometry for part in line_parts(geometry)
    ]
    if not input_parts:
        raise RuntimeError("De sleuvenlaag bevat geen bruikbare lijngeometrie")

    # Unary union performs exact planar noding: crossings and exact T-junctions
    # become shared line endpoints, independent of feature boundaries.
    exact_parts = list(line_parts(unary_union(input_parts)))
    if not exact_parts:
        raise RuntimeError("Automatisch noden leverde geen bruikbaar kabelnet op")

    tolerance_m = max(0.0, float(tolerance_m))
    connectors: list[LineString] = []
    if tolerance_m > 0.0:
        # Only repair dangling endpoints. This avoids joining parallel cables
        # near ordinary vertices while still closing small T-junction gaps.
        endpoint_count: Counter[tuple[float, float]] = Counter()
        endpoint_records: list[tuple[int, Point, tuple[float, float]]] = []
        for line_index, line in enumerate(exact_parts):
            for coordinate in (line.coords[0], line.coords[-1]):
                key = tuple(np.round(np.asarray(coordinate, dtype=float), 6))
                endpoint_count[key] += 1
                endpoint_records.append((line_index, Point(coordinate), key))

        tree = STRtree(exact_parts)
        for own_index, endpoint, key in endpoint_records:
            if endpoint_count[key] != 1:
                continue
            candidate_indices = tree.query(endpoint.buffer(tolerance_m))
            best_distance = math.inf
            best_point = None
            for raw_index in candidate_indices:
                candidate_index = int(raw_index)
                if candidate_index == own_index:
                    continue
                candidate = exact_parts[candidate_index]
                distance = float(endpoint.distance(candidate))
                if distance <= 1e-7 or distance > tolerance_m + 1e-9:
                    continue
                if distance < best_distance:
                    best_distance = distance
                    best_point = candidate.interpolate(candidate.project(endpoint))
            if best_point is not None:
                connectors.append(LineString([endpoint, best_point]))

    if connectors:
        noded_parts = list(line_parts(unary_union([*exact_parts, *connectors])))
    else:
        noded_parts = exact_parts

    # Add a real graph vertex at the closest position on a cable for every LS
    # connection and existing station. No source geometry is changed and no
    # fictitious cable from the point to the line is created.
    tree = STRtree(noded_parts)
    split_measures: dict[int, set[float]] = defaultdict(set)
    for frame in (points, stations):
        for terminal in frame.geometry:
            if terminal is None or terminal.is_empty:
                continue
            line_index = int(tree.nearest(terminal))
            line = noded_parts[line_index]
            measure = float(line.project(terminal))
            if 1e-7 < measure < line.length - 1e-7:
                split_measures[line_index].add(round(measure, 6))

    terminal_count = sum(len(measures) for measures in split_measures.values())

    final_parts: list[LineString] = []
    for line_index, line in enumerate(noded_parts):
        measures = sorted(split_measures.get(line_index, ()))
        boundaries = [0.0, *measures, float(line.length)]
        for start, end in zip(boundaries[:-1], boundaries[1:]):
            if end - start <= 1e-7:
                continue
            piece = substring(line, start, end)
            final_parts.extend(line_parts(piece))

    log(
        "Sleuven automatisch genood: "
        f"{len(input_parts):,} invoerlijndelen, "
        f"{len(connectors):,} herstelde T-aansluitingen binnen "
        f"{tolerance_m:.2f} m, {terminal_count:,} extra aansluit-/stationsknopen, "
        f"{len(final_parts):,} netwerklijndelen."
    )
    if zero_cost_geometry is None or zero_cost_geometry.is_empty:
        factors = np.ones(len(final_parts), dtype=float)
    else:
        # Buffer the individual zero-cost conductors and use an STRtree. The
        # union of these buffers is mathematically identical to buffering the
        # unary union, but avoids thousands of expensive predicates against one
        # huge MultiPolygon (the former 30-40 second hotspot).
        zero_buffers = [
            line.buffer(0.02)
            for line in line_parts(zero_cost_geometry)
            if line is not None and not line.is_empty
        ]
        zero_buffer_tree = STRtree(zero_buffers)
        combined_zero_buffer_cache: dict[tuple[int, ...], object] = {}

        def is_zero_cost_part(part) -> bool:
            covering_indices = zero_buffer_tree.query(
                part, predicate="covered_by"
            )
            if len(covering_indices):
                return True
            candidate_indices = zero_buffer_tree.query(part)
            if not len(candidate_indices):
                return False
            if len(candidate_indices) == 1:
                return False
            # Rare boundary case: adjacent buffers can jointly cover a noded
            # segment although neither covers it alone. Cache equal candidate
            # sets, which occur repeatedly along the same apartment network.
            key = tuple(sorted(int(index) for index in candidate_indices))
            combined = combined_zero_buffer_cache.get(key)
            if combined is None:
                combined = unary_union([zero_buffers[index] for index in key])
                combined_zero_buffer_cache[key] = combined
            return bool(combined.covers(part))

        factors = np.asarray(
            [0.0 if is_zero_cost_part(part) else 1.0 for part in final_parts],
            dtype=float,
        )
    return gpd.GeoDataFrame(
        {"Rekenfactor": factors}, geometry=final_parts, crs=cables.crs
    )


def build_network(cables: gpd.GeoDataFrame) -> nx.Graph:
    log("Kabelnetwerk opbouwen (afronding 0,1 meter)...")
    graph = nx.Graph()

    for _row_index, row in cables.iterrows():
        geometry = row.geometry
        try:
            calculation_factor = float(row.get("Rekenfactor", 1.0))
        except (TypeError, ValueError):
            calculation_factor = 1.0
        calculation_factor = 0.0 if calculation_factor <= 1e-9 else 1.0
        for part in line_parts(geometry):
            coordinates = np.asarray(part.coords, dtype=float)
            for a, b in zip(coordinates[:-1], coordinates[1:]):
                u = tuple(np.round(a, 1))
                v = tuple(np.round(b, 1))
                if u == v:
                    continue
                physical_length = float(np.linalg.norm(np.asarray(v) - np.asarray(u)))
                # SciPy sparse graphs use numeric zero as 'no edge'. A one
                # micrometre epsilon keeps indoor trenches connected while
                # making their contribution round to exactly 0.0 m in outputs.
                weight = max(1e-6, physical_length * calculation_factor)
                if not graph.has_edge(u, v) or weight < graph[u][v]["weight"]:
                    graph.add_edge(
                        u,
                        v,
                        weight=weight,
                        physical_length=physical_length,
                        calculation_factor=calculation_factor,
                    )

    if graph.number_of_nodes() == 0 or graph.number_of_edges() == 0:
        raise RuntimeError("Het kabelnet bevat geen bruikbare verbindingen")
    component_count = nx.number_connected_components(graph)
    log(
        f"Kabelnet: {graph.number_of_nodes():,} knopen, "
        f"{graph.number_of_edges():,} verbindingen, "
        f"{component_count:,} los(se) component(en)."
    )
    return graph


def snap_xy(
    xy: np.ndarray, node_list: list[tuple[float, float]], tree: cKDTree
) -> tuple[list[tuple[float, float]], np.ndarray, np.ndarray]:
    distance, indices = tree.query(xy)
    nodes = [node_list[int(i)] for i in indices]
    return nodes, np.asarray(distance, dtype=float), np.asarray(indices, dtype=int)


def linework_distances(xy: np.ndarray, parts: list, boundary_m=None) -> np.ndarray:
    """Exact distance to the union, querying only nearby indexed line parts."""
    distances = np.full(len(xy), np.inf, dtype=float)
    if parts and len(xy):
        pairs, values = STRtree(parts).query_nearest(
            shapely_points(xy), all_matches=False, return_distance=True
        )
        distances[pairs[0]] = values
        if boundary_m is not None:
            # GEOS union noding can introduce a tiny coordinate roundoff.
            # Preserve the old strict decision for points on the boundary.
            near_boundary = np.flatnonzero(np.abs(distances - boundary_m) <= 1e-8)
            if len(near_boundary):
                reference = unary_union(parts)
                for index in near_boundary:
                    distances[index] = Point(xy[index]).distance(reference)
    return distances


def network_distance_matrix(
    adjacency: csr_matrix, source_indices: np.ndarray, target_indices: np.ndarray
) -> np.ndarray:
    result = dijkstra(
        adjacency,
        directed=False,
        indices=np.asarray(source_indices, dtype=int),
        return_predecessors=False,
    )
    distances = np.asarray(result[:, target_indices].T, dtype=float)
    return distances


def station_load_matrix(loads: np.ndarray, station_count: int) -> csr_matrix:
    unit_count = len(loads)
    rows = np.tile(np.arange(station_count), unit_count)
    cols = np.arange(unit_count * station_count)
    data = np.repeat(loads, station_count)
    return coo_matrix(
        (data, (rows, cols)), shape=(station_count, unit_count * station_count)
    ).tocsr()


def assignment_matrix(unit_count: int, station_count: int) -> csr_matrix:
    return kron(
        identity(unit_count, format="csr"),
        np.ones((1, station_count), dtype=float),
        format="csr",
    )


def assignment_cost(
    distances: np.ndarray,
    loads: np.ndarray,
    legacy_labels: np.ndarray,
    station_legacy_labels: list[str],
) -> np.ndarray:
    mismatch = legacy_labels[:, None] != np.asarray(station_legacy_labels)[None, :]
    finite_distances = np.where(
        np.isfinite(distances),
        distances,
        max(1_000_000.0, MAX_ROUTE_M * 1000.0),
    )
    effective_distance = finite_distances + mismatch * LEGACY_CHANGE_PENALTY_M
    # A small base weight keeps zero-amp records spatially logical too.
    return ((loads + 0.5)[:, None] * effective_distance / 1000.0).ravel()


def fixed_utilization_target_constraints(
    a_load: csr_matrix,
    capacities: np.ndarray,
) -> tuple[csr_matrix, np.ndarray, np.ndarray]:
    """Linear absolute deviation from the preferred station utilization."""
    station_count, x_count = a_load.shape
    normalized_load = diags(1.0 / capacities) @ a_load
    deviations = identity(station_count, format="csr")
    matrix = vstack(
        [
            hstack([normalized_load, -deviations], format="csr"),
            hstack([normalized_load, deviations], format="csr"),
        ],
        format="csr",
    )
    lower = np.concatenate(
        [
            np.full(station_count, -np.inf),
            np.full(station_count, TARGET_UTILIZATION),
        ]
    )
    upper = np.concatenate(
        [
            np.full(station_count, TARGET_UTILIZATION),
            np.full(station_count, np.inf),
        ]
    )
    return matrix, lower, upper


def assignment_upper_bounds(distances: np.ndarray) -> np.ndarray:
    """Disallow every station assignment whose cable distance exceeds the limit."""
    allowed = np.isfinite(distances) & (distances <= MAX_ROUTE_M + 1e-7)
    unreachable = np.flatnonzero(~allowed.any(axis=1))
    if len(unreachable):
        raise RuntimeError(
            f"{len(unreachable)} aansluitingseenheden liggen via de kabel verder "
            f"dan {MAX_ROUTE_M:.0f} m van ieder beschikbaar station"
        )
    return allowed.astype(float).ravel()


def choose_automatic_new_station_count(
    total_load: float,
    existing_capacity: float,
    new_station_capacity: float,
) -> int:
    """Choose the feasible integer count closest to the utilization target."""
    return automatic_new_station_count_options(
        total_load, existing_capacity, new_station_capacity
    )[0]


def automatic_new_station_count_options(
    total_load: float,
    existing_capacity: float,
    new_station_capacity: float,
) -> list[int]:
    """Return capacity-valid counts ordered by closeness to the target."""
    if not 0.0 < TARGET_UTILIZATION <= 1.0:
        raise RuntimeError("Voorkeursbenutting moet groter dan 0 en maximaal 100% zijn")
    minimum_count = max(
        int(_AUTO_TOPOLOGY_MINIMUM_NEW),
        int(
            math.ceil(
                max(0.0, total_load - existing_capacity)
                / new_station_capacity
                - 1e-12
            )
        ),
    )
    def score(count: int) -> tuple[float, int]:
        capacity = existing_capacity + count * new_station_capacity
        utilization = total_load / capacity if capacity > 0 else np.inf
        return abs(utilization - TARGET_UTILIZATION), count

    # Een kabelnet met veel losse componenten kan topologisch veel meer
    # stations vereisen dan de zuivere capaciteitsberekening. Laat na zo'n
    # verhoging ook aantallen boven die topologische ondergrens proberen.
    # Voorheen eindigde de lijst bijvoorbeeld precies bij 16, zodat een
    # mislukte selectie van 16 niet automatisch met 17 verder kon.
    maximum_count = max(
        minimum_count + MAX_AUTOMATIC_TOPOLOGY_RETRIES,
        int(_AUTO_TOPOLOGY_MINIMUM_NEW) + MAX_AUTOMATIC_TOPOLOGY_RETRIES,
    )
    candidates = range(minimum_count, maximum_count + 1)
    return sorted(candidates, key=score)


def indivisible_capacity_issues(unit_load, unit_node_indices, unit_components,
                               station_nodes, station_components, capacities, new_capacity):
    """Necessary capacity bounds, before any expensive spatial solver."""
    issues = []
    root_capacity = {int(node): float(capacity) for node, capacity in zip(station_nodes, capacities)}
    for index, load in enumerate(unit_load):
        component = int(unit_components[index])
        component_capacities = np.asarray(capacities)[np.asarray(station_components) == component]
        available = max(float(new_capacity), float(component_capacities.max()) if len(component_capacities) else 0.)
        node = int(unit_node_indices[index])
        at_root = node in root_capacity
        maximum = root_capacity[node] if at_root else available
        if float(load) > maximum + 1e-6:
            issues.append({"unit": index, "load_a": float(load), "maximum_a": maximum,
                           "component": component + 1, "station_root": at_root})
    return issues


def solve_facility_selection(
    distances: np.ndarray,
    loads: np.ndarray,
    capacities_existing: np.ndarray,
    legacy_labels: np.ndarray,
    station_legacy_labels: list[str],
    candidate_count: int,
) -> tuple[np.ndarray, np.ndarray, float]:
    """Select exactly N_NEW candidate stations and assign every unit to an open site."""
    unit_count, station_count = distances.shape
    existing_count = len(capacities_existing)
    x_count = unit_count * station_count
    deviation_count = station_count
    variable_count = x_count + candidate_count + deviation_count
    a_assign = assignment_matrix(unit_count, station_count)
    a_load = station_load_matrix(loads, station_count)
    zero_y_assign = csr_matrix((unit_count, candidate_count))
    zero_d_assign = csr_matrix((unit_count, deviation_count))
    candidate_capacity = NEW_KVA / 0.23 / 3.0
    capacities_all = np.concatenate(
        [capacities_existing, np.full(candidate_count, candidate_capacity)]
    )

    normalized_load = diags(1.0 / capacities_all) @ a_load
    selection_effect = coo_matrix(
        (
            np.full(candidate_count, -TARGET_UTILIZATION),
            (
                existing_count + np.arange(candidate_count),
                np.arange(candidate_count),
            ),
        ),
        shape=(station_count, candidate_count),
    ).tocsr()
    deviations = identity(deviation_count, format="csr")
    target_reference = np.concatenate(
        [
            np.full(existing_count, TARGET_UTILIZATION),
            np.zeros(candidate_count),
        ]
    )
    total_load = float(np.sum(loads))
    maximum_selected_capacity = float(
        np.sum(capacities_existing) + N_NEW * candidate_capacity
    )
    reachable = np.isfinite(distances) & (distances <= MAX_ROUTE_M + 1e-7)
    reachable_load = np.sum(reachable * loads[:, None], axis=0)

    for min_utilization in MIN_UTILIZATION:
        # These are mathematical necessary conditions, not heuristics. Skipping
        # an impossible lower-bound model therefore changes neither the chosen
        # stations nor the solution quality, while avoiding needless MILP runs.
        required_total = min_utilization * maximum_selected_capacity
        existing_reachable = reachable_load[:existing_count]
        candidate_reachable = reachable_load[existing_count:]
        enough_candidate_sites = int(
            np.count_nonzero(
                candidate_reachable
                >= candidate_capacity * min_utilization - 1e-7
            )
        )
        if (
            total_load + 1e-7 < required_total
            or np.any(
                existing_reachable
                < capacities_existing * min_utilization - 1e-7
            )
            or enough_candidate_sites < N_NEW
        ):
            log(
                f"Minimale benutting {min_utilization * 100:.0f}% is "
                "rekenkundig onhaalbaar; MILP veilig overgeslagen."
            )
            continue
        blocks: list[csr_matrix] = []
        lower: list[np.ndarray] = []
        upper: list[np.ndarray] = []

        blocks.append(
            hstack([a_assign, zero_y_assign, zero_d_assign], format="csr")
        )
        lower.append(np.ones(unit_count))
        upper.append(np.ones(unit_count))

        existing_rows = a_load[:existing_count]
        blocks.append(
            hstack(
                [existing_rows, csr_matrix((existing_count, candidate_count))],
                format="csr",
            )
        )
        blocks[-1] = hstack(
            [blocks[-1], csr_matrix((existing_count, deviation_count))],
            format="csr",
        )
        lower.append(capacities_existing * min_utilization)
        upper.append(capacities_existing)

        for candidate_index in range(candidate_count):
            station_index = existing_count + candidate_index
            load_row = a_load.getrow(station_index)

            y_upper = coo_matrix(
                ([-candidate_capacity], ([0], [candidate_index])),
                shape=(1, candidate_count),
            ).tocsr()
            blocks.append(
                hstack(
                    [load_row, y_upper, csr_matrix((1, deviation_count))],
                    format="csr",
                )
            )
            lower.append(np.asarray([-np.inf]))
            upper.append(np.asarray([0.0]))

            y_lower = coo_matrix(
                ([-candidate_capacity * min_utilization], ([0], [candidate_index])),
                shape=(1, candidate_count),
            ).tocsr()
            blocks.append(
                hstack(
                    [load_row, y_lower, csr_matrix((1, deviation_count))],
                    format="csr",
                )
            )
            lower.append(np.asarray([0.0]))
            upper.append(np.asarray([np.inf]))

            # Capacity linking alone does not bind zero-amp units: they could
            # otherwise be assigned to a candidate with y=0. Explicitly impose
            # x[unit, candidate] <= y[candidate] for every unit, including
            # records whose design current is exactly zero.
            x_selector = coo_matrix(
                (
                    np.ones(unit_count),
                    (
                        np.arange(unit_count),
                        np.arange(unit_count) * station_count + station_index,
                    ),
                ),
                shape=(unit_count, x_count),
            ).tocsr()
            y_selector = coo_matrix(
                (
                    -np.ones(unit_count),
                    (
                        np.arange(unit_count),
                        np.full(unit_count, candidate_index),
                    ),
                ),
                shape=(unit_count, candidate_count),
            ).tocsr()
            blocks.append(
                hstack(
                    [
                        x_selector,
                        y_selector,
                        csr_matrix((unit_count, deviation_count)),
                    ],
                    format="csr",
                )
            )
            lower.append(np.full(unit_count, -np.inf))
            upper.append(np.zeros(unit_count))

        select_y = hstack(
            [
                csr_matrix((1, x_count)),
                np.ones((1, candidate_count)),
                csr_matrix((1, deviation_count)),
            ],
            format="csr",
        )
        blocks.append(select_y)
        lower.append(np.asarray([float(N_NEW)]))
        upper.append(np.asarray([float(N_NEW)]))

        blocks.extend(
            [
                hstack(
                    [normalized_load, selection_effect, -deviations],
                    format="csr",
                ),
                hstack(
                    [normalized_load, selection_effect, deviations],
                    format="csr",
                ),
            ]
        )
        lower.extend(
            [
                np.full(station_count, -np.inf),
                target_reference,
            ]
        )
        upper.extend(
            [
                target_reference,
                np.full(station_count, np.inf),
            ]
        )

        constraints = LinearConstraint(
            vstack(blocks, format="csr"), np.concatenate(lower), np.concatenate(upper)
        )
        objective = np.concatenate(
            [
                assignment_cost(
                    distances, loads, legacy_labels, station_legacy_labels
                ),
                np.zeros(candidate_count),
                np.full(deviation_count, TARGET_UTILIZATION_PENALTY),
            ]
        )
        log(
            f"Optimalisatie stationskeuze: minimale benutting "
            f"{min_utilization * 100:.0f}%..."
        )
        result = milp(
            c=objective,
            integrality=np.concatenate(
                [
                    np.ones(x_count + candidate_count, dtype=np.uint8),
                    np.zeros(deviation_count, dtype=np.uint8),
                ]
            ),
            bounds=Bounds(
                np.zeros(variable_count),
                np.concatenate(
                    [
                        assignment_upper_bounds(distances),
                        np.ones(candidate_count + deviation_count),
                    ]
                ),
            ),
            constraints=constraints,
            options=milp_options(120, 0.01),
        )
        if result.x is not None:
            x = result.x[:x_count].reshape(unit_count, station_count)
            selected = result.x[x_count : x_count + candidate_count] > 0.5
            assignment = np.argmax(x, axis=1)
            assigned_candidates = assignment >= existing_count
            assigned_to_closed = np.zeros(unit_count, dtype=bool)
            candidate_units = np.flatnonzero(assigned_candidates)
            if len(candidate_units):
                assigned_to_closed[candidate_units] = ~selected[
                    assignment[candidate_units] - existing_count
                ]
            if int(selected.sum()) != N_NEW or np.any(assigned_to_closed):
                log(
                    "MILP-incumbent is niet integer-consistent met de geopende "
                    "stations; deze oplossing wordt verworpen."
                )
                continue
            log(
                f"Stationskeuze opgelost (status {result.status}, "
                f"benutting >= {min_utilization * 100:.0f}%)."
            )
            return assignment, selected, min_utilization
        log(f"Geen oplossing bij {min_utilization * 100:.0f}%; grens versoepelen.")
    raise RuntimeError(
        f"Geen geldige selectie van {N_NEW} nieuwe stations gevonden"
    )


def solve_fixed_assignment(
    distances: np.ndarray,
    loads: np.ndarray,
    capacities: np.ndarray,
    legacy_labels: np.ndarray,
    station_legacy_labels: list[str],
) -> tuple[np.ndarray, float]:
    unit_count, station_count = distances.shape
    x_count = unit_count * station_count
    deviation_count = station_count
    variable_count = x_count + deviation_count
    a_assign = assignment_matrix(unit_count, station_count)
    a_load = station_load_matrix(loads, station_count)
    zero_assign_deviation = csr_matrix((unit_count, deviation_count))
    zero_load_deviation = csr_matrix((station_count, deviation_count))
    target_matrix, target_lower, target_upper = fixed_utilization_target_constraints(
        a_load, capacities
    )
    matrix = vstack(
        [
            hstack([a_assign, zero_assign_deviation], format="csr"),
            hstack([a_load, zero_load_deviation], format="csr"),
            target_matrix,
        ],
        format="csr",
    )
    objective = np.concatenate(
        [
            assignment_cost(
                distances, loads, legacy_labels, station_legacy_labels
            ),
            np.full(deviation_count, TARGET_UTILIZATION_PENALTY),
        ]
    )

    for min_utilization in MIN_UTILIZATION:
        lower = np.concatenate(
            [
                np.ones(unit_count),
                capacities * min_utilization,
                target_lower,
            ]
        )
        upper = np.concatenate(
            [np.ones(unit_count), capacities, target_upper]
        )
        log(
            f"Definitieve toedeling: minimale benutting "
            f"{min_utilization * 100:.0f}%..."
        )
        result = milp(
            c=objective,
            integrality=np.concatenate(
                [
                    np.ones(x_count, dtype=np.uint8),
                    np.zeros(deviation_count, dtype=np.uint8),
                ]
            ),
            bounds=Bounds(
                np.zeros(variable_count),
                np.concatenate(
                    [assignment_upper_bounds(distances), np.ones(deviation_count)]
                ),
            ),
            constraints=LinearConstraint(matrix, lower, upper),
            options=milp_options(240, 0.005),
        )
        if result.x is not None:
            assignment = np.argmax(
                result.x[:x_count].reshape(unit_count, station_count), axis=1
            )
            log(
                f"Toedeling opgelost (status {result.status}, "
                f"benutting >= {min_utilization * 100:.0f}%)."
            )
            return assignment, min_utilization
        log(f"Geen oplossing bij {min_utilization * 100:.0f}%; grens versoepelen.")
    raise RuntimeError("Geen capaciteitsgeldige definitieve toedeling gevonden")


def solve_cable_connected_assignment(
    graph: nx.Graph,
    node_list: list[tuple[float, float]],
    adjacency: csr_matrix,
    distances: np.ndarray,
    loads: np.ndarray,
    capacities: np.ndarray,
    unit_nodes: list[tuple[float, float]],
    unit_node_indices: np.ndarray,
    station_nodes: list[tuple[float, float]],
    previous_assignment: np.ndarray,
) -> tuple[np.ndarray, float, np.ndarray]:
    """Partition demand and cable graph into exclusive station-rooted subnetworks."""
    unit_count, station_count = distances.shape
    x_count = unit_count * station_count
    deviation_count = station_count
    variable_count = x_count + deviation_count
    node_index = {node: i for i, node in enumerate(node_list)}

    terminal_nodes = list(unit_nodes)
    terminal_by_node = {node: i for i, node in enumerate(terminal_nodes)}
    station_terminal_ids: list[int] = []
    for station_node in station_nodes:
        terminal_id = terminal_by_node.get(station_node)
        if terminal_id is None:
            terminal_id = len(terminal_nodes)
            terminal_nodes.append(station_node)
            terminal_by_node[station_node] = terminal_id
        station_terminal_ids.append(terminal_id)
    if len(set(station_terminal_ids)) != station_count:
        raise RuntimeError("Twee stations zijn op dezelfde kabelknoop gesnapt")

    terminal_graph_indices = np.asarray(
        [node_index[node] for node in terminal_nodes], dtype=int
    )
    log("Netwerk-Voronoi en kabelbuurschap berekenen...")
    voronoi_distance, _, nearest_source = dijkstra(
        adjacency,
        directed=False,
        indices=terminal_graph_indices,
        min_only=True,
        return_predecessors=True,
    )
    source_to_terminal = {
        int(graph_index): terminal_id
        for terminal_id, graph_index in enumerate(terminal_graph_indices)
    }
    terminal_owner = np.asarray(
        [source_to_terminal.get(int(source), -1) for source in nearest_source],
        dtype=int,
    )

    terminal_graph = nx.Graph()
    terminal_graph.add_nodes_from(range(len(terminal_nodes)))
    for u, v, data in graph.edges(data=True):
        ui = node_index[u]
        vi = node_index[v]
        owner_u = int(terminal_owner[ui])
        owner_v = int(terminal_owner[vi])
        if owner_u < 0 or owner_v < 0:
            continue
        if owner_u == owner_v:
            continue
        terminal_distance = float(
            voronoi_distance[ui] + data["weight"] + voronoi_distance[vi]
        )
        if (
            not terminal_graph.has_edge(owner_u, owner_v)
            or terminal_distance < terminal_graph[owner_u][owner_v]["weight"]
        ):
            terminal_graph.add_edge(owner_u, owner_v, weight=terminal_distance)
    terminal_component_count = nx.number_connected_components(terminal_graph)
    if terminal_component_count > 1:
        log(
            f"Kabelbuurschap bestaat uit {terminal_component_count} losse "
            "componenten; toedelingen tussen componenten worden verboden."
        )

    a_assign = assignment_matrix(unit_count, station_count)
    a_load = station_load_matrix(loads, station_count)
    row_indices: list[int] = []
    col_indices: list[int] = []
    coefficients: list[float] = []
    connectivity_upper: list[float] = []
    connectivity_row = 0
    root_unit_by_station: dict[int, int] = {}

    for station_index, root_terminal in enumerate(station_terminal_ids):
        radial = nx.single_source_dijkstra_path_length(
            terminal_graph, root_terminal, weight="weight"
        )
        if root_terminal < unit_count:
            root_unit_by_station[station_index] = root_terminal
        for unit_index in range(unit_count):
            if unit_index not in radial:
                # Exact network-distance bounds already force this
                # cross-component assignment variable to zero.
                continue
            if unit_index == root_terminal:
                continue
            row_indices.append(connectivity_row)
            col_indices.append(unit_index * station_count + station_index)
            coefficients.append(1.0)
            root_is_predecessor = False
            for neighbor in terminal_graph.neighbors(unit_index):
                if neighbor not in radial or radial[neighbor] >= radial[unit_index] - 1e-7:
                    continue
                if neighbor < unit_count:
                    row_indices.append(connectivity_row)
                    col_indices.append(neighbor * station_count + station_index)
                    coefficients.append(-1.0)
                elif neighbor == root_terminal:
                    root_is_predecessor = True
            connectivity_upper.append(1.0 if root_is_predecessor else 0.0)
            connectivity_row += 1

    a_connectivity = coo_matrix(
        (coefficients, (row_indices, col_indices)),
        shape=(connectivity_row, x_count),
    ).tocsr()
    target_matrix, target_lower, target_upper = fixed_utilization_target_constraints(
        a_load, capacities
    )
    matrix = vstack(
        [
            hstack(
                [a_assign, csr_matrix((unit_count, deviation_count))],
                format="csr",
            ),
            hstack(
                [a_load, csr_matrix((station_count, deviation_count))],
                format="csr",
            ),
            hstack(
                [a_connectivity, csr_matrix((connectivity_row, deviation_count))],
                format="csr",
            ),
            target_matrix,
        ],
        format="csr",
    )
    lower_bounds = np.zeros(variable_count)
    # The contracted terminal graph is used only for contiguity. Its edge
    # weights can overestimate the real cable distance, so the hard route limit
    # is applied to the exact source-to-unit network distances here and checked
    # again on the final exclusive routes below.
    upper_bounds = np.concatenate(
        [assignment_upper_bounds(distances), np.ones(deviation_count)]
    )
    for station_index, root_unit in root_unit_by_station.items():
        variable_index = root_unit * station_count + station_index
        lower_bounds[variable_index] = 1.0
        upper_bounds[variable_index] = 1.0

    mismatch = np.arange(station_count)[None, :] != previous_assignment[:, None]
    finite_distances = np.where(
        np.isfinite(distances),
        distances,
        max(1_000_000.0, MAX_ROUTE_M * 1000.0),
    )
    objective = np.concatenate(
        [
            (
                (loads + 0.5)[:, None]
                * (finite_distances + mismatch * CONTIGUITY_CHANGE_PENALTY_M)
                / 1000.0
            ).ravel(),
            np.full(deviation_count, TARGET_UTILIZATION_PENALTY),
        ]
    )

    for min_utilization in (0.75, 0.65, 0.0):
        lower = np.concatenate(
            [
                np.ones(unit_count),
                capacities * min_utilization,
                np.full(connectivity_row, -np.inf),
                target_lower,
            ]
        )
        upper = np.concatenate(
            [
                np.ones(unit_count),
                capacities,
                np.asarray(connectivity_upper, dtype=float),
                target_upper,
            ]
        )
        log(
            f"Kabelverbonden optimalisatie: minimale benutting "
            f"{min_utilization * 100:.0f}%..."
        )
        result = milp(
            c=objective,
            integrality=np.concatenate(
                [
                    np.ones(x_count, dtype=np.uint8),
                    np.zeros(deviation_count, dtype=np.uint8),
                ]
            ),
            bounds=Bounds(lower_bounds, upper_bounds),
            constraints=LinearConstraint(matrix, lower, upper),
            options=milp_options(30, 0.01),
        )
        if result.x is None:
            log(f"Geen kabelverbonden oplossing bij {min_utilization * 100:.0f}%.")
            continue
        assignment = np.argmax(
            result.x[:x_count].reshape(unit_count, station_count), axis=1
        )
        terminal_cluster = np.full(len(terminal_nodes), -1, dtype=int)
        terminal_cluster[:unit_count] = assignment
        for station_index, terminal_id in enumerate(station_terminal_ids):
            if terminal_id < unit_count:
                if assignment[terminal_id] != station_index:
                    raise RuntimeError("Stationswortel is verkeerd toegewezen")
            else:
                terminal_cluster[terminal_id] = station_index
        if np.any(terminal_cluster < 0):
            raise RuntimeError("Niet alle kabelterritoria hebben een cluster")
        node_cluster = np.full(len(node_list), -1, dtype=int)
        owned_node_mask = terminal_owner >= 0
        node_cluster[owned_node_mask] = terminal_cluster[
            terminal_owner[owned_node_mask]
        ]
        for station_index, source in enumerate(station_nodes):
            if node_cluster[node_index[source]] != station_index:
                raise RuntimeError("Station ligt niet in het eigen kabelterritorium")
            for unit_index in np.flatnonzero(assignment == station_index):
                if node_cluster[unit_node_indices[unit_index]] != station_index:
                    raise RuntimeError("Aansluiting ligt niet in eigen kabelterritorium")
        log(
            f"Kabelverbonden toedeling opgelost (status {result.status}, "
            f"benutting >= {min_utilization * 100:.0f}%)."
        )
        return assignment, min_utilization, node_cluster
    log(
        "Kortste-pad-connectiviteit is te streng; algemene "
        "netwerk-flow-connectiviteit proberen..."
    )
    return solve_general_connected_terminal_assignment(
        terminal_graph,
        terminal_owner,
        terminal_nodes,
        station_terminal_ids,
        node_index,
        station_nodes,
        unit_node_indices,
        distances,
        loads,
        capacities,
        previous_assignment,
    )


def solve_general_connected_terminal_assignment(
    terminal_graph: nx.Graph,
    terminal_owner: np.ndarray,
    terminal_nodes: list[tuple[float, float]],
    station_terminal_ids: list[int],
    node_index: dict[tuple[float, float], int],
    station_nodes: list[tuple[float, float]],
    unit_node_indices: np.ndarray,
    distances: np.ndarray,
    loads: np.ndarray,
    capacities: np.ndarray,
    previous_assignment: np.ndarray,
) -> tuple[np.ndarray, float, np.ndarray]:
    """General connected partition using one commodity flow per station."""
    unit_count, station_count = distances.shape
    x_count = unit_count * station_count
    deviation_count = station_count
    deviation_offset = x_count
    flow_offset = x_count + deviation_count

    directed_edges: list[tuple[int, int]] = []
    directed_weights: list[float] = []
    for first, second, data in terminal_graph.edges(data=True):
        weight = float(data["weight"])
        directed_edges.extend([(int(first), int(second)), (int(second), int(first))])
        directed_weights.extend([weight, weight])
    flow_count = len(directed_edges) * station_count
    variable_count = flow_offset + flow_count

    def flow_variable(edge_index: int, station_index: int) -> int:
        return flow_offset + edge_index * station_count + station_index

    a_assign = assignment_matrix(unit_count, station_count)
    a_load = station_load_matrix(loads, station_count)
    target_matrix, target_lower, target_upper = fixed_utilization_target_constraints(
        a_load, capacities
    )

    conservation_rows = station_count * (unit_count + 1)
    conservation_r: list[int] = []
    conservation_c: list[int] = []
    conservation_v: list[float] = []
    flow_upper = np.zeros(flow_count, dtype=float)
    link_r: list[int] = []
    link_c: list[int] = []
    link_v: list[float] = []
    link_row = 0
    max_flow = float(unit_count)

    for station_index, root_terminal in enumerate(station_terminal_ids):
        base_row = station_index * (unit_count + 1)
        root_row = base_row + unit_count
        root_unit = root_terminal if root_terminal < unit_count else None

        for unit_index in range(unit_count):
            if unit_index == root_unit:
                continue
            x_index = unit_index * station_count + station_index
            conservation_r.extend([base_row + unit_index, root_row])
            conservation_c.extend([x_index, x_index])
            conservation_v.extend([-1.0, -1.0])

        for edge_index, (first, second) in enumerate(directed_edges):
            flow_local_index = edge_index * station_count + station_index
            flow_index = flow_variable(edge_index, station_index)
            first_allowed = first < unit_count or first == root_terminal
            second_allowed = second < unit_count or second == root_terminal
            if not (first_allowed and second_allowed):
                continue
            flow_upper[flow_local_index] = max_flow

            if first == root_terminal:
                conservation_r.append(root_row)
                conservation_c.append(flow_index)
                conservation_v.append(1.0)
            elif first < unit_count:
                conservation_r.append(base_row + first)
                conservation_c.append(flow_index)
                conservation_v.append(-1.0)

            if second == root_terminal:
                conservation_r.append(root_row)
                conservation_c.append(flow_index)
                conservation_v.append(-1.0)
            elif second < unit_count:
                conservation_r.append(base_row + second)
                conservation_c.append(flow_index)
                conservation_v.append(1.0)

            if second < unit_count and second != root_unit:
                x_index = second * station_count + station_index
                link_r.extend([link_row, link_row])
                link_c.extend([flow_index, x_index])
                link_v.extend([1.0, -max_flow])
                link_row += 1

    a_conservation = coo_matrix(
        (conservation_v, (conservation_r, conservation_c)),
        shape=(conservation_rows, variable_count),
    ).tocsr()
    a_links = coo_matrix(
        (link_v, (link_r, link_c)),
        shape=(link_row, variable_count),
    ).tocsr()
    zero_assign_d = csr_matrix((unit_count, deviation_count))
    zero_assign_f = csr_matrix((unit_count, flow_count))
    zero_load_d = csr_matrix((station_count, deviation_count))
    zero_load_f = csr_matrix((station_count, flow_count))
    target_with_flow = hstack(
        [target_matrix, csr_matrix((target_matrix.shape[0], flow_count))],
        format="csr",
    )
    matrix = vstack(
        [
            hstack([a_assign, zero_assign_d, zero_assign_f], format="csr"),
            hstack([a_load, zero_load_d, zero_load_f], format="csr"),
            a_conservation,
            a_links,
            target_with_flow,
        ],
        format="csr",
    )

    lower_bounds = np.zeros(variable_count)
    upper_bounds = np.concatenate(
        [
            assignment_upper_bounds(distances),
            np.ones(deviation_count),
            flow_upper,
        ]
    )
    for station_index, root_terminal in enumerate(station_terminal_ids):
        if root_terminal < unit_count:
            variable_index = root_terminal * station_count + station_index
            lower_bounds[variable_index] = 1.0
            upper_bounds[variable_index] = 1.0

    mismatch = np.arange(station_count)[None, :] != previous_assignment[:, None]
    finite_distances = np.where(
        np.isfinite(distances),
        distances,
        max(1_000_000.0, MAX_ROUTE_M * 1000.0),
    )
    assignment_objective = (
        (loads + 0.5)[:, None]
        * (finite_distances + mismatch * CONTIGUITY_CHANGE_PENALTY_M)
        / 1000.0
    ).ravel()
    flow_objective = (
        np.repeat(np.asarray(directed_weights, dtype=float), station_count) * 1e-6
    )
    objective = np.concatenate(
        [
            assignment_objective,
            np.full(deviation_count, TARGET_UTILIZATION_PENALTY),
            flow_objective,
        ]
    )
    integrality = np.concatenate(
        [
            np.ones(x_count, dtype=np.uint8),
            np.zeros(deviation_count + flow_count, dtype=np.uint8),
        ]
    )

    for min_utilization in (0.75, 0.65, 0.50, 0.0):
        lower = np.concatenate(
            [
                np.ones(unit_count),
                capacities * min_utilization,
                np.zeros(conservation_rows),
                np.full(link_row, -np.inf),
                target_lower,
            ]
        )
        upper = np.concatenate(
            [
                np.ones(unit_count),
                capacities,
                np.zeros(conservation_rows),
                np.zeros(link_row),
                target_upper,
            ]
        )
        log(
            f"Algemene kabel-flow-optimalisatie: minimale benutting "
            f"{min_utilization * 100:.0f}%..."
        )
        result = milp(
            c=objective,
            integrality=integrality,
            bounds=Bounds(lower_bounds, upper_bounds),
            constraints=LinearConstraint(matrix, lower, upper),
            options=milp_options(45, 0.015),
        )
        if result.x is None:
            log(f"Geen algemene flow-oplossing bij {min_utilization * 100:.0f}%.")
            continue

        assignment = np.argmax(
            result.x[:x_count].reshape(unit_count, station_count), axis=1
        )
        terminal_cluster = np.full(len(terminal_nodes), -1, dtype=int)
        terminal_cluster[:unit_count] = assignment
        for station_index, terminal_id in enumerate(station_terminal_ids):
            if terminal_id < unit_count:
                if assignment[terminal_id] != station_index:
                    raise RuntimeError("Stationswortel is verkeerd toegewezen")
            else:
                terminal_cluster[terminal_id] = station_index
        if np.any(terminal_cluster < 0):
            raise RuntimeError("Niet alle kabelterritoria hebben een cluster")
        node_cluster = np.full(len(terminal_owner), -1, dtype=int)
        owned_node_mask = terminal_owner >= 0
        node_cluster[owned_node_mask] = terminal_cluster[
            terminal_owner[owned_node_mask]
        ]
        for station_index, source in enumerate(station_nodes):
            if node_cluster[node_index[source]] != station_index:
                raise RuntimeError("Station ligt niet in het eigen kabelterritorium")
            for unit_index in np.flatnonzero(assignment == station_index):
                if node_cluster[unit_node_indices[unit_index]] != station_index:
                    raise RuntimeError("Aansluiting ligt niet in eigen kabelterritorium")
        log(
            f"Algemene kabel-flow-toedeling opgelost (status {result.status}, "
            f"benutting >= {min_utilization * 100:.0f}%)."
        )
        return assignment, min_utilization, node_cluster

    raise RuntimeError("Geen capaciteitsgeldige kabelverbonden toedeling gevonden")


def solve_greedy_voronoi_connected_assignment(
    adjacency: csr_matrix,
    node_list: list[tuple[float, float]],
    unit_node_indices: np.ndarray,
    loads: np.ndarray,
    existing_source_indices: np.ndarray,
    candidate_source_indices: list[int],
    existing_capacities: np.ndarray,
    new_capacity: float,
    regular_node_indices: np.ndarray,
    graph_component_by_node_index: np.ndarray,
    preferred_candidate_indices: list[int] | None = None,
) -> tuple[np.ndarray, float, np.ndarray, list[int], np.ndarray]:
    """Build exclusive shortest-path territories and prune redundant candidates.

    Multi-source Dijkstra creates one connected cable territory per source.  A
    candidate may only be removed when every demand node remains reachable,
    within the hard route limit, and below its station capacity.
    """

    node_xy = np.asarray(node_list, dtype=float)
    regular_by_component: dict[int, np.ndarray] = {}
    regular_tree_by_component: dict[int, cKDTree] = {}
    for component_index in np.unique(graph_component_by_node_index):
        indices = regular_node_indices[
            graph_component_by_node_index[regular_node_indices] == component_index
        ]
        if len(indices):
            regular_by_component[int(component_index)] = indices
            regular_tree_by_component[int(component_index)] = cKDTree(node_xy[indices])

    last_overloaded: np.ndarray | None = None
    last_assignment: np.ndarray | None = None
    last_unit_distances: np.ndarray | None = None
    source_distance_cache: dict[int, np.ndarray] = {}
    source_distance_lock = Lock()

    def cached_source_distances(source_indices: np.ndarray) -> np.ndarray:
        """Return exact SciPy shortest paths, calculating every source once."""
        requested = [int(value) for value in source_indices]
        with source_distance_lock:
            missing = [
                value for value in requested if value not in source_distance_cache
            ]
        if missing:
            calculated = dijkstra(
                adjacency,
                directed=False,
                indices=np.asarray(missing, dtype=int),
                return_predecessors=False,
            )
            calculated = np.asarray(calculated, dtype=float)
            if calculated.ndim == 1:
                calculated = calculated[None, :]
            with source_distance_lock:
                for source_index, row in zip(missing, calculated):
                    source_distance_cache.setdefault(source_index, row)
        with source_distance_lock:
            return np.vstack(
                [source_distance_cache[source_index] for source_index in requested]
            )

    def evaluate(selected_candidates: list[int], record_failure=True):
        nonlocal last_overloaded, last_assignment, last_unit_distances
        source_indices = np.concatenate(
            [
                np.asarray(existing_source_indices, dtype=int),
                np.asarray(
                    [candidate_source_indices[index] for index in selected_candidates],
                    dtype=int,
                ),
            ]
        )
        if len(np.unique(source_indices)) != len(source_indices):
            return None
        source_distances = cached_source_distances(source_indices)
        unit_distance_matrix = np.asarray(
            source_distances[:, unit_node_indices].T, dtype=float
        )
        if np.any(~np.isfinite(unit_distance_matrix).any(axis=1)):
            return None
        capacities = np.concatenate(
            [
                np.asarray(existing_capacities, dtype=float),
                np.full(len(selected_candidates), new_capacity, dtype=float),
            ]
        )
        biases = np.zeros(len(capacities), dtype=float)
        assignment = np.zeros(len(loads), dtype=int)
        unit_distances = np.zeros(len(loads), dtype=float)
        station_loads = np.zeros(len(capacities), dtype=float)
        for _balance_iteration in range(10000):
            adjusted = unit_distance_matrix + biases[None, :]
            assignment = np.argmin(adjusted, axis=1)
            unit_distances = unit_distance_matrix[
                np.arange(len(loads)), assignment
            ]
            if np.any(~np.isfinite(unit_distances)) or np.any(
                unit_distances > MAX_ROUTE_M + 1e-7
            ):
                break
            station_loads = np.bincount(
                assignment, weights=loads, minlength=len(capacities)
            )
            overloaded = np.flatnonzero(station_loads > capacities + 1e-6)
            if not len(overloaded):
                node_cluster = np.argmin(
                    np.asarray(source_distances, dtype=float).T
                    + biases[None, :],
                    axis=1,
                ).astype(int)
                for station_index, graph_index in enumerate(source_indices):
                    node_cluster[int(graph_index)] = station_index
                # Weighted shortest-path Voronoi has connected cells; demand
                # ownership must exactly match the node territories.
                if np.any(node_cluster[unit_node_indices] != assignment):
                    return None
                utilization = station_loads / capacities
                distance_cost = float(np.sum((loads + 0.5) * unit_distances))
                target_cost = float(
                    np.sum(np.abs(utilization - TARGET_UTILIZATION))
                    * TARGET_UTILIZATION_PENALTY
                )
                return (
                    assignment,
                    node_cluster,
                    capacities,
                    unit_distances,
                    distance_cost + target_cost,
                )

            overload_ratio = station_loads[overloaded] / capacities[overloaded]
            station_index = int(overloaded[int(np.argmax(overload_ratio))])
            members = np.flatnonzero(assignment == station_index)
            if not len(members):
                break
            alternative_cost = adjusted[members].copy()
            alternative_cost[:, station_index] = np.inf
            alternative_station = np.argmin(alternative_cost, axis=1)
            alternative_distance = unit_distance_matrix[
                members, alternative_station
            ]
            transferable = np.isfinite(alternative_distance) & (
                alternative_distance <= MAX_ROUTE_M + 1e-7
            )
            if not np.any(transferable):
                break
            margins = (
                alternative_cost[np.arange(len(members)), alternative_station]
                - adjusted[members, station_index]
            )
            margins[~transferable] = np.inf
            required_increase = float(np.min(margins))
            if not np.isfinite(required_increase):
                break
            biases[station_index] += max(0.0, required_increase) + 0.05
            biases -= float(np.min(biases))

        if record_failure:
            last_overloaded = np.flatnonzero(station_loads > capacities + 1e-6)
            last_assignment = assignment
            last_unit_distances = unit_distances
        return None

    selected = (
        list(preferred_candidate_indices)
        if preferred_candidate_indices is not None
        else list(range(len(candidate_source_indices)))
    )
    current = evaluate(selected)
    added_for_capacity = 0
    while current is None and last_overloaded is not None:
        if added_for_capacity >= 50:
            break
        existing_sources = set(int(value) for value in existing_source_indices)
        candidate_sources = set(int(value) for value in candidate_source_indices)
        chosen_graph_index = None
        for overloaded_station in last_overloaded:
            members = np.flatnonzero(last_assignment == int(overloaded_station))
            scores = (last_unit_distances[members] + 10.0) * (loads[members] + 0.5)
            for member in members[np.argsort(scores)[::-1]]:
                unit_graph_index = int(unit_node_indices[int(member)])
                component_index = int(
                    graph_component_by_node_index[unit_graph_index]
                )
                component_regular = regular_by_component.get(component_index)
                component_tree = regular_tree_by_component.get(component_index)
                if component_regular is None or component_tree is None:
                    continue
                _distance, local_indices = component_tree.query(
                    node_xy[unit_graph_index],
                    k=min(25, len(component_regular)),
                )
                for local_index in np.atleast_1d(local_indices):
                    graph_index = int(component_regular[int(local_index)])
                    if (
                        graph_index in existing_sources
                        or graph_index in candidate_sources
                    ):
                        continue
                    chosen_graph_index = graph_index
                    break
                if chosen_graph_index is not None:
                    break
            if chosen_graph_index is not None:
                break
        if chosen_graph_index is None:
            break
        candidate_source_indices.append(chosen_graph_index)
        selected.append(len(candidate_source_indices) - 1)
        added_for_capacity += 1
        log(
            f"Capaciteitskandidaat {added_for_capacity} toegevoegd op "
            f"kabelknoop {node_list[chosen_graph_index]}."
        )
        last_overloaded = None
        last_assignment = None
        last_unit_distances = None
        current = evaluate(selected)
    if current is None:
        raise RuntimeError(
            "Ook met alle beschikbare kandidaatstations ontstaat geen "
            "capaciteitsgeldige kabel-Voronoi-verdeling"
        )

    def evaluate_removal(candidate_index):
        trial = [index for index in selected if index != candidate_index]
        evaluated = evaluate(trial, record_failure=False)
        if evaluated is not None:
            return (evaluated[4], candidate_index, trial, evaluated)
        return None

    pending_removals: list[int] = []
    while selected:
        # Candidates which were proven individually removable in the previous
        # full scan remain the best exact batch proposals. Test those batches
        # first (each with the same full route/capacity/territory evaluation)
        # instead of immediately recalculating every remaining single removal.
        # If interactions make all carried proposals invalid, fall back to the
        # exhaustive parallel scan below. No feasibility rule is relaxed.
        if pending_removals:
            ordered_pending = [
                index for index in pending_removals if index in selected
            ]
            carried_valid = []
            carry_workers = min(
                max(1, CPU_THREADS), len(ordered_pending), 24
            )
            if carry_workers > 1:
                with ThreadPoolExecutor(max_workers=carry_workers) as executor:
                    for result in executor.map(
                        evaluate_removal, ordered_pending
                    ):
                        if result is not None:
                            carried_valid.append(result)
            else:
                for candidate_index in ordered_pending:
                    result = evaluate_removal(candidate_index)
                    if result is not None:
                        carried_valid.append(result)
            if carried_valid:
                ordered_carried = [
                    value[1]
                    for value in sorted(
                        carried_valid, key=lambda value: (value[0], value[1])
                    )
                ]
                accelerated_removed: list[int] = []
                batch_size = len(ordered_carried)
                while batch_size >= 2:
                    trial_removed = set(ordered_carried[:batch_size])
                    trial = [
                        index for index in selected if index not in trial_removed
                    ]
                    evaluated = evaluate(trial, record_failure=False)
                    if evaluated is not None:
                        accelerated_removed = ordered_carried[:batch_size]
                        selected = trial
                        current = evaluated
                        break
                    batch_size //= 2
                if not accelerated_removed:
                    _score, removed, selected, current = min(
                        carried_valid, key=lambda value: (value[0], value[1])
                    )
                    accelerated_removed = [removed]
                removed_set = set(accelerated_removed)
                pending_removals = [
                    index
                    for index in ordered_carried
                    if index not in removed_set and index in selected
                ]
                log(
                    "Overbodige kabel-Voronoi-kandidaat/kandidaten via "
                    "versnelde herscan verwijderd: "
                    + ", ".join(
                        str(index + 1)
                        for index in sorted(accelerated_removed)
                    )
                    + "."
                )
                continue
            pending_removals = []

        valid_removals = []

        # Candidate removals are independent and mostly run inside NumPy/SciPy,
        # which releases the GIL. Use all configured logical processors (up to
        # 24 concurrent trials) instead of the old artificial cap of eight.
        removal_workers = min(max(1, CPU_THREADS), len(selected), 24)
        if removal_workers > 1 and len(selected) > 1:
            log(
                f"{len(selected)} onafhankelijke kandidaatcontroles met "
                f"{removal_workers} CPU-threads uitvoeren..."
            )
            with ThreadPoolExecutor(max_workers=removal_workers) as executor:
                futures = {
                    executor.submit(evaluate_removal, candidate_index): candidate_index
                    for candidate_index in selected
                }
                for future in as_completed(futures):
                    result = future.result()
                    if result is not None:
                        valid_removals.append(result)
        else:
            for candidate_index in selected:
                result = evaluate_removal(candidate_index)
                if result is not None:
                    valid_removals.append(result)
        if not valid_removals:
            break

        # Removing only one candidate after evaluating every candidate makes
        # pruning quadratic.  Real connection cables add many graph vertices
        # and can temporarily require a larger emergency set, so that approach
        # became needlessly slow.  Try the individually valid removals as a
        # batch (largest half first), and fall back to the single best removal
        # when combinations interact.
        ordered_removals = [
            value[1]
            for value in sorted(valid_removals, key=lambda value: (value[0], value[1]))
        ]
        removed_batch: list[int] = []
        batch_size = len(ordered_removals)
        while batch_size >= 2:
            trial_removed = set(ordered_removals[:batch_size])
            trial = [index for index in selected if index not in trial_removed]
            evaluated = evaluate(trial, record_failure=False)
            if evaluated is not None:
                removed_batch = ordered_removals[:batch_size]
                selected = trial
                current = evaluated
                break
            batch_size //= 2
        if not removed_batch:
            _score, removed, selected, current = min(
                valid_removals, key=lambda value: (value[0], value[1])
            )
            removed_batch = [removed]
        removed_set = set(removed_batch)
        pending_removals = [
            index
            for index in ordered_removals
            if index not in removed_set and index in selected
        ]
        log(
            "Overbodige kabel-Voronoi-kandidaat/kandidaten verwijderd: "
            + ", ".join(str(index + 1) for index in sorted(removed_batch))
            + "."
        )

    assignment, node_cluster, capacities, unit_distances, _score = current
    min_utilization = float(
        np.min(
            np.bincount(assignment, weights=loads, minlength=len(capacities))
            / capacities
        )
    )
    log(
        f"Kabel-Voronoi-terugval geldig met {len(selected)} nieuw(e) "
        "station(s); alle territoria volgen exclusieve kortste kabelpaden."
    )
    return assignment, min_utilization, node_cluster, selected, unit_distances


def build_exclusive_routes(
    graph: nx.Graph,
    node_list: list[tuple[float, float]],
    node_cluster: np.ndarray,
    source_nodes: list[tuple[float, float]],
    target_nodes: list[tuple[float, float]],
    unit_assignment: np.ndarray,
) -> tuple[list[object], np.ndarray, np.ndarray]:
    node_index = {node: i for i, node in enumerate(node_list)}
    route_geometries: list[object] = []
    route_lengths: list[float] = []
    unit_route_distance = np.zeros(len(target_nodes), dtype=float)
    for station_index, source in enumerate(source_nodes):
        log(
            f"Exclusieve kabelroute {station_index + 1}/{len(source_nodes)} "
            "samenstellen..."
        )
        owned_nodes = {
            node_list[i] for i in np.flatnonzero(node_cluster == station_index)
        }
        owned_graph = graph.subgraph(owned_nodes)
        owned_node_count = owned_graph.number_of_nodes()
        if source not in owned_graph:
            raise RuntimeError("Station ontbreekt in het eigen kabeldeel")
        predecessors, owned_distances = nx.dijkstra_predecessor_and_distance(
            owned_graph, source, weight="weight"
        )
        edges: set[tuple[tuple[float, float], tuple[float, float]]] = set()
        targets = {
            target_nodes[i]
            for i in np.flatnonzero(unit_assignment == station_index)
        }
        for target in targets:
            if target not in owned_distances:
                raise RuntimeError("Aansluiting is niet bereikbaar binnen eigen kabeldeel")
            current = target
            guard = 0
            while current != source:
                previous_candidates = predecessors.get(current)
                if not previous_candidates:
                    raise RuntimeError("Routeboom bevat een onbereikbare aansluiting")
                previous = previous_candidates[0]
                edge = (current, previous) if current < previous else (previous, current)
                edges.add(edge)
                current = previous
                guard += 1
                if guard > owned_node_count:
                    raise RuntimeError("Lus gedetecteerd in routeboom")
        lines = [LineString([u, v]) for u, v in edges]
        geometry = merge_linework(lines)
        route_geometries.append(geometry)
        route_lengths.append(float(sum(line.length for line in lines)))
        for unit_index in np.flatnonzero(unit_assignment == station_index):
            unit_route_distance[unit_index] = float(
                owned_distances[target_nodes[unit_index]]
            )
    return route_geometries, np.asarray(route_lengths), unit_route_distance


def build_guided_manual_routes(
    graph: nx.Graph,
    source_nodes: list[tuple[float, float]],
    target_nodes: list[tuple[float, float]],
    point_assignment: np.ndarray,
    previous_assignment: np.ndarray,
    target_station_index: int,
    previous_route_geometries: list[object],
    station_names: list[str],
    block_other_cluster_routes: bool = True,
    check_shared_routes_and_branches: bool = True,
    previous_point_route_distance: np.ndarray | None = None,
    preserved_station_indices: set[int] | None = None,
) -> tuple[list[object], np.ndarray, np.ndarray]:
    """Rebuild fixed routes while strongly preferring existing cable ownership."""
    graph_edges = list(graph.edges)
    edge_lines = [LineString([first, second]) for first, second in graph_edges]
    edge_tree = STRtree(edge_lines)
    zero_cost_edges = [
        LineString([first, second])
        for first, second, attributes in graph.edges(data=True)
        if float(attributes.get("calculation_factor", 1.0)) <= 1e-9
    ]
    zero_cost_geometry = unary_union(zero_cost_edges) if zero_cost_edges else None
    edge_owner: dict[
        tuple[tuple[float, float], tuple[float, float]], tuple[int, float]
    ] = {}

    def edge_key(first, second):
        return (first, second) if first < second else (second, first)

    # Recover prior cable ownership as a routing hint. A small tolerance absorbs
    # the 0.1 m graph rounding without joining genuinely parallel cable lines.
    ownership_tolerance = 0.16
    for station_index, geometry in enumerate(previous_route_geometries):
        for part in line_parts(geometry):
            search_area = part.buffer(
                ownership_tolerance,
                cap_style="flat",
                join_style="mitre",
            )
            for raw_edge_index in edge_tree.query(search_area):
                edge_index = int(raw_edge_index)
                edge = edge_lines[edge_index]
                midpoint = edge.interpolate(0.5, normalized=True)
                distance = float(midpoint.distance(part))
                if distance > ownership_tolerance + 1e-9:
                    continue
                key = edge_key(*graph_edges[edge_index])
                current = edge_owner.get(key)
                if current is None or distance < current[1]:
                    edge_owner[key] = (station_index, distance)

    if previous_point_route_distance is None:
        point_route_distance = np.zeros(len(target_nodes), dtype=float)
    else:
        point_route_distance = np.asarray(
            previous_point_route_distance, dtype=float
        ).copy()
        if len(point_route_distance) != len(target_nodes):
            raise RuntimeError("Bestaande Route_m-waarden passen niet bij de aansluitingen")

    def trace_on_graph(
        route_graph: nx.Graph,
        source,
        indexed_targets: dict[int, tuple[float, float]],
        weight_function,
    ):
        if source not in route_graph:
            raise RuntimeError("Station ligt niet op de beschikbare routeboom")
        if not indexed_targets:
            return set(), {}
        predecessors, _ = nx.dijkstra_predecessor_and_distance(
            route_graph,
            source,
            weight=weight_function,
        )
        edges: set[tuple[tuple[float, float], tuple[float, float]]] = set()
        distances: dict[int, float] = {}
        for point_index, target in indexed_targets.items():
            if target not in predecessors and target != source:
                raise RuntimeError(
                    f"Aansluiting {point_index} is niet bereikbaar zonder kabels "
                    "van een ander cluster"
                )
            current = target
            physical_distance = 0.0
            guard = 0
            while current != source:
                previous_candidates = predecessors.get(current)
                if not previous_candidates:
                    raise RuntimeError(
                        f"Route naar aansluiting {point_index} is onvolledig"
                    )
                previous = previous_candidates[0]
                edges.add(edge_key(current, previous))
                physical_distance += float(
                    route_graph[current][previous]["weight"]
                )
                current = previous
                guard += 1
                if guard > route_graph.number_of_nodes():
                    raise RuntimeError("Lus gedetecteerd in handmatige routeboom")
            distances[int(point_index)] = physical_distance
        return edges, distances

    route_geometries: list[object] = [LineString()] * len(source_nodes)
    route_lengths = np.zeros(len(source_nodes), dtype=float)
    retained_geometries: list[object] = [LineString()] * len(source_nodes)

    # Prune each old exclusive route using that route itself as graph. This
    # preserves every unchanged cluster exactly and releases only unused twigs.
    for station_index, old_geometry in enumerate(previous_route_geometries):
        retained_points = np.flatnonzero(
            (previous_assignment == station_index)
            & (point_assignment == station_index)
        )
        if not len(retained_points):
            continue
        # The complete cable graph was already noded at every connection and
        # station immediately before this function. Recover the old route as an
        # edge subgraph instead of unary-unioning and noding every cluster route
        # again. On a normal design this removes 10-30 seconds of duplicate
        # geometry work per station from every manual correction.
        retained_route_edges = [
            edge
            for edge in graph_edges
            if edge_owner.get(edge_key(*edge), (-1, math.inf))[0] == station_index
        ]
        retained_graph = graph.edge_subgraph(retained_route_edges).copy()
        snapped_source = source_nodes[station_index]
        retained_target_nodes = [target_nodes[index] for index in retained_points]
        required_nodes = {snapped_source, *retained_target_nodes}
        if not required_nodes.issubset(retained_graph.nodes):
            # Compatibility fallback for an older/manual route geometry that no
            # longer matches the saved noded cable layer closely enough.
            route_frame = gpd.GeoDataFrame(geometry=[old_geometry], crs=CRS_RD)
            terminal_frame = gpd.GeoDataFrame(
                geometry=[Point(target_nodes[index]) for index in retained_points],
                crs=CRS_RD,
            )
            station_frame = gpd.GeoDataFrame(
                geometry=[Point(source_nodes[station_index])], crs=CRS_RD
            )
            noded_old_route = node_cable_network(
                route_frame,
                terminal_frame,
                station_frame,
                0.0,
                zero_cost_geometry=zero_cost_geometry,
            )
            retained_graph = build_network(noded_old_route)
            retained_nodes = list(retained_graph.nodes)
            retained_tree = cKDTree(np.asarray(retained_nodes, dtype=float))
            snapped_source = snap_xy(
                np.asarray([source_nodes[station_index]], dtype=float),
                retained_nodes,
                retained_tree,
            )[0][0]
            retained_target_nodes = snap_xy(
                np.asarray(
                    [target_nodes[index] for index in retained_points], dtype=float
                ),
                retained_nodes,
                retained_tree,
            )[0]
        indexed_targets = {
            int(point_index): retained_target_nodes[position]
            for position, point_index in enumerate(retained_points)
        }
        retained_edges, distances = trace_on_graph(
            retained_graph,
            snapped_source,
            indexed_targets,
            "weight",
        )
        retained_lines = [
            LineString([first, second]) for first, second in retained_edges
        ]
        geometry = merge_linework(retained_lines)
        if geometry.is_empty and old_geometry is not None and not old_geometry.is_empty:
            geometry = old_geometry
            if preserved_station_indices is not None:
                preserved_station_indices.add(int(station_index))
            log(
                f"WAARSCHUWING: route {station_names[station_index]} zou na "
                "de clustercorrectie leeg worden doordat de overblijvende "
                "aansluiting(en) op dezelfde netwerkknoop liggen; de bestaande "
                "zichtbare route en Route_m-waarden zijn behouden."
            )
            retained_geometries[station_index] = geometry
            route_geometries[station_index] = geometry
            route_lengths[station_index] = float(geometry.length)
            continue
        retained_geometries[station_index] = geometry
        route_geometries[station_index] = geometry
        route_lengths[station_index] = float(
            sum(
                retained_graph[first][second]["weight"]
                for first, second in retained_edges
            )
        )
        for point_index, distance in distances.items():
            point_route_distance[point_index] = distance

    blocked_edges: set[
        tuple[tuple[float, float], tuple[float, float]]
    ] = set()
    if block_other_cluster_routes:
        blocked_geometry = unary_union(
            [
                geometry
                for station_index, geometry in enumerate(retained_geometries)
                if station_index != target_station_index and not geometry.is_empty
            ]
        )
        target_retained_geometry = retained_geometries[target_station_index]
        if not blocked_geometry.is_empty:
            for edge, edge_line in zip(graph_edges, edge_lines):
                midpoint = edge_line.interpolate(0.5, normalized=True)
                belongs_to_target = (
                    not target_retained_geometry.is_empty
                    and midpoint.distance(target_retained_geometry)
                    <= ownership_tolerance
                )
                if (
                    not belongs_to_target
                    and midpoint.distance(blocked_geometry) <= ownership_tolerance
                ):
                    blocked_edges.add(edge_key(*edge))

    def target_weight(first, second, data):
        key = edge_key(first, second)
        if key in blocked_edges:
            return None
        owner = edge_owner.get(key)
        penalty = (
            0.0
            if owner is not None and owner[0] == target_station_index
            else 25.0
        )
        return float(data["weight"]) + penalty

    # Existing target connections keep their verified old route. Only the newly
    # moved terminals need a path through released or previously unowned cable.
    target_indices = np.flatnonzero(
        (point_assignment == target_station_index)
        & (previous_assignment != target_station_index)
    )
    target_edges, target_distances = trace_on_graph(
        graph,
        source_nodes[target_station_index],
        {int(index): target_nodes[index] for index in target_indices},
        target_weight,
    )
    target_lines = [LineString([first, second]) for first, second in target_edges]
    new_target_geometry = merge_linework(target_lines)
    combined_target = unary_union(
        [retained_geometries[target_station_index], new_target_geometry]
    )
    route_geometries[target_station_index] = merge_linework([combined_target])
    if (
        route_geometries[target_station_index].is_empty
        and previous_route_geometries[target_station_index] is not None
        and not previous_route_geometries[target_station_index].is_empty
    ):
        route_geometries[target_station_index] = previous_route_geometries[
            target_station_index
        ]
        if preserved_station_indices is not None:
            preserved_station_indices.add(int(target_station_index))
        log(
            f"WAARSCHUWING: doelroute {station_names[target_station_index]} "
            "zou leeg worden; de bestaande zichtbare route is behouden."
        )
    route_lengths[target_station_index] = float(
        route_geometries[target_station_index].length
    )
    for point_index, distance in target_distances.items():
        point_route_distance[point_index] = distance

    if check_shared_routes_and_branches:
        conflicts: set[tuple[int, int]] = set()
        for first in range(len(route_geometries)):
            for second in range(first + 1, len(route_geometries)):
                shared_length = float(
                    route_geometries[first].intersection(
                        route_geometries[second]
                    ).length
                )
                if shared_length > 0.01:
                    conflicts.add((first, second))
        if conflicts:
            labels = ", ".join(
                f"{station_names[first]} / {station_names[second]}"
                for first, second in sorted(conflicts)
            )
            raise RuntimeError(
                "De handmatige verplaatsing zou dezelfde kabeldelen door meerdere "
                f"clusters laten gebruiken ({labels}). Selecteer de volledige kabeltak."
            )

    return (
        route_geometries,
        route_lengths,
        point_route_distance,
    )


def build_refreshed_fixed_routes(
    graph: nx.Graph,
    source_nodes: list[tuple[float, float]],
    target_nodes: list[tuple[float, float]],
    point_assignment: np.ndarray,
    previous_route_geometries: list[object],
    station_names: list[str],
    block_other_cluster_routes: bool = True,
    check_shared_routes_and_branches: bool = True,
    refresh_station_indices: set[int] | None = None,
    previous_point_route_distance: np.ndarray | None = None,
    preserved_station_indices: set[int] | None = None,
    relocated_station_indices: set[int] | None = None,
) -> tuple[list[object], np.ndarray, np.ndarray]:
    """Rebuild every fixed cluster on shortest available exclusive cable paths.

    Existing route ownership is only a boundary constraint. Unowned cable parts
    (including a newly drawn trench) may be selected whenever they shorten a
    path. Connection-to-station assignments remain unchanged. When a subset is
    supplied, all other saved routes and their point distances remain intact.
    """
    graph_edges = list(graph.edges)
    edge_lines = [LineString([first, second]) for first, second in graph_edges]
    edge_tree = STRtree(edge_lines)

    def edge_key(first, second):
        return (first, second) if first < second else (second, first)

    ownership_tolerance = 0.16
    edge_owner: dict[
        tuple[tuple[float, float], tuple[float, float]], tuple[int, float]
    ] = {}
    edge_owner_candidates: dict[
        tuple[tuple[float, float], tuple[float, float]], set[int]
    ] = defaultdict(set)
    for station_index, geometry in enumerate(previous_route_geometries):
        for part in line_parts(geometry):
            search_area = part.buffer(
                ownership_tolerance,
                cap_style="flat",
                join_style="mitre",
            )
            for raw_edge_index in edge_tree.query(search_area):
                edge_index = int(raw_edge_index)
                edge = edge_lines[edge_index]
                midpoint = edge.interpolate(0.5, normalized=True)
                distance = float(midpoint.distance(part))
                if distance > ownership_tolerance + 1e-9:
                    continue
                key = edge_key(*graph_edges[edge_index])
                edge_owner_candidates[key].add(station_index)
                current = edge_owner.get(key)
                if current is None or distance < current[1]:
                    edge_owner[key] = (station_index, distance)

    refresh_station_indices = (
        set(range(len(source_nodes)))
        if refresh_station_indices is None
        else {int(index) for index in refresh_station_indices}
    )
    invalid_indices = sorted(
        index
        for index in refresh_station_indices
        if index < 0 or index >= len(source_nodes)
    )
    if invalid_indices:
        raise RuntimeError("Ongeldige geselecteerde stationindex voor routeverversing")

    # Dense parallel service cables can put the globally nearest graph node on
    # a neighbouring cluster after the network has been noded again. Anchor
    # every fixed terminal to the nearest node of its own verified old route
    # before looking for shorter paths through newly added, unowned cable.
    owned_nodes: list[set[tuple[float, float]]] = [
        set() for _ in source_nodes
    ]
    for first, second in graph_edges:
        candidates = edge_owner_candidates.get(edge_key(first, second), set())
        for candidate in candidates:
            owned_nodes[candidate].update((first, second))
    for station_index, nodes in enumerate(owned_nodes):
        if station_index not in refresh_station_indices:
            continue
        if not nodes:
            # A previously empty/missing route has no ownership anchor. Keep
            # the normal nearest cable nodes so the refresh can repair it from
            # the current noded trench network instead of failing immediately.
            log(
                f"Route {station_names[station_index]} heeft geen bruikbaar "
                "bestaand kabelanker; herstel vanaf de dichtstbijzijnde "
                "sleufknopen wordt geprobeerd."
            )
            continue
        own_node_list = list(nodes)
        own_tree = cKDTree(np.asarray(own_node_list, dtype=float))
        _distance, source_position = own_tree.query(
            np.asarray(source_nodes[station_index], dtype=float), k=1
        )
        # Normally a refresh anchors the station to its former route to avoid
        # accidentally jumping onto another cluster's parallel service cable.
        # A user-relocated station has already been placed on a verified
        # network vertex: preserve that precise location instead.
        if station_index not in (relocated_station_indices or set()):
            source_nodes[station_index] = own_node_list[int(source_position)]
        member_indices = np.flatnonzero(point_assignment == station_index)
        if len(member_indices):
            _distances, target_positions = own_tree.query(
                np.asarray(
                    [target_nodes[int(index)] for index in member_indices],
                    dtype=float,
                ),
                k=1,
            )
            for point_index, position in zip(member_indices, target_positions):
                target_nodes[int(point_index)] = own_node_list[int(position)]

    route_geometries: list[object] = []
    route_lengths = np.zeros(len(source_nodes), dtype=float)
    if previous_point_route_distance is None:
        point_route_distance = np.zeros(len(target_nodes), dtype=float)
    else:
        point_route_distance = np.asarray(
            previous_point_route_distance, dtype=float
        ).copy()
        if len(point_route_distance) != len(target_nodes):
            raise RuntimeError("Bestaande Route_m-waarden passen niet bij de aansluitingen")

    for station_index, source in enumerate(source_nodes):
        previous_geometry = previous_route_geometries[station_index]
        member_indices = np.flatnonzero(point_assignment == station_index)
        previous_member_distances = point_route_distance[member_indices].copy()

        def retain_previous_route(reason):
            if previous_geometry is None or previous_geometry.is_empty:
                raise RuntimeError(reason)
            route_geometries.append(previous_geometry)
            route_lengths[station_index] = float(previous_geometry.length)
            point_route_distance[member_indices] = previous_member_distances
            if preserved_station_indices is not None:
                preserved_station_indices.add(int(station_index))
            log(
                f"WAARSCHUWING: route {station_names[station_index]} kon niet "
                f"veilig worden vernieuwd ({reason}); de bestaande zichtbare "
                "route en Route_m-waarden zijn behouden."
            )

        if station_index not in refresh_station_indices:
            route_geometries.append(previous_geometry)
            route_lengths[station_index] = float(previous_geometry.length)
            continue
        if source not in graph:
            retain_previous_route(
                f"station {station_names[station_index]} ligt niet op het kabelnet"
            )
            continue

        def cluster_weight(first, second, data):
            candidates = edge_owner_candidates.get(
                edge_key(first, second), set()
            )
            if (
                block_other_cluster_routes
                and candidates
                and station_index not in candidates
            ):
                return None
            return float(data["weight"])

        try:
            predecessors, _distances = nx.dijkstra_predecessor_and_distance(
                graph,
                source,
                weight=cluster_weight,
            )
            used_edges: set[
                tuple[tuple[float, float], tuple[float, float]]
            ] = set()
            for point_index in member_indices:
                target = target_nodes[int(point_index)]
                if target != source and target not in predecessors:
                    raise RuntimeError(
                        f"aansluiting {int(point_index)} is niet bereikbaar via "
                        "het eigen of nieuw toegevoegde kabelnet"
                    )
                current = target
                physical_route_m = 0.0
                guard = 0
                while current != source:
                    previous_candidates = predecessors.get(current)
                    if not previous_candidates:
                        raise RuntimeError(
                            f"route naar aansluiting {int(point_index)} is onvolledig"
                        )
                    previous = previous_candidates[0]
                    used_edges.add(edge_key(current, previous))
                    physical_route_m += float(graph[current][previous]["weight"])
                    current = previous
                    guard += 1
                    if guard > graph.number_of_nodes():
                        raise RuntimeError("lus gedetecteerd bij routeverversing")
                point_route_distance[int(point_index)] = physical_route_m
        except (RuntimeError, nx.NetworkXException) as exc:
            retain_previous_route(str(exc))
            continue

        lines = [LineString([first, second]) for first, second in used_edges]
        geometry = merge_linework(lines)
        if geometry.is_empty and len(member_indices):
            retain_previous_route(
                "station en aansluiting(en) kwamen op dezelfde netwerkknoop; "
                "de nieuwe route zou leeg zijn"
            )
            continue
        route_geometries.append(geometry)
        route_lengths[station_index] = float(geometry.length)

    if check_shared_routes_and_branches:
        conflicts = []
        for first in range(len(route_geometries)):
            for second in range(first + 1, len(route_geometries)):
                shared_length = float(
                    route_geometries[first].intersection(
                        route_geometries[second]
                    ).length
                )
                if shared_length > 0.01:
                    conflicts.append(
                        f"{station_names[first]} / {station_names[second]}"
                    )
        if conflicts:
            raise RuntimeError(
                "De kortste herberekende routes zouden kabeldelen delen tussen "
                "clusters: " + ", ".join(conflicts)
            )

    return route_geometries, route_lengths, point_route_distance


def make_cable_based_cluster_polygons(
    route_geometries: list[object],
    point_xy: np.ndarray,
    point_snap_xy: np.ndarray,
    point_assignment: np.ndarray,
    station_xy: np.ndarray,
    station_snap_xy: np.ndarray,
    station_count: int,
    study_area_override: object | None = None,
    allow_external_routes: bool = False,
) -> tuple[list[object], object]:
    sites: dict[tuple[float, float], tuple[np.ndarray, int, int]] = {}

    def add_site(xy: np.ndarray, cluster: int, priority: int) -> None:
        key = tuple(np.round(np.asarray(xy, dtype=float), 2))
        current = sites.get(key)
        if current is None or priority > current[2]:
            sites[key] = (np.asarray(xy, dtype=float), int(cluster), priority)
        elif current[1] != int(cluster) and priority == current[2]:
            # Equal-priority conflicts only occur at a cluster boundary. Keep
            # the first site; adjacent samples on both sides still define it.
            return

    sample_step = 2.0
    for cluster_index, geometry in enumerate(route_geometries):
        parts = (
            list(geometry.geoms)
            if geometry.geom_type == "MultiLineString"
            else [geometry]
        )
        for part in parts:
            if part.is_empty:
                continue
            sample_count = max(1, int(math.ceil(part.length / sample_step)))
            for distance_along in np.linspace(0.0, part.length, sample_count + 1):
                point = part.interpolate(float(distance_along))
                add_site(np.asarray(point.coords[0]), cluster_index, 1)

    def add_connector(a: np.ndarray, b: np.ndarray, cluster: int, priority: int) -> None:
        length = float(np.linalg.norm(b - a))
        count = max(1, int(math.ceil(length / sample_step)))
        for fraction in np.linspace(0.0, 1.0, count + 1):
            add_site(a + (b - a) * float(fraction), cluster, priority)

    for index in range(len(point_xy)):
        add_connector(
            point_xy[index],
            point_snap_xy[index],
            int(point_assignment[index]),
            2,
        )
    for station_index in range(station_count):
        add_connector(
            station_xy[station_index],
            station_snap_xy[station_index],
            station_index,
            3,
        )

    site_values = list(sites.values())
    site_xy = np.asarray([value[0] for value in site_values], dtype=float)
    site_cluster = np.asarray([value[1] for value in site_values], dtype=int)
    points = MultiPoint([Point(xy) for xy in site_xy])
    if study_area_override is None:
        study_area = points.convex_hull.buffer(55).simplify(1.0)
    else:
        study_area = study_area_override.buffer(0)
        if study_area.is_empty:
            raise RuntimeError("Het opgegeven plangebied is leeg of ongeldig")
    cells_collection = voronoi_polygons(
        points, extend_to=study_area.envelope, ordered=True
    )
    cells = [cell.intersection(study_area) for cell in cells_collection.geoms]
    if len(cells) != len(site_xy):
        raise RuntimeError("Aantal kabel-Voronoi-cellen komt niet overeen met sites")
    polygons: list[object] = []
    for station_index in range(station_count):
        cluster_cells = [
            cells[i] for i in np.flatnonzero(site_cluster == station_index)
        ]
        polygon = unary_union(cluster_cells)
        # A cable tree may pass a junction where Voronoi cells meet only in one
        # mathematical point. OGC then reports two polygons even though the
        # exclusive cable route itself is connected. Reserve a narrow corridor
        # around that route (and the point/station snap connectors), so the
        # cartographic area is also one visibly connected polygon.
        backbone_parts = [route_geometries[station_index]]
        for point_index in np.flatnonzero(point_assignment == station_index):
            a = point_xy[point_index]
            b = point_snap_xy[point_index]
            if float(np.linalg.norm(b - a)) > 1e-9:
                backbone_parts.append(LineString([a, b]))
        a = station_xy[station_index]
        b = station_snap_xy[station_index]
        if float(np.linalg.norm(b - a)) > 1e-9:
            backbone_parts.append(LineString([a, b]))
        backbone = unary_union(backbone_parts)
        if not backbone.is_empty:
            corridor = backbone.buffer(0.75, cap_style="flat", join_style="mitre")
            polygon = unary_union([polygon, corridor.intersection(study_area)]).buffer(0)

        # Defensive fallback for precision slivers: join remaining parts by the
        # shortest possible in-plan bridge. This is only used after the cable
        # corridor repair above and keeps the result free of exclaves.
        repair_guard = 0
        while (not allow_external_routes and polygon.geom_type == "MultiPolygon" and len(polygon.geoms) > 1):
            repair_guard += 1
            if repair_guard > 100:
                break
            parts = sorted(polygon.geoms, key=lambda part: part.area, reverse=True)
            main = parts[0]
            nearest_part = min(parts[1:], key=lambda part: main.distance(part))
            start, end = nearest_points(main, nearest_part)
            if start.distance(end) < 1e-9:
                bridge = start.buffer(0.75)
            else:
                bridge = LineString([start, end]).buffer(
                    0.75, cap_style="flat", join_style="mitre"
                )
            polygon = unary_union([polygon, bridge.intersection(study_area)]).buffer(0)
        if polygon.geom_type == "MultiPolygon" and len(polygon.geoms) == 1:
            polygon = polygon.geoms[0]
        polygons.append(polygon)
    return polygons, study_area


def external_routing_enabled(routes):
    """Older projects keep their original policy; new results persist it."""
    return bool(len(routes) and "Buitenplan_toegestaan" in routes and
                all(str(value).strip().casefold() in ("true", "1", "ja")
                    for value in routes["Buitenplan_toegestaan"]))


def invalid_disconnected_area(polygon, route, study_area, allow_external_routes):
    if polygon.geom_type != "MultiPolygon" or len(polygon.geoms) <= 1:
        return False
    # Clipping a connected cable route to a concave/disjoint study area can
    # legitimately leave multiple service polygons inside it. Each piece must
    # touch the actual connected route; arbitrary detached slivers still fail.
    if not allow_external_routes or route.difference(study_area.buffer(.05)).length <= .1:
        return True
    return any(not part.buffer(.05).intersects(route) for part in polygon.geoms)


def recalculate_manual_assignment(
    connections: gpd.GeoDataFrame,
    stations: gpd.GeoDataFrame,
    areas: gpd.GeoDataFrame,
    routes: gpd.GeoDataFrame,
    cables: gpd.GeoDataFrame,
    selected_source_fids: set[int],
    target_station_source_fid: int,
    remove_source_clusters: bool = False,
    force_assignment: bool = False,
    max_route_m: float = 850.0,
    node_tolerance_m: float = 1.0,
    plan_layer: gpd.GeoDataFrame | None = None,
    check_station_capacity: bool = True,
    check_max_route: bool = True,
    block_other_cluster_routes: bool = True,
    check_shared_routes_and_branches: bool = True,
    safety_checks_enabled: bool | None = None,
    refresh_all_routes: bool = False,
    refresh_cluster_names: set[str] | None = None,
    defer_area_rebuild: bool = False,
    preserve_all_routes: bool = False,
    relocated_station_names: set[str] | None = None,
    allow_external_routes: bool | None = None,
) -> tuple[
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    gpd.GeoDataFrame,
    dict[str, object],
]:
    """Apply a fixed manual move and rebuild all dependent cluster products."""
    # Compatibility with assignments created by the former single checkbox.
    if safety_checks_enabled is not None:
        legacy_value = bool(safety_checks_enabled)
        check_station_capacity = legacy_value
        check_max_route = legacy_value
        block_other_cluster_routes = legacy_value
        check_shared_routes_and_branches = legacy_value
    log("Handmatige clustertoedeling voorbereiden...")
    frames = {
        "aansluitingen": connections.copy(),
        "stations": stations.copy(),
        "gebieden": areas.copy(),
        "routes": routes.copy(),
        "sleuven": cables.copy(),
    }
    if plan_layer is not None:
        frames["plangebied"] = plan_layer.copy()
    if any(frame.crs is None for frame in frames.values()):
        raise RuntimeError("Alle handmatige correctielagen moeten een geldige CRS hebben")

    required_columns = {
        "aansluitingen": {"__src_fid", "Cluster", "Ontwerp_A"},
        "stations": {"__src_fid", "Cluster", "Type", "KVA"},
        "gebieden": {"__src_fid", "Cluster"},
        "routes": {"__src_fid", "Cluster"},
    }
    for layer_name, required in required_columns.items():
        missing = sorted(required.difference(frames[layer_name].columns))
        if missing:
            raise RuntimeError(
                f"Laag {layer_name} mist verplichte velden: {', '.join(missing)}"
            )

    original_crs = {name: frame.crs for name, frame in frames.items()}
    rd = {
        name: frame.to_crs(CRS_RD).copy()
        for name, frame in frames.items()
    }
    connections_rd = rd["aansluitingen"]
    stations_rd = rd["stations"]
    areas_rd = rd["gebieden"]
    routes_rd = rd["routes"]
    cables_rd = rd["sleuven"]
    if allow_external_routes is None:
        allow_external_routes = external_routing_enabled(routes_rd)
    explicit_study_area = None
    if "plangebied" in rd:
        valid_plan = rd["plangebied"].loc[
            rd["plangebied"].geometry.notna()
            & ~rd["plangebied"].geometry.is_empty
        ].copy()
        explicit_study_area = unary_union(valid_plan.geometry.tolist()).buffer(0)
        if explicit_study_area.is_empty:
            raise RuntimeError("Het opgegeven plangebied is leeg of ongeldig")
        outside_points = sum(
            not explicit_study_area.buffer(0.05).covers(geometry)
            for geometry in connections_rd.geometry
        )
        if outside_points:
            raise RuntimeError(
                f"{outside_points} aansluiting(en) liggen buiten het plangebied"
            )
        cables_rd = cables_rd.copy()
        if not allow_external_routes:
            cables_rd.geometry = cables_rd.geometry.intersection(explicit_study_area)
        cables_rd = cables_rd.loc[~cables_rd.geometry.is_empty].copy()
        if cables_rd.empty:
            raise RuntimeError("Binnen het plangebied liggen geen bruikbare sleuven")

    previous_assignment_values = connections_rd["Cluster"].astype(str).str.strip()
    if refresh_all_routes:
        if stations_rd.empty:
            raise RuntimeError("Stationslaag bevat geen stations")
        selected_mask = np.zeros(len(connections_rd), dtype=bool)
        old_clusters = []
        target_cluster = str(stations_rd.iloc[0]["Cluster"]).strip()
        remove_source_clusters = False
        log(
            "Alle clusterroutes volledig verversen; bestaande "
            "aansluitingstoewijzingen blijven ongewijzigd."
        )
    else:
        selected_source_fids = {int(value) for value in selected_source_fids}
        selected_mask = connections_rd["__src_fid"].astype(int).isin(
            selected_source_fids
        )
        if not selected_mask.any():
            raise RuntimeError("Geen geselecteerde aansluitingen in de invoer gevonden")
        target_rows = stations_rd[
            stations_rd["__src_fid"].astype(int) == int(target_station_source_fid)
        ]
        if len(target_rows) != 1:
            raise RuntimeError(
                "Het geselecteerde doelstation kon niet uniek worden gevonden"
            )
        target_cluster = str(target_rows.iloc[0]["Cluster"]).strip()
        if not target_cluster:
            raise RuntimeError("Het doelstation heeft geen geldige Cluster-waarde")
        old_clusters = sorted(
            {
                str(value)
                for value in connections_rd.loc[selected_mask, "Cluster"]
                if str(value) != target_cluster
            }
        )
        if not old_clusters:
            raise RuntimeError(
                f"Alle geselecteerde aansluitingen horen al bij {target_cluster}"
            )
        if remove_source_clusters:
            # One selected connection is enough to identify a source cluster.
            selected_mask = previous_assignment_values.isin(old_clusters)
            if not selected_mask.any():
                raise RuntimeError(
                    "De te verwijderen broncluster bevat geen aansluitingen"
                )
        connections_rd.loc[selected_mask, "Cluster"] = target_cluster

    if remove_source_clusters:
        source_cluster_set = set(old_clusters)
        stations_rd = stations_rd.loc[
            ~stations_rd["Cluster"].astype(str).str.strip().isin(source_cluster_set)
        ].copy()
        areas_rd = areas_rd.loc[
            ~areas_rd["Cluster"].astype(str).str.strip().isin(source_cluster_set)
        ].copy()
        routes_rd = routes_rd.loc[
            ~routes_rd["Cluster"].astype(str).str.strip().isin(source_cluster_set)
        ].copy()
        log(
            "Hele broncluster(s) samenvoegen en verwijderen: "
            + ", ".join(old_clusters)
            + f" -> {target_cluster}."
        )

    stations_rd = _sort_station_records(stations_rd)
    station_sequence = np.arange(1, len(stations_rd) + 1, dtype=int)
    stations_rd["Volgnummer"] = station_sequence
    station_names = stations_rd["Cluster"].astype(str).str.strip().tolist()
    if len(set(station_names)) != len(station_names):
        raise RuntimeError("Stationslaag bevat dubbele Cluster-waarden")
    station_index = {name: index for index, name in enumerate(station_names)}
    selected_refresh_clusters = {
        str(name).strip()
        for name in (refresh_cluster_names or set())
        if str(name).strip()
    }
    if refresh_all_routes and selected_refresh_clusters:
        unknown_refresh_clusters = sorted(
            selected_refresh_clusters.difference(station_index)
        )
        if unknown_refresh_clusters:
            raise RuntimeError(
                "Geselecteerde route(s) horen niet bij een bestaand station: "
                + ", ".join(unknown_refresh_clusters)
            )
        refresh_station_indices = {
            station_index[name] for name in selected_refresh_clusters
        }
        log(
            "Alleen geselecteerde clusterroutes verversen: "
            + ", ".join(
                name for name in station_names if name in selected_refresh_clusters
            )
            + "."
        )
    else:
        refresh_station_indices = None

    def align_cluster_frame(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
        if frame["Cluster"].astype(str).duplicated().any():
            raise RuntimeError("Een resultaatlaag bevat dubbele Cluster-waarden")
        indexed = frame.copy()
        indexed["Cluster"] = indexed["Cluster"].astype(str).str.strip()
        indexed = indexed.set_index("Cluster", drop=False)
        missing = [name for name in station_names if name not in indexed.index]
        if missing:
            raise RuntimeError(
                "Resultaatlaag mist clusters: " + ", ".join(missing)
            )
        return indexed.loc[station_names].reset_index(drop=True)

    areas_rd = align_cluster_frame(areas_rd)
    routes_rd = align_cluster_frame(routes_rd)
    areas_rd["Volgnummer"] = station_sequence
    routes_rd["Volgnummer"] = station_sequence
    assignment_values = connections_rd["Cluster"].astype(str).str.strip()
    unknown_clusters = sorted(set(assignment_values).difference(station_index))
    if unknown_clusters:
        raise RuntimeError(
            "Aansluitingen verwijzen naar ontbrekende stations: "
            + ", ".join(unknown_clusters)
        )
    point_assignment = np.asarray(
        [station_index[value] for value in assignment_values], dtype=int
    )
    previous_assignment = np.asarray(
        [station_index.get(value, -1) for value in previous_assignment_values],
        dtype=int,
    )
    station_count = len(stations_rd)

    loads = pd.to_numeric(connections_rd["Ontwerp_A"], errors="coerce").to_numpy(
        dtype=float
    )
    station_kva = pd.to_numeric(stations_rd["KVA"], errors="coerce").to_numpy(
        dtype=float
    )
    if not np.isfinite(loads).all() or np.any(loads < 0.0):
        raise RuntimeError("Ontwerp_A bevat lege, ongeldige of negatieve waarden")
    if not np.isfinite(station_kva).all() or np.any(station_kva <= 0.0):
        raise RuntimeError("KVA bevat lege, ongeldige of niet-positieve waarden")
    capacities = station_kva / 0.23 / 3.0
    cluster_loads = np.bincount(
        point_assignment, weights=loads, minlength=station_count
    )
    overload = np.flatnonzero(cluster_loads > capacities + 1e-6)
    if check_station_capacity and len(overload):
        details = ", ".join(
            f"{station_names[index]}: {cluster_loads[index]:.1f} / "
            f"{capacities[index]:.1f} A"
            for index in overload
        )
        raise RuntimeError(
            "Handmatige verplaatsing overschrijdt de stationcapaciteit: " + details
        )

    if float(node_tolerance_m) > 1e-9:
        log("Kabelnet opnieuw knippen en noden...")
        noded_cables = node_cable_network(
            cables_rd,
            connections_rd,
            stations_rd,
            node_tolerance_m,
        )
    else:
        # The wizard passes its persisted 'Sleuven geknipt/genood' layer and
        # neither point nor station geometry moves during a manual reassignment.
        # Re-running unary_union over thousands of already noded pieces cost
        # roughly half a minute without changing the graph.
        log("Bestaand geknipt/genood kabelnet rechtstreeks hergebruiken...")
        noded_cables = cables_rd.copy()
    graph = build_network(noded_cables)
    node_list = list(graph.nodes)
    if not node_list:
        raise RuntimeError("Het sleuvennet bevat geen bereikbare netwerkknooppunten")
    node_tree = cKDTree(np.asarray(node_list, dtype=float))
    point_xy = np.asarray(
        [[geometry.x, geometry.y] for geometry in connections_rd.geometry],
        dtype=float,
    )
    station_xy = np.asarray(
        [[geometry.x, geometry.y] for geometry in stations_rd.geometry],
        dtype=float,
    )
    point_nodes, point_snap_m, point_node_indices = snap_xy(
        point_xy, node_list, node_tree
    )
    station_nodes, station_snap_m, station_node_indices = snap_xy(
        station_xy, node_list, node_tree
    )

    log(
        "Alle kortste clusterroutes opnieuw berekenen..."
        if refresh_all_routes
        else "Kabelroutes voor de aangepaste clusters berekenen..."
    )
    used_forced_direct_routes = False
    preserved_route_indices: set[int] = set()
    previous_route_m = pd.to_numeric(
        connections_rd.get("Route_m", pd.Series(np.zeros(len(connections_rd)))),
        errors="coerce",
    ).fillna(0.0).to_numpy(dtype=float)
    try:
        if preserve_all_routes:
            route_geometries = list(routes_rd.geometry)
            route_lengths = pd.to_numeric(routes_rd["Route_km"], errors="raise").to_numpy(float) * 1000.0
            point_route_m = previous_route_m.copy()
        elif refresh_all_routes:
            route_geometries, route_lengths, point_route_m = (
                build_refreshed_fixed_routes(
                    graph,
                    station_nodes,
                    point_nodes,
                    point_assignment,
                    list(routes_rd.geometry),
                    station_names,
                    block_other_cluster_routes=block_other_cluster_routes,
                    check_shared_routes_and_branches=(
                        check_shared_routes_and_branches
                    ),
                    refresh_station_indices=refresh_station_indices,
                    previous_point_route_distance=previous_route_m,
                    preserved_station_indices=preserved_route_indices,
                    relocated_station_indices={
                        station_index[name]
                        for name in (relocated_station_names or set())
                        if name in station_index
                    },
                )
            )
        else:
            route_geometries, route_lengths, point_route_m = (
                build_guided_manual_routes(
                    graph,
                    station_nodes,
                    point_nodes,
                    point_assignment,
                    previous_assignment,
                    station_index[target_cluster],
                    list(routes_rd.geometry),
                    station_names,
                    block_other_cluster_routes=block_other_cluster_routes,
                    check_shared_routes_and_branches=(
                        check_shared_routes_and_branches
                    ),
                    previous_point_route_distance=previous_route_m,
                    preserved_station_indices=preserved_route_indices,
                )
            )
    except RuntimeError as exc:
        if force_assignment and not refresh_all_routes:
            used_forced_direct_routes = True
            log(
                "ALLES TOESTAAN: geen volledige kabelroute mogelijk; directe "
                "correctieroute(s) naar het doelstation worden gebruikt."
            )
            existing_route_m = pd.to_numeric(
                connections_rd.get("Route_m", pd.Series(np.zeros(len(connections_rd)))),
                errors="coerce",
            ).fillna(0.0).to_numpy(dtype=float)
            route_geometries = list(routes_rd.geometry)
            route_lengths = np.zeros(station_count, dtype=float)
            point_route_m = existing_route_m.copy()
            for current_station_index in range(station_count):
                member_indices = np.flatnonzero(
                    point_assignment == current_station_index
                )
                added_lines = []
                for point_index in member_indices:
                    if previous_assignment[point_index] == current_station_index:
                        continue
                    direct_line = LineString(
                        [
                            station_nodes[current_station_index],
                            point_nodes[int(point_index)],
                        ]
                    )
                    added_lines.append(direct_line)
                    point_route_m[int(point_index)] = float(direct_line.length)
                route_geometries[current_station_index] = merge_linework(
                    [route_geometries[current_station_index], *added_lines]
                )
                route_lengths[current_station_index] = float(
                    route_geometries[current_station_index].length
                )
        else:
            active_route_checks = []
            if block_other_cluster_routes:
                active_route_checks.append(
                    "de controle op routes door/over andere clusters is actief"
                )
            if check_shared_routes_and_branches:
                active_route_checks.append(
                    "de controle op gedeelde routes en onvolledige vertakkingen is actief"
                )
            check_hint = (
                " " + "; ".join(active_route_checks).capitalize() + "."
                if active_route_checks
                else ""
            )
            raise RuntimeError(
                "De handmatige verplaatsing kan geen geldige kabelroute opbouwen."
                + check_hint
                + " "
                f"Technische melding: {exc}"
            ) from exc

    too_long = np.flatnonzero(point_route_m > float(max_route_m) + 1e-6)
    if check_max_route and len(too_long):
        longest = float(point_route_m[too_long].max())
        raise RuntimeError(
            f"{len(too_long)} aansluiting(en) komen na de verplaatsing boven "
            f"{max_route_m:.1f} m uit; langste route is {longest:.1f} m."
        )

    study_area = (
        explicit_study_area
        if explicit_study_area is not None
        else unary_union(list(areas_rd.geometry)).buffer(0)
    )
    if defer_area_rebuild:
        cluster_polygons = list(areas_rd.geometry)
    else:
        log("Aaneengesloten clustergebieden opnieuw opbouwen...")
        cluster_polygons, _ = make_cable_based_cluster_polygons(
            route_geometries,
            point_xy,
            np.asarray(point_nodes, dtype=float),
            point_assignment,
            station_xy,
            np.asarray(station_nodes, dtype=float),
            station_count,
            study_area_override=study_area,
            allow_external_routes=allow_external_routes,
        )
        disconnected = [
            station_names[index]
            for index, polygon in enumerate(cluster_polygons)
            if invalid_disconnected_area(polygon, route_geometries[index], study_area, allow_external_routes)
        ]
        if check_shared_routes_and_branches and disconnected:
            raise RuntimeError(
                "De handmatige herberekening maakt exclaves in: "
                + ", ".join(disconnected)
            )
        outside_area = sum(
            float(polygon.difference(study_area.buffer(0.01)).area)
            for polygon in cluster_polygons
        )

        if outside_area > 0.01:
            raise RuntimeError(
                f"Clustergebieden vallen {outside_area:.2f} m² buiten het plangebied"
            )

    point_counts = np.bincount(point_assignment, minlength=station_count)
    max_route = np.asarray(
        [
            float(point_route_m[point_assignment == index].max())
            if np.any(point_assignment == index)
            else 0.0
            for index in range(station_count)
        ]
    )
    mean_route = np.asarray(
        [
            float(point_route_m[point_assignment == index].mean())
            if np.any(point_assignment == index)
            else 0.0
            for index in range(station_count)
        ]
    )
    utilization = np.divide(
        cluster_loads * 100.0,
        capacities,
        out=np.zeros(station_count, dtype=float),
        where=capacities > 0.0,
    )
    station_types = stations_rd["Type"].astype(str).tolist()

    connections_rd["Stat_type"] = [
        station_types[index] for index in point_assignment
    ]
    connections_rd["Stat_KVA"] = station_kva[point_assignment]
    connections_rd["Max_A"] = capacities[point_assignment]
    connections_rd["Clust_A"] = cluster_loads[point_assignment]
    connections_rd["Benut_pct"] = utilization[point_assignment]
    connections_rd["Route_m"] = point_route_m
    connections_rd["Snap_m"] = point_snap_m

    common_values = {
        "Volgnummer": station_sequence,
        "Type": station_types,
        "KVA": station_kva,
        "Max_A": capacities,
        "Belast_A": cluster_loads,
        "Benut_pct": utilization,
        "Aantal": point_counts,
        "Gem_route": mean_route,
        "Max_route": max_route,
        "Route_km": route_lengths / 1000.0,
    }
    for field, values in common_values.items():
        stations_rd[field] = values

    for field, values in common_values.items():
        areas_rd[field] = values
        routes_rd[field] = values
    areas_rd.geometry = gpd.GeoSeries(cluster_polygons, crs=CRS_RD)
    routes_rd.geometry = gpd.GeoSeries(route_geometries, crs=CRS_RD)

    result_frames = {
        "aansluitingen": connections_rd.to_crs(original_crs["aansluitingen"]),
        "stations": stations_rd.to_crs(original_crs["stations"]),
        "gebieden": areas_rd.to_crs(original_crs["gebieden"]),
        "routes": routes_rd.to_crs(original_crs["routes"]),
        "sleuven": noded_cables.to_crs(original_crs["sleuven"]),
    }
    summary = {
        "moved_count": int(selected_mask.sum()),
        "target_cluster": target_cluster,
        "old_clusters": old_clusters,
        "removed_source_clusters": old_clusters if remove_source_clusters else [],
        "used_forced_direct_routes": bool(used_forced_direct_routes),
        "maximum_route_m": float(point_route_m.max()) if len(point_route_m) else 0.0,
        "target_load_a": float(cluster_loads[station_index[target_cluster]]),
        "target_capacity_a": float(capacities[station_index[target_cluster]]),
        "safety_checks": {
            "check_station_capacity": bool(check_station_capacity),
            "check_max_route": bool(check_max_route),
            "block_other_cluster_routes": bool(block_other_cluster_routes),
            "check_shared_routes_and_branches": bool(
                check_shared_routes_and_branches
            ),
        },
        "routes_refreshed": bool(refresh_all_routes),
        "refreshed_clusters": (
            [name for name in station_names if name in selected_refresh_clusters]
            if refresh_all_routes and selected_refresh_clusters
            else station_names if refresh_all_routes else []
        ),
        "preserved_route_clusters": [
            station_names[index] for index in sorted(preserved_route_indices)
        ],
    }
    return (
        result_frames["aansluitingen"],
        result_frames["stations"],
        result_frames["gebieden"],
        result_frames["routes"],
        result_frames["sleuven"],
        summary,
    )


def write_manual_cluster_snapshot(
    path: Path,
    connections: gpd.GeoDataFrame,
    stations: gpd.GeoDataFrame,
    areas: gpd.GeoDataFrame,
    routes: gpd.GeoDataFrame,
    cables: gpd.GeoDataFrame,
    plan_layer: gpd.GeoDataFrame | None = None,
) -> Path:
    """Write a recoverable multi-layer snapshot for a manual correction."""
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.unlink(missing_ok=True)
    layers = [
        ("aansluitingen_geclusterd", connections),
        ("stations_ontwerp", stations),
        ("clustergebieden", areas),
        ("cluster_kabelroutes", routes),
        ("sleuven_genood", cables),
    ]
    if plan_layer is not None and not plan_layer.empty:
        layers.append(("plangebied", plan_layer))
    for layer_name, frame in layers:
        snapshot = frame.copy()
        if "__src_fid" in snapshot.columns:
            snapshot = snapshot.rename(columns={"__src_fid": "Bron_FID"})
        snapshot.to_file(path, layer=layer_name, driver="GPKG")
    return path


def remove_shapefile(path: Path) -> None:
    for suffix in (".shp", ".shx", ".dbf", ".prj", ".cpg", ".qix"):
        path.with_suffix(suffix).unlink(missing_ok=True)


def write_layers(
    connections: gpd.GeoDataFrame,
    stations_design: gpd.GeoDataFrame,
    areas: gpd.GeoDataFrame,
    routes: gpd.GeoDataFrame,
    noded_cables: gpd.GeoDataFrame,
    plan_layer: gpd.GeoDataFrame | None = None,
    original_ls_cables: gpd.GeoDataFrame | None = None,
    original_connection_cables: gpd.GeoDataFrame | None = None,
    flat_cabinets: gpd.GeoDataFrame | None = None,
    apartment_trenches: gpd.GeoDataFrame | None = None,
    apartment_buildings: gpd.GeoDataFrame | None = None,
    station_enclosures: gpd.GeoDataFrame | None = None,
    distribution_cabinets: gpd.GeoDataFrame | None = None,
    equipment_links: gpd.GeoDataFrame | None = None,
    missing_connection_links: gpd.GeoDataFrame | None = None,
) -> Path:
    gpkg = OUT / "clustering_ontwerp.gpkg"
    gpkg.unlink(missing_ok=True)
    connections.to_file(gpkg, layer="aansluitingen_geclusterd", driver="GPKG")
    stations_design.to_file(gpkg, layer="stations_ontwerp", driver="GPKG")
    areas.to_file(gpkg, layer="clustergebieden", driver="GPKG")
    routes.to_file(gpkg, layer="cluster_kabelroutes", driver="GPKG")
    noded_cables.to_file(gpkg, layer="sleuven_genood", driver="GPKG")
    if plan_layer is not None and not plan_layer.empty:
        plan_layer.to_file(gpkg, layer="plangebied", driver="GPKG")
    if original_ls_cables is not None and not original_ls_cables.empty:
        original_ls_cables.to_file(
            gpkg, layer="originele_ls_kabels", driver="GPKG"
        )
    if (
        original_connection_cables is not None
        and not original_connection_cables.empty
    ):
        original_connection_cables.to_file(
            gpkg, layer="originele_aansluitkabels", driver="GPKG"
        )
    if flat_cabinets is not None and not flat_cabinets.empty:
        flat_cabinets.to_file(gpkg, layer="flatkasten", driver="GPKG")
    if apartment_trenches is not None and not apartment_trenches.empty:
        apartment_trenches.to_file(
            gpkg, layer="inpandige_appartementssleuven", driver="GPKG"
        )
    if apartment_buildings is not None and not apartment_buildings.empty:
        apartment_buildings.to_file(
            gpkg, layer="bag_panden_appartementen", driver="GPKG"
        )
    if station_enclosures is not None and not station_enclosures.empty:
        station_enclosures.to_file(
            gpkg, layer="stationomtrekken", driver="GPKG"
        )
    if distribution_cabinets is not None and not distribution_cabinets.empty:
        distribution_cabinets.to_file(
            gpkg, layer="verdeelkasten", driver="GPKG"
        )
    if equipment_links is not None and not equipment_links.empty:
        equipment_links.to_file(
            gpkg, layer="interne_netkoppelingen", driver="GPKG"
        )
    if missing_connection_links is not None and not missing_connection_links.empty:
        missing_connection_links.to_file(
            gpkg, layer="aangevulde_aansluitkabels", driver="GPKG"
        )

    if not WRITE_SHAPEFILES:
        return gpkg

    shp_dir = OUT / "shapefiles"
    shp_dir.mkdir(parents=True, exist_ok=True)
    layers = {
        "aansluitingen_geclusterd.shp": connections,
        "stations_ontwerp.shp": stations_design,
        "clustergebieden.shp": areas,
        "cluster_kabelroutes.shp": routes,
        "sleuven_genood.shp": noded_cables,
    }
    if plan_layer is not None and not plan_layer.empty:
        layers["plangebied.shp"] = plan_layer
    if original_ls_cables is not None and not original_ls_cables.empty:
        layers["originele_ls_kabels.shp"] = original_ls_cables
    if (
        original_connection_cables is not None
        and not original_connection_cables.empty
    ):
        layers["originele_aansluitkabels.shp"] = original_connection_cables
    if flat_cabinets is not None and not flat_cabinets.empty:
        layers["flatkasten.shp"] = flat_cabinets
    if apartment_trenches is not None and not apartment_trenches.empty:
        layers["inpandige_appartementssleuven.shp"] = apartment_trenches
    if apartment_buildings is not None and not apartment_buildings.empty:
        layers["bag_panden_appartementen.shp"] = apartment_buildings
    if station_enclosures is not None and not station_enclosures.empty:
        layers["stationomtrekken.shp"] = station_enclosures
    if distribution_cabinets is not None and not distribution_cabinets.empty:
        layers["verdeelkasten.shp"] = distribution_cabinets
    if equipment_links is not None and not equipment_links.empty:
        layers["interne_netkoppelingen.shp"] = equipment_links
    if missing_connection_links is not None and not missing_connection_links.empty:
        layers["aangevulde_aansluitkabels.shp"] = missing_connection_links
    for filename, layer in layers.items():
        target = shp_dir / filename
        remove_shapefile(target)
        layer.to_file(target, driver="ESRI Shapefile", encoding="UTF-8")
    return gpkg


def osm_tile_background(
    bounds_3857: tuple[float, float, float, float],
    maximum_tiles: int = OSM_MAXIMUM_TILES,
) -> tuple[np.ndarray, tuple[float, float, float, float], int] | None:
    """Download/cache an OSM tile mosaic covering Web Mercator bounds."""
    try:
        from PIL import Image

        origin = 20037508.342789244
        world = origin * 2.0
        minx, miny, maxx, maxy = bounds_3857

        def tile_range(zoom: int) -> tuple[int, int, int, int]:
            count = 2**zoom
            x0 = max(0, min(count - 1, int(math.floor((minx + origin) / world * count))))
            x1 = max(0, min(count - 1, int(math.floor((maxx + origin) / world * count))))
            y0 = max(0, min(count - 1, int(math.floor((origin - maxy) / world * count))))
            y1 = max(0, min(count - 1, int(math.floor((origin - miny) / world * count))))
            return x0, x1, y0, y1

        zoom = OSM_MAX_ZOOM
        while zoom > 8:
            x0, x1, y0, y1 = tile_range(zoom)
            if (x1 - x0 + 1) * (y1 - y0 + 1) <= maximum_tiles:
                break
            zoom -= 1
        x0, x1, y0, y1 = tile_range(zoom)
        mosaic = Image.new(
            "RGB",
            ((x1 - x0 + 1) * 256, (y1 - y0 + 1) * 256),
            color=(238, 238, 238),
        )
        cache = Path(tempfile.gettempdir()) / "laagspanning_clustering_osm_tiles"
        missing = 0
        tile_specs = [
            (tile_x, tile_y)
            for tile_y in range(y0, y1 + 1)
            for tile_x in range(x0, x1 + 1)
        ]

        def load_tile(spec):
            tile_x, tile_y = spec
            tile_path = cache / str(zoom) / str(tile_x) / f"{tile_y}.png"
            try:
                if tile_path.exists():
                    data = tile_path.read_bytes()
                else:
                    url = (
                        f"https://tile.openstreetmap.org/{zoom}/"
                        f"{tile_x}/{tile_y}.png"
                    )
                    request = Request(
                        url,
                        headers={"User-Agent": "LaagspanningClustering-QGIS/1.0"},
                    )
                    with urlopen(request, timeout=8) as response:
                        data = response.read()
                    tile_path.parent.mkdir(parents=True, exist_ok=True)
                    tile_path.write_bytes(data)
                return tile_x, tile_y, data
            except Exception:
                return tile_x, tile_y, None

        # Tile decoding/pasting remains deterministic and single-threaded;
        # independent cached reads/downloads may use a small worker pool.
        tile_workers = min(max(1, CPU_THREADS), len(tile_specs), 8)
        with ThreadPoolExecutor(max_workers=tile_workers) as executor:
            loaded_tiles = list(executor.map(load_tile, tile_specs))
        for tile_x, tile_y, data in loaded_tiles:
            if data is None:
                missing += 1
                continue
            try:
                with Image.open(io.BytesIO(data)) as tile:
                    mosaic.paste(
                        tile.convert("RGB"),
                        ((tile_x - x0) * 256, (tile_y - y0) * 256),
                    )
            except Exception:
                missing += 1

        if missing == (x1 - x0 + 1) * (y1 - y0 + 1):
            log("Waarschuwing: geen OpenStreetMap-tegels konden worden geladen.")
            return None
        if missing:
            log(f"Waarschuwing: {missing} OpenStreetMap-tegels ontbraken.")

        count = 2**zoom
        left = x0 / count * world - origin
        right = (x1 + 1) / count * world - origin
        top = origin - y0 / count * world
        bottom = origin - (y1 + 1) / count * world
        return np.asarray(mosaic), (left, right, bottom, top), zoom
    except Exception as exc:
        log(f"Waarschuwing: OpenStreetMap-achtergrond kon niet worden gemaakt: {exc}")
        return None


def _format_nl_number(value: float, decimals: int = 1) -> str:
    """Format a number with a Dutch decimal comma."""
    return f"{float(value):.{decimals}f}".replace(".", ",")


def _station_sort_key(row: pd.Series) -> tuple:
    """Sort existing stations first and apply natural numeric station order."""
    station_type = str(row.get("Type", "")).strip().casefold()
    type_rank = (
        0 if station_type == "bestaand" else 1 if station_type == "nieuw" else 2
    )
    cluster = str(row.get("Cluster", "")).strip()
    decimal_match = re.fullmatch(
        r"\D*(\d+(?:[.,]\d+)?)\D*",
        cluster,
    )
    decimal_number = (
        float(decimal_match.group(1).replace(",", "."))
        if decimal_match
        else math.inf
    )
    numbers = tuple(int(value) for value in re.findall(r"\d+", cluster))
    return type_rank, decimal_number, numbers, cluster.casefold()


def _sort_station_records(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Return station-related records in stable natural order."""
    order = sorted(
        range(len(frame)),
        key=lambda index: _station_sort_key(frame.iloc[index]),
    )
    return frame.iloc[order].reset_index(drop=True)


def _plot_connection_currents(axis, connections: gpd.GeoDataFrame) -> None:
    """Place the design current, with one decimal, inside every connection marker."""
    if "Ontwerp_A" not in connections.columns:
        return
    for geometry, raw_current in zip(connections.geometry, connections["Ontwerp_A"]):
        try:
            current = float(raw_current)
        except (TypeError, ValueError):
            continue
        if geometry is None or geometry.is_empty or not np.isfinite(current):
            continue
        axis.annotate(
            _format_nl_number(current),
            xy=(geometry.x, geometry.y),
            xytext=(0.0, -0.25),
            textcoords="offset points",
            ha="center",
            va="center",
            fontsize=2.15,
            fontweight="bold",
            color="#111111",
            zorder=5,
            clip_on=True,
            path_effects=[
                patheffects.withStroke(linewidth=0.45, foreground="white")
            ],
        )


def _add_station_statistics(
    legend_axis,
    stations_design: gpd.GeoDataFrame,
    station_colors: dict[int, tuple[float, float, float]],
) -> None:
    """Add per-station capacity statistics and a calculated total to the side panel."""
    rows: list[list[str]] = []
    total_connections = 0
    total_load = 0.0
    total_capacity = 0.0
    total_max_current = 0.0

    def number(row: pd.Series, field: str) -> float:
        try:
            value = float(row.get(field, 0.0))
            return value if np.isfinite(value) else 0.0
        except (TypeError, ValueError):
            return 0.0

    for _, row in stations_design.iterrows():
        connection_count = int(round(number(row, "Aantal")))
        load = number(row, "Belast_A")
        capacity = number(row, "KVA")
        utilization = number(row, "Benut_pct")
        max_current = number(row, "Max_A")
        total_connections += connection_count
        total_load += load
        total_capacity += capacity
        total_max_current += max_current
        capacity_text = (
            f"{capacity:.0f}"
            if math.isclose(capacity, round(capacity), abs_tol=1e-9)
            else _format_nl_number(capacity)
        )
        rows.append(
            [
                str(row.get("Cluster", "")),
                str(connection_count),
                _format_nl_number(load),
                _format_nl_number(max_current),
                capacity_text,
                _format_nl_number(utilization),
            ]
        )

    total_utilization = (
        100.0 * total_load / total_max_current if total_max_current > 0.0 else 0.0
    )
    total_capacity_text = (
        f"{total_capacity:.0f}"
        if math.isclose(total_capacity, round(total_capacity), abs_tol=1e-9)
        else _format_nl_number(total_capacity)
    )
    rows.append(
        [
            "Totaal",
            str(total_connections),
            _format_nl_number(total_load),
            _format_nl_number(total_max_current),
            total_capacity_text,
            _format_nl_number(total_utilization),
        ]
    )

    row_count = len(rows) + 1
    table_height = min(0.44, max(0.31, row_count * 0.026))
    table_top = 0.73
    table_bottom = table_top - table_height
    font_size = max(3.2, min(5.7, 140.0 / max(row_count, 1)))
    legend_axis.text(
        0.5,
        0.775,
        "Stationstatistieken",
        transform=legend_axis.transAxes,
        ha="center",
        va="top",
        fontsize=10,
        fontweight="bold",
        color="#222222",
    )
    table = legend_axis.table(
        cellText=rows,
        colLabels=[
            "Station",
            "Aansl.",
            "Belast.\n(A)",
            "Max.\n(A)",
            "Cap.\n(kVA)",
            "Benut.\n(%)",
        ],
        cellLoc="right",
        colLoc="center",
        colWidths=[0.22, 0.12, 0.18, 0.16, 0.16, 0.16],
        bbox=[0.02, table_bottom, 0.96, table_height],
    )
    table.auto_set_font_size(False)
    table.set_fontsize(font_size)
    last_row = len(rows)
    for (row_index, column_index), cell in table.get_celld().items():
        cell.set_edgecolor("#b8b8b8")
        cell.set_linewidth(0.35)
        if row_index == 0:
            cell.set_facecolor("#3c4a57")
            cell.get_text().set_color("white")
            cell.get_text().set_fontweight("bold")
        elif row_index == last_row:
            cell.set_facecolor("#dce5eb")
            cell.get_text().set_fontweight("bold")
        elif row_index % 2 == 0:
            cell.set_facecolor("#f2f4f5")
        else:
            cell.set_facecolor("white")
        if column_index == 0:
            cell.get_text().set_ha("left")
            if 1 <= row_index <= len(stations_design):
                station_color = station_colors[row_index - 1]
                cell.set_facecolor(station_color)
                red, green, blue = station_color[:3]
                luminance = 0.2126 * red + 0.7152 * green + 0.0722 * blue
                cell.get_text().set_color("white" if luminance < 0.48 else "black")
                cell.get_text().set_fontweight("bold")
    legend_axis.text(
        0.5,
        table_bottom - 0.018,
        "Belasting = som ontwerpstroom.\n"
        "Max. A = KVA / 0,23 / 3.  Benutting = belasting / Max. A.",
        transform=legend_axis.transAxes,
        ha="center",
        va="top",
        fontsize=5.5,
        color="#555555",
        linespacing=1.25,
    )


def _add_coordinate_zebra(
    axis,
    view_bounds: tuple[float, float, float, float],
) -> None:
    """Draw one functional RD grid as zebra frame, ticks, labels and crosses."""
    minx, miny, maxx, maxy = view_bounds
    to_rd = Transformer.from_crs("EPSG:3857", CRS_RD, always_xy=True)
    from_rd = Transformer.from_crs(CRS_RD, "EPSG:3857", always_xy=True)
    center_map_x = (minx + maxx) / 2.0
    center_map_y = (miny + maxy) / 2.0
    center_rd_x, center_rd_y = to_rd.transform(center_map_x, center_map_y)

    rd_corners = [
        to_rd.transform(map_x, map_y)
        for map_x in (minx, maxx)
        for map_y in (miny, maxy)
    ]
    rd_min_x = min(point[0] for point in rd_corners)
    rd_max_x = max(point[0] for point in rd_corners)
    rd_min_y = min(point[1] for point in rd_corners)
    rd_max_y = max(point[1] for point in rd_corners)

    def fitted_grid_values(
        minimum: float,
        maximum: float,
        fraction_for_value,
    ) -> list[tuple[float, float]]:
        """Choose 2-5 round grid values, with room for corner annotations."""
        span = maximum - minimum
        if not math.isfinite(span) or span <= 0:
            return []
        magnitude = 10.0 ** math.floor(math.log10(span / 4.0))
        intervals = sorted(
            {
                multiplier * magnitude * (10.0**power)
                for power in (-2, -1, 0, 1, 2)
                for multiplier in (1.0, 2.0, 2.5, 5.0, 10.0)
            }
        )
        candidates: list[tuple[tuple[float, float], list[tuple[float, float]]]] = []
        for interval in intervals:
            first = math.ceil(minimum / interval - 1e-10) * interval
            last = math.floor(maximum / interval + 1e-10) * interval
            count = max(0, int(round((last - first) / interval)) + 1)
            values: list[tuple[float, float]] = []
            for index in range(count):
                value = first + index * interval
                fraction = float(fraction_for_value(value))
                if 0.055 <= fraction <= 0.945:
                    values.append((fraction, value))
            if 2 <= len(values) <= 5:
                candidates.append(
                    (
                        (
                            abs(len(values) - 4),
                            abs(math.log10(interval / (span / 4.0))),
                        ),
                        values,
                    )
                )
        if candidates:
            return min(candidates, key=lambda candidate: candidate[0])[1]
        # Very small or unusual extents still receive two meaningful values.
        return [(0.25, minimum + 0.25 * span), (0.75, minimum + 0.75 * span)]

    x_grid = fitted_grid_values(
        rd_min_x,
        rd_max_x,
        lambda rd_x: (
            from_rd.transform(rd_x, center_rd_y)[0] - minx
        )
        / (maxx - minx),
    )
    y_grid = fitted_grid_values(
        rd_min_y,
        rd_max_y,
        lambda rd_y: (
            from_rd.transform(center_rd_x, rd_y)[1] - miny
        )
        / (maxy - miny),
    )
    x_grid.sort()
    y_grid.sort()

    # Every internal zebra transition is one actual, labelled RD grid value.
    thickness = 0.012
    x_boundaries = [0.0, *(fraction for fraction, _ in x_grid), 1.0]
    y_boundaries = [0.0, *(fraction for fraction, _ in y_grid), 1.0]
    for index, (start, end) in enumerate(zip(x_boundaries, x_boundaries[1:])):
        color = "#111111" if index % 2 == 0 else "white"
        for y in (0.0, 1.0 - thickness):
            axis.add_patch(
                Rectangle(
                    (start, y),
                    end - start,
                    thickness,
                    transform=axis.transAxes,
                    facecolor=color,
                    edgecolor="#111111",
                    linewidth=0.45,
                    clip_on=False,
                    zorder=20,
                )
            )
    for index, (start, end) in enumerate(zip(y_boundaries, y_boundaries[1:])):
        color = "#111111" if index % 2 == 0 else "white"
        for x in (0.0, 1.0 - thickness):
            axis.add_patch(
                Rectangle(
                    (x, start),
                    thickness,
                    end - start,
                    transform=axis.transAxes,
                    facecolor=color,
                    edgecolor="#111111",
                    linewidth=0.45,
                    clip_on=False,
                    zorder=20,
                )
            )

    text_box = dict(facecolor="white", alpha=0.82, edgecolor="none", pad=0.5)
    axis_bounds = axis.get_window_extent()
    side_tick_length = 0.010
    # Axes fractions have different physical sizes horizontally and vertically.
    # Convert the top/bottom length so all four sides print equally long.
    top_bottom_tick_length = side_tick_length * (
        axis_bounds.width / axis_bounds.height
    )
    coordinate_mark_color = "#4f4f4f"
    for fraction, rd_x in x_grid:
        # A butt cap begins exactly at the zebra edge without protruding into it.
        axis.plot(
            [fraction, fraction],
            [thickness, thickness + top_bottom_tick_length],
            transform=axis.transAxes,
            color=coordinate_mark_color,
            linewidth=1.25,
            solid_capstyle="butt",
            clip_on=False,
            zorder=19,
        )
        axis.plot(
            [fraction, fraction],
            [1.0 - thickness - top_bottom_tick_length, 1.0 - thickness],
            transform=axis.transAxes,
            color=coordinate_mark_color,
            linewidth=1.25,
            solid_capstyle="butt",
            clip_on=False,
            zorder=19,
        )
        axis.text(
            fraction,
            -0.014,
            f"X {rd_x:.0f}",
            transform=axis.transAxes,
            ha="center",
            va="top",
            fontsize=5.3,
            fontweight="bold",
            bbox=text_box,
            clip_on=False,
            zorder=21,
        )
        axis.text(
            fraction,
            1.014,
            f"X {rd_x:.0f}",
            transform=axis.transAxes,
            ha="center",
            va="bottom",
            fontsize=5.3,
            fontweight="bold",
            bbox=text_box,
            clip_on=False,
            zorder=21,
        )
    for fraction, rd_y in y_grid:
        axis.plot(
            [thickness, thickness + side_tick_length],
            [fraction, fraction],
            transform=axis.transAxes,
            color=coordinate_mark_color,
            linewidth=1.25,
            solid_capstyle="butt",
            clip_on=False,
            zorder=19,
        )
        axis.plot(
            [1.0 - thickness - side_tick_length, 1.0 - thickness],
            [fraction, fraction],
            transform=axis.transAxes,
            color=coordinate_mark_color,
            linewidth=1.25,
            solid_capstyle="butt",
            clip_on=False,
            zorder=19,
        )
        axis.text(
            -0.014,
            fraction,
            f"Y {rd_y:.0f}",
            transform=axis.transAxes,
            ha="right",
            va="center",
            rotation=90,
            fontsize=5.3,
            fontweight="bold",
            bbox=text_box,
            clip_on=False,
            zorder=21,
        )
        axis.text(
            1.014,
            fraction,
            f"Y {rd_y:.0f}",
            transform=axis.transAxes,
            ha="left",
            va="center",
            rotation=270,
            fontsize=5.3,
            fontweight="bold",
            bbox=text_box,
            clip_on=False,
            zorder=21,
        )

    # Show the intersections of the implied coordinate grid without drawing
    # grid lines across the clusters.
    for x_fraction, _ in x_grid:
        for y_fraction, _ in y_grid:
            axis.plot(
                x_fraction,
                y_fraction,
                marker="+",
                markersize=6.0,
                markeredgewidth=1.15,
                color=coordinate_mark_color,
                linestyle="none",
                transform=axis.transAxes,
                clip_on=True,
                zorder=19,
            )


def _add_north_arrow(
    legend_axis,
    center_y: float,
    legend_left: float,
) -> None:
    """Place a heavy arrow left of, and vertically centred on, the legend."""
    arrow_x = max(0.035, min(0.105, legend_left - 0.075))
    half_height = 0.040
    legend_axis.annotate(
        "",
        xy=(arrow_x, center_y + half_height),
        xytext=(arrow_x, center_y - half_height),
        xycoords=legend_axis.transAxes,
        arrowprops=dict(
            arrowstyle="-|>",
            color="#111111",
            linewidth=3.2,
            mutation_scale=19,
        ),
    )
    legend_axis.text(
        arrow_x,
        center_y + half_height + 0.010,
        "N",
        transform=legend_axis.transAxes,
        ha="center",
        va="bottom",
        fontsize=10.5,
        fontweight="bold",
        color="#111111",
    )


def make_map(
    cables: gpd.GeoDataFrame,
    connections: gpd.GeoDataFrame,
    stations_design: gpd.GeoDataFrame,
    areas: gpd.GeoDataFrame,
    routes: gpd.GeoDataFrame,
    plan_layer: gpd.GeoDataFrame | None = None,
) -> None:
    map_crs = "EPSG:3857"
    # Keep the map, table and colour palette in the same natural order.
    stations_design = _sort_station_records(stations_design)
    areas = _sort_station_records(areas)
    routes = _sort_station_records(routes)
    station_sequence = np.arange(1, len(stations_design) + 1, dtype=int)
    stations_design["Volgnummer"] = station_sequence
    areas["Volgnummer"] = station_sequence
    routes["Volgnummer"] = station_sequence
    cables = cables.to_crs(map_crs)
    connections = connections.to_crs(map_crs)
    stations_design = stations_design.to_crs(map_crs)
    areas = areas.to_crs(map_crs)
    routes = routes.to_crs(map_crs)
    plan_map = (
        plan_layer.to_crs(map_crs)
        if plan_layer is not None and not plan_layer.empty
        else None
    )
    station_count = len(stations_design)
    palette = list(plt.cm.tab20.colors) + list(plt.cm.Set3.colors)
    colors = {i: palette[i % len(palette)] for i in range(station_count)}

    minx, miny, maxx, maxy = connections.total_bounds
    if plan_map is not None:
        plan_minx, plan_miny, plan_maxx, plan_maxy = plan_map.total_bounds
        minx = min(minx, plan_minx)
        miny = min(miny, plan_miny)
        maxx = max(maxx, plan_maxx)
        maxy = max(maxy, plan_maxy)
    if len(routes):
        route_bounds = routes.total_bounds
        if np.isfinite(route_bounds).all():
            minx, miny = min(minx, route_bounds[0]), min(miny, route_bounds[1])
            maxx, maxy = max(maxx, route_bounds[2]), max(maxy, route_bounds[3])
    margin = 100.0
    view_bounds = (minx - margin, miny - margin, maxx + margin, maxy + margin)

    figure, (axis, legend_axis) = plt.subplots(
        1,
        2,
        figsize=(15, 11),
        gridspec_kw={"width_ratios": [5.1, 1.9], "wspace": 0.035},
    )
    legend_axis.axis("off")
    osm = osm_tile_background(view_bounds)
    osm_loaded = osm is not None
    if osm is not None:
        image, extent, zoom = osm
        axis.imshow(image, extent=extent, interpolation="bilinear", zorder=0)
        log(f"OpenStreetMap-achtergrond geladen op zoomniveau {zoom}.")
    cables.plot(ax=axis, color="#c6c6c6", linewidth=0.18, zorder=1)
    for i in range(station_count):
        area = areas.iloc[[i]]
        route = routes.iloc[[i]]
        subset = connections[
            connections["Cluster"] == stations_design.iloc[i]["Cluster"]
        ]
        area.plot(
            ax=axis,
            facecolor=colors[i],
            edgecolor=colors[i],
            alpha=0.36,
            linewidth=0.7,
            zorder=2,
        )
        route.plot(ax=axis, color=colors[i], linewidth=1.05, zorder=3)
        subset.plot(
            ax=axis,
            color=colors[i],
            edgecolor="#222222",
            linewidth=0.18,
            markersize=18.0,
            zorder=4,
        )
        _plot_connection_currents(axis, subset)

    if plan_map is not None:
        plan_map.plot(
            ax=axis,
            facecolor="none",
            edgecolor="#303030",
            linewidth=1.15,
            zorder=6,
        )

    existing = stations_design[stations_design["Type"] == "Bestaand"]
    new = stations_design[stations_design["Type"] == "Nieuw"]
    existing.plot(
        ax=axis,
        marker="s",
        facecolor="#e31a1c",
        edgecolor="black",
        linewidth=0.9,
        markersize=38,
        zorder=7,
    )
    new.plot(
        ax=axis,
        marker="*",
        facecolor="#9ecae1",
        edgecolor="black",
        linewidth=0.7,
        markersize=115,
        zorder=8,
    )
    for _, row in stations_design.iterrows():
        max_current_label = int(round(float(row.get("Max_A", 0.0))))
        load_label = int(round(float(row.get("Belast_A", 0.0))))
        axis.annotate(
            f'{row["Cluster"]}\nMax_A: {max_current_label}\nBelast_A: {load_label}',
            (row.geometry.x, row.geometry.y),
            xytext=(4, 4),
            textcoords="offset points",
            fontsize=5.7,
            fontweight="bold",
            color="black",
            bbox=dict(facecolor="white", alpha=0.65, edgecolor="none", pad=0.4),
            zorder=9,
        )
    axis.set_xlim(view_bounds[0], view_bounds[2])
    axis.set_ylim(view_bounds[1], view_bounds[3])
    axis.set_aspect("equal")
    axis.axis("off")
    figure.subplots_adjust(
        left=0.025,
        right=0.99,
        bottom=0.035,
        top=0.975,
        wspace=0.035,
    )
    # Resolve the final map dimensions before matching tick lengths in pixels.
    figure.canvas.draw()
    _add_coordinate_zebra(axis, view_bounds)
    _add_station_statistics(legend_axis, stations_design, colors)
    legend_handles = [
            Line2D(
                [0],
                [0],
                marker="s",
                color="none",
                markerfacecolor="#e31a1c",
                markeredgecolor="black",
                label="Bestaand station",
            ),
            Line2D(
                [0],
                [0],
                marker="*",
                color="none",
                markerfacecolor="#9ecae1",
                markeredgecolor="black",
                markersize=12,
                label=f"Nieuw station {NEW_KVA:g} kVA",
            ),
            Line2D([0], [0], color="#555555", linewidth=1.2, label="Gebruikte kabelroute"),
            Line2D(
                [0],
                [0],
                marker="o",
                color="none",
                markerfacecolor="#9ecae1",
                markeredgecolor="#222222",
                markersize=5.5,
                label="LS-aansluiting (cijfer = ontwerpstroom A)",
            ),
        ]
    if plan_map is not None:
        legend_handles.append(
            Line2D(
                [0],
                [0],
                color="#303030",
                linewidth=1.4,
                label="Plangebied",
            )
        )
    legend = legend_axis.legend(
        handles=legend_handles,
        title="Legenda",
        loc="lower right",
        bbox_to_anchor=(0.98, 0.075),
        borderaxespad=0.0,
        fontsize=8,
        title_fontsize=9,
        framealpha=0.96,
    )
    if osm_loaded:
        legend_axis.text(
            0.5,
            0.012,
            "(c) OpenStreetMap contributors\nCoordinaten: RD New (EPSG:28992)",
            transform=legend_axis.transAxes,
            ha="center",
            va="bottom",
            fontsize=6.3,
            color="#333333",
            zorder=10,
        )
    # Align against the legend's rendered bounding box, not an estimated y.
    figure.canvas.draw()
    legend_bounds = legend.get_window_extent(
        figure.canvas.get_renderer()
    ).transformed(legend_axis.transAxes.inverted())
    _add_north_arrow(
        legend_axis,
        center_y=(legend_bounds.y0 + legend_bounds.y1) / 2.0,
        legend_left=legend_bounds.x0,
    )
    png_path = OUT / "clustering_overzicht.png"
    pdf_path = OUT / "clustering_overzicht.pdf"
    figure.savefig(png_path, dpi=MAP_OUTPUT_DPI, bbox_inches="tight")
    # Some PDF readers render GeoPandas/Matplotlib transparency groups as black
    # shapes. Embed the verified high-resolution map as RGB instead, which gives
    # identical output in QGIS, Acrobat, Edge and lightweight PDF renderers.
    try:
        from PIL import Image

        with Image.open(png_path) as image:
            image.convert("RGB").save(
                pdf_path,
                "PDF",
                resolution=float(MAP_OUTPUT_DPI),
            )
    except Exception:
        figure.savefig(pdf_path, bbox_inches="tight")
    plt.close(figure)


def make_qgis_project(gpkg: Path) -> Path | None:
    try:
        from qgis.PyQt.QtCore import Qt, QVariant
        from qgis.PyQt.QtGui import QColor, QFont
        from qgis.core import (
            Qgis,
            QgsApplication,
            QgsField,
            QgsCategorizedSymbolRenderer,
            QgsConditionalStyle,
            QgsCoordinateReferenceSystem,
            QgsLayoutFrame,
            QgsLayoutItemAttributeTable,
            QgsLayoutItemLegend,
            QgsLayoutItemMap,
            QgsLayoutItemMapGrid,
            QgsLayoutItemPage,
            QgsLayoutItemLabel,
            QgsLayoutPoint,
            QgsLayoutSize,
            QgsLayoutTableColumn,
            QgsLegendStyle,
            QgsLineSymbol,
            QgsMarkerSymbol,
            QgsPalLayerSettings,
            QgsPrintLayout,
            QgsProject,
            QgsRasterLayer,
            QgsReadWriteContext,
            QgsRectangle,
            QgsRendererCategory,
            QgsSimpleFillSymbolLayer,
            QgsSymbol,
            QgsTextBufferSettings,
            QgsTextFormat,
            QgsVectorLayer,
            QgsVectorLayerSimpleLabeling,
        )
        try:
            from .layout_style_utils import (
                configure_layout_style,
            )
        except ImportError:
            from layout_style_utils import (
                configure_layout_style,
            )

        if QgsApplication.instance() is not None:
            raise RuntimeError(
                "Project- en layoutopbouw moet in het aparte QGIS-projectproces draaien"
            )
        owned_qgis_app = QgsApplication([], False)
        owned_qgis_app.initQgis()
        # The short-lived worker has no user project. QgsPrintLayout is most
        # stable against the singleton project, especially in QGIS 4.x.
        project = QgsProject.instance()
        project.clear()
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:28992"))
        project_path = OUT / "clustering_ontwerp.qgz"
        project.setFileName(str(project_path))
        # Keep the project portable with its sibling GeoPackage. A relative
        # project home continues to work when the whole result folder is moved.
        project.setPresetHomePath(".")
        project.setFilePathStorage(Qgis.FilePathType.Relative)

        layer_specs = [
            ("clustergebieden", "Clustergebieden"),
            ("sleuven_genood", "Sleuven geknipt/genood"),
            ("cluster_kabelroutes", "Kabelroutes per cluster"),
            ("aansluitingen_geclusterd", "Aansluitingen geclusterd"),
            ("stations_ontwerp", "Stations ontwerp"),
        ]
        gpkg_dataset = ogr.Open(str(gpkg))
        gpkg_layer_names = (
            {
                gpkg_dataset.GetLayer(index).GetName()
                for index in range(gpkg_dataset.GetLayerCount())
            }
            if gpkg_dataset is not None
            else set()
        )
        gpkg_dataset = None
        if "plangebied" in gpkg_layer_names:
            layer_specs.append(("plangebied", "Plangebied"))
        if "originele_ls_kabels" in gpkg_layer_names:
            layer_specs.append(
                ("originele_ls_kabels", "Originele laagspanningskabels")
            )
        if "originele_aansluitkabels" in gpkg_layer_names:
            layer_specs.append(
                ("originele_aansluitkabels", "Originele aansluitkabels")
            )
        if "flatkasten" in gpkg_layer_names:
            layer_specs.append(("flatkasten", "Flatkasten appartementen"))
        if "inpandige_appartementssleuven" in gpkg_layer_names:
            layer_specs.append(
                ("inpandige_appartementssleuven", "Inpandige appartementssleuven (0 m)")
            )
        if "bag_panden_appartementen" in gpkg_layer_names:
            layer_specs.append(
                ("bag_panden_appartementen", "BAG-panden appartementen")
            )
        if "stationomtrekken" in gpkg_layer_names:
            layer_specs.append(("stationomtrekken", "Stationomtrekken"))
        if "verdeelkasten" in gpkg_layer_names:
            layer_specs.append(("verdeelkasten", "Verdeelkasten"))
        if "interne_netkoppelingen" in gpkg_layer_names:
            layer_specs.append(
                ("interne_netkoppelingen", "Interne station-/kastkoppelingen (0 m)")
            )
        if "aangevulde_aansluitkabels" in gpkg_layer_names:
            layer_specs.append(
                ("aangevulde_aansluitkabels", "Aangevulde aansluitkabels")
            )
        loaded = {}
        palette = list(plt.cm.tab20.colors) + list(plt.cm.Set3.colors)
        overview = pd.read_csv(OUT / "cluster_overzicht.csv", sep=";", decimal=",")
        cluster_names = overview["Cluster"].tolist()
        cluster_rgb = {
            cluster_name: tuple(
                int(round(component * 255))
                for component in palette[index % len(palette)]
            )
            for index, cluster_name in enumerate(cluster_names)
        }

        def use_fixed_paper_units(symbol) -> None:
            """Force symbols to fixed millimetres instead of map/scale units."""
            if symbol is None:
                return
            try:
                symbol.setOutputUnit(Qgis.RenderUnit.Millimeters)
            except (AttributeError, TypeError):
                pass
            try:
                symbol.setSizeUnit(Qgis.RenderUnit.Millimeters)
            except (AttributeError, TypeError):
                pass
            try:
                symbol.setWidthUnit(Qgis.RenderUnit.Millimeters)
            except (AttributeError, TypeError):
                pass

        for layer_name, display_name in layer_specs:
            uri = f"{gpkg}|layername={layer_name}"
            layer = QgsVectorLayer(uri, display_name, "ogr")
            if not layer.isValid():
                raise RuntimeError(f"Ongeldige QGIS-laag: {display_name}")
            if layer.isTemporary():
                raise RuntimeError(
                    f"QGIS beschouwt '{display_name}' nog als tijdelijke laag. "
                    "Kies een blijvende uitvoermap."
                )
            if layer_name in (
                "originele_ls_kabels",
                "originele_aansluitkabels",
            ):
                function_index = layer.fields().lookupField("Function")
                if function_index < 0:
                    raise RuntimeError(
                        f"{display_name} mist de voorbereide kolom Function"
                    )
                function_values = sorted(
                    layer.uniqueValues(function_index),
                    key=lambda value: str(value).casefold(),
                )
                function_palette = list(plt.cm.Set1.colors) + list(
                    plt.cm.Dark2.colors
                )
                function_categories = []
                for value_index, function_value in enumerate(function_values):
                    rgb = tuple(
                        int(round(component * 255))
                        for component in function_palette[
                            value_index % len(function_palette)
                        ]
                    )
                    line_symbol = QgsLineSymbol.createSimple(
                        {
                            "color": f"{rgb[0]},{rgb[1]},{rgb[2]},255",
                            "width": "0.65",
                        }
                    )
                    use_fixed_paper_units(line_symbol)
                    label = str(function_value).strip() or "(leeg)"
                    function_categories.append(
                        QgsRendererCategory(function_value, line_symbol, label)
                    )
                layer.setRenderer(
                    QgsCategorizedSymbolRenderer(
                        "Function", function_categories
                    )
                )
            elif layer_name == "sleuven_genood":
                cable_symbol = QgsSymbol.defaultSymbol(layer.geometryType())
                cable_symbol.setColor(
                    __import__("qgis.PyQt.QtGui", fromlist=["QColor"]).QColor(
                        125, 125, 125
                    )
                )
                cable_symbol.setWidth(0.22)
                use_fixed_paper_units(cable_symbol)
                layer.renderer().setSymbol(cable_symbol)
            elif layer_name == "inpandige_appartementssleuven":
                indoor_symbol = QgsLineSymbol.createSimple(
                    {
                        "color": "117,42,143,255",
                        "width": "0.85",
                        "line_style": "dash",
                    }
                )
                use_fixed_paper_units(indoor_symbol)
                layer.renderer().setSymbol(indoor_symbol)
            elif layer_name == "flatkasten":
                cabinet_symbol = QgsMarkerSymbol.createSimple(
                    {
                        "name": "square",
                        "color": "255,255,255,255",
                        "outline_color": "117,42,143,255",
                        "outline_width": "0.65",
                        "size": "3.6",
                    }
                )
                use_fixed_paper_units(cabinet_symbol)
                layer.renderer().setSymbol(cabinet_symbol)
            elif layer_name == "bag_panden_appartementen":
                building_symbol = QgsSymbol.defaultSymbol(layer.geometryType())
                building_fill = QgsSimpleFillSymbolLayer.create(
                    {
                        "color": "255,255,255,0",
                        "outline_color": "117,42,143,170",
                        "outline_width": "0.35",
                        "outline_style": "dash",
                    }
                )
                building_symbol.changeSymbolLayer(0, building_fill)
                use_fixed_paper_units(building_symbol)
                layer.renderer().setSymbol(building_symbol)
            elif layer_name in ("stationomtrekken", "interne_netkoppelingen"):
                equipment_symbol = QgsSymbol.defaultSymbol(layer.geometryType())
                equipment_symbol.setColor(QColor(230, 97, 1))
                if hasattr(equipment_symbol, "setWidth"):
                    equipment_symbol.setWidth(
                        0.75 if layer_name == "stationomtrekken" else 0.45
                    )
                use_fixed_paper_units(equipment_symbol)
                layer.renderer().setSymbol(equipment_symbol)
            elif layer_name == "aangevulde_aansluitkabels":
                inferred_symbol = QgsLineSymbol.createSimple(
                    {
                        "color": "85,85,85,255",
                        "width": "0.55",
                        "line_style": "dash",
                    }
                )
                use_fixed_paper_units(inferred_symbol)
                layer.renderer().setSymbol(inferred_symbol)
            elif layer_name == "verdeelkasten":
                cabinet_network_symbol = QgsSymbol.defaultSymbol(
                    layer.geometryType()
                )
                cabinet_network_symbol.setColor(QColor(102, 51, 153))
                if hasattr(cabinet_network_symbol, "setSize"):
                    cabinet_network_symbol.setSize(3.8)
                elif hasattr(cabinet_network_symbol, "setWidth"):
                    cabinet_network_symbol.setWidth(0.8)
                else:
                    cabinet_network_symbol.setOpacity(0.55)
                use_fixed_paper_units(cabinet_network_symbol)
                layer.renderer().setSymbol(cabinet_network_symbol)
            elif layer_name == "plangebied":
                plan_symbol = QgsSymbol.defaultSymbol(layer.geometryType())
                plan_fill = QgsSimpleFillSymbolLayer.create(
                    {
                        "color": "255,255,255,0",
                        "outline_color": "48,48,48,255",
                        "outline_width": "0.65",
                        "outline_style": "solid",
                    }
                )
                plan_symbol.changeSymbolLayer(0, plan_fill)
                use_fixed_paper_units(plan_symbol)
                layer.renderer().setSymbol(plan_symbol)
            elif layer_name == "stations_ontwerp":
                existing_symbol = QgsMarkerSymbol.createSimple(
                    {
                        "name": "square",
                        "color": "227,26,28",
                        "outline_color": "0,0,0",
                        "outline_width": "0.5",
                        "size": "3.2",
                    }
                )
                new_symbol = QgsMarkerSymbol.createSimple(
                    {
                        "name": "star",
                        "color": "158,202,225",
                        "outline_color": "0,0,0",
                        "outline_width": "0.5",
                        "size": "5.0",
                    }
                )
                use_fixed_paper_units(existing_symbol)
                use_fixed_paper_units(new_symbol)
                layer.setRenderer(
                    QgsCategorizedSymbolRenderer(
                        "Type",
                        [
                            QgsRendererCategory("Bestaand", existing_symbol, "Bestaand"),
                            QgsRendererCategory("Nieuw", new_symbol, "Nieuw 630 kVA"),
                        ],
                    )
                )
                label_settings = QgsPalLayerSettings()
                label_settings.fieldName = (
                    'concat("Cluster", \'\\nMax_A: \', '
                    'format_number("Max_A", 0), \'\\nBelast_A: \', '
                    'format_number("Belast_A", 0))'
                )
                label_settings.isExpression = True
                label_settings.enabled = True
                label_settings.scaleVisibility = False
                # Station labels are mandatory design information. Give them
                # maximum priority and explicitly permit overlap/degraded
                # placement so QGIS never silently drops one in the layout.
                label_settings.displayAll = True
                label_settings.priority = 10
                label_settings.obstacle = False
                label_settings.zIndex = 100.0
                try:
                    station_placement_settings = label_settings.placementSettings()
                    station_placement_settings.setAllowDegradedPlacement(True)
                    station_placement_settings.setOverlapHandling(
                        Qgis.LabelOverlapHandling.AllowOverlapAtNoCost
                    )
                    label_settings.setPlacementSettings(
                        station_placement_settings
                    )
                except (AttributeError, TypeError):
                    pass
                station_font = QFont("Arial", 8)
                station_font.setBold(True)
                station_format = QgsTextFormat()
                station_format.setFont(station_font)
                station_format.setSize(8.0)
                try:
                    station_format.setSizeUnit(Qgis.RenderUnit.Points)
                except (AttributeError, TypeError):
                    pass
                station_buffer = QgsTextBufferSettings()
                station_buffer.setEnabled(True)
                station_buffer.setSize(0.65)
                try:
                    station_buffer.setSizeUnit(Qgis.RenderUnit.Millimeters)
                except (AttributeError, TypeError):
                    pass
                station_buffer.setColor(QColor(255, 255, 255))
                station_format.setBuffer(station_buffer)
                label_settings.setFormat(station_format)
                layer.setLabeling(QgsVectorLayerSimpleLabeling(label_settings))
                layer.setLabelsEnabled(True)
                row_styles = []
                for cluster_name in cluster_names:
                    rgb = cluster_rgb[cluster_name]
                    style = QgsConditionalStyle()
                    style.setName(str(cluster_name))
                    escaped_cluster = str(cluster_name).replace("'", "''")
                    style.setRule(f'"Cluster" = \'{escaped_cluster}\'')
                    # A light transparent version of the exact cluster colour
                    # keeps all table text readable while matching the map.
                    style.setBackgroundColor(QColor(*rgb, 105))
                    row_styles.append(style)
                layer.conditionalStyles().setRowStyles(row_styles)
            else:
                categories = []
                for i, cluster_name in enumerate(cluster_names):
                    rgb = cluster_rgb[cluster_name]
                    if layer_name == "aansluitingen_geclusterd":
                        symbol = QgsMarkerSymbol.createSimple(
                            {
                                "name": "circle",
                                "color": f"{rgb[0]},{rgb[1]},{rgb[2]},255",
                                "outline_color": "34,34,34,255",
                                "outline_width": "0.22",
                                "size": "4.7",
                            }
                        )
                        use_fixed_paper_units(symbol)
                    else:
                        symbol = QgsSymbol.defaultSymbol(layer.geometryType())
                        symbol.setColor(QColor(*rgb))
                    if layer_name == "clustergebieden":
                        symbol.setOpacity(0.30)
                    elif layer_name != "aansluitingen_geclusterd":
                        if hasattr(symbol, "setWidth"):
                            symbol.setWidth(0.8)
                        else:
                            symbol.setOpacity(0.75)
                        use_fixed_paper_units(symbol)
                    categories.append(QgsRendererCategory(cluster_name, symbol, cluster_name))
                layer.setRenderer(QgsCategorizedSymbolRenderer("Cluster", categories))
                if layer_name == "aansluitingen_geclusterd":
                    current_labels = QgsPalLayerSettings()
                    current_labels.fieldName = 'format_number("Ontwerp_A", 1)'
                    current_labels.isExpression = True
                    current_labels.enabled = True
                    current_labels.scaleVisibility = False
                    current_labels.placement = Qgis.LabelPlacement.OverPoint
                    current_labels.displayAll = True
                    try:
                        current_labels.quadOffset = Qgis.LabelQuadrantPosition.Over
                    except (AttributeError, TypeError):
                        pass
                    current_font = QFont("Arial", 6)
                    current_font.setBold(True)
                    current_format = QgsTextFormat()
                    current_format.setFont(current_font)
                    current_format.setSize(5.7)
                    try:
                        current_format.setSizeUnit(Qgis.RenderUnit.Points)
                    except (AttributeError, TypeError):
                        pass
                    current_format.setColor(QColor(20, 20, 20))
                    current_buffer = QgsTextBufferSettings()
                    current_buffer.setEnabled(True)
                    current_buffer.setSize(0.55)
                    try:
                        current_buffer.setSizeUnit(Qgis.RenderUnit.Millimeters)
                    except (AttributeError, TypeError):
                        pass
                    current_buffer.setColor(QColor(255, 255, 255))
                    current_format.setBuffer(current_buffer)
                    current_labels.setFormat(current_format)
                    layer.setLabeling(
                        QgsVectorLayerSimpleLabeling(current_labels)
                    )
                    layer.setLabelsEnabled(True)
            # Never let QGIS switch an output layer on/off or resize its
            # symbology through scale-dependent visibility settings.
            layer.setScaleBasedVisibility(False)
            project.addMapLayer(layer)
            loaded[layer_name] = layer

        # The print layout and canvas use these exact same project layers. A
        # data-defined layout-name expression selects the compact physical size
        # only while the print layout renders, so no duplicate zoom layers or
        # serialized style overrides are required.
        source_connections = loaded["aansluitingen_geclusterd"]
        configure_layout_style(
            source_connections,
            symbol_scale=LAYOUT_CONNECTION_SCALE,
            label_scale=LAYOUT_CONNECTION_SCALE,
        )

        source_stations = loaded["stations_ontwerp"]
        if source_stations.fields().lookupField("Volgnummer") < 0:
            # Older results assigned sequence numbers only after writing the
            # GeoPackage. Keep recovery read-only by storing a virtual field
            # in the project, using the order of the existing overview CSV.
            sequence_cases = [
                "WHEN \"Cluster\" = '" + str(name).replace("'", "''") + f"' THEN {index + 1}"
                for index, name in enumerate(cluster_names)
            ]
            source_stations.addExpressionField(
                "CASE " + " ".join(sequence_cases) + " ELSE NULL END", QgsField("Volgnummer", QVariant.Int)
            )
        configure_layout_style(
            source_stations,
            symbol_scale=LAYOUT_STATION_SYMBOL_SCALE,
            label_scale=LAYOUT_STATION_LABEL_SCALE,
            label_distance_mm=LAYOUT_STATION_LABEL_DISTANCE_MM,
        )

        source_routes = loaded["cluster_kabelroutes"]
        configure_layout_style(
            source_routes, line_scale=LAYOUT_ROUTE_WIDTH_SCALE
        )

        if "flatkasten" in loaded:
            source_flat_cabinets = loaded["flatkasten"]
            configure_layout_style(
                source_flat_cabinets,
                symbol_scale=LAYOUT_FLAT_CABINET_SCALE,
                stroke_scale=LAYOUT_FLAT_CABINET_SCALE,
            )

        osm_uri = (
            "type=xyz&url=https://tile.openstreetmap.org/"
            "{z}/{x}/{y}.png&zmin=0&zmax=19&tilePixelRatio=2"
        )
        osm_layer = QgsRasterLayer(osm_uri, "OpenStreetMap", "wms")
        if not osm_layer.isValid():
            raise RuntimeError("De OpenStreetMap XYZ-laag kon niet worden gemaakt")
        project.addMapLayer(osm_layer)

        root = project.layerTreeRoot()
        visible_order = [
            loaded["stations_ontwerp"],
            loaded["aansluitingen_geclusterd"],
            loaded["cluster_kabelroutes"],
        ]
        for optional_visible in (
            "flatkasten",
            "inpandige_appartementssleuven",
            "verdeelkasten",
            "stationomtrekken",
            "interne_netkoppelingen",
            "aangevulde_aansluitkabels",
        ):
            if optional_visible in loaded:
                visible_order.append(loaded[optional_visible])
        if "plangebied" in loaded:
            visible_order.append(loaded["plangebied"])
        visible_order.extend(
            [
                loaded["clustergebieden"],
                loaded["sleuven_genood"],
                osm_layer,
            ]
        )
        original_cable_layers = [
            loaded[name]
            for name in (
                "originele_aansluitkabels",
                "originele_ls_kabels",
            )
            if name in loaded
        ]
        hidden_reference_layers = [
            loaded[name]
            for name in ("bag_panden_appartementen",)
            if name in loaded
        ]
        order = [
            *visible_order[:-1],
            *original_cable_layers,
            *hidden_reference_layers,
            osm_layer,
        ]
        # Store the actual layer-list order so later manual additions render
        # normally instead of falling behind a fixed project render list/OSM.
        root.setHasCustomLayerOrder(False)
        for position, layer in enumerate(order):
            node = root.findLayer(layer.id())
            if node is not None:
                clone = node.clone()
                root.insertChildNode(position, clone)
                node.parent().removeChildNode(node)
        project.writeEntry("LSNetontwerp", "presentation_version", 147)
        connection_node = root.findLayer(loaded["aansluitingen_geclusterd"].id())
        if connection_node is not None:
            connection_node.setExpanded(True)
        for original_layer in original_cable_layers:
            tree_node = root.findLayer(original_layer.id())
            if tree_node is not None:
                tree_node.setItemVisibilityChecked(False)
        for reference_layer in hidden_reference_layers:
            tree_node = root.findLayer(reference_layer.id())
            if tree_node is not None:
                tree_node.setItemVisibilityChecked(False)
        # Editable A3 landscape print layout, stored in the project and also as
        # a separate QPT template. It deliberately uses the same persistent
        # GeoPackage layers as the map, so statistics update after manual edits.
        layout = QgsPrintLayout(project)
        layout.initializeDefaults()
        layout.setName("Clustering overzicht")
        layout.renderContext().setDpi(float(LAYOUT_EXPORT_DPI))
        layout.setCustomProperty(
            "LSNetontwerp/export_dpi", int(LAYOUT_EXPORT_DPI)
        )
        page = layout.pageCollection().page(0)
        if not page.setPageSize("A3", QgsLayoutItemPage.Landscape):
            page.setPageSize(
                QgsLayoutSize(420.0, 297.0, Qgis.LayoutUnit.Millimeters)
            )

        map_item = QgsLayoutItemMap(layout)
        map_item.setId("clusterkaart")
        map_item.setBackgroundColor(QColor(255, 255, 255))
        map_item.setFrameEnabled(True)
        map_item.attemptMove(
            QgsLayoutPoint(15.0, 15.0, Qgis.LayoutUnit.Millimeters)
        )
        map_item.attemptResize(
            QgsLayoutSize(300.0, 267.0, Qgis.LayoutUnit.Millimeters)
        )
        # The two original cable layers are available in the project but are
        # deliberately absent from the locked layout layer set by default.
        layout_visible_order = list(visible_order)
        map_item.setLayers(layout_visible_order)
        map_item.setKeepLayerSet(True)
        extent_layer = loaded.get("plangebied", loaded["aansluitingen_geclusterd"])
        map_extent = QgsRectangle(extent_layer.extent())
        for route_feature in source_routes.getFeatures():
            if route_feature.hasGeometry() and not route_feature.geometry().isEmpty():
                map_extent.combineExtentWith(route_feature.geometry().boundingBox())
        map_extent.grow(100.0)
        map_item.zoomToExtent(map_extent)
        layout.addLayoutItem(map_item)
        layout.setReferenceMap(map_item)

        width = max(map_extent.width(), 1.0)
        height = max(map_extent.height(), 1.0)
        target_interval = max(width / 5.0, height / 5.0)
        magnitude = 10.0 ** math.floor(math.log10(max(target_interval, 1.0)))
        interval = min(
            (1.0, 2.0, 5.0, 10.0),
            key=lambda factor: abs(factor * magnitude - target_interval),
        ) * magnitude
        coordinate_grid = QgsLayoutItemMapGrid("RD New", map_item)
        coordinate_grid.setCrs(QgsCoordinateReferenceSystem("EPSG:28992"))
        coordinate_grid.setEnabled(True)
        coordinate_grid.setIntervalX(interval)
        coordinate_grid.setIntervalY(interval)
        coordinate_grid.setStyle(Qgis.MapGridStyle.LineCrosses)
        coordinate_grid.setCrossLength(1.4)
        coordinate_grid.setLineSymbol(
            QgsLineSymbol.createSimple(
                {"color": "75,75,75,255", "width": "0.28"}
            )
        )
        coordinate_grid.setFrameStyle(Qgis.MapGridFrameStyle.Zebra)
        coordinate_grid.setFrameWidth(4.0)
        coordinate_grid.setFramePenSize(0.25)
        coordinate_grid.setFramePenColor(QColor(75, 75, 75))
        coordinate_grid.setFrameFillColor1(QColor(255, 255, 255))
        coordinate_grid.setFrameFillColor2(QColor(25, 25, 25))
        coordinate_grid.setAnnotationEnabled(True)
        coordinate_grid.setAnnotationPrecision(0)
        coordinate_grid.setAnnotationFrameDistance(1.3)
        coordinate_font = QFont("Arial", 7)
        coordinate_font.setBold(True)
        coordinate_grid.setAnnotationFont(coordinate_font)
        coordinate_grid.setAnnotationFontColor(QColor(75, 75, 75))
        for side in (
            Qgis.MapGridBorderSide.Left,
            Qgis.MapGridBorderSide.Right,
            Qgis.MapGridBorderSide.Bottom,
            Qgis.MapGridBorderSide.Top,
        ):
            coordinate_grid.setAnnotationPosition(
                Qgis.MapGridAnnotationPosition.OutsideMapFrame, side
            )
        coordinate_grid.setAnnotationDirection(
            Qgis.MapGridAnnotationDirection.Vertical,
            Qgis.MapGridBorderSide.Left,
        )
        coordinate_grid.setAnnotationDirection(
            Qgis.MapGridAnnotationDirection.VerticalDescending,
            Qgis.MapGridBorderSide.Right,
        )
        coordinate_grid.setAnnotationDirection(
            Qgis.MapGridAnnotationDirection.Horizontal,
            Qgis.MapGridBorderSide.Bottom,
        )
        coordinate_grid.setAnnotationDirection(
            Qgis.MapGridAnnotationDirection.Horizontal,
            Qgis.MapGridBorderSide.Top,
        )
        map_item.grids().addGrid(coordinate_grid)

        # The white side panel spans x=315..420 mm. These positions centre the
        # 86 mm table and the combined north-arrow/legend group on x=367.5 mm.
        side_panel_content_x = 324.5
        side_panel_legend_x = 343.5

        table_title = QgsLayoutItemLabel(layout)
        table_title.setId("stationsoverzicht_titel")
        table_title.setText("Stationsoverzicht")
        table_font = QFont("Arial", 9)
        table_font.setBold(True)
        table_title.setFont(table_font)
        table_title.attemptMove(
            QgsLayoutPoint(side_panel_content_x, 18.0, Qgis.LayoutUnit.Millimeters)
        )
        table_title.attemptResize(
            QgsLayoutSize(86.0, 7.0, Qgis.LayoutUnit.Millimeters)
        )
        layout.addLayoutItem(table_title)

        # QgsLayoutFrame/attribute-table resizing corrupts the Windows QGIS
        # 4.2 heap for some station sets. A dynamic HTML label keeps the same
        # live project fields and cluster colors without that multiframe path.
        table_label = QgsLayoutItemLabel(layout)
        table_label.setId("stationsoverzicht")
        table_label.setMode(QgsLayoutItemLabel.Mode.ModeHtml)
        table_label.setMargin(0)
        table_label.setFont(QFont("Arial", 6))
        color_cases = []
        for cluster_name in cluster_names:
            rgb = cluster_rgb[cluster_name]
            pastel = "#" + "".join(f"{round(component * .3 + 255 * .7):02x}" for component in rgb)
            escaped = str(cluster_name).replace("'", "''")
            color_cases.append(f"WHEN \"Cluster\" = '{escaped}' THEN '{pastel}'")
        background_expression = "CASE " + " ".join(color_cases) + " ELSE '#ffffff' END"
        row_expression = (
            "concat('<tr style=\"background-color:', " + background_expression + ", '\">', "
            "'<td>', \"Volgnummer\", '</td><td>', \"Cluster\", '</td><td>', \"Aantal\", "
            "'</td><td>', format_number(\"Belast_A\", 1), '</td><td>', "
            "format_number(\"Max_A\", 1), '</td><td>', format_number(\"Benut_pct\", 1), '</td></tr>')"
        )
        table_expression = (
            f"aggregate(layer:='{loaded['stations_ontwerp'].id()}', aggregate:='concatenate', "
            f"expression:={row_expression}, concatenator:='', filter:=\"Volgnummer\" <= 100, order_by:=\"Volgnummer\")"
        )
        table_label.setText(
            '<table width="100%" border="1" cellspacing="0" cellpadding="0" '
            'style="font-family:Arial; font-size:6pt; border-color:#7d7d7d;">'
            '<tr style="background-color:#eeeeee"><th>Nr</th><th>Station</th><th>Aantal</th>'
            '<th>Belast A</th><th>Max A</th><th>Benut %</th></tr>'
            '[% ' + table_expression + ' %]</table>'
        )
        table_label.attemptMove(
            QgsLayoutPoint(side_panel_content_x, 26.0, Qgis.LayoutUnit.Millimeters)
        )
        table_label.attemptResize(
            QgsLayoutSize(86.0, 137.0, Qgis.LayoutUnit.Millimeters)
        )
        layout.addLayoutItem(table_label)

        north_arrow = QgsLayoutItemLabel(layout)
        north_arrow.setId("noordpijl")
        north_arrow.setText("N\n↑")
        north_font = QFont("Arial", 16)
        north_font.setBold(True)
        north_arrow.setFont(north_font)
        north_arrow.setHAlign(Qt.AlignmentFlag.AlignHCenter)
        north_arrow.setVAlign(Qt.AlignmentFlag.AlignVCenter)
        north_arrow.attemptMove(
            QgsLayoutPoint(side_panel_content_x, 206.0, Qgis.LayoutUnit.Millimeters)
        )
        north_arrow.attemptResize(
            QgsLayoutSize(16.0, 30.0, Qgis.LayoutUnit.Millimeters)
        )
        layout.addLayoutItem(north_arrow)

        legend = QgsLayoutItemLegend(layout)
        legend.setId("legenda")
        legend.setTitle("Legenda")
        legend.setLinkedMap(map_item)
        legend.setAutoUpdateModel(False)
        legend.setResizeToContents(False)
        legend.setColumnCount(2)
        legend.setEqualColumnWidth(True)
        legend.setColumnSpace(2.0)
        legend.setBoxSpace(1.5)
        legend.setSymbolWidth(4.0)
        legend.setSymbolHeight(3.0)
        legend_title_font = QFont("Arial", 9)
        legend_title_font.setBold(True)
        legend_group_font = QFont("Arial", 7)
        legend_group_font.setPointSizeF(6.5)
        legend_group_font.setBold(True)
        legend_item_font = QFont("Arial", 7)
        legend_item_font.setPointSizeF(6.2)
        legend.setStyleFont(QgsLegendStyle.Title, legend_title_font)
        legend.setStyleFont(QgsLegendStyle.Subgroup, legend_group_font)
        legend.setStyleFont(QgsLegendStyle.SymbolLabel, legend_item_font)
        legend.setBackgroundEnabled(True)
        legend.setBackgroundColor(QColor(255, 255, 255, 245))
        legend.setFrameEnabled(True)
        legend_root = legend.model().rootGroup()
        legend_root.removeAllChildren()
        legend_layers = [source_stations]
        if "flatkasten" in loaded:
            legend_layers.append(loaded["flatkasten"])
        if "plangebied" in loaded:
            legend_layers.append(loaded["plangebied"])
        legend_layers.append(loaded["sleuven_genood"])
        for legend_layer in legend_layers:
            legend_node = legend_root.addLayer(legend_layer)
            legend_node.setCustomProperty("legend/splitLayer", True)
        legend.attemptMove(
            QgsLayoutPoint(side_panel_legend_x, 170.0, Qgis.LayoutUnit.Millimeters)
        )
        legend.attemptResize(
            QgsLayoutSize(67.0, 102.0, Qgis.LayoutUnit.Millimeters)
        )
        layout.addLayoutItem(legend)

        source_label = QgsLayoutItemLabel(layout)
        source_label.setText(
            "Achtergrond: © OpenStreetMap-bijdragers\n"
            "Coördinaten: RD New (EPSG:28992)"
        )
        source_font = QFont("Arial", 6)
        source_label.setFont(source_font)
        source_label.attemptMove(
            QgsLayoutPoint(side_panel_content_x, 277.0, Qgis.LayoutUnit.Millimeters)
        )
        source_label.attemptResize(
            QgsLayoutSize(86.0, 9.0, Qgis.LayoutUnit.Millimeters)
        )
        layout.addLayoutItem(source_label)

        if not project.layoutManager().addLayout(layout):
            raise RuntimeError("De Print Layout kon niet aan het project worden toegevoegd")
        from scope_layout import add_scope_layout
        add_scope_layout(project, layout, loaded, OUT, cluster_rgb)
        if not project.write(str(project_path)):
            raise RuntimeError("QGIS kon het projectbestand niet schrijven")

        qpt_path = OUT / "clustering_overzicht.qpt"
        qpt_path.unlink(missing_ok=True)
        if not layout.saveAsTemplate(str(qpt_path), QgsReadWriteContext()):
            raise RuntimeError("De losse QGIS-layouttemplate kon niet worden geschreven")
        log(
            "QGIS-project met blijvende GeoPackage-lagen, OpenStreetMap en "
            "bewerkbare Print Layout geschreven."
        )
        if os.environ.get("LS_QGIS_PROJECT_WORKER") == "1":
            log(f"QGIS-project geschreven: {project_path}")
            log(f"QGIS-layouttemplate geschreven: {qpt_path}")
            sys.stdout.flush()
            sys.stderr.flush()
            if os.name == "nt":
                # QGIS 4.2 installs a faulty CRT shutdown hook after layout
                # serialization, which can even intercept os._exit(). Use the
                # Win32 process primitive to skip every teardown callback.
                import ctypes

                kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
                kernel32.TerminateProcess(kernel32.GetCurrentProcess(), 0)
            os._exit(0)
        # Do not tear the project/layout object tree down here. The dedicated
        # worker terminates with os._exit after all files are verified, avoiding
        # QGIS 4.x ownership crashes during layout destruction.
        return project_path
    except Exception as exc:
        log(f"Waarschuwing: QGIS-project kon niet worden gemaakt: {exc}")
        return None


def filter_cables_by_function_words(
    frame: gpd.GeoDataFrame,
    terms: tuple[str, ...],
    enabled: bool,
    layer_label: str,
) -> gpd.GeoDataFrame:
    """Keep lines whose Function value contains one of the chosen words."""
    if not enabled or not terms:
        log(f"{layer_label}: {len(frame)} lijn(en) gebruikt zonder Function-filter.")
        return frame.copy()
    if "Function" not in frame.columns:
        raise RuntimeError(f"{layer_label} mist de voorbereide kolom Function")
    values = frame["Function"].fillna("").astype(str)
    mask = pd.Series(False, index=frame.index)
    for term in terms:
        pattern = rf"(?<!\w){re.escape(str(term).strip())}(?!\w)"
        mask |= values.str.contains(pattern, case=False, regex=True, na=False)
    selected = frame.loc[mask].copy()
    log(
        f"{layer_label}: {len(selected)} van {len(frame)} lijn(en) geselecteerd; "
        "Function bevat " + ", ".join(terms) + "."
    )
    if selected.empty:
        raise RuntimeError(
            f"Geen lijnen uit {layer_label} voldoen aan de Function-filter: "
            + ", ".join(terms)
        )
    return selected


def ensure_canonical_function_column(frame: gpd.GeoDataFrame) -> gpd.GeoDataFrame:
    """Keep all source attributes and expose the styling/filter field uniformly."""
    if "Function" in frame.columns:
        return frame
    candidate = next(
        (
            column
            for column in frame.columns
            if str(column).casefold() in ("function", "functie", "functiecode", "func")
            or str(column).casefold().startswith(("function", "functie"))
        ),
        None,
    )
    prepared = frame.copy()
    prepared["Function"] = "" if candidate is None else prepared[candidate]
    return prepared


def excluded_station_mask(node_xy, records):
    excluded = np.zeros(len(node_xy), dtype=bool)
    for record in records:
        distances = np.linalg.norm(node_xy - np.asarray([record["x"], record["y"]]), axis=1)
        excluded |= distances <= float(record.get("radius", 20.0))
    return excluded


def include_pinned_stations(stations, records):
    existing_names = set(stations["Stationsnaa"].astype(str))
    additions = []
    for record in records:
        if record["name"] in existing_names:
            continue
        additions.append({"Stationsnaa": record["name"], "Status": f"Nieuw {record['kva']:g}Kva",
                          "KVA": float(record["kva"]), "geometry": Point(record["x"], record["y"])})
        existing_names.add(record["name"])
    if not additions:
        return stations
    return gpd.GeoDataFrame(pd.concat([stations, gpd.GeoDataFrame(additions, crs=stations.crs)], ignore_index=True), geometry="geometry", crs=stations.crs)


def main(_automatic_retry: bool = False) -> None:
    global N_NEW, _AUTO_COUNTS_TRIED, _AUTO_TOPOLOGY_MINIMUM_NEW

    if not _automatic_retry:
        log(f"CPU-versnelling actief met maximaal {CPU_THREADS} threads.")
    if AUTO_NEW_STATIONS and not _automatic_retry:
        _AUTO_COUNTS_TRIED.clear()
        _AUTO_TOPOLOGY_MINIMUM_NEW = 0

    for path in (POINTS_PATH, CABLES_PATH, STATIONS_PATH):
        if not path.exists():
            raise FileNotFoundError(path)
    if CONNECTION_CABLES_PATH is not None and not Path(CONNECTION_CABLES_PATH).exists():
        raise FileNotFoundError(CONNECTION_CABLES_PATH)
    if FLAT_CABINETS_PATH is not None and not Path(FLAT_CABINETS_PATH).exists():
        raise FileNotFoundError(FLAT_CABINETS_PATH)
    if STATION_ENCLOSURES_PATH is not None and not Path(STATION_ENCLOSURES_PATH).exists():
        raise FileNotFoundError(STATION_ENCLOSURES_PATH)
    if DISTRIBUTION_CABINETS_PATH is not None and not Path(DISTRIBUTION_CABINETS_PATH).exists():
        raise FileNotFoundError(DISTRIBUTION_CABINETS_PATH)

    if OUT.exists():
        shutil.rmtree(OUT)
    OUT.mkdir(parents=True)

    log("Bronbestanden lezen...")
    design_current, design_field_index, design_field_name = extract_design_current(
        POINTS_PATH
    )
    points = gpd.read_file(POINTS_PATH).to_crs(CRS_RD)
    original_ls_cables = ensure_canonical_function_column(
        gpd.read_file(CABLES_PATH)
    )
    ls_cables = filter_cables_by_function_words(
        original_ls_cables.to_crs(CRS_RD),
        tuple(LS_FUNCTION_TERMS),
        bool(LS_FUNCTION_FILTER_ENABLED),
        "Laagspanningskabels",
    )
    # Keep the main-cable layer separate. It is the only preferred placement
    # surface for new stations; the optional connection-cable layer is used for
    # routing, but never as a normal station site.
    main_cables_for_station_placement = ls_cables.copy()
    original_connection_cables = None
    connection_cables_for_station_exclusion = None
    cable_frames = [ls_cables]
    if CONNECTION_CABLES_PATH is not None:
        original_connection_cables = ensure_canonical_function_column(
            gpd.read_file(CONNECTION_CABLES_PATH)
        )
        selected_connection_cables = filter_cables_by_function_words(
            original_connection_cables.to_crs(CRS_RD),
            tuple(CONNECTION_FUNCTION_TERMS),
            bool(CONNECTION_FUNCTION_FILTER_ENABLED),
            "Aansluitkabels",
        )
        connection_cables_for_station_exclusion = selected_connection_cables.copy()
        cable_frames.append(selected_connection_cables)
    cables = gpd.GeoDataFrame(
        pd.concat(cable_frames, ignore_index=True, sort=False),
        geometry="geometry",
        crs=CRS_RD,
    )
    cables = cables.loc[cables.geometry.notna() & ~cables.geometry.is_empty].copy()
    if cables.empty:
        raise RuntimeError("Na het samenvoegen zijn geen bruikbare kabels over")
    if original_connection_cables is not None:
        log(
            "Gefilterde laagspannings- en aansluitkabels zijn samengevoegd; "
            "onderlinge kruisingen en T-aansluitingen worden gezamenlijk genood."
        )
    stations = gpd.read_file(STATIONS_PATH).to_crs(CRS_RD)
    stations = include_pinned_stations(stations, globals().get("PINNED_NEW_STATIONS", []))
    flat_cabinets = None
    if FLAT_CABINETS_PATH is not None:
        flat_cabinets = gpd.read_file(FLAT_CABINETS_PATH).to_crs(CRS_RD)
        flat_cabinets = flat_cabinets.loc[
            flat_cabinets.geometry.notna() & ~flat_cabinets.geometry.is_empty
        ].reset_index(drop=True)
    station_enclosures = None
    if STATION_ENCLOSURES_PATH is not None:
        station_enclosures = gpd.read_file(STATION_ENCLOSURES_PATH).to_crs(CRS_RD)
        station_enclosures = station_enclosures.loc[
            station_enclosures.geometry.notna()
            & ~station_enclosures.geometry.is_empty
        ].reset_index(drop=True)
    distribution_cabinets = None
    if DISTRIBUTION_CABINETS_PATH is not None:
        distribution_cabinets = gpd.read_file(
            DISTRIBUTION_CABINETS_PATH
        ).to_crs(CRS_RD)
        distribution_cabinets = distribution_cabinets.loc[
            distribution_cabinets.geometry.notna()
            & ~distribution_cabinets.geometry.is_empty
        ].reset_index(drop=True)
    plan_area = None
    plan_layer = None
    if PLANGEBIED_PATH is not None:
        plan_path = Path(PLANGEBIED_PATH)
        if not plan_path.exists():
            raise FileNotFoundError(plan_path)
        plan_layer = gpd.read_file(plan_path).to_crs(CRS_RD)
        plan_layer = plan_layer.loc[
            plan_layer.geometry.notna() & ~plan_layer.geometry.is_empty
        ].copy()
        plan_layer.geometry = plan_layer.geometry.buffer(0)
        plan_layer = plan_layer.loc[~plan_layer.geometry.is_empty].copy()
        plan_area = unary_union(plan_layer.geometry.tolist()).buffer(0)
        if plan_area.is_empty:
            raise RuntimeError("Het opgegeven plangebied bevat geen geldige geometrie")
        buffered_plan = plan_area.buffer(0.05)
        point_inside = np.asarray(
            [buffered_plan.covers(geometry) for geometry in points.geometry],
            dtype=bool,
        )
        station_inside = np.asarray(
            [buffered_plan.covers(geometry) for geometry in stations.geometry],
            dtype=bool,
        )
        outside_points = int((~point_inside).sum())
        outside_stations = int((~station_inside).sum())
        if ONLY_WITHIN_PLAN_AREA:
            if outside_points:
                points = points.loc[point_inside].reset_index(drop=True)
                design_current = design_current[point_inside]
            if outside_stations:
                stations = stations.loc[station_inside].reset_index(drop=True)
            log(
                "Plangebiedfilter: "
                f"{outside_points} aansluiting(en) en {outside_stations} "
                "bestaand(e) station(s) buiten de grens genegeerd."
            )
            if points.empty:
                raise RuntimeError(
                    "Binnen het plangebied liggen geen LS-aansluitingen"
                )
            if stations.empty:
                raise RuntimeError(
                    "Binnen het plangebied liggen geen bestaande stations"
                )
            if not ALLOW_EXTERNAL_ROUTES and flat_cabinets is not None and not flat_cabinets.empty:
                flat_inside = np.asarray(
                    [buffered_plan.covers(geometry) for geometry in flat_cabinets.geometry],
                    dtype=bool,
                )
                outside_flat_cabinets = int((~flat_inside).sum())
                flat_cabinets = flat_cabinets.loc[flat_inside].reset_index(drop=True)
                if outside_flat_cabinets:
                    log(
                        "Plangebiedfilter: "
                        f"{outside_flat_cabinets} flatkast(en) buiten de grens genegeerd."
                    )
        elif outside_points:
            raise RuntimeError(
                f"{outside_points} LS-aansluitingen liggen buiten het plangebied"
            )
        cables = cables.copy()
        if not ALLOW_EXTERNAL_ROUTES:
            cables.geometry = cables.geometry.intersection(plan_area)
        cables = cables.loc[~cables.geometry.is_empty].copy()
        main_cables_for_station_placement = (
            main_cables_for_station_placement.copy()
        )
        main_cables_for_station_placement.geometry = (
            main_cables_for_station_placement.geometry.intersection(plan_area)
        )
        main_cables_for_station_placement = (
            main_cables_for_station_placement.loc[
                ~main_cables_for_station_placement.geometry.is_empty
            ].copy()
        )
        if not ALLOW_EXTERNAL_ROUTES and connection_cables_for_station_exclusion is not None:
            connection_cables_for_station_exclusion = (
                connection_cables_for_station_exclusion.copy()
            )
            connection_cables_for_station_exclusion.geometry = (
                connection_cables_for_station_exclusion.geometry.intersection(plan_area)
            )
            connection_cables_for_station_exclusion = (
                connection_cables_for_station_exclusion.loc[
                    ~connection_cables_for_station_exclusion.geometry.is_empty
                ].copy()
            )
        if not ALLOW_EXTERNAL_ROUTES and station_enclosures is not None and not station_enclosures.empty:
            station_enclosures = station_enclosures.copy()
            station_enclosures.geometry = station_enclosures.geometry.intersection(
                plan_area
            )
            station_enclosures = station_enclosures.loc[
                ~station_enclosures.geometry.is_empty
            ].reset_index(drop=True)
        if not ALLOW_EXTERNAL_ROUTES and distribution_cabinets is not None and not distribution_cabinets.empty:
            cabinet_inside = np.asarray(
                [buffered_plan.intersects(geometry) for geometry in distribution_cabinets.geometry],
                dtype=bool,
            )
            distribution_cabinets = distribution_cabinets.loc[
                cabinet_inside
            ].reset_index(drop=True)
        if cables.empty:
            raise RuntimeError("Binnen het plangebied liggen geen bruikbare sleuven")
        log("Kabelroutes mogen buiten het plangebied lopen; aansluitingen en stations volgen het plangebiedfilter." if ALLOW_EXTERNAL_ROUTES else
            "Het kabelnet wordt op de grens van het plangebied afgeknipt.")
        log("Clustergebieden worden begrensd door het opgegeven plangebied.")

    parsed_station_kva = []
    valid_station_mask = []
    ignored_station_labels = []
    for _station_index, station_row in stations.iterrows():
        try:
            name = str(station_row.get("Stationsnaa", "")).strip()
            override = globals().get("STATION_CAPACITY_OVERRIDES", {}).get(name)
            capacity_value = float(override) if override is not None else parse_design_kva(station_row.get("Status"))
            if not np.isfinite(capacity_value) or capacity_value <= 0:
                raise ValueError("Ongeldige ontwerpcapaciteit")
            parsed_station_kva.append(capacity_value)
            valid_station_mask.append(True)
        except (TypeError, ValueError):
            parsed_station_kva.append(np.nan)
            valid_station_mask.append(False)
            ignored_station_labels.append(
                str(station_row.get("Stationsnaa", "")).strip() or "(zonder naam)"
            )
    valid_station_mask = np.asarray(valid_station_mask, dtype=bool)
    if ignored_station_labels:
        log(
            f"Trafocapaciteitsfilter: {len(ignored_station_labels)} station(s) "
            "met NULL, een lege waarde of zonder getal genegeerd: "
            + ", ".join(ignored_station_labels[:20])
            + (" ..." if len(ignored_station_labels) > 20 else "")
        )
    stations = stations.loc[valid_station_mask].reset_index(drop=True)
    stations["KVA"] = np.asarray(parsed_station_kva, dtype=float)[
        valid_station_mask
    ]
    if stations.empty:
        raise RuntimeError(
            "Na het negeren van lege/ongeldige trafocapaciteiten blijft geen "
            "geldig bestaand station over"
        )
    if station_enclosures is not None and not station_enclosures.empty:
        valid_station_names = {
            normalize_link_id(value) for value in stations["Stationsnaa"]
        }
        enclosure_mask = station_enclosures["Stationsnaa"].map(
            normalize_link_id
        ).isin(valid_station_names)
        ignored_enclosures = int((~enclosure_mask).sum())
        station_enclosures = station_enclosures.loc[
            enclosure_mask
        ].reset_index(drop=True)
        if ignored_enclosures:
            log(
                f"Stationomtrekken: {ignored_enclosures} onderdeel/onderdelen "
                "zonder geldig gelijknamig station genegeerd."
            )
    # Keep a strictly main-cable-only copy for positioning new stations.
    # Connection cables, inferred links and internal equipment/apartment
    # conductors may carry routes, but are not normal new-station sites.
    regular_cables_for_station_placement = (
        main_cables_for_station_placement.copy()
    )
    equipment_links = make_equipment_network_links(
        regular_cables_for_station_placement,
        stations,
        station_enclosures,
        distribution_cabinets,
        NODE_TOLERANCE_M,
    )
    apartment_trenches = None
    apartment_buildings = None
    if flat_cabinets is not None:
        apartment_trenches, apartment_buildings = make_apartment_trenches(
            points, flat_cabinets, cables
        )
        if apartment_trenches is not None and not apartment_trenches.empty:
            if plan_area is not None and not ALLOW_EXTERNAL_ROUTES:
                outside_length = float(
                    unary_union(apartment_trenches.geometry.tolist()).difference(
                        plan_area.buffer(0.05)
                    ).length
                )
                if outside_length > 0.05:
                    raise RuntimeError(
                        "Een inpandige appartementssleuf valt buiten het gekozen "
                        f"plangebied ({outside_length:.2f} m)."
                    )
    already_connected_lines = []
    if apartment_trenches is not None and not apartment_trenches.empty:
        already_connected_lines.extend(apartment_trenches.geometry.tolist())
    if equipment_links is not None and not equipment_links.empty:
        already_connected_lines.extend(equipment_links.geometry.tolist())
    missing_connection_links = make_missing_connection_links(
        points,
        cables,
        already_connected_lines,
    )
    if (
        plan_area is not None
        and not ALLOW_EXTERNAL_ROUTES
        and missing_connection_links is not None
        and not missing_connection_links.empty
    ):
        outside_missing_length = float(
            unary_union(missing_connection_links.geometry.tolist()).difference(
                plan_area.buffer(0.05)
            ).length
        )
        if outside_missing_length > 0.05:
            raise RuntimeError(
                "Een automatisch aangevulde aansluitkabel valt buiten het "
                f"gekozen plangebied ({outside_missing_length:.2f} m)."
            )
    # Keep every filtered physical routing cable in the graph.  The separate
    # main-cable frame above is deliberately used only for positioning new
    # stations.  Previously this line rebuilt the routing network from that
    # main-only frame as well, silently dropping all real connection cables
    # after they had already been read and logged.  Connections were then
    # replaced by artificial nearest-main-cable links.
    normal_cables = cables.copy()
    normal_cables["Rekenfactor"] = 1.0
    network_frames = [normal_cables]
    if missing_connection_links is not None and not missing_connection_links.empty:
        inferred_cables = missing_connection_links[["geometry"]].copy()
        inferred_cables["Rekenfactor"] = 1.0
        network_frames.append(inferred_cables)
    if apartment_trenches is not None and not apartment_trenches.empty:
        indoor_cables = apartment_trenches[["geometry"]].copy()
        indoor_cables["Rekenfactor"] = 0.0
        network_frames.append(indoor_cables)
    if equipment_links is not None and not equipment_links.empty:
        equipment_cables = equipment_links[["geometry"]].copy()
        equipment_cables["Rekenfactor"] = 0.0
        network_frames.append(equipment_cables)
    cables = gpd.GeoDataFrame(
        pd.concat(network_frames, ignore_index=True, sort=False),
        geometry="geometry",
        crs=CRS_RD,
    )
    network_was_noded = (
        AUTO_NODE_CABLES
        or original_connection_cables is not None
        or (apartment_trenches is not None and not apartment_trenches.empty)
        or (equipment_links is not None and not equipment_links.empty)
        or (
            missing_connection_links is not None
            and not missing_connection_links.empty
        )
    )
    if network_was_noded:
        cables = node_cable_network(cables, points, stations, NODE_TOLERANCE_M)
        if original_connection_cables is not None and not AUTO_NODE_CABLES:
            log(
                "Knippen/noden is voor twee kabellagen verplicht geactiveerd, "
                "zodat verbindingen tussen beide lagen echte netwerkknooppunten zijn."
            )
    else:
        log(
            "Automatisch knippen/noden van sleuven staat uit; alleen bestaande "
            "lijnvertices worden als netwerkknoop gebruikt."
        )
    if len(design_current) != len(points):
        raise RuntimeError("Aantal ontwerpstromen komt niet overeen met aantal punten")
    if np.any(design_current < 0):
        raise RuntimeError("Negatieve ontwerpstroom aangetroffen")
    log(
        f"Ontwerpstroom: DBF-index {design_field_index}, {len(points):,} records, "
        f"totaal {design_current.sum():,.1f} A"
    )

    stations["Max_A"] = stations["KVA"] / 0.23 / 3.0
    existing_capacity = stations["Max_A"].to_numpy(float)
    new_capacity = NEW_KVA / 0.23 / 3.0
    theoretical_new = math.ceil(
        max(0.0, design_current.sum() - existing_capacity.sum()) / new_capacity
    )
    if AUTO_NEW_STATIONS:
        count_options = automatic_new_station_count_options(
            float(design_current.sum()),
            float(existing_capacity.sum()),
            float(new_capacity),
        )
        remaining_counts = [
            count for count in count_options if count not in _AUTO_COUNTS_TRIED
        ]
        if not remaining_counts:
            raise RuntimeError(
                "Geen automatisch stationsaantal leverde een kabeltopologisch "
                "geldige clustering op"
            )
        N_NEW = remaining_counts[0]
        _AUTO_COUNTS_TRIED.add(N_NEW)
        automatic_average = design_current.sum() / (
            existing_capacity.sum() + N_NEW * new_capacity
        )
        log(
            f"Automatische stationskeuze: {N_NEW} nieuwe stations van "
            f"{NEW_KVA:g} kVA; verwachte gewogen gemiddelde benutting "
            f"{automatic_average * 100:.1f}%."
        )
    else:
        log(
            f"Handmatig stationsaantal: exact {N_NEW} nieuwe stations van "
            f"{NEW_KVA:g} kVA."
        )
    total_capacity = existing_capacity.sum() + N_NEW * new_capacity
    if design_current.sum() > total_capacity + 1e-6:
        raise RuntimeError(
            f"{N_NEW} nieuwe stations van {NEW_KVA:g} kVA leveren onvoldoende capaciteit"
        )
    log(
        f"Bestaande capaciteit {existing_capacity.sum():,.1f} A; "
        f"minimaal benodigd nieuw: {theoretical_new} x {NEW_KVA:g} kVA"
    )
    weighted_required_utilization = design_current.sum() / total_capacity
    log(
        f"Voorkeursbenutting {TARGET_UTILIZATION * 100:.1f}%; door de totale "
        f"belasting is het gewogen gemiddelde minimaal "
        f"{weighted_required_utilization * 100:.1f}%. Harde routegrens: "
        f"{MAX_ROUTE_M:.1f} m."
    )

    graph = build_network(cables)
    node_list = list(graph.nodes)
    node_index = {node: i for i, node in enumerate(node_list)}
    node_xy = np.asarray(node_list, dtype=float)
    tree = cKDTree(node_xy)
    point_xy = np.column_stack((points.geometry.x, points.geometry.y))
    # Detached spare cables without connections need no new station. In the
    # unbounded run they used to abort all demand-bearing components merely
    # because every vertex of such a spare cable was excluded for placement.
    _demand_nodes, _demand_snap, demand_node_indices = snap_xy(point_xy, node_list, tree)
    point_tree = cKDTree(point_xy)
    point_clearance_m, _point_nearest = point_tree.query(node_xy)
    station_placement_parts = [
        part
        for geometry in regular_cables_for_station_placement.geometry
        for part in line_parts(geometry)
    ]
    connection_exclusion_parts = (
        [
            part
            for geometry in connection_cables_for_station_exclusion.geometry
            for part in line_parts(geometry)
        ]
        if connection_cables_for_station_exclusion is not None
        else []
    )
    raw_main_node_indices = np.flatnonzero(
        linework_distances(node_xy, station_placement_parts, 0.08) <= 0.08
    )
    main_node_indices = raw_main_node_indices[
        linework_distances(node_xy[raw_main_node_indices], connection_exclusion_parts, NEW_STATION_CONNECTION_CABLE_CLEARANCE_M)
        >= NEW_STATION_CONNECTION_CABLE_CLEARANCE_M
    ]
    # A new station must not coincide with an LS connection point. Candidate
    # nodes on the main cable are therefore filtered by a real-world clearance.
    # Components without any main cable receive a safe routing anchor on their
    # own cable component; their displayed station is offset beside that cable.
    safe_node_mask = point_clearance_m >= NEW_STATION_POINT_CLEARANCE_M
    excluded_node_mask = excluded_station_mask(node_xy, globals().get("EXCLUDED_STATION_AREAS", []))
    safe_node_mask &= ~excluded_node_mask
    placement_inside = np.ones(len(node_xy), dtype=bool)
    if plan_area is not None:
        placement_inside = np.asarray([buffered_plan.covers(Point(xy)) for xy in node_xy], dtype=bool)
        safe_node_mask &= placement_inside
    regular_node_indices_list: list[int] = []
    graph_component_by_node_index = np.full(len(node_list), -1, dtype=int)
    regular_indices_by_component: dict[int, np.ndarray] = {}
    regular_trees_by_component: dict[int, cKDTree] = {}
    component_has_main_cable: dict[int, bool] = {}
    for component_index, component_nodes in enumerate(nx.connected_components(graph)):
        component_indices = np.asarray(
            [node_index[node] for node in component_nodes], dtype=int
        )
        graph_component_by_node_index[component_indices] = component_index
        if not np.isin(demand_node_indices, component_indices).any():
            log(f"Kabelcomponent {component_index + 1}: geen aansluitingen; geen nieuwe stationslocatie nodig.")
            continue
        component_raw_main = np.intersect1d(
            component_indices, raw_main_node_indices, assume_unique=False
        )
        component_main = np.intersect1d(
            component_indices, main_node_indices, assume_unique=False
        )
        has_main = bool(len(component_raw_main))
        component_has_main_cable[component_index] = has_main
        if has_main:
            component_regular = component_main[safe_node_mask[component_main]]
            if not len(component_regular):
                raise RuntimeError(
                    "Een kabelcomponent bevat wel een hoofdkabel, maar geen "
                    "vrije stationslocatie die niet op een aansluitkabel ligt "
                    "en minstens "
                    f"{NEW_STATION_POINT_CLEARANCE_M:.2f} m van alle "
                    "LS-aansluitingen ligt"
                )
        else:
            component_regular = component_indices[safe_node_mask[component_indices]]
            if not len(component_regular):
                allowed_indices = component_indices[(~excluded_node_mask[component_indices]) & placement_inside[component_indices]]
                if not len(allowed_indices):
                    raise RuntimeError("Een kabelcomponent heeft geen stationslocatie buiten de uitgesloten locaties.")
                # Retain a deterministic last-resort routing anchor, choosing
                # the node with the largest possible separation. The displayed
                # station will still be placed beside the cable and away from
                # the connection point below.
                component_regular = np.asarray(
                    [allowed_indices[int(np.argmax(point_clearance_m[allowed_indices]))]],
                    dtype=int,
                )
        regular_indices_by_component[component_index] = component_regular
        regular_trees_by_component[component_index] = cKDTree(
            node_xy[component_regular]
        )
        regular_node_indices_list.extend(component_regular.tolist())

    regular_node_indices = np.asarray(
        sorted(set(regular_node_indices_list)), dtype=int
    )
    if not len(regular_node_indices):
        raise RuntimeError("Het netwerk bevat geen geschikte stationsknopen")
    regular_tree = cKDTree(node_xy[regular_node_indices])

    def regular_graph_index_near(xy_value, component_node_index=None) -> int:
        query_xy = np.asarray(xy_value, dtype=float)
        if component_node_index is not None:
            component_index = int(
                graph_component_by_node_index[int(component_node_index)]
            )
            component_regular = regular_indices_by_component.get(component_index)
            component_tree = regular_trees_by_component.get(component_index)
            if component_regular is None or component_tree is None:
                raise RuntimeError(
                    "De kabelcomponent van een aansluiting bevat geen geschikte "
                    "kabelknoop voor een nieuw station"
                )
            _distance, local_index = component_tree.query(query_xy)
            return int(component_regular[int(local_index)])
        _distance, local_index = regular_tree.query(query_xy)
        return int(regular_node_indices[int(local_index)])

    adjacency = nx.to_scipy_sparse_array(
        graph, nodelist=node_list, weight="weight", format="csr", dtype=float
    )

    point_nodes, point_snap_m, point_node_indices = snap_xy(point_xy, node_list, tree)
    station_xy = np.column_stack((stations.geometry.x, stations.geometry.y))
    station_nodes, station_snap_m, station_node_indices = snap_xy(
        station_xy, node_list, tree
    )
    log(
        f"Snapafstand aansluitingen: mediaan {np.median(point_snap_m):.2f} m, "
        f"maximum {np.max(point_snap_m):.2f} m"
    )
    disconnected_point_indices = np.flatnonzero(point_snap_m > 0.16)
    if len(disconnected_point_indices):
        raise RuntimeError(
            f"{len(disconnected_point_indices)} aansluiting(en) konden ondanks "
            "de aangevulde aansluitkabel niet topologisch met het hoofdkabelnet "
            "worden verbonden; controleer losse kabelcomponenten."
        )

    # Records snapped to the same cable node must stay together: one physical
    # cable node cannot belong to two exclusive station subnetworks.
    key_to_points: dict[int, list[int]] = defaultdict(list)
    for point_index, key in enumerate(point_node_indices):
        key_to_points[int(key)].append(point_index)
    groups = list(key_to_points.values())
    point_to_unit = np.empty(len(points), dtype=int)
    unit_xy = np.empty((len(groups), 2), dtype=float)
    unit_load = np.empty(len(groups), dtype=float)
    unit_node_indices = np.empty(len(groups), dtype=int)
    unit_nodes: list[tuple[float, float]] = []
    unit_legacy: list[str] = []
    legacy_series = points["GebiedLabel"].fillna("").astype(str).to_numpy()
    for unit_index, members in enumerate(groups):
        point_to_unit[members] = unit_index
        unit_xy[unit_index] = np.average(
            point_xy[members],
            axis=0,
            weights=design_current[members] + 0.5,
        )
        unit_load[unit_index] = design_current[members].sum()
        unit_node_indices[unit_index] = point_node_indices[members[0]]
        unit_nodes.append(point_nodes[members[0]])
        unit_legacy.append(Counter(legacy_series[members]).most_common(1)[0][0])
    unit_legacy_array = np.asarray(unit_legacy, dtype=object)
    log(f"Optimalisatie-eenheden: {len(groups):,}")
    unit_component_indices = graph_component_by_node_index[unit_node_indices]
    station_component_indices = graph_component_by_node_index[station_node_indices]
    for component_index in sorted(set(unit_component_indices.tolist())):
        component_units = unit_component_indices == component_index
        component_stations = np.flatnonzero(
            station_component_indices == component_index
        )
        station_text = ", ".join(
            str(stations.iloc[index]["Stationsnaa"])
            for index in component_stations
        ) or "geen"
        component_capacity = float(existing_capacity[component_stations].sum())
        log(
            f"Kabelcomponent {component_index + 1}: "
            f"{int(component_units.sum())} aansluitingseenheden, "
            f"{float(unit_load[component_units].sum()):.1f} A, "
            f"bestaande stations {station_text}, capaciteit "
            f"{component_capacity:.1f} A."
        )
    if AUTO_NEW_STATIONS:
        component_minimum_new = 0
        for component_index in sorted(set(unit_component_indices.tolist())):
            component_units = unit_component_indices == component_index
            component_stations = np.flatnonzero(
                station_component_indices == component_index
            )
            component_load = float(unit_load[component_units].sum())
            component_capacity = float(
                existing_capacity[component_stations].sum()
            )
            component_minimum_new += max(
                int(not len(component_stations)),
                int(
                    math.ceil(
                        max(0.0, component_load - component_capacity)
                        / new_capacity
                        - 1e-12
                    )
                ),
            )
        if N_NEW < component_minimum_new:
            log(
                f"Losse kabelcomponenten vereisen samen minimaal "
                f"{component_minimum_new} nieuwe stations; automatische keuze "
                f"wordt verhoogd van {N_NEW} naar {component_minimum_new}."
            )
            _AUTO_COUNTS_TRIED.update(range(N_NEW, component_minimum_new))
            N_NEW = component_minimum_new
            _AUTO_COUNTS_TRIED.add(N_NEW)
        _AUTO_TOPOLOGY_MINIMUM_NEW = max(
            int(_AUTO_TOPOLOGY_MINIMUM_NEW), int(component_minimum_new)
        )

    issues = indivisible_capacity_issues(unit_load, unit_node_indices, unit_component_indices,
                                        station_node_indices, station_component_indices,
                                        existing_capacity, new_capacity)
    if issues:
        problem_units = {issue["unit"] for issue in issues}
        problem_points = points.iloc[np.flatnonzero(np.isin(point_to_unit, list(problem_units)))].copy()
        problem_points["Knelpunt"] = "Ondeelbare groep boven beschikbare stationscapaciteit"
        problem_points.to_file(OUT / "capaciteitsknelpunten.gpkg", layer="knelpunten", driver="GPKG")
        pd.DataFrame(issues).to_csv(OUT / "capaciteitsknelpunten.csv", index=False, sep=";")
        first = issues[0]
        raise RuntimeError(
            f"{len(issues)} ondeelbare aansluitingseenheid/eenheden overschrijden de stationscapaciteit. "
            f"Eerste knelpunt: kabelcomponent {first['component']}, {first['load_a']:.1f} A "
            f"bij maximaal {first['maximum_a']:.1f} A. "
            "Aansluitingen op dezelfde kabelknoop kunnen niet veilig over stations worden gesplitst. "
            "Controleer ontwerpstromen, flat-/kabelkoppelingen of de capaciteit van het station op deze knoop."
        )

    # A solver failure must leave a map of the independent network parts, not
    # just a generic 'no solution' string. This is a control layer, not a design.
    component_lines = defaultdict(list)
    for start, end in graph.edges:
        component = int(graph_component_by_node_index[node_index[start]])
        if start != end:
            component_lines[component].append(LineString([start, end]))
    component_records = []
    for component, lines in component_lines.items():
        unit_mask = unit_component_indices == component
        station_mask = station_component_indices == component
        demand = float(unit_load[unit_mask].sum())
        capacity = float(existing_capacity[station_mask].sum())
        count = int(np.count_nonzero(unit_mask))
        component_records.append({
            "Component": component + 1, "Aansl_eenheden": count,
            "Belasting_A": demand, "Bestaand_A": capacity,
            "Stations": int(np.count_nonzero(station_mask)),
            "Min_nieuw": max(int(count > 0 and not station_mask.any()), math.ceil(max(0., demand-capacity)/new_capacity - 1e-12)),
            "Controle": "Zonder bestaand station" if count and not station_mask.any() else "Met bestaand station" if count else "Geen aansluitingen",
            "geometry": unary_union(lines),
        })
    gpd.GeoDataFrame(component_records, geometry="geometry", crs=CRS_RD).to_file(
        OUT / "netwerkcontrole.gpkg", layer="kabelcomponenten", driver="GPKG")

    legacy_new_labels = sorted(
        {
            label
            for label in unit_legacy
            if re.fullmatch(r"Trafo\s+\d+", label, flags=re.I)
        },
        key=lambda value: int(re.search(r"\d+", value).group()),
    )
    candidate_nodes: list[tuple[float, float]] = []
    candidate_node_indices: list[int] = []
    for label in legacy_new_labels:
        mask = unit_legacy_array == label
        median = weighted_geometric_median(unit_xy[mask], unit_load[mask])
        representative = int(np.flatnonzero(mask)[0])
        nearest = regular_graph_index_near(
            median, unit_node_indices[representative]
        )
        candidate_node_indices.append(nearest)
        candidate_nodes.append(node_list[nearest])
        log(f"Kandidaat {label}: kabelknoop {candidate_nodes[-1]}")

    # When GebiedLabel falls back to the existing Station assignment, create
    # candidate sites inside every overloaded/missing station area. This puts
    # new roots on the cable branches that actually need capacity instead of
    # relying only on globally farthest geometry.
    used_candidate_indices = set(candidate_node_indices)
    capacity_by_label = {
        str(stations.iloc[index]["Stationsnaa"]).strip(): float(existing_capacity[index])
        for index in range(len(stations))
    }
    station_node_by_label = {
        str(stations.iloc[index]["Stationsnaa"]).strip(): int(station_node_indices[index])
        for index in range(len(stations))
    }
    non_trafo_labels = sorted(
        {
            str(label).strip()
            for label in unit_legacy
            if str(label).strip()
            and not re.fullmatch(r"Trafo\s+\d+", str(label).strip(), flags=re.I)
        }
    )
    for label in non_trafo_labels:
        members = np.flatnonzero(unit_legacy_array == label)
        area_load = float(unit_load[members].sum())
        current_capacity = capacity_by_label.get(label, 0.0)
        required_candidates = max(
            0,
            int(
                math.ceil(
                    max(
                        0.0,
                        area_load / TARGET_UTILIZATION - current_capacity,
                    )
                    / new_capacity
                    - 1e-12
                )
            ),
        )
        local_seed_indices: list[int] = []
        if label in station_node_by_label:
            local_seed_indices.append(station_node_by_label[label])

        for candidate_number in range(1, required_candidates + 1):
            available_members = [
                int(unit_index)
                for unit_index in members
                if regular_graph_index_near(
                    unit_xy[int(unit_index)], unit_node_indices[int(unit_index)]
                )
                not in used_candidate_indices
            ]
            if not available_members:
                break
            if local_seed_indices:
                local_seed_xy = node_xy[np.asarray(local_seed_indices, dtype=int)]
                member_xy = unit_xy[np.asarray(available_members, dtype=int)]
                nearest_sq = np.min(
                    np.sum(
                        (member_xy[:, None, :] - local_seed_xy[None, :, :]) ** 2,
                        axis=2,
                    ),
                    axis=1,
                )
                member_loads = unit_load[np.asarray(available_members, dtype=int)]
                chosen_unit = available_members[
                    int(np.argmax(nearest_sq * (member_loads + 0.5)))
                ]
            else:
                median = weighted_geometric_median(
                    unit_xy[members], unit_load[members]
                )
                chosen_unit = min(
                    available_members,
                    key=lambda unit_index: float(
                        np.sum((unit_xy[unit_index] - median) ** 2)
                    ),
                )
            graph_index = regular_graph_index_near(
                unit_xy[chosen_unit], unit_node_indices[chosen_unit]
            )
            legacy_new_labels.append(label)
            candidate_node_indices.append(graph_index)
            candidate_nodes.append(node_list[graph_index])
            used_candidate_indices.add(graph_index)
            local_seed_indices.append(graph_index)
            log(
                f"Belastingskandidaat {label} {candidate_number}/"
                f"{required_candidates}: kabelknoop {candidate_nodes[-1]}"
            )

    # If the automatically selected station count is larger than the supplied
    # Trafo candidate labels, add deterministic demand-weighted farthest sites.
    # They start on a real connection cable node and are relocated to the
    # load-weighted center of their assigned cluster in the normal iterations.
    seed_indices = list(station_node_indices) + candidate_node_indices
    if seed_indices:
        seed_xy = node_xy[np.asarray(seed_indices, dtype=int)]
        closest_sq = np.min(
            np.sum((unit_xy[:, None, :] - seed_xy[None, :, :]) ** 2, axis=2),
            axis=1,
        )
    else:
        closest_sq = np.full(len(unit_xy), np.inf)
    auto_number = 1
    candidate_pool_target = max(len(candidate_nodes), N_NEW + 4) if N_NEW > 0 else 0
    while len(candidate_nodes) < candidate_pool_target:
        scores = closest_sq * (unit_load + 0.5)
        chosen_unit = None
        for unit_index in np.argsort(scores)[::-1]:
            graph_index = regular_graph_index_near(
                unit_xy[int(unit_index)], unit_node_indices[int(unit_index)]
            )
            if graph_index not in used_candidate_indices:
                chosen_unit = int(unit_index)
                break
        if chosen_unit is None:
            raise RuntimeError("Geen extra unieke kabelknopen voor nieuwe stations")
        graph_index = regular_graph_index_near(
            unit_xy[chosen_unit], unit_node_indices[chosen_unit]
        )
        automatic_name = f"Auto kandidaat {auto_number}"
        legacy_hint = str(unit_legacy[chosen_unit]).strip()
        label = legacy_hint or automatic_name
        auto_number += 1
        legacy_new_labels.append(label)
        candidate_node_indices.append(graph_index)
        candidate_nodes.append(node_list[graph_index])
        used_candidate_indices.add(graph_index)
        delta = unit_xy - node_xy[graph_index]
        closest_sq = np.minimum(closest_sq, np.sum(delta * delta, axis=1))
        hint_text = f" voor {legacy_hint}" if legacy_hint else ""
        log(
            f"Kandidaat {automatic_name}{hint_text}: "
            f"kabelknoop {candidate_nodes[-1]}"
        )

    # The geometric/farthest candidate pool can still miss a long, winding
    # cable branch: a unit may look close on the map while its network route is
    # longer than MAX_ROUTE_M. Add deterministic candidates at uncovered unit
    # nodes until every unit has at least one available station location within
    # the hard route limit. The facility MILP still decides which N_NEW sites
    # are actually selected.
    coverage_sources = np.asarray(
        list(station_node_indices) + candidate_node_indices, dtype=int
    )
    coverage_distances = network_distance_matrix(
        adjacency, coverage_sources, unit_node_indices
    )
    nearest_coverage = np.min(coverage_distances, axis=1)
    route_candidate_number = 1
    while np.any(nearest_coverage > MAX_ROUTE_M + 1e-7):
        uncovered = np.flatnonzero(nearest_coverage > MAX_ROUTE_M + 1e-7)
        chosen_unit = int(
            uncovered[np.argmax(nearest_coverage[uncovered] * (unit_load[uncovered] + 0.5))]
        )
        graph_index = regular_graph_index_near(
            unit_xy[chosen_unit], unit_node_indices[chosen_unit]
        )
        if graph_index in used_candidate_indices:
            raise RuntimeError(
                "Route-dekkingskandidaat kon niet op een unieke kabelknoop "
                "worden geplaatst"
            )
        previous_distance = float(nearest_coverage[chosen_unit])
        automatic_name = f"Route kandidaat {route_candidate_number}"
        legacy_hint = str(unit_legacy[chosen_unit]).strip()
        label = legacy_hint or automatic_name
        route_candidate_number += 1
        legacy_new_labels.append(label)
        candidate_node_indices.append(graph_index)
        candidate_nodes.append(node_list[graph_index])
        used_candidate_indices.add(graph_index)

        new_coverage = network_distance_matrix(
            adjacency, np.asarray([graph_index], dtype=int), unit_node_indices
        )[:, 0]
        nearest_coverage = np.minimum(nearest_coverage, new_coverage)
        hint_text = f" voor {legacy_hint}" if legacy_hint else ""
        log(
            f"Kandidaat {automatic_name}{hint_text}: kabelknoop "
            f"{candidate_nodes[-1]} (voorheen {previous_distance:.1f} m van "
            "de dichtstbijzijnde beschikbare stationslocatie)"
        )

    all_source_indices = np.concatenate(
        [station_node_indices, np.asarray(candidate_node_indices, dtype=int)]
    )
    log("Netwerkafstanden naar bestaande stations en kandidaatlocaties berekenen...")
    all_distances = network_distance_matrix(
        adjacency, all_source_indices, unit_node_indices
    )
    station_legacy_labels_all = stations["Stationsnaa"].astype(str).tolist() + legacy_new_labels
    initial_voronoi_node_cluster = None
    try:
        initial_assignment, selected_mask, facility_min_util = solve_facility_selection(
            all_distances,
            unit_load,
            existing_capacity,
            unit_legacy_array,
            station_legacy_labels_all,
            len(legacy_new_labels),
        )
    except RuntimeError as exc:
        if str(exc) == f"Geen geldige selectie van {N_NEW} nieuwe stations gevonden":
            if AUTO_NEW_STATIONS:
                # The mixed-integer facility model can end without an incumbent
                # on larger projects, especially inside an already busy QGIS
                # process.  That is not proof that the cable topology is
                # infeasible.  Build connected shortest-path territories
                # directly before trying arbitrary larger station counts.  This
                # fallback starts with every available candidate, removes the
                # redundant ones and may add a capacity candidate on a real
                # cable node when required.
                log(
                    "Optimalisatiesolver vond geen stationsselectie; "
                    "kabelverbonden kortste-pad-terugval uitvoeren..."
                )
                try:
                    (
                        voronoi_assignment,
                        facility_min_util,
                        initial_voronoi_node_cluster,
                        voronoi_candidate_indices,
                        _voronoi_unit_distances,
                    ) = solve_greedy_voronoi_connected_assignment(
                        adjacency,
                        node_list,
                        unit_node_indices,
                        unit_load,
                        station_node_indices,
                        candidate_node_indices,
                        existing_capacity,
                        new_capacity,
                        regular_node_indices,
                        graph_component_by_node_index,
                        None,
                    )
                except RuntimeError as voronoi_exc:
                    log(
                        "Kabelverbonden kortste-pad-terugval nog niet geldig: "
                        f"{voronoi_exc}"
                    )
                else:
                    while len(candidate_nodes) < len(candidate_node_indices):
                        appended_index = len(candidate_nodes)
                        candidate_nodes.append(
                            node_list[candidate_node_indices[appended_index]]
                        )
                        legacy_new_labels.append(
                            f"Capaciteitskandidaat {appended_index + 1}"
                        )
                    # The greedy fallback may have introduced extra cable-node
                    # candidates.  Refresh the distance matrix before the
                    # common downstream code selects its columns.
                    all_source_indices = np.concatenate(
                        [
                            station_node_indices,
                            np.asarray(candidate_node_indices, dtype=int),
                        ]
                    )
                    all_distances = network_distance_matrix(
                        adjacency, all_source_indices, unit_node_indices
                    )
                    selected_mask = np.zeros(len(candidate_node_indices), dtype=bool)
                    selected_mask[voronoi_candidate_indices] = True
                    existing_count = len(stations)
                    compact_to_global = np.asarray(
                        list(range(existing_count))
                        + [
                            existing_count + int(index)
                            for index in voronoi_candidate_indices
                        ],
                        dtype=int,
                    )
                    initial_assignment = compact_to_global[voronoi_assignment]
                    N_NEW = len(voronoi_candidate_indices)
                    _AUTO_COUNTS_TRIED.add(N_NEW)
                    log(
                        f"Kortste-pad-terugval selecteert {N_NEW} nieuwe "
                        "stations met volledig kabelverbonden gebieden."
                    )
                    exc = None

                if exc is not None:
                    count_options = automatic_new_station_count_options(
                        float(design_current.sum()),
                        float(existing_capacity.sum()),
                        float(new_capacity),
                    )
                    remaining_counts = [
                        count
                        for count in count_options
                        if count not in _AUTO_COUNTS_TRIED
                    ]
                else:
                    remaining_counts = []
                if exc is not None and remaining_counts:
                    log(
                        f"{N_NEW} nieuwe stations leveren geen geldige ruimtelijke "
                        "stationsselectie; automatisch opnieuw proberen met "
                        f"{remaining_counts[0]}."
                    )
                    return main(_automatic_retry=True)
            else:
                raise RuntimeError(
                    f"Geen geldige selectie van exact {N_NEW} handmatig ingestelde "
                    "nieuwe stations gevonden. Zet 'Aantal nieuwe stations "
                    "automatisch bepalen' aan of verhoog het handmatige aantal."
                ) from exc
        if exc is not None:
            raise
    selected_candidate_indices = np.flatnonzero(selected_mask)
    selected_legacy_labels = [legacy_new_labels[i] for i in selected_candidate_indices]
    log("Geselecteerde kandidaatgebieden: " + ", ".join(selected_legacy_labels))

    # Collapse the assignment indices from all candidates to the selected set.
    existing_count = len(stations)
    selected_global_station_indices = list(range(existing_count)) + [
        existing_count + int(i) for i in selected_candidate_indices
    ]
    selected_assignment = np.empty(len(groups), dtype=int)
    global_to_selected = {
        global_index: selected_index
        for selected_index, global_index in enumerate(selected_global_station_indices)
    }
    for unit_index, global_station_index in enumerate(initial_assignment):
        if int(global_station_index) not in global_to_selected:
            raise RuntimeError("Een aansluiting is aan een niet-geselecteerd station toegewezen")
        selected_assignment[unit_index] = global_to_selected[int(global_station_index)]

    new_nodes = [candidate_nodes[i] for i in selected_candidate_indices]
    new_node_indices = [candidate_node_indices[i] for i in selected_candidate_indices]
    capacities = np.concatenate(
        [existing_capacity, np.full(N_NEW, new_capacity, dtype=float)]
    )
    final_legacy_labels = stations["Stationsnaa"].astype(str).tolist() + selected_legacy_labels

    # Relocate each new station to the load-weighted middle of its assigned area,
    # snap it to a real cable node, and optimize the assignment once. A second
    # centre pass can make a marginally feasible component needlessly unstable.
    final_assignment = selected_assignment
    final_min_util = facility_min_util
    final_distances = all_distances[:, selected_global_station_indices].copy()
    # A Voronoi fallback already places every demand node in an exclusive,
    # connected shortest-path territory.  Keep those proven source locations;
    # moving them and solving the same large MILP again would only reintroduce
    # the solver failure that triggered the fallback.
    for iteration in range(0 if initial_voronoi_node_cluster is not None else 1):
        log(f"Nieuwe stations centreren, iteratie {iteration + 1}/1...")
        previous_new_nodes = list(new_nodes)
        previous_new_node_indices = list(new_node_indices)
        previous_assignment = final_assignment.copy()
        previous_distances = final_distances.copy()
        for new_index in range(N_NEW):
            station_index = existing_count + new_index
            mask = final_assignment == station_index
            if not np.any(mask):
                raise RuntimeError("Leeg nieuw cluster tijdens centreren")
            median = weighted_geometric_median(unit_xy[mask], unit_load[mask])
            assigned_units = np.flatnonzero(mask)
            representative = int(assigned_units[0])
            nearest = regular_graph_index_near(
                median, unit_node_indices[representative]
            )
            new_node_indices[new_index] = nearest
            new_nodes[new_index] = node_list[nearest]
        source_indices = np.concatenate(
            [station_node_indices, np.asarray(new_node_indices, dtype=int)]
        )
        final_distances = network_distance_matrix(
            adjacency, source_indices, unit_node_indices
        )
        try:
            final_assignment, final_min_util = solve_fixed_assignment(
                final_distances,
                unit_load,
                capacities,
                unit_legacy_array,
                final_legacy_labels,
            )
        except RuntimeError:
            new_nodes = previous_new_nodes
            new_node_indices = previous_new_node_indices
            final_assignment = previous_assignment
            final_distances = previous_distances
            log(
                "Centreren zou de capaciteit- of routevoorwaarden breken; "
                "de laatst geldige stationslocaties blijven behouden."
            )
            break

    source_nodes = station_nodes + new_nodes
    try:
        if initial_voronoi_node_cluster is not None:
            node_cluster = initial_voronoi_node_cluster
            log(
                "De geldige kabel-Voronoi-verdeling wordt rechtstreeks als "
                "eindtoedeling gebruikt."
            )
        else:
            final_assignment, final_min_util, node_cluster = solve_cable_connected_assignment(
                graph,
                node_list,
                adjacency,
                final_distances,
                unit_load,
                capacities,
                unit_nodes,
                unit_node_indices,
                source_nodes,
                final_assignment,
            )
    except RuntimeError as exc:
        if (
            AUTO_NEW_STATIONS
            and str(exc)
            == "Geen capaciteitsgeldige kabelverbonden toedeling gevonden"
        ):
            try:
                (
                    voronoi_assignment,
                    voronoi_min_util,
                    voronoi_node_cluster,
                    voronoi_candidate_indices,
                    _voronoi_unit_distances,
                ) = solve_greedy_voronoi_connected_assignment(
                    adjacency,
                    node_list,
                    unit_node_indices,
                    unit_load,
                    station_node_indices,
                    candidate_node_indices,
                    existing_capacity,
                    new_capacity,
                    regular_node_indices,
                    graph_component_by_node_index,
                    # Reconsider every prepared main-cable candidate. Starting
                    # only with the failed MILP selection can otherwise cause
                    # dozens of almost coincident emergency candidates to be
                    # added before a connected balance is found.
                    None,
                )
            except RuntimeError as voronoi_exc:
                log(f"Kabel-Voronoi-terugval nog niet geldig: {voronoi_exc}")
            else:
                while len(candidate_nodes) < len(candidate_node_indices):
                    appended_index = len(candidate_nodes)
                    candidate_nodes.append(
                        node_list[candidate_node_indices[appended_index]]
                    )
                    legacy_new_labels.append(
                        f"Capaciteitskandidaat {appended_index + 1}"
                    )
                selected_candidate_indices = np.asarray(
                    voronoi_candidate_indices, dtype=int
                )
                N_NEW = len(voronoi_candidate_indices)
                selected_legacy_labels = [
                    legacy_new_labels[index]
                    for index in voronoi_candidate_indices
                ]
                new_nodes = [
                    candidate_nodes[index] for index in voronoi_candidate_indices
                ]
                new_node_indices = [
                    candidate_node_indices[index]
                    for index in voronoi_candidate_indices
                ]
                capacities = np.concatenate(
                    [
                        existing_capacity,
                        np.full(N_NEW, new_capacity, dtype=float),
                    ]
                )
                final_legacy_labels = (
                    stations["Stationsnaa"].astype(str).tolist()
                    + selected_legacy_labels
                )
                source_nodes = station_nodes + new_nodes
                source_indices = np.concatenate(
                    [station_node_indices, np.asarray(new_node_indices, dtype=int)]
                )
                final_distances = network_distance_matrix(
                    adjacency, source_indices, unit_node_indices
                )
                final_assignment = voronoi_assignment
                final_min_util = voronoi_min_util
                node_cluster = voronoi_node_cluster
                exc = None
            if exc is None:
                pass
            else:
                count_options = automatic_new_station_count_options(
                    float(design_current.sum()),
                    float(existing_capacity.sum()),
                    float(new_capacity),
                )
                remaining_counts = [
                    count for count in count_options if count not in _AUTO_COUNTS_TRIED
                ]
                if remaining_counts:
                    log(
                        f"{N_NEW} nieuwe stations is niet kabeltopologisch haalbaar; "
                        f"automatisch opnieuw proberen met {remaining_counts[0]}."
                    )
                    return main(_automatic_retry=True)
        if exc is not None:
            raise exc
    cluster_loads = np.bincount(
        final_assignment, weights=unit_load, minlength=len(capacities)
    )
    if np.any(cluster_loads > capacities + 1e-5):
        raise RuntimeError("Capaciteitsoverschrijding in eindresultaat")
    utilization = cluster_loads / capacities * 100.0
    log(
        f"Eindbenutting: minimum {utilization.min():.1f}%, "
        f"gemiddeld {np.average(utilization, weights=capacities):.1f}%, "
        f"maximum {utilization.max():.1f}%"
    )

    new_order = sorted(
        range(N_NEW), key=lambda i: (-new_nodes[i][1], new_nodes[i][0])
    )
    reserved_names = set(stations["Stationsnaa"].astype(str)) | set(globals().get("RESERVED_STATION_NAMES", set()))
    free_names = (f"N-{number:02d}" for number in range(1, 1000000) if f"N-{number:02d}" not in reserved_names)
    new_name_by_index = {old_index: next(free_names) for old_index in new_order}
    cluster_names = stations["Stationsnaa"].astype(str).tolist() + [
        new_name_by_index[i] for i in range(N_NEW)
    ]
    pinned_names = {record["name"] for record in globals().get("PINNED_NEW_STATIONS", [])}
    cluster_types = ["Nieuw" if name in pinned_names else "Bestaand" for name in stations["Stationsnaa"].astype(str)] + ["Nieuw"] * N_NEW
    point_assignment = final_assignment[point_to_unit]

    # Determine the actual displayed/physical new-station position separately
    # from its graph routing anchor. On components with a main cable the point
    # is projected exactly onto that main cable. Only when a component has no
    # main cable at all is the station placed beside the available network.
    main_geometry_list = list(regular_cables_for_station_placement.geometry)
    main_geometry_tree = STRtree(main_geometry_list) if main_geometry_list else None
    physical_cable_parts = [
        part for geometry in normal_cables.geometry for part in line_parts(geometry)
    ]
    physical_cable_geometry = unary_union(physical_cable_parts)
    physical_cable_tree = STRtree(physical_cable_parts)

    def point_beside_cable(anchor: Point) -> Point:
        candidates: list[tuple[float, float, Point]] = []
        for radius in (
            NEW_STATION_FALLBACK_OFFSET_M,
            NEW_STATION_FALLBACK_OFFSET_M * 0.75,
            NEW_STATION_FALLBACK_OFFSET_M * 0.50,
        ):
            for angle in np.linspace(0.0, 2.0 * math.pi, 32, endpoint=False):
                candidate = Point(
                    anchor.x + radius * math.cos(float(angle)),
                    anchor.y + radius * math.sin(float(angle)),
                )
                if plan_area is not None and not plan_area.buffer(-0.05).covers(candidate):
                    continue
                point_distance = float(
                    point_tree.query(np.asarray([candidate.x, candidate.y]))[0]
                )
                cable_distance = float(candidate.distance(physical_cable_geometry))
                if point_distance < 0.75 or cable_distance < 0.30:
                    continue
                candidates.append((cable_distance, point_distance, candidate))
            if candidates:
                break
        if not candidates:
            raise RuntimeError(
                "Voor een kabelcomponent zonder hoofdkabel kon geen vrije "
                "stationspositie naast de kabel en buiten de LS-aansluitingen "
                "worden gevonden"
            )
        return max(candidates, key=lambda item: (item[0], item[1]))[2]

    exact_new_station_geometries: list[Point] = []
    new_station_links: list[LineString] = []
    new_station_placement_types: list[str] = []
    for new_index, node in enumerate(new_nodes):
        graph_anchor = Point(node)
        component_index = int(
            graph_component_by_node_index[int(new_node_indices[new_index])]
        )
        if component_has_main_cable.get(component_index, False):
            if main_geometry_tree is None:
                raise RuntimeError("Hoofdkabelgeometrie ontbreekt bij stationsplaatsing")
            cable_index = int(main_geometry_tree.nearest(graph_anchor))
            main_geometry = main_geometry_list[cable_index]
            display_point = main_geometry.interpolate(
                main_geometry.project(graph_anchor)
            )
            placement_type = "Op hoofdkabel"
        else:
            cable_index = int(physical_cable_tree.nearest(graph_anchor))
            cable_geometry = physical_cable_parts[cable_index]
            exact_anchor = cable_geometry.interpolate(
                cable_geometry.project(graph_anchor)
            )
            display_point = point_beside_cable(exact_anchor)
            placement_type = "Naast kabel (geen hoofdkabel in component)"
        exact_new_station_geometries.append(display_point)
        new_station_links.append(
            LineString([display_point.coords[0], graph_anchor.coords[0]])
        )
        new_station_placement_types.append(placement_type)

    station_geometries = list(stations.geometry) + exact_new_station_geometries
    station_display_xy = np.asarray(
        [[geometry.x, geometry.y] for geometry in station_geometries], dtype=float
    )
    station_snap_xy = np.asarray(source_nodes, dtype=float)

    log("Exclusieve kabelroutes binnen elk eigen kabeldeel afleiden...")
    route_geometries, route_lengths, unit_route_m = build_exclusive_routes(
        graph,
        node_list,
        node_cluster,
        source_nodes,
        unit_nodes,
        final_assignment,
    )
    for new_index, link in enumerate(new_station_links):
        station_index = existing_count + new_index
        if not link.is_empty and link.length > 1e-9:
            current_route = route_geometries[station_index]
            merged_parts = [link]
            if current_route is not None and not current_route.is_empty:
                merged_parts.append(current_route)
            route_geometries[station_index] = merge_linework(merged_parts)
            route_lengths[station_index] += float(link.length)
            unit_route_m[final_assignment == station_index] += float(link.length)
    longest_route = float(unit_route_m.max()) if len(unit_route_m) else 0.0
    if longest_route > MAX_ROUTE_M + 1e-6:
        raise RuntimeError(
            f"Langste exclusieve kabelroute is {longest_route:.1f} m en "
            f"overschrijdt de harde grens van {MAX_ROUTE_M:.1f} m"
        )
    log(
        f"Routecontrole: langste station-aansluitingroute {longest_route:.1f} m "
        f"(maximum {MAX_ROUTE_M:.1f} m)."
    )
    log("Clustergebieden vanuit de dichtstbijzijnde exclusieve kabels maken...")
    cluster_polygons, _ = make_cable_based_cluster_polygons(
        route_geometries,
        point_xy,
        node_xy[point_node_indices],
        point_assignment,
        station_display_xy,
        station_snap_xy,
        len(capacities),
        plan_area,
        allow_external_routes=bool(plan_area is not None and ALLOW_EXTERNAL_ROUTES),
    )
    disconnected = [
        index
        for index, polygon in enumerate(cluster_polygons)
        if invalid_disconnected_area(polygon, route_geometries[index], plan_area, bool(plan_area is not None and ALLOW_EXTERNAL_ROUTES))
    ]
    if disconnected:
        raise RuntimeError(
            "Exclaves aangetroffen in clusters: "
            + ", ".join(str(index) for index in disconnected)
        )
    for station_index, polygon in enumerate(cluster_polygons):
        checked_route = route_geometries[station_index]
        if plan_area is not None and ALLOW_EXTERNAL_ROUTES:
            checked_route = checked_route.intersection(plan_area)
        outside_length = checked_route.difference(
            polygon.buffer(0.05)
        ).length
        if outside_length > 0.1:
            raise RuntimeError(
                f"Kabelroute {station_index} ligt {outside_length:.2f} m "
                "buiten het eigen gebied"
            )
        own_points = point_xy[point_assignment == station_index]
        if any(not polygon.covers(Point(xy)) for xy in own_points):
            raise RuntimeError(
                f"Aansluiting buiten kabelgebaseerd gebied {station_index}"
            )
    for first in range(len(route_geometries)):
        for second in range(first + 1, len(route_geometries)):
            shared_length = route_geometries[first].intersection(
                route_geometries[second]
            ).length
            if shared_length > 1e-6:
                raise RuntimeError(
                    f"Kabelroutes {first} en {second} delen {shared_length:.2f} m"
                )

    point_route_m = unit_route_m[point_to_unit]
    point_cluster_load = cluster_loads[point_assignment]
    point_capacity = capacities[point_assignment]
    point_utilization = utilization[point_assignment]

    def safe_column(name: str, fallback=None):
        name = next((column for column in points.columns if column.casefold() == name.casefold()), name)
        if name in points.columns:
            value = points[name]
            if isinstance(value, pd.DataFrame):
                return value.iloc[:, 0]
            return value
        return [fallback] * len(points)

    connections = gpd.GeoDataFrame(
        {
            "Orig_ID": safe_column("ID"),
            "Master_asset_id": safe_column("master_asset_id", ""),
            "Station": safe_column("Station", ""),
            "Straat": safe_column("Straat", ""),
            "Huisnr": safe_column("Huisnummer"),
            "Toevoeging": safe_column("Toevoeging", ""),
            "Postcode": safe_column("Postcode", ""),
            "Gebr_doel": safe_column("Gebruiksdoe", ""),
            "Ontwerp_A": design_current,
            "Cluster": [cluster_names[i] for i in point_assignment],
            "Stat_type": [cluster_types[i] for i in point_assignment],
            "Stat_KVA": [
                (stations.iloc[i]["KVA"] if i < existing_count else NEW_KVA)
                for i in point_assignment
            ],
            "Max_A": point_capacity,
            "Clust_A": point_cluster_load,
            "Benut_pct": point_utilization,
            "Route_m": point_route_m,
            "Snap_m": point_snap_m,
            "Oud_gebied": legacy_series,
            "Multistory": safe_column("Multistory", ""),
            "Nieuwbouw": safe_column("Nieuwbouw", ""),
            "HandmatigNieuwbouw": safe_column("HandmatigNieuwbouw", ""),
            "NWB_ID": safe_column("NWB_ID", ""),
            "Bron": safe_column("Bron", ""),
            "Nieuwbouwproject": safe_column("Nieuwbouwproject", ""),
            "Buitenplan_toegestaan": bool(plan_area is not None and ALLOW_EXTERNAL_ROUTES),
        },
        geometry=points.geometry,
        crs=CRS_RD,
    )

    point_counts = np.bincount(point_assignment, minlength=len(capacities))
    max_route = np.asarray(
        [
            float(point_route_m[point_assignment == i].max())
            if np.any(point_assignment == i)
            else 0.0
            for i in range(len(capacities))
        ]
    )
    mean_route = np.asarray(
        [
            float(point_route_m[point_assignment == i].mean())
            if np.any(point_assignment == i)
            else 0.0
            for i in range(len(capacities))
        ]
    )

    station_statuses = stations["Status"].astype(str).tolist() + [
        "Nieuw 630Kva"
    ] * N_NEW
    station_kva = stations["KVA"].to_numpy(float).tolist() + [NEW_KVA] * N_NEW
    candidate_origins = [""] * existing_count + selected_legacy_labels
    placement_types = ["Vastgelegd nieuw" if name in pinned_names else "Bestaand" for name in stations["Stationsnaa"].astype(str)] + new_station_placement_types
    network_anchor_x = [geometry.x for geometry in stations.geometry] + [
        float(node[0]) for node in new_nodes
    ]
    network_anchor_y = [geometry.y for geometry in stations.geometry] + [
        float(node[1]) for node in new_nodes
    ]
    stations_design = gpd.GeoDataFrame(
        {
            "Cluster": cluster_names,
            "Type": cluster_types,
            "Status": station_statuses,
            "KVA": station_kva,
            "Max_A": capacities,
            "Belast_A": cluster_loads,
            "Benut_pct": utilization,
            "Aantal": point_counts,
            "Gem_route": mean_route,
            "Max_route": max_route,
            "Route_km": route_lengths / 1000.0,
            "Kandidaat": candidate_origins,
            "Plaatsing": placement_types,
            "Net_X": network_anchor_x,
            "Net_Y": network_anchor_y,
        },
        geometry=station_geometries,
        crs=CRS_RD,
    )

    common_summary = {
        "Cluster": cluster_names,
        "Type": cluster_types,
        "KVA": station_kva,
        "Max_A": capacities,
        "Belast_A": cluster_loads,
        "Benut_pct": utilization,
        "Aantal": point_counts,
        "Gem_route": mean_route,
        "Max_route": max_route,
        "Route_km": route_lengths / 1000.0,
        "Buitenplan_toegestaan": bool(plan_area is not None and ALLOW_EXTERNAL_ROUTES),
    }
    areas = gpd.GeoDataFrame(common_summary, geometry=cluster_polygons, crs=CRS_RD)
    routes = gpd.GeoDataFrame(
        common_summary, geometry=route_geometries, crs=CRS_RD
    )
    # Preserve this order in the CSV, GeoPackage, shapefiles and map:
    # existing stations first, then new stations, both naturally numbered.
    stations_design = _sort_station_records(stations_design)
    areas = _sort_station_records(areas)
    routes = _sort_station_records(routes)
    cable_parts = []
    cable_factors = []
    for _cable_index, cable_row in cables.iterrows():
        try:
            factor = float(cable_row.get("Rekenfactor", 1.0))
        except (TypeError, ValueError):
            factor = 1.0
        factor = 0.0 if factor <= 1e-9 else 1.0
        for part in line_parts(cable_row.geometry):
            cable_parts.append(part)
            cable_factors.append(factor)
    noded_cables = gpd.GeoDataFrame(
        {
            "Deel_ID": np.arange(1, len(cable_parts) + 1, dtype=int),
            "Lengte_m": [float(part.length) for part in cable_parts],
            "Reken_m": [
                float(part.length) * factor
                for part, factor in zip(cable_parts, cable_factors)
            ],
            "Rekenfactor": cable_factors,
            "Sleuftype": [
                "Interne koppeling (0 m)" if factor <= 1e-9 else "Regulier"
                for factor in cable_factors
            ],
            "Genood": ["Ja" if network_was_noded else "Nee"] * len(cable_parts),
        },
        geometry=cable_parts,
        crs=CRS_RD,
    )

    overview = stations_design.drop(columns="geometry").copy()
    overview["Volgnummer"] = np.arange(1, len(overview) + 1)
    overview = overview[
        ["Volgnummer"]
        + [column for column in overview.columns if column != "Volgnummer"]
    ]
    overview.to_csv(
        OUT / "cluster_overzicht.csv",
        sep=";",
        decimal=",",
        index=False,
        encoding="utf-8-sig",
    )

    gpkg = write_layers(
        connections,
        stations_design,
        areas,
        routes,
        noded_cables,
        plan_layer,
        original_ls_cables,
        original_connection_cables,
        flat_cabinets,
        apartment_trenches,
        apartment_buildings,
        station_enclosures,
        distribution_cabinets,
        equipment_links,
        missing_connection_links,
    )
    log("Overzichtskaart renderen...")
    try:
        make_map(cables, connections, stations_design, areas, routes, plan_layer)
    except Exception as exc:
        # All hard design checks and GeoPackage writes have passed. A bitmap
        # or PDF export failure must not throw the valid design away.
        for filename in ("clustering_overzicht.png", "clustering_overzicht.pdf"):
            (OUT / filename).unlink(missing_ok=True)
        warning = f"De clustering is berekend, maar de overzichtskaart kon niet worden geëxporteerd: {exc}"
        (OUT / "clustering_waarschuwingen.json").write_text(json.dumps([warning], ensure_ascii=False, indent=2), encoding="utf-8")
        log("WAARSCHUWING: " + warning)

    readme = f"""# Clustering laagspanning

Dit resultaat verdeelt {len(points)} aansluitingen over {len(stations)} bestaande
stations en {N_NEW} nieuwe stations van {NEW_KVA:g} kVA. De totale ontwerpstroom is
{design_current.sum():.1f} A. De totale beschikbare ontwerpstroom is
{total_capacity:.1f} A.

## Rekenregels

- Belasting per aansluiting: het gevulde DBF-veld `{design_field_name}` op
  veldindex {design_field_index} (de bron bevat meerdere gelijk afgekorte namen).
- Stationcapaciteit: KVA / 0,23 / 3.
- Bij een status met meerdere KVA-waarden is de laatste waarde gebruikt; dit is
  de waarde tussen haakjes (de verzwaring). Als er geen haakjes zijn, is de enige
  aanwezige KVA-waarde gebruikt.
- Aantal nieuwe stations: {N_NEW} x {NEW_KVA:g} kVA. Het aantal is
  {'automatisch gekozen op de voorkeursbenutting' if AUTO_NEW_STATIONS else 'handmatig ingesteld'};
  de harde rekenkundige ondergrens op alleen capaciteit is {theoretical_new}.
- Toedeling: capaciteitsbegrensde optimalisatie op kortste afstand over het
  aangeleverde kabelnet. De oude `GebiedLabel`-indeling telt als lichte
  continuiteitsvoorkeur, maar capaciteit en kabelafstand zijn leidend.
- Voorkeursbenutting: zo dicht mogelijk bij {TARGET_UTILIZATION * 100:.1f}% per
  station. Dit is een optimalisatiedoel en geen harde grens; de totale belasting
  kan een hogere gemiddelde benutting noodzakelijk maken.
- Maximale route: iedere aansluiting ligt via het exclusieve eigen kabelsubnet
  maximaal {MAX_ROUTE_M:.1f} meter van het toegewezen station.
- Appartementen: {'multistory-aansluitingen zijn via de ingestelde PDOK BAG OGC API aan een flatkast of voorkeurskabel binnen hetzelfde BAG-pand gekoppeld; deze inpandige sleuven hebben 0 m rekenlengte' if apartment_trenches is not None and not apartment_trenches.empty else 'geen appartement-/flatkastkoppeling toegepast'}.
- Stationomtrekken en verdeelkasten: {'als echte netwerkkoppelingen gebruikt; kabels die hetzelfde object raken zijn onderling bereikbaar en de interne rekenlengte is 0 m' if equipment_links is not None and not equipment_links.empty else 'geen aanvullende installatiegeometrie toegepast'}.
- Ontbrekende gewone aansluitkabels: {len(missing_connection_links) if missing_connection_links is not None else 0} expliciete verbinding(en) naar de dichtstbijzijnde reguliere kabel aangevuld; deze fysieke lengte telt volledig mee voor de routegrens.
- Kabelfilter laagspanningskabels: {'Function bevat ' + ', '.join(LS_FUNCTION_TERMS) if LS_FUNCTION_FILTER_ENABLED and LS_FUNCTION_TERMS else 'geen Function-filter'}.
- Kabelfilter aansluitkabels: {'Function bevat ' + ', '.join(CONNECTION_FUNCTION_TERMS) if original_connection_cables is not None and CONNECTION_FUNCTION_FILTER_ENABLED and CONNECTION_FUNCTION_TERMS else ('geen Function-filter' if original_connection_cables is not None else 'geen aparte aansluitkabellaag')}.
- Plangebiedselectie: {'aansluitingen en bestaande stations buiten de grens zijn genegeerd' if plan_area is not None and ONLY_WITHIN_PLAN_AREA else ('aansluitingen buiten de grens zijn niet toegestaan' if plan_area is not None else 'geen plangebied opgegeven')}.
- Kabelroutes buiten plangebied: {'toegestaan; de volledige omweg telt mee voor de routelengte' if plan_area is not None and ALLOW_EXTERNAL_ROUTES else ('niet toegestaan; het netwerk is op de grens geknipt' if plan_area is not None else 'geen plangebiedbeperking')}.
- De gefilterde kabellagen zijn vóór de routeberekening samengevoegd en als één
  netwerk geknipt/genood. Daardoor zijn ook onderlinge kruisingen en
  T-aansluitingen echte netwerkknooppunten.
- Kabeltopologie: ieder cluster heeft een exclusief, stationsgeworteld
  kabelsubnet. Iedere aansluiting is via uitsluitend het eigen kabeldeel met het
  station verbonden; gedeelde kabellengte tussen clusters is 0 meter.
- Nieuwe stationlocatie: het belastingsgewogen midden van het cluster, exact
  gesnapt op een kabelknoop.
- Gebiedstopologie: {'gebieden blijven binnen het plangebied; meerdere vlakken zijn alleen toegestaan als de aangesloten kabelroute buiten het plangebied doorloopt en ieder vlak de route raakt' if plan_area is not None and ALLOW_EXTERNAL_ROUTES else 'elk cluster is één aaneengesloten polygoon zonder exclaves'}.
  De grenzen zijn afgeleid van de dichtstbijzijnde exclusieve kabelroutes; bij
  een knooppunt wordt zo nodig een smalle corridor om de eigen kabel gereserveerd.
  Alle eigen aansluitingen, routes en het station liggen binnen het eigen gebied.
- Gegarandeerde minimale benutting in de eindoplossing: {final_min_util * 100:.0f}%.

## Bestanden

- `clustering_ontwerp.gpkg`: alle vijf resultaatlagen in een GeoPackage,
  inclusief `sleuven_genood` met het werkelijk gebruikte, geknipte kabelnet.
  Wanneer een plangebied is gekozen staat dit als zesde laag `plangebied` in
  hetzelfde GeoPackage.
- `shapefiles/`: dezelfde vijf lagen als losse shapefiles; het genode kabelnet
  staat ook apart in `sleuven_genood.shp`. Een gekozen plangebied staat er als
  `plangebied.shp` bij.
- `originele_ls_kabels` en, indien gekozen, `originele_aansluitkabels`: de
  volledige bronlagen in het GeoPackage en als losse shapefiles. In het
  QGIS-project hebben ze categorie-symboliek op `Function` en staan ze
  standaard uitgevinkt.
- `flatkasten`, `inpandige_appartementssleuven` en
  `bag_panden_appartementen` zijn aanwezig wanneer de optionele flatkastenlaag
  is gebruikt. De fysieke lengte blijft zichtbaar; `Reken_m` is voor deze
  inpandige sleuven 0 zodat zij niet meetellen voor de maximale route.
- `stationomtrekken`, `verdeelkasten` en `interne_netkoppelingen` zijn aanwezig
  wanneer deze optionele installatielagen zijn gebruikt. De stationsnaam van
  een omtrek is aan het gelijknamige bestaande station gekoppeld; alle kabels
  tegen dezelfde omtrek of verdeelkast vormen één genood netwerk.
- `aangevulde_aansluitkabels` bevat gewone LS-aansluitingen die de bronkabels
  niet werkelijk raakten. Deze lijnen hebben `Reken_m` gelijk aan hun fysieke
  lengte en zijn onderdeel van de exclusieve clusterroute.
- `cluster_overzicht.csv`: capaciteit, belasting, benutting en routelengte.
- `clustering_overzicht.png` en `.pdf`: controlekaart zonder boventitel, met
  OpenStreetMap tot zoomniveau {OSM_MAX_ZOOM}, exportresolutie
  {MAP_OUTPUT_DPI} dpi en een functionele zebra-coordinatenrand. Een automatisch
  passend interval bepaalt zowel de zebra-overgangen als de vetgedrukte RD
  New-labels, donkergrijze ticks exact vanaf de binnenrand en donkergrijze
  plusmarkeringen op de kruisingen. De ticks staan onder de zebra in de
  tekenvolgorde, zijn rondom fysiek even lang en steken niet in de zebra door.
  Een compacte noordpijl staat links van en exact verticaal gecentreerd op de
  legenda. De stationstabel gebruikt per rij een lichte versie van de eigen
  clusterkleur en bevat ook de maximale ontwerpstroom in ampere. De tabel en de
  combinatie van noordpijl en legenda staan horizontaal gecentreerd in het witte
  zijvlak. Eerst staan de bestaande stations op nummer, daarna de nieuwe stations
  op nummer. Er worden geen rasterlijnen over de kaart getekend. De legenda en
  tabel staan in een apart zijpaneel buiten het plangebied.
- `clustering_ontwerp.qgz`: QGIS-project met alle vijf resultaatlagen en een
  OpenStreetMap XYZ-achtergrond. Een gekozen plangebied is als aparte omlijnde
  laag opgenomen. De lagen verwijzen relatief naar het blijvende GeoPackage in
  dezelfde resultaatmap en zijn geen tijdelijke lagen. De LS-aansluitingen zijn
  grote gekleurde cirkels met de ontwerpstroom, op één decimaal, vet en
  gecentreerd in iedere cirkel. Alle vector-symbolen gebruiken vaste
  millimetermaten en alle labels vaste puntmaten; zij veranderen dus niet van
  grootte bij zoomen. Stationslabels hebben in de layout verplichte plaatsing,
  ook wanneer labels elkaar raken. De speciale layoutweergave gebruikt voor
  stationssymbolen {LAYOUT_STATION_SYMBOL_SCALE * 100:.0f}%, voor
  stationslabels {LAYOUT_STATION_LABEL_SCALE * 100:.0f}% met
  {LAYOUT_STATION_LABEL_DISTANCE_MM:.1f} mm afstand, voor flatkasten
  {LAYOUT_FLAT_CABINET_SCALE * 100:.0f}%, voor gekleurde kabelroutes
  {LAYOUT_ROUTE_WIDTH_SCALE * 100:.0f}% lijndikte en voor aansluitingen
  {LAYOUT_CONNECTION_SCALE * 100:.0f}% van de grootte in het kaartvenster. De
  layout bewaart {LAYOUT_EXPORT_DPI} dpi als
  exportresolutie en de OSM-laag gebruikt HiDPI-tegels tot zoomniveau
  {OSM_MAX_ZOOM}.
- Nieuwe stations worden uitsluitend op vrije hoofdkabelknopen geplaatst en
  blijven minimaal {NEW_STATION_POINT_CLEARANCE_M:.2f} m van LS-aansluitpunten.
  Aansluitkabels zijn geen toegestane normale stationslocatie. Alleen wanneer
  een volledige kabelcomponent geen hoofdkabel bevat, wordt het station
  {NEW_STATION_FALLBACK_OFFSET_M:.2f} m naast die kabel geplaatst en met een
  korte, meegerekende stationaansluiting aan de exclusieve route gekoppeld.
- `clustering_overzicht.qpt`: losse QGIS Print Layout-template. Dezelfde
  bewerkbare A3-layout staat ook al in het project als `Clustering overzicht`,
  met stationstabel, legenda, noordpijl en RD New-coordinatenrand. Vanuit deze
  layout kunnen later opnieuw PNG- en PDF-bestanden worden geexporteerd.

## Handmatige correctie

Gebruik in QGIS `Handmatige clustercorrectie (selectie naar station)` om later
geselecteerde aansluitingen naar een geselecteerd doelstation te verplaatsen.
De tool werkt daarna de kabelroutes, aaneengesloten gebieden en alle
statistiekvelden gezamenlijk bij en maakt eerst een GeoPackage-back-up.
Bij het samenvoegen/verwijderen van een hele broncluster worden ook de
stationsvolgnummers, stationstabel, legenda-categorieën en layoutweergave
direct opnieuw opgebouwd. Het project wordt als gewijzigd gemarkeerd; de
GeoPackage-gegevens zelf zijn meteen opgeslagen.
De controles op ontwerpstroom, kabellengte, routes door/over andere clusters en
gedeelde kabelroutes/onvolledige vertakkingen staan standaard afzonderlijk aan.
Iedere controle kan bewust onafhankelijk worden uitgezet; technische
basiscontroles en de back-up blijven altijd actief.

## Sleuven en routes onderhouden

Gebruik in de wizard `5. Sleuven/routes`. Met `Nieuwe sleuf tekenen` wordt een
kaartlijn na afronden blijvend toegevoegd aan `Sleuven geknipt/genood`. Alleen
het door de nieuwe lijn geraakte deel wordt opnieuw geknipt/genood; de rest
blijft exact behouden. Bij een grote wijziging volgt automatisch volledig
noden. Met `Alle clusterroutes verversen` blijven de
clusterwaarden van de aansluitingen ongewijzigd, maar worden alle kortste
exclusieve kabelroutes, Route_m, route- en stationstatistieken,
clustergebieden, layouttabel en legenda opnieuw opgebouwd. Een nieuwe
onbeheerde sleuf kan daarbij automatisch een langere bestaande route
vervangen. Voor iedere wijziging wordt een GeoPackage-back-up geschreven.
Met `Geselecteerde routes verversen` worden uitsluitend de in
`Kabelroutes per cluster` of `Stations ontwerp` geselecteerde clusters opnieuw
berekend; de overige routegeometrieën blijven ongewijzigd.

## Aandachtspunt

Dit is een ruimtelijk ontwerpvoorstel op basis van de aangeleverde civiele
sleuflijnen. Beveiligingsselectiviteit, spanningsval, kabeldoorsnede, fasebalans,
grondpositie en fysieke plaatsbaarheid van nieuwe stations zijn niet in de
brongegevens aanwezig en moeten vóór uitvoering technisch worden getoetst.
"""
    (OUT / "LEESMIJ.md").write_text(readme, encoding="utf-8")
    # QGIS/Qt cleanup can return exit code 1 when it is initialized in the same
    # long-running process that used HiGHS and Matplotlib. Generate the project
    # in a short child process so the main clustering command exits cleanly.
    if CREATE_QGIS_PROJECT:
        qgis_project_result = subprocess.run(
            [
                sys.executable,
                "-u",
                "-c",
                (
                    "import maak_clustering as m; "
                    "m.make_qgis_project(m.OUT / 'clustering_ontwerp.gpkg')"
                ),
            ],
            cwd=ROOT,
            check=False,
        )
        if qgis_project_result.returncode != 0:
            log(
                "Waarschuwing: apart QGIS-projectproces eindigde met code "
                f"{qgis_project_result.returncode}."
            )

    log("\nClusterbenutting:")
    print(
        overview[
            [
                "Cluster",
                "Type",
                "KVA",
                "Max_A",
                "Belast_A",
                "Benut_pct",
                "Aantal",
                "Max_route",
            ]
        ].to_string(index=False, float_format=lambda value: f"{value:.1f}"),
        flush=True,
    )
    log(f"\nGereed: {OUT}")


if __name__ == "__main__":
    try:
        main()
    except Exception as exc:
        log(f"FOUT: {exc}")
        raise

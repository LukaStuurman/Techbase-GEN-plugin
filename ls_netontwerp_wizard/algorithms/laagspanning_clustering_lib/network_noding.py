"""Lightweight and incremental trench noding for the QGIS drawing tool."""

from __future__ import annotations

import math
from collections import Counter, defaultdict

import geopandas as gpd
import numpy as np
import pandas as pd
from shapely.geometry import LineString
from shapely.ops import substring, unary_union
from shapely.strtree import STRtree


CRS_RD = "EPSG:28992"


def log(message):
    print(str(message), flush=True)


def line_parts(geometry):
    if geometry is None or geometry.is_empty:
        return
    if geometry.geom_type in ("LineString", "LinearRing"):
        if geometry.length > 1e-7:
            yield LineString(geometry.coords)
        return
    if hasattr(geometry, "geoms"):
        for child in geometry.geoms:
            yield from line_parts(child)


def node_cable_network(cables, points, stations, tolerance_m):
    """Exact planar noding plus local dangling-end and terminal splits."""
    zero_geometries = []
    if "Rekenfactor" in cables.columns:
        zero_geometries.extend(
            cables.loc[
                pd.to_numeric(cables["Rekenfactor"], errors="coerce").fillna(1.0)
                <= 1e-9,
                "geometry",
            ].tolist()
        )
    zero_cost_geometry = unary_union(zero_geometries) if zero_geometries else None
    input_parts = [
        part for geometry in cables.geometry for part in line_parts(geometry)
    ]
    if not input_parts:
        raise RuntimeError("De sleuvenlaag bevat geen bruikbare lijngeometrie")

    exact_parts = list(line_parts(unary_union(input_parts)))
    if not exact_parts:
        raise RuntimeError("Automatisch noden leverde geen bruikbaar kabelnet op")

    tolerance_m = max(0.0, float(tolerance_m))
    connectors = []
    if tolerance_m > 0.0:
        endpoint_count = Counter()
        endpoint_records = []
        for line_index, line in enumerate(exact_parts):
            for coordinate in (line.coords[0], line.coords[-1]):
                key = tuple(np.round(np.asarray(coordinate, dtype=float), 6))
                endpoint_count[key] += 1
                endpoint_records.append((line_index, coordinate, key))
        tree = STRtree(exact_parts)
        from shapely.geometry import Point

        for own_index, coordinate, key in endpoint_records:
            if endpoint_count[key] != 1:
                continue
            endpoint = Point(coordinate)
            best_distance = math.inf
            best_point = None
            for raw_index in tree.query(endpoint.buffer(tolerance_m)):
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

    noded_parts = (
        list(line_parts(unary_union([*exact_parts, *connectors])))
        if connectors
        else exact_parts
    )
    tree = STRtree(noded_parts)
    split_measures = defaultdict(set)
    for frame in (points, stations):
        for terminal in frame.geometry:
            if terminal is None or terminal.is_empty:
                continue
            line_index = int(tree.nearest(terminal))
            line = noded_parts[line_index]
            measure = float(line.project(terminal))
            if 1e-7 < measure < line.length - 1e-7:
                split_measures[line_index].add(round(measure, 6))

    final_parts = []
    for line_index, line in enumerate(noded_parts):
        boundaries = [
            0.0,
            *sorted(split_measures.get(line_index, ())),
            float(line.length),
        ]
        for start, end in zip(boundaries[:-1], boundaries[1:]):
            if end - start > 1e-7:
                final_parts.extend(line_parts(substring(line, start, end)))

    if zero_cost_geometry is None or zero_cost_geometry.is_empty:
        factors = np.ones(len(final_parts), dtype=float)
    else:
        zero_buffers = [
            line.buffer(0.02)
            for line in line_parts(zero_cost_geometry)
            if line is not None and not line.is_empty
        ]
        zero_tree = STRtree(zero_buffers)
        combined_cache = {}

        def zero_cost(part):
            covered = zero_tree.query(part, predicate="covered_by")
            if len(covered):
                return True
            candidates = zero_tree.query(part)
            if not len(candidates):
                return False
            if len(candidates) == 1:
                return False
            key = tuple(sorted(int(index) for index in candidates))
            combined = combined_cache.get(key)
            if combined is None:
                combined = unary_union([zero_buffers[index] for index in key])
                combined_cache[key] = combined
            return bool(combined.covers(part))

        factors = np.asarray(
            [0.0 if zero_cost(part) else 1.0 for part in final_parts], dtype=float
        )
    return gpd.GeoDataFrame(
        {"Rekenfactor": factors}, geometry=final_parts, crs=cables.crs
    )


def incremental_node_cable_network(
    cables,
    new_routes,
    points,
    stations,
    tolerance_m,
    full_rebuild_fraction=0.60,
):
    """Node only existing features whose topology can change."""
    tolerance_m = max(0.0, float(tolerance_m))
    valid_cables = cables.loc[
        cables.geometry.notna() & ~cables.geometry.is_empty
    ].copy()
    valid_new = new_routes.loc[
        new_routes.geometry.notna() & ~new_routes.geometry.is_empty
    ].copy()
    new_parts = [
        part for geometry in valid_new.geometry for part in line_parts(geometry)
    ]
    if not new_parts:
        raise RuntimeError("De nieuw getekende sleuflaag bevat geen geldige lijn")
    new_geometry = unary_union(new_parts)

    cable_geometries = valid_cables.geometry.tolist()
    tree = STRtree(cable_geometries)
    search_distance = max(tolerance_m, 0.02)
    search_area = new_geometry.buffer(search_distance)
    affected_indices = sorted(
        {
            int(index)
            for index in tree.query(search_area)
            if float(cable_geometries[int(index)].distance(new_geometry))
            <= search_distance + 1e-9
        }
    )
    affected_fraction = len(affected_indices) / max(len(valid_cables), 1)
    if affected_fraction >= float(full_rebuild_fraction):
        factors = pd.to_numeric(
            valid_cables.get("Rekenfactor", 1.0), errors="coerce"
        )
        if hasattr(factors, "fillna"):
            factors = factors.fillna(1.0).to_numpy(dtype=float)
        else:
            factors = np.ones(len(valid_cables), dtype=float)
        combined = gpd.GeoDataFrame(
            {
                "Rekenfactor": np.concatenate(
                    [factors, np.ones(len(valid_new), dtype=float)]
                )
            },
            geometry=[*valid_cables.geometry.tolist(), *valid_new.geometry.tolist()],
            crs=valid_cables.crs,
        )
        log(
            f"Nieuwe sleuf raakt {len(affected_indices):,} van "
            f"{len(valid_cables):,} delen; volledig noden is hier efficiënter."
        )
        return node_cable_network(
            combined, points, stations, tolerance_m
        ), len(affected_indices), False

    affected = valid_cables.iloc[affected_indices].copy()
    untouched = valid_cables.drop(valid_cables.index[affected_indices]).copy()
    affected_factors = pd.to_numeric(
        affected.get("Rekenfactor", 1.0), errors="coerce"
    )
    if hasattr(affected_factors, "fillna"):
        affected_factors = affected_factors.fillna(1.0).to_numpy(dtype=float)
    else:
        affected_factors = np.ones(len(affected), dtype=float)
    local_input = gpd.GeoDataFrame(
        {
            "Rekenfactor": np.concatenate(
                [affected_factors, np.ones(len(valid_new), dtype=float)]
            )
        },
        geometry=[*affected.geometry.tolist(), *valid_new.geometry.tolist()],
        crs=valid_cables.crs,
    )
    local_geometry = unary_union(local_input.geometry.tolist())
    terminal_radius = max(tolerance_m, 5.0)

    def nearby(frame):
        if frame is None or frame.empty:
            return gpd.GeoDataFrame(geometry=[], crs=valid_cables.crs)
        mask = frame.geometry.apply(
            lambda geometry: geometry is not None
            and not geometry.is_empty
            and geometry.distance(local_geometry) <= terminal_radius + 1e-9
        )
        return frame.loc[mask].copy()

    local_noded = node_cable_network(
        local_input,
        nearby(points),
        nearby(stations),
        tolerance_m,
    )
    untouched_factors = pd.to_numeric(
        untouched.get("Rekenfactor", 1.0), errors="coerce"
    )
    if hasattr(untouched_factors, "fillna"):
        untouched_factors = untouched_factors.fillna(1.0).to_numpy(dtype=float)
    else:
        untouched_factors = np.ones(len(untouched), dtype=float)
    result = gpd.GeoDataFrame(
        {
            "Rekenfactor": np.concatenate(
                [untouched_factors, local_noded["Rekenfactor"].to_numpy(dtype=float)]
            )
        },
        geometry=[*untouched.geometry.tolist(), *local_noded.geometry.tolist()],
        crs=valid_cables.crs,
    )
    log(
        f"Snel lokaal noden: {len(affected_indices):,} van "
        f"{len(valid_cables):,} bestaande delen opnieuw berekend; "
        f"{len(untouched):,} delen exact behouden."
    )
    return result, len(affected_indices), True

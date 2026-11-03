"""Validate and calculate an entire edit session in one isolated worker."""
import hashlib
import json
import sys
import traceback
from pathlib import Path


def calculate(engine, frames, operations, maximum_route, preview=False, rules=None):
    import networkx as nx
    import numpy as np
    from scipy.spatial import cKDTree

    rules = dict(rules or {})
    cache = {}
    original_build = engine.build_network

    def cached_build(cables):
        digest = hashlib.sha256()
        for geometry in cables.geometry:
            digest.update(geometry.wkb)
        if "Rekenfactor" in cables:
            digest.update(cables["Rekenfactor"].to_numpy().tobytes())
        key = digest.digest()
        if key not in cache:
            if len(cache) >= 32:
                cache.clear()
            cache[key] = original_build(cables)
        return cache[key]

    engine.build_network = cached_build
    if frames.get("plan") is None:
        from shapely.ops import unary_union
        frames["plan"] = engine.gpd.GeoDataFrame(geometry=[unary_union(frames["areas"].geometry.tolist())], crs=frames["areas"].crs)
    state = [frames[name].copy() for name in ("connections", "stations", "areas", "routes", "cables")]
    moved_ids = set()
    retired = []
    relocated = []
    route_summaries = []

    def move(ids, target):
        nonlocal state
        stations = state[1]
        row = stations.loc[stations.Cluster.astype(str) == target]
        if len(row) != 1:
            raise ValueError(f"Doelstation {target} ontbreekt of is niet uniek.")
        ids = {int(x) for x in ids}
        members = state[0].loc[state[0].__src_fid.isin(ids)]
        if len(members) != len(ids):
            raise ValueError("Een geselecteerde aansluiting ontbreekt; vernieuw de wachtrij.")
        changing = members.loc[members.Cluster.astype(str) != target]
        if changing.empty:
            return
        result = engine.recalculate_manual_assignment(
            *state, selected_source_fids=set(changing.__src_fid.astype(int)),
            target_station_source_fid=int(row.iloc[0]["__src_fid"]),
            max_route_m=maximum_route, node_tolerance_m=0.0,
            plan_layer=frames.get("plan"), defer_area_rebuild=True,
        )
        state = list(result[:5])
        moved_ids.update(changing.__src_fid.astype(int))
        route_summaries.append(result[5])

    def branch_groups(source):
        """Keep terminals on the same outgoing route branch/apartment together."""
        points, stations, _, routes, cables = state
        members = points.loc[points.Cluster.astype(str) == source]
        if members.empty:
            return []
        route = routes.loc[routes.Cluster.astype(str) == source].iloc[0].geometry
        route_frame = engine.gpd.GeoDataFrame(geometry=[route], crs=routes.crs)
        graph = cached_build(route_frame)
        if not graph:
            return [list(members.__src_fid.astype(int))]
        nodes = list(graph)
        tree = cKDTree(np.asarray(nodes))
        station = stations.loc[stations.Cluster.astype(str) == source].iloc[0]
        root = nodes[int(tree.query([station.geometry.x, station.geometry.y])[1])]
        paths = nx.single_source_dijkstra_path(graph, root, weight="weight")
        groups = {}
        for _, member in members.iterrows():
            node = nodes[int(tree.query([member.geometry.x, member.geometry.y])[1])]
            path = paths.get(node)
            if not path:
                return [list(members.__src_fid.astype(int))]
            key = tuple(path[:2]) if len(path) > 1 else (root,)
            groups.setdefault(key, []).append(int(member["__src_fid"]))
        # A flat/multistory object must never be split between stations.
        if "Multistory" in members:
            for _, flat in members.groupby("Multistory"):
                value = str(flat.iloc[0]["Multistory"]).strip()
                if value in ("", "None", "nan", "0"):
                    continue
                ids = set(flat.__src_fid.astype(int))
                keys = [key for key, group in groups.items() if ids.intersection(group)]
                if len(keys) > 1:
                    merged = []
                    for key in keys:
                        merged.extend(groups.pop(key))
                    groups[keys[0]] = merged
        return sorted(groups.values(), key=lambda ids: -len(ids))

    def redistribute(source):
        """Search a bounded set of complete, route-checked branch assignments."""
        nonlocal state
        groups = branch_groups(source)
        if not groups:
            return
        graph = cached_build(state[4])
        nodes = list(graph)
        tree = cKDTree(np.asarray(nodes))
        distances = {}
        for _, station in state[1].iterrows():
            name = str(station.Cluster)
            if name == source:
                continue
            node = nodes[int(tree.query([station.geometry.x, station.geometry.y])[1])]
            distances[name] = nx.single_source_dijkstra_path_length(graph, node, cutoff=maximum_route, weight="weight")
        attempts = [0]

        def search(index):
            nonlocal state
            if index == len(groups):
                return True
            ids = groups[index]
            points = state[0].loc[state[0].__src_fid.isin(ids)]
            load = float(points.Ontwerp_A.sum())
            point_nodes = [nodes[int(tree.query([p.x, p.y])[1])] for p in points.geometry]
            candidates = []
            for _, station in state[1].iterrows():
                name = str(station.Cluster)
                if name == source:
                    continue
                existing_load = float(state[0].loc[state[0].Cluster.astype(str) == name, "Ontwerp_A"].sum())
                if existing_load + load > float(station.KVA) / .23 / 3 + 1e-6:
                    continue
                lengths = [distances[name].get(node, float("inf")) for node in point_nodes]
                if max(lengths, default=0) <= maximum_route:
                    candidates.append((sum(lengths), name))
            for _, target in sorted(candidates)[:8]:
                attempts[0] += 1
                if attempts[0] > 120:
                    return False
                before = state
                previous_moved = set(moved_ids)
                try:
                    move(ids, target)
                    if search(index + 1):
                        return True
                except (RuntimeError, ValueError):
                    pass
                state = before
                moved_ids.clear()
                moved_ids.update(previous_moved)
            return False

        if not search(0):
            raise ValueError(f"Geen geldige herverdeling gevonden voor {source}. Kies een doelstation of pas eerst kabeltakken aan; het ontwerp is niet gewijzigd.")

    try:
        for index, operation in enumerate(operations, 1):
            engine.log(f"Wijziging {index} van {len(operations)} controleren...")
            kind = operation["kind"]
            if kind == "allow":
                rules.pop(str(operation["station"]), None)
                continue
            if kind == "protect":
                name = str(operation["station"])
                row = state[1].loc[state[1].Cluster.astype(str) == name]
                if len(row) != 1:
                    raise ValueError(f"Station {name} is niet meer actief in het ontwerp.")
                station = row.iloc[0]
                rules[name] = {**rules.get(name, {}), "type": str(station.Type),
                               "x": float(station.geometry.x), "y": float(station.geometry.y),
                               "kva": float(station.KVA), "protected": bool(operation.get("protected", True))}
                continue
            if kind == "move":
                move(operation["point_ids"], str(operation["target"]))
                continue
            if kind == "relocate":
                # Move only a newly designed station; existing stations stay
                # anchored to the source inventory. The target must be an
                # *existing* noded cable vertex inside this station's cluster.
                source = str(operation["source"])
                points, stations, areas, routes, cables = state
                rows = stations.loc[stations.Cluster.astype(str) == source]
                if len(rows) != 1:
                    raise ValueError(f"Station {source} ontbreekt of is niet uniek.")
                station = rows.iloc[0]
                if not str(station.Type).strip().casefold().startswith("nieuw"):
                    raise ValueError("Alleen nieuw geplaatste stations kunnen worden verplaatst.")
                raw_x, raw_y = float(operation["x"]), float(operation["y"])
                if not (np.isfinite(raw_x) and np.isfinite(raw_y)):
                    raise ValueError("De gekozen stationslocatie is ongeldig.")
                new_point = engine.Point(raw_x, raw_y)
                if new_point.distance(station.geometry) < 0.01:
                    raise ValueError("Het station staat al op deze netwerklocatie.")
                area_rows = areas.loc[areas.Cluster.astype(str) == source]
                if len(area_rows) != 1:
                    raise ValueError(f"Clustergebied van {source} ontbreekt.")
                in_area = engine.gpd.GeoSeries([new_point], crs=stations.crs).to_crs(areas.crs).iloc[0]
                if not area_rows.iloc[0].geometry.buffer(0.05).covers(in_area):
                    raise ValueError(f"De nieuwe locatie ligt buiten het clustergebied van {source}.")
                cable_point = engine.gpd.GeoSeries([new_point], crs=stations.crs).to_crs(cables.crs).iloc[0]
                graph = cached_build(cables)
                nodes = list(graph.nodes)
                if not nodes:
                    raise ValueError("Het sleuvennet is leeg.")
                distance, position = cKDTree(np.asarray(nodes, dtype=float)).query(
                    [cable_point.x, cable_point.y]
                )
                # build_network deliberately rounds each graph vertex to 0.1 m;
                # a real QGIS trench vertex can be up to ~0.071 m from it.
                if distance > 0.08:
                    raise ValueError(
                        "De locatie ligt niet op een bestaande netwerkknoop van een sleuf. "
                        "Kies een gesnapte sleufknoop binnen het cluster."
                    )
                node = nodes[int(position)]
                exact_point = engine.gpd.GeoSeries(
                    [engine.Point(*node)], crs=cables.crs
                ).to_crs(stations.crs).iloc[0]
                edited = stations.copy()
                edited.at[rows.index[0], "geometry"] = exact_point
                rd_point = engine.gpd.GeoSeries(
                    [exact_point], crs=stations.crs
                ).to_crs(engine.CRS_RD).iloc[0]
                if "Net_X" in edited:
                    edited.at[rows.index[0], "Net_X"] = float(rd_point.x)
                if "Net_Y" in edited:
                    edited.at[rows.index[0], "Net_Y"] = float(rd_point.y)
                if "Plaatsing" in edited:
                    edited.at[rows.index[0], "Plaatsing"] = "Handmatig verplaatst"
                state[1] = edited
                result = engine.recalculate_manual_assignment(
                    *state, selected_source_fids=set(),
                    target_station_source_fid=0,
                    max_route_m=maximum_route, node_tolerance_m=0.0,
                    plan_layer=frames.get("plan"), refresh_all_routes=True,
                    refresh_cluster_names={source}, defer_area_rebuild=True,
                    relocated_station_names={source},
                )
                if source in result[5].get("preserved_route_clusters", []):
                    raise ValueError(
                        f"De nieuwe locatie van {source} heeft geen geldige kabelroute; "
                        "de vorige route mag niet behouden blijven."
                    )
                route_geometry = result[3].loc[
                    result[3].Cluster.astype(str) == source
                ].iloc[0].geometry
                route_point = engine.gpd.GeoSeries(
                    [exact_point], crs=stations.crs
                ).to_crs(result[3].crs).iloc[0]
                if route_geometry is None or route_geometry.is_empty or route_geometry.distance(route_point) > 0.02:
                    raise ValueError(
                        f"De herberekende kabelroute van {source} begint niet bij de nieuwe stationslocatie."
                    )
                state = list(result[:5])
                rules[source] = {
                    **rules.get(source, {}), "type": "Nieuw",
                    "x": float(rd_point.x), "y": float(rd_point.y),
                    "kva": float(station.KVA), "protected": True,
                }
                relocated.append(source)
                route_summaries.append(result[5])
                continue
            if kind != "retire":
                raise ValueError("Onbekende clusterwijziging.")
            source = str(operation["source"])
            if rules.get(source, {}).get("protected"):
                raise ValueError(f"Station {source} is beschermd. Hef de bescherming eerst op.")
            row = state[1].loc[state[1].Cluster.astype(str) == source]
            if len(row) != 1:
                raise ValueError(f"Station {source} ontbreekt of staat dubbel in de wachtrij.")
            station = row.iloc[0]
            target = operation.get("target")
            if target == source:
                raise ValueError("Bronstation en doelstation moeten verschillend zijn.")
            ids = state[0].loc[state[0].Cluster.astype(str) == source, "__src_fid"].astype(int).tolist()
            if ids:
                if target:
                    move(ids, str(target))
                else:
                    redistribute(source)
            if (state[0].Cluster.astype(str) == source).any():
                raise ValueError(f"Station {source} heeft nog aansluitingen.")
            record = {"type": str(station.Type), "status": "Te verwijderen" if str(station.Type).casefold() == "bestaand" else "Vervallen",
                      "x": float(station.geometry.x), "y": float(station.geometry.y), "kva": float(station.KVA), "protected": False, "radius": float(operation.get("radius", 20.0))}
            rules[source] = record
            retired.append(source)
            for frame_index in (1, 2, 3):
                state[frame_index] = state[frame_index].loc[state[frame_index].Cluster.astype(str) != source].copy()
        if not preview and len(state[1]) and (moved_ids or retired or relocated):
            # A single final coverage rebuild for the entire queue. Retain all
            # checked routes instead of changing an unrelated cluster's route.
            result = engine.recalculate_manual_assignment(
                *state, selected_source_fids=set(), target_station_source_fid=0,
                max_route_m=maximum_route, node_tolerance_m=0.0,
                plan_layer=frames.get("plan"), refresh_all_routes=True,
                preserve_all_routes=True,
            )
            state = list(result[:5])
        elif not len(state[1]) and len(state[0]):
            raise ValueError("Er blijven aansluitingen zonder station over.")
        return state, {"moved_count": len(moved_ids), "removed_source_clusters": retired,
                       "station_rules": rules, "preview": preview,
                       "relocated_stations": relocated,
                       "maximum_route_m": float(state[0].Route_m.max()) if len(state[0]) else 0,
                       "target_cluster": "meerdere stations",
                       "station_overview": [{"cluster": str(row.Cluster), "load": float(state[0].loc[state[0].Cluster.astype(str)==str(row.Cluster),"Ontwerp_A"].sum()), "capacity": float(row.KVA)/.23/3} for _,row in state[1].iterrows()]}
    finally:
        engine.build_network = original_build


def main(path):
    import maak_clustering_engine as engine
    config = json.loads(Path(path).read_text(encoding="utf-8"))
    engine.log = lambda text: print(text, flush=True)
    frames = {name: engine.gpd.read_file(spec["path"], layer=spec["layer"]) for name, spec in config["inputs"].items()}
    preview = config.get("preview", False)
    state, summary = calculate(engine, frames, config["operations"], config["max_route_m"], preview, config.get("station_rules"))
    if not preview:
        engine.write_manual_cluster_snapshot(Path(config["backup_path"]), *(frames[n] for n in ("connections", "stations", "areas", "routes", "cables")), frames.get("plan"))
        engine.write_manual_cluster_snapshot(Path(config["result_path"]), *state, frames.get("plan"))
    Path(config["summary_path"]).write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    print("Voorstel gecontroleerd." if preview else "Alle wijzigingen berekend; gebieden Ã©Ã©n keer opgebouwd.", flush=True)


if __name__ == "__main__":
    try:
        main(sys.argv[1])
    except Exception:
        traceback.print_exc()
        sys.exit(1)

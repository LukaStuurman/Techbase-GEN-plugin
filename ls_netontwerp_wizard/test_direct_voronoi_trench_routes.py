"""Regression tests: direct connected fallback, existing stations and exact trenches."""

import os
import sys
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    import geopandas as gpd
    import networkx as nx
    import numpy as np
    from shapely.geometry import LineString
    from ls_netontwerp_wizard.algorithms.laagspanning_clustering_lib import (
        maak_clustering_engine as engine,
    )

    # A previous design already provides Max_A even when Status is descriptive.
    kva = engine.station_capacity_kva(
        {"KVA": float("nan"), "Max_A": "217", "Status": "Bestaand"}
    )
    assert abs(kva - 217 * 0.69) < 1e-7
    assert engine.station_capacity_kva(
        {"KVA": "150", "Max_A": 0, "Status": "Bestaand"}
    ) == 150
    assert engine.station_capacity_kva(
        {"KVA": None, "Max_A": None, "Status": "Trafo 150KVA"}
    ) == 150
    assert engine.station_capacity_kva(
        {"KVA": 150, "Max_A": 217, "Status": "Trafo 150KVA"}, 200
    ) == 200
    try:
        engine.station_capacity_kva(
            {"KVA": None, "Max_A": None, "Status": "Bestaand"}
        )
    except ValueError:
        pass
    else:
        raise AssertionError("Unknown station capacity was silently invented")

    # Nodes stay rounded for graph connectivity, but output routes must use
    # the actual input trench coordinates (not a rounded diagonal shortcut).
    trench = LineString([
        (100.03, 200.02), (101.37, 201.08), (103.21, 202.42),
    ])
    cables = gpd.GeoDataFrame(
        {"Rekenfactor": [1.0]}, geometry=[trench], crs=engine.CRS_RD
    )
    graph = engine.build_network(cables)
    nodes = list(graph.nodes)
    source = tuple(round(value, 1) for value in trench.coords[0])
    target = tuple(round(value, 1) for value in trench.coords[-1])
    assert source in graph and target in graph
    lines, _lengths, distances = engine.build_exclusive_routes(
        graph, nodes, np.zeros(len(nodes), dtype=int),
        [source], [target], np.zeros(1, dtype=int),
    )
    assert lines[0].symmetric_difference(trench).length < 1e-6
    assert distances[0] > 0

    # A reachable existing station with sufficient capacity must not become
    # unused solely because optional new-station candidates were generated.
    simple = nx.path_graph([(float(index), 0.0) for index in range(8)])
    nx.set_edge_attributes(simple, 1.0, "weight")
    simple_nodes = list(simple.nodes)
    adjacency = nx.to_scipy_sparse_array(
        simple, nodelist=simple_nodes, weight="weight",
        format="csr", dtype=float,
    )
    engine.CPU_THREADS = 1
    engine.MAX_ROUTE_M = 850.0
    assignment, _util, ownership, selected, _distance = (
        engine.solve_greedy_voronoi_connected_assignment(
            adjacency, simple_nodes, np.array([7]), np.array([100.0]),
            np.array([0]), [3], np.array([217.0]), 913.0,
            np.arange(len(simple_nodes)), np.zeros(len(simple_nodes), dtype=int),
        )
    )
    assert selected == [] and assignment.tolist() == [0]
    assert ownership[0] == 0
    print("DIRECT_VORONOI_STATION_TRENCH_OK", flush=True)
    os._exit(0)


if __name__ == "__main__":
    main()

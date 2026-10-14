"""Compare faster calculations with independent existing geometry/graph methods."""
from pathlib import Path
import ast
import os
import subprocess
import sys
import numpy as np
import networkx as nx
from qgis.core import QgsApplication


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    app = QgsApplication([], False)
    app.initQgis()
    from ls_netontwerp_wizard.algorithms.laagspanning_clustering_tool import LaagspanningClusteringAlgorithm
    from ls_netontwerp_wizard import automatic_clustering_optimization as optimization
    from ls_netontwerp_wizard.automatic_clustering_optimization import _make_greedy_solver, _install_distance_cache
    original = LaagspanningClusteringAlgorithm._load_engine()
    fast = LaagspanningClusteringAlgorithm._load_engine()
    original.log = fast.log = lambda *_: None
    original.CPU_THREADS = fast.CPU_THREADS = 1
    original.MAX_ROUTE_M = fast.MAX_ROUTE_M = 200
    # Compare with the actual optimized fallback shipped in v1.22, not the
    # older unused full-graph fallback still present in the engine module.
    reference_source = subprocess.check_output([os.environ.get("LS_TEST_GIT", "git"), "show",
        "ae919c046cefcb644e89b95d3953a95a52ea3387:ls_netontwerp_wizard/automatic_clustering_optimization.py"],
        cwd=Path(__file__).resolve().parent.parent).decode("utf-8")
    reference_tree = ast.parse(reference_source)
    reference_function = next(node for node in reference_tree.body if isinstance(node, ast.FunctionDef) and node.name == "_make_greedy_solver")
    namespace = dict(vars(optimization))
    exec(compile(ast.Module(body=[reference_function], type_ignores=[]), "<released-v1.22-fallback>", "exec"), namespace)
    _install_distance_cache(original)
    reference_solver = namespace["_make_greedy_solver"](original)
    _install_distance_cache(fast)
    from shapely.geometry import LineString, Point
    from shapely.ops import unary_union
    parts = [LineString([(0, 0), (5, 0), (5, 5)]), LineString([(5, 5), (8, 9)])]
    xy = np.array([(0, 0), (2, .08), (2, .080000001), (5, 6), (6, 8), (100, 100)], dtype=float)
    reference = np.array([Point(point).distance(unary_union(parts)) for point in xy])
    measured = fast.linework_distances(xy, parts, .08)
    np.testing.assert_allclose(reference, measured, rtol=0, atol=1e-12)
    assert np.array_equal(reference <= .08, measured <= .08)
    assert np.isinf(fast.linework_distances(xy, [])).all()
    assert fast.linework_distances(np.empty((0, 2)), parts).shape == (0,)
    route_nodes = [(float(i), 0.0) for i in range(100)]
    route_graph = nx.path_graph(route_nodes)
    nx.set_edge_attributes(route_graph, 1.0, "weight")
    routes, lengths, distances = fast.build_exclusive_routes(
        route_graph, route_nodes, np.zeros(len(route_nodes), dtype=int),
        [route_nodes[0]], [route_nodes[50], route_nodes[99]], np.zeros(2, dtype=int))
    assert routes[0].equals(LineString([route_nodes[0], route_nodes[99]]))
    np.testing.assert_array_equal(lengths, [99.0])
    np.testing.assert_array_equal(distances, [50.0, 99.0])
    cases = [
        # Enough capacity, empty candidates, zero-amp demand and root ownership.
        ([5, 10, 15, 20], [1, 0, 2, 1], [0], [25, 35], [8], 8),
        # Capacity balancing, ties and candidate pruning.
        ([5, 10, 15, 20, 25, 30, 35], [3, 2, 3, 2, 3, 2, 3], [0], [15, 25, 40], [6], 7),
        ([0, 10, 20, 30, 40], [1, 2, 4, 2, 1], [0, 40], [15, 25], [3, 3], 4),
        # Exhaust the iteration budget / candidate locations with indivisible
        # demand: both versions must refuse rather than relax hard capacity.
        ([5, 10], [100, 100], [0], [15], [1], 1),
    ]
    graph = nx.path_graph([(float(i), 0.0) for i in range(41)])
    nx.set_edge_attributes(graph, 1.0, "weight")
    nodes = list(graph.nodes)
    adjacency = nx.to_scipy_sparse_array(graph, nodelist=nodes, weight="weight", format="csr", dtype=float)
    for units, loads, existing, candidates, capacities, new_capacity in cases:
        answers = []
        for engine, solver in ((original, reference_solver), (fast, _make_greedy_solver(fast))):
            try:
                answers.append(solver(adjacency, nodes, np.array(units), np.array(loads, dtype=float), np.array(existing),
                    list(candidates), np.array(capacities, dtype=float), new_capacity, np.arange(len(nodes)), np.zeros(len(nodes), dtype=int)))
            except RuntimeError as exc:
                answers.append(str(exc))
        if isinstance(answers[0], str):
            assert answers[0] == answers[1], answers
        else:
            for before, after in zip(*answers):
                np.testing.assert_array_equal(before, after)
    print("AUTO_CLUSTER_EFFICIENCY_TEST_OK (identical assignments, candidate choices, node ownership, distances, capacities, ties and impossible demands)", flush=True)
    app.exitQgis()


if __name__ == "__main__":
    main()

"""Integration-style test for preservation -> exclusively new-station assignment.

Uses actual geometries/units and a deterministic residual Voronoi stub so
the invariant is independent of QGIS, matplotlib and the heavy engine itself.
"""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import numpy as np
import geopandas as gpd
import networkx as nx
from shapely.geometry import Point,LineString
from scipy.sparse import csgraph
from ls_netontwerp_wizard.existing_locked_clustering import (
    prepare_retention,solve_locked_voronoi,
)


def test():
    station="044.529"
    points=gpd.GeoDataFrame({
        "Station":[station]*4+[""],
        "Kabel Subgroep":["K01-00","K01-01","K01-02","K01-03",""],
        "Master Asset ID":["a00","a01","a02","a03","new"],
        "Ontwerpstroom":[20.,15.,30.,25.,50.],
        "Opwek ontwerpstroom":[0.]*5,
        "Ontwerpstroom kabel":[20.,15.,30.,25.,50.],
        "Kabel opwek ontwerpstroom":[0.]*5,
    },geometry=[
        Point(95,0),Point(40,30),Point(80,20),Point(60,30),Point(160,0),
    ],crs="EPSG:28992")
    stations=gpd.GeoDataFrame({
        "Stationsnaa":[station],"Max_A":[217.],
    },geometry=[Point(0,0)],crs="EPSG:28992")
    cable_frame=gpd.GeoDataFrame({
        "Kabel Subgroep":["K01-00","K01-01","K01-02","K01-03",""],
        "Type":["4*150mm2 Al","4*95mm2 Al","4*50mm2 Cu",
                "4*70mm2 Al","4*150mm2 Al"],
    },geometry=[
        LineString([(0,0),(100,0)]),
        LineString([(40,0),(40,30)]),
        LineString([(80,0),(80,20)]),
        LineString([(60,0),(60,30)]),
        LineString([(100,0),(160,0)]),
    ],crs="EPSG:28992")
    retention=prepare_retention(points,stations,cable_frame,850.)
    assert len(retention["retained_by_index"])==4
    assert retention["all_original_by_index"].keys()=={0,1,2,3}
    assert retention["retention"]["richtingen"][(station,"K01-00")]["belasting_a"]==90.

    # Build graph from exact GEN cable segment geometries; new spur begins
    # on a distinct downstream cable, beyond last originally retained
    # connection, and never uses the reserved old main section.
    from ls_netontwerp_wizard.existing_group_trace import trace_group_cables
    from ls_netontwerp_wizard.existing_station_retention import Cable
    traced=trace_group_cables(points.iloc[:4],stations,cable_frame)
    graph=nx.Graph()
    from ast import literal_eval
    for cable in traced["cables"]:
        u=literal_eval(cable.from_node)
        v=literal_eval(cable.to_node)
        graph.add_edge(
            u,v,weight=cable.length_m,
            route_geometry=traced["edge_geometries"][cable.id],
        )
    graph.add_edge(
        (100.,0.),(120.,0.),weight=20.,
        route_geometry=LineString([(100,0),(120,0)]),
    )
    graph.add_edge(
        (120.,0.),(160.,0.),weight=40.,
        route_geometry=LineString([(120,0),(160,0)]),
    )
    nodes=list(graph.nodes)
    node_index={node:i for i,node in enumerate(nodes)}
    point_indices=np.asarray([
        node_index[(95.,0.)],node_index[(40.,30.)],
        node_index[(80.,20.)],node_index[(60.,30.)],node_index[(160.,0.)],
    ],dtype=int)
    calls=[]
    def stub_solver(adjacency, node_list, free_units, loads,
                    existing_sources, proposed_sources, existing_cap,
                    new_cap, regular_nodes, comps, preferred):
        # Real residual graph still must connect chosen new station to
        # every free consumer via only unreserved physical cable pieces.
        assert len(existing_sources)==0
        assert len(free_units)==1
        assert len(loads)==1 and loads[0]==50
        assert proposed_sources
        source=next((i for i in proposed_sources
                     if node_list[i]==(120.,0.)),proposed_sources[0])
        graph_dist=csgraph.dijkstra(adjacency,indices=[source])
        assert np.isfinite(graph_dist[0,free_units[0]])
        assert graph_dist[0,free_units[0]]==40.
        calls.append(True)
        return (
            np.asarray([0],dtype=int),0.2,
            np.zeros(len(node_list),dtype=int),
            [proposed_sources.index(source)],
            np.asarray([40.],dtype=float),
        )
    result=solve_locked_voronoi(
        graph,nodes,point_indices,np.array([20.,15.,30.,25.,50.]),
        np.arange(5),[station],np.asarray([node_index[(0.,0.)]]),
        np.asarray([node_index[(0.,0.)],node_index[(120.,0.)]]),
        retention,250.,850.,stub_solver,lambda text:None,
    )
    assert calls
    assert result["assignment"].tolist()==[0,0,0,0,1]
    assert result["new_nodes"]==[(120.,0.)]
    assert result["node_cluster"][node_index[(0.,0.)]]==0
    assert result["node_cluster"][node_index[(160.,0.)]]==1
    assert all(result["node_cluster"][node_index[(xy,0.)]]==0
               for xy in (40.,60.,80.,95.))
    assert not any((120.,0.) in edge or (160.,0.) in edge
                   for edge in result["reserved"])
    # The documented -00/-01/-02 branches remain owned by 044.529,
    # not by the new station.
    assert set(result["owner_by_node"].values())=={station}

    # Also exercise the ACTUAL production connected-Voronoi solver. Extract
    # this pure function by AST to avoid requiring QGIS/osgeo/Matplotlib on CI.
    import ast
    from threading import Lock
    from scipy.spatial import cKDTree
    from scipy.sparse.csgraph import dijkstra
    from ls_netontwerp_wizard.existing_locked_clustering import np as real_np
    engine_path=(Path(__file__).resolve().parent /
                 "algorithms/laagspanning_clustering_lib/maak_clustering_engine.py")
    module=ast.parse(engine_path.read_text(encoding="utf-8-sig"))
    solver_ast=next(node for node in module.body
                    if isinstance(node,ast.FunctionDef)
                    and node.name=="solve_greedy_voronoi_connected_assignment")
    scope={"np":real_np, "cKDTree":cKDTree, "dijkstra":dijkstra,
           "Lock":Lock, "MAX_ROUTE_M":850., "TARGET_UTILIZATION":.9,
           "TARGET_UTILIZATION_PENALTY":10000.,
           "log":lambda message:None}
    exec(compile(ast.Module(body=[solver_ast],type_ignores=[]),
                 str(engine_path),"exec"),scope)
    real=solve_locked_voronoi(
        graph,nodes,point_indices,np.array([20.,15.,30.,25.,50.]),
        np.arange(5),[station],np.asarray([node_index[(0.,0.)]]),
        np.asarray([node_index[(0.,0.)],node_index[(120.,0.)]]),
        retention,250.,850.,
        scope["solve_greedy_voronoi_connected_assignment"],
        lambda message:None,
    )
    assert real["assignment"].tolist()==[0,0,0,0,1],real
    assert real["new_nodes"]==[(120.,0.)],real
    print("OLD_STATIONS_LOCKED_NEW_STATIONS_ONLY_OK")


if __name__=="__main__":
    test()

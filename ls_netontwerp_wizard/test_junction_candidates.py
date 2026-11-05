"""New station options must have demand in independent main-cable directions."""
import os,sys
from pathlib import Path


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    import networkx as nx
    import numpy as np
    from ls_netontwerp_wizard.algorithms.laagspanning_clustering_lib import maak_clustering_engine as e
    graph=nx.Graph()
    hub=(0.,0.);left=(-100.,0.);right=(100.,0.);up=(0.,100.);service=(0.,1.)
    for node in (left,right,up,service):graph.add_edge(hub,node,weight=float(np.linalg.norm(node)))
    nodes=list(graph);indices={node:i for i,node in enumerate(nodes)}
    main=[indices[node] for node in (hub,left,right,up)]
    units=[indices[node] for node in (left,right,up,service)]
    result=e.junction_station_candidates(graph,nodes,main,main,units,np.array([120.,300.,350.,20.]),913.)
    assert len(result)==1 and result[0]['index']==indices[hub] and result[0]['directions']==3
    assert result[0]['load']==770.  # Service cable does not create a main direction.
    assert not e.junction_station_candidates(graph,nodes,[indices[left]],main,units,np.array([120.,300.,350.,20.]),913.)
    assert not e.junction_station_candidates(graph,nodes,main,main,units,np.array([0.,0.,350.,20.]),913.)
    assert not e.junction_station_candidates(graph,nodes,main,main,units,np.array([120.,300.,350.,20.]),913.,radius_m=50.)
    # A house service tee with two main directions is not a three-way main junction.
    assert not e.junction_station_candidates(graph,nodes,main,main[:-1],units,np.array([120.,300.,350.,20.]),913.)
    print('JUNCTION_CANDIDATES_TEST_OK (three useful main directions, terminal exclusion, one-sided load exclusion, route radius, service tees excluded)',flush=True)
    os._exit(0)


if __name__=='__main__':main()

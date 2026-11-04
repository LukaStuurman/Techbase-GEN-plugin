"""A feasible discrete demand network must survive weighted-balancing failure."""
import os
import sys
from pathlib import Path


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from qgis.core import QgsApplication
    app=QgsApplication([],False);app.initQgis()
    import numpy as np
    import networkx as nx
    from ls_netontwerp_wizard.algorithms.laagspanning_clustering_tool import LaagspanningClusteringAlgorithm
    from ls_netontwerp_wizard.automatic_clustering_optimization import _make_greedy_solver
    graph=nx.path_graph(16)
    nx.set_edge_attributes(graph,2.,'weight')
    adjacency=nx.to_scipy_sparse_array(graph,format='csr',dtype=float)
    nodes=[(float(i)*2,0.) for i in graph]
    units=np.array([0,1,6,10,11,13,14,15])
    loads=np.array([1.,1.,6.,3.,6.,6.,4.,6.])
    answers=[]
    for optimized in (False,True):
        engine=LaagspanningClusteringAlgorithm._load_engine()
        engine.MAX_ROUTE_M=12.;engine.CPU_THREADS=1
        candidates=[5,10]
        solver=_make_greedy_solver(engine) if optimized else engine.solve_greedy_voronoi_connected_assignment
        assignment,_,ownership,selected,distances=solver(adjacency,nodes,units,loads,
            np.array([0,15]),candidates,np.array([6.,8.]),12.,np.arange(16),np.zeros(16,dtype=int))
        sources=[0,15]+[candidates[i] for i in selected]
        capacities=np.array([6.,8.]+[12.]*len(selected))
        assert np.all(np.bincount(assignment,weights=loads,minlength=len(sources))<=capacities+1e-6)
        assert np.all(distances<=12.+1e-7)
        np.testing.assert_array_equal(ownership[units],assignment)
        for index,source in enumerate(sources):
            assert ownership[source]==index
            owned=graph.subgraph(np.flatnonzero(ownership==index))
            assert nx.is_connected(owned)
            for unit in units[assignment==index]:
                assert nx.shortest_path_length(owned,source,int(unit),weight='weight')<=12.+1e-7
        answers.append((assignment,ownership,selected,distances))
        assert len(selected)==3
        # This indivisible root demand really exceeds the existing station's
        # capacity. Recovery must reject it rather than moving the root load.
        impossible=loads.copy();impossible[0]=7.
        try:solver(adjacency,nodes,units,impossible,np.array([0,15]),[5,10],np.array([6.,8.]),12.,np.arange(16),np.zeros(16,dtype=int))
        except RuntimeError:pass
        else:raise AssertionError('Over-capacity fixed root demand accepted')
    for before,after in zip(*answers):np.testing.assert_array_equal(before,after)
    print('STATION_RECOVERY_TEST_OK (previously rejected feasible network, exact load preservation, route limit, root ownership, connectivity, optimized equivalence, impossible fixed root rejected)',flush=True)
    os._exit(0)


if __name__=='__main__':main()

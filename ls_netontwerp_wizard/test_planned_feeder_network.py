"""New 150Al corridors are planned conductors, not borrowed existing capacity."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import numpy as np,networkx as nx
from shapely.geometry import Point,LineString
from ls_netontwerp_wizard.existing_residual_circuits import CircuitNode
from ls_netontwerp_wizard.planned_feeder_network import add_planned_feeders

def test():
    g=nx.Graph();nodes=[]
    def node(xy,key):
        n=CircuitNode(xy,key);g.add_node(n,physical_xy=xy);nodes.append(n);return n
    units=[]
    for x,key in ((100.,'B'),(200.,'C')):
        a=node((x,0.),key);b=node((x,10.),key);c=node((x,20.),key)
        g.add_edge(a,b,weight=10.,calculation_factor=1.,physical_length=10.,source_asset_id=key+'-main',route_geometry=LineString([a,b]))
        g.add_edge(b,c,weight=1e-6,calculation_factor=0.,physical_length=10.,source_asset_id=key+'-service',route_geometry=LineString([b,c]))
        units.append(nodes.index(c))
    old=(150.,0.);g.add_node(old);nodes.append(old)
    original=list(nodes);line=LineString([(0,0),(250,0)])
    m,n,u,r,a=add_planned_feeders(g,nodes,np.array(units),np.array([0,1]),[],[line],lambda xy:True,lambda _:None)
    assert len(a['transfers'])==2
    assert tuple(n[u[0]])==(100.,10.) and tuple(n[u[1]])==(200.,10.)
    source=min((node for node in n if isinstance(node,CircuitNode) and node.circuit==('ONTWERP','150AL')),key=lambda node:abs(node[0]-150.))
    lengths=nx.single_source_dijkstra_path_length(m,source,weight='weight')
    assert abs(lengths[n[u[0]]]-(abs(source[0]-100)+10))<1e-4 and abs(lengths[n[u[1]]]-(abs(source[0]-200)+10))<1e-4
    assert old not in lengths # same coordinates do not connect to an old wire
    assert not any(d.get('source_asset_id','').endswith('service') for _,_,d in m.edges(data=True))
    planned=[d for _,_,d in m.edges(data=True) if d.get('is_planned')]
    assert all(d['cable_type']=='150AL' and 'source_asset_id' not in d for d in planned)
    assert abs(sum(d['physical_length'] for d in planned)-250.)<1e-6
    assert list(g.nodes)==original and g.number_of_edges()==4
    # Unreachable service evidence stays open; no bridge to a distant road.
    far=LineString([(0,100),(250,100)])
    m,n,u,r,a=add_planned_feeders(g,nodes,np.array(units),np.array([0,1]),[],[far],lambda xy:True,lambda _:None)
    assert not nx.has_path(m,n[u[0]],next(x for x in n if isinstance(x,CircuitNode) and x.circuit==('ONTWERP','150AL')))
    print('PLANNED_150AL_NETWORK_OK (shared new station, source isolation, service endpoint only, real new length)')
if __name__=='__main__':test()

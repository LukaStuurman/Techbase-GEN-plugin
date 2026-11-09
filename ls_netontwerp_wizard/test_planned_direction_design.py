from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import networkx as nx
from shapely.geometry import LineString
from ls_netontwerp_wizard.planned_direction_design import design_station_directions,direction_design_graph

def test():
    g=nx.Graph(planned_150al_network=True)
    g.add_edge((0,0),(100,0),weight=100.,physical_length=100.,calculation_factor=1.,source_asset_id='A',cable_type='50CU',rating_available=True,construction_cost=0.,route_geometry=LineString([(0,0),(100,0)]))
    result=design_station_directions(g,(0,0),{0:(100,0)},{0:100.},{0:0.})
    assert len(result['directions'])==1 and not result['unresolved']
    assert result['directions'][0]['assessment']['reused_length_m']==100.
    # Same physical terminal cannot be split into imaginary independently
    # connected household circuits. A new cable can carry its whole load.
    result=design_station_directions(g,(0,0),{0:(100,0),1:(100,0)},{0:100.,1:100.},{0:0.,1:0.})
    assert not result['unresolved'] and len(result['directions'])==1
    assert result['directions'][0]['assessment']['new_length_m']==100.
    # Distinct terminals sharing a 50Cu main need independent directions.
    for y in (-1,1):
        g.add_edge((100,0),(100,y),weight=1.,physical_length=1.,calculation_factor=1.,is_planned=True,cable_type='150AL',construction_cost=1.,route_geometry=LineString([(100,0),(100,y)]))
    result=design_station_directions(g,(0,0),{0:(100,-1),1:(100,1)},{0:140.,1:140.},{0:0.,1:0.})
    assert len(result['directions'])==2 and not result['unresolved']
    old=[{e for e,(_u,_v,planned) in b['assessment']['edges'].items() if not planned} for b in result['directions']]
    assert not old[0]&old[1]
    assert sum(b['assessment']['reused_length_m'] for b in result['directions'])==100.
    assert sum(b['assessment']['new_length_m'] for b in result['directions'])==102.
    # Generation is not cancelled against consumption; blocked new geometry
    # cannot be accepted as a replacement for an overloaded source cable.
    result=design_station_directions(g,(0,0),{0:(100,-1),1:(100,1)},{0:0.,1:0.},{0:180.,1:180.},geometry_check=lambda _:False)
    assert len(result['unresolved'])==2
    from ls_netontwerp_wizard.existing_residual_circuits import CircuitNode
    a=CircuitNode((0,0),('ONTWERP','150AL'));b=CircuitNode((1,0),('ONTWERP','150AL'))
    c=CircuitNode((2,0),('OTHER','GEN'))
    mesh=nx.Graph();mesh.add_edge(a,b,is_planned=True);mesh.add_edge(b,c,is_planned=True)
    mesh.add_edge(c,'other-wire',source_asset_id='FOREIGN')
    shared=direction_design_graph(mesh,{a:0,b:1,c:1,'other-wire':1},0)
    assert shared.has_edge(a,b) and not shared.has_edge(b,c) and not shared.has_edge(c,'other-wire')
    print('PLANNED_DIRECTION_DESIGN_OK (reuse first, independent conductors, indivisible contacts, separate generation, blocked geometry)')
if __name__=='__main__':test()

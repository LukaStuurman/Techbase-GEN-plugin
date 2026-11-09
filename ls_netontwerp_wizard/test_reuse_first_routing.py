"""Prefer reuse without hiding an excessive real route or unrated wire."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import networkx as nx
from ls_netontwerp_wizard.reuse_first_routing import route_tree

def test():
    g=nx.Graph(planned_150al_network=True)
    g.add_edge('S','old',weight=400.,construction_cost=0.,source_asset_id='A')
    g.add_edge('old','T',weight=10.,construction_cost=10.,is_planned=True)
    g.add_edge('S','T',weight=100.,construction_cost=100.,is_planned=True)
    p,d=route_tree(g,'S',['T'],850.)
    assert p['T']==['old'] and d['T']==410.
    p,d=route_tree(g,'S',['T'],300.)
    assert p['T']==['S'] and d['T']==100.
    g['S']['old']['ov_route']=True
    p,d=route_tree(g,'S',['T'],850.)
    assert p['T']==['S'] and d['T']==100.
    g['S']['old']['ov_route']=False;g['S']['old']['rating_available']=False
    p,d=route_tree(g,'S',['T'],850.)
    assert p['T']==['S'] and d['T']==100.
    print('REUSE_FIRST_ROUTING_OK (reuse, physical limit, OV and unknown type excluded)')
if __name__=='__main__':test()

"""Regression: retain a calculable prefix before releasing a full feeder."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from ls_netontwerp_wizard.existing_station_retention import Cable,OriginalConnection,retain_original

def c(id,edges,load=20,group='K01-00'):
    return OriginalConnection(id,'S',group,tuple(edges),load,0,load,0)

def run():
    cables=[Cable('a','K01-00','s','n1','150AL',40),
            Cable('b','K01-00','n1','n2','150AL',30),
            Cable('c','K01-00','n2','n3','150AL',30)]
    points=[c('near',['a']),c('middle',['a','b']),c('far',['a','b','c'])]
    def retain(points=points,cables=cables,capacity=1000,**kw):
        return retain_original({'S':capacity},points,cables,station_origins={'S':'s'},end_muff_first=True,**kw)
    result=retain(max_route_m=80)
    assert set(result['behouden'])=={'near','middle'},result
    cut=result['eindmof_voorstellen'][0]
    assert cut['Kabeldeel']=='c' and cut['Voorstel_knoop']=='n2',cut
    assert cut['Vrijgegeven_aansluitingen']==('far',),cut
    # Transformer overload must first remove a distal subtree, even when a
    # nearer consumer has higher demand. Retained consumers remain original.
    result=retain([c('near',['a'],40),c('middle',['a','b'],10),c('far',['a','b','c'],20)],capacity=55)
    assert set(result['behouden'])=={'near','middle'},result
    assert result['stations']['S']['pass']
    # All consumers sharing the cut conductor are released together.
    result=retain(points+[c('far2',['a','b','c'])],max_route_m=80)
    assert set(result['vrijgegeven'])=={'far','far2'},result
    # Parent overload: try the remote cabinet feeder, not the upstream trunk.
    branch=Cable('branch','K01-01','n1','bx','150AL',100)
    result=retain([c('near',['a'],40),c('downstream',['branch'],40,'K01-01')],
                  [cables[0],branch],capacity=55,
                  branch_roots={('S','K01-01'):'n1'},parent_routes={('S','K01-01'):('a',)})
    assert result['behouden']==('near',),result
    assert result['eindmof_voorstellen'][0]['Kabeldeel']=='branch',result
    # Unknown LS electrical data: cap before that conductor; known prefix kept.
    unknown=Cable('b','K01-00','n1','n2','6CU',30,rating_available=False)
    result=retain(points[:2],[cables[0],unknown])
    assert result['behouden']==('near',),result
    assert result['eindmof_voorstellen'][0]['Voorstel_knoop']=='n1',result
    # If even the first connection cannot fit, record the attempted cap and
    # release all; no fictitious upstream customer or capacity is invented.
    result=retain([c('near',['a'],40)],[cables[0]],capacity=10)
    assert not result['behouden'] and result['eindmof_voorstellen'],result
    # Real geometry bridge: verified end-cap coordinates, unchanged source,
    # original-only ownership and identical prefix length in the audit.
    import geopandas as gpd
    from shapely.geometry import Point,LineString
    from ls_netontwerp_wizard.existing_locked_clustering import prepare_retention
    p=gpd.GeoDataFrame({'Station':['S']*3,'Kabel Subgroep':['K01-00']*3,
        'Master Asset ID':['near','middle','far'],'Ontwerpstroom':[20.]*3,
        'Opwek ontwerpstroom':[0.]*3,'Ontwerpstroom kabel':[20.]*3,
        'Kabel opwek ontwerpstroom':[0.]*3},geometry=[Point(40,0),Point(70,0),Point(100,0)],crs=28992)
    stations=gpd.GeoDataFrame({'Stationsnaa':['S'],'Max_A':[1000.]},geometry=[Point(0,0)],crs=28992)
    wires=gpd.GeoDataFrame({'Kabel Subgroep':['K01-00'],'Type':['150AL']},geometry=[LineString([(0,0),(100,0)])],crs=28992)
    original=wires.copy(deep=True)
    prepared=prepare_retention(p,stations,wires,80)
    assert prepared['retained_by_index']=={0:'S',1:'S'},prepared
    proposal=prepared['retention']['eindmof_voorstellen'][0]
    assert (proposal['X'],proposal['Y'])==(70.,0.),proposal
    assert wires.equals(original)
    assert sum(line.length for line in prepared['physical_by_station']['S'].values())==70.
    # Collinear source type boundaries may merge in the routing graph.
    # The complete edge must still be within ONE retained station union.
    import networkx as nx
    from ls_netontwerp_wizard.existing_locked_clustering import _select_reserved_edges,RetentionSeparationError
    graph=nx.Graph();graph.add_edge((0,0),(70,0),route_geometry=LineString([(0,0),(70,0)]))
    sections={'S':{'first':LineString([(0,0),(40,0)]),'second':LineString([(40,0),(70,0)])}}
    reserved=_select_reserved_edges(graph,list(graph.nodes),sections)
    assert set(reserved.values())=={'S'},reserved
    for bad in ({'S':{'first':LineString([(0,0),(40,0)])}},
                {'S':{'first':LineString([(0,0),(30,0)]),'second':LineString([(40,0),(70,0)])}}):
        try:_select_reserved_edges(graph,list(graph.nodes),bad)
        except ValueError:pass
        else:raise AssertionError('Reserved an unretained tail or a source gap')
    overlap=dict(sections,T={'same':LineString([(0,0),(70,0)])})
    try:_select_reserved_edges(graph,list(graph.nodes),overlap)
    except RetentionSeparationError:pass
    else:raise AssertionError('Shared physical old feeder was accepted')
    # A flat's explicit terminal may use an already present indoor zero-metre
    # graph link. Missing relation, counted cable or foreign ownership cannot
    # be used as a shortcut to a reserved old feeder.
    from collections import defaultdict
    from ls_netontwerp_wizard.existing_locked_clustering import reserve_original_terminal_links
    nodes=[(0.,0.),(7.,0.),(8.,0.)]
    flatgraph=nx.Graph();flatgraph.add_edge(nodes[0],nodes[1],weight=1e-6,calculation_factor=0.)
    flatgraph.add_edge(nodes[1],nodes[2],weight=1.,calculation_factor=1.)
    info={'retained_by_index':{0:'S'},'equipment_terminals':{0:{'flatkast':'F','netanker_xy':nodes[0]}}}
    owners={nodes[0]:'S'};reserved={};by=defaultdict(set)
    reserve_original_terminal_links(flatgraph,nodes,[1],[0],info,owners,reserved,by)
    assert owners[nodes[1]]=='S' and len(reserved)==1
    for modified,target,initial in (
        ({'retained_by_index':{0:'S'},'equipment_terminals':{}},1,{nodes[0]:'S'}),
        (info,2,{nodes[0]:'S'}),
        (info,1,{nodes[0]:'S',nodes[1]:'T'})):
        owners=dict(initial);reserved={}
        reserve_original_terminal_links(flatgraph,nodes,[target],[0],modified,owners,reserved,defaultdict(set))
        assert not reserved,(modified,target,initial,reserved)
    from ls_netontwerp_wizard.existing_locked_clustering import reserve_station_zero_links
    stationgraph=nx.Graph();stationgraph.add_edge(nodes[0],nodes[1],weight=1e-6,calculation_factor=0.)
    owners={nodes[0]:'S',nodes[1]:'S'};by=defaultdict(set,{'S':set(owners)});reserved={}
    reserve_station_zero_links(stationgraph,nodes,[0],['S'],owners,reserved,by)
    assert len(reserved)==1
    owners={nodes[0]:'S',nodes[1]:'T'};by=defaultdict(set,{'S':{nodes[0]},'T':{nodes[1]}});reserved={}
    reserve_station_zero_links(stationgraph,nodes,[0],['S'],owners,reserved,by)
    assert not reserved and owners[nodes[1]]=='T'
    # Route-only OV and excluded service cables never receive a proposed LS
    # end cap, even when transformer capacity forces a service transfer.
    ov=Cable('ov','K01-00','s','light','6CU',100,electrical_check=False,ov_route=True)
    result=retain([c('light',['ov'],40)],[ov],capacity=10)
    assert not result['behouden'] and not result['eindmof_voorstellen'],result
    assert 'OV-route' in result['redenen']['light']
    lead=Cable('lead','K01-00','s','house','6CU',20,calculation_factor=0.,rating_available=False)
    result=retain([c('house',['lead'],40)],[lead],capacity=10)
    assert not result['eindmof_voorstellen'] and 'buiten rekenbibliotheek' not in result['redenen']['house'],result
    combined=Cable('combined','K01-00','s','end','150AL',100,protect_ov=True)
    result=retain([c('house',['combined'],40)],[combined],capacity=10)
    assert result['eindmof_voorstellen'][0]['OV_continuiteit_controleren'],result
    print('END_MUFF_FIRST_TEST_OK (route, transformer, subtree, cabinet, unknown LS, no viable prefix)')

if __name__=='__main__':run()

"""Shared trench is not a shared conductor; new-side terminals stay separate."""
from pathlib import Path
import sys,pickle
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import networkx as nx
import numpy as np
from shapely.geometry import LineString
from ls_netontwerp_wizard.existing_residual_circuits import CircuitNode,add_released_circuits
from ls_netontwerp_wizard.existing_station_retention import OriginalConnection

def test():
    old=OriginalConnection('old','S','A-00',('S|A-00|a',),10,0,10,0)
    free=OriginalConnection('free','S','B-00',('S|B-00|b','S|B-00|s'),10,0,10,0)
    main=LineString([(0,0),(50,0),(100,0)]);service=LineString([(100,0),(100,5)])
    graph=nx.Graph();graph.add_edge((0.,0.),(50.,0.),weight=50.);graph.add_edge((50.,0.),(100.,0.),weight=50.)
    graph.add_edge((100.,0.),(100.,5.),weight=1e-6)
    nodes=list(graph.nodes)
    info=dict(retained_by_index={0:'S'},all_original_by_index={0:old,1:free},connections_by_index={0:[old],1:[free]},
        edge_geometries={'S|A-00|a':main,'S|B-00|b':main,'S|B-00|s':service},
        edge_source_assets={'S|A-00|a':('physical-A',),'S|B-00|b':('physical-B',),'S|B-00|s':('service-B',)},
        edge_calculation_factors={'S|A-00|a':1.,'S|B-00|b':1.,'S|B-00|s':0.},
        retention={'whole_path_edge_ids':{'old':old.edge_ids,'free':free.edge_ids}})
    indices=np.array([nodes.index((100.,0.)),nodes.index((100.,5.))])
    m,n,u,r,a=add_released_circuits(graph,nodes,indices,np.array([0,1]),[1],[nodes.index((50.,0.))],info,lambda _:None)
    new=n[int(u[1])];assert isinstance(new,CircuitNode) and tuple(new)==(100.,5.)
    assert new!=(100.,5.) and (100.,5.)!=new
    assert pickle.loads(pickle.dumps(new))==new
    assert np.asarray(n,dtype=float).shape==(len(n),2)
    assert not nx.has_path(m,new,(100.,0.))
    candidate=next(n[int(i)] for i in r if isinstance(n[int(i)],CircuitNode))
    path=nx.shortest_path(m,candidate,new,weight='weight')
    assert abs(sum(m[x][y]['weight'] for x,y in zip(path[:-1],path[1:]))-50.)<1e-5
    assert nx.number_of_nodes(graph)==4 # input unchanged
    # A coincident drawing of the SAME original asset cannot be reused.
    info['edge_source_assets']['S|B-00|b']=('physical-A',)
    m,n,u,r,a=add_released_circuits(graph,nodes,indices,np.array([0,1]),[1],[nodes.index((50.,0.))],info,lambda _:None)
    assert 'S|B-00|b' in a['open_edges']
    assert all(not isinstance(n[int(i)],CircuitNode) for i in r)
    # No safe vertex does not mean no safe station site: insert a checked
    # point on the REAL main segment, preserving length and asset identity.
    info['edge_source_assets']['S|B-00|b']=('physical-B',)
    m,n,u,r,a=add_released_circuits(graph,nodes,indices,np.array([0,1]),[1],[],info,lambda _:None,
        placement_check=lambda xy:20<xy[0]<30 and xy[1]==0)
    assert len(a['new_station_candidates'])==1,a
    site=n[int(r[-1])];assert tuple(site)==(25.,0.) and isinstance(site,CircuitNode)
    length=sum(d['physical_length'] for _,_,d in m.edges(data=True) if d.get('source_asset_id')=='physical-B')
    assert abs(length-100.)<1e-8,length
    m,n,u,r,a=add_released_circuits(graph,nodes,indices,np.array([0,1]),[1],[],info,lambda _:None,placement_check=lambda xy:False)
    assert not len(r) and not a['new_station_candidates']
    # Full preservation bridge: two distinct source cables share every XY.
    # The old station keeps A. B is released and must remain reachable by a
    # NEW station through its own original wire, never through cable A.
    import geopandas as gpd
    from shapely.geometry import Point
    from scipy.sparse.csgraph import dijkstra
    from ls_netontwerp_wizard.existing_locked_clustering import prepare_retention,solve_locked_voronoi
    points=gpd.GeoDataFrame({'Station':['S','S'],'Kabel Subgroep':['A-00','B-00'],
        'Master Asset ID':['old','free'],'Ontwerpstroom':[10.,20.],
        'Opwek ontwerpstroom':[0.,0.],'Ontwerpstroom kabel':[10.,20.],
        'Kabel opwek ontwerpstroom':[0.,0.]},geometry=[Point(100,0),Point(100,5)],crs=28992)
    stations=gpd.GeoDataFrame({'Stationsnaa':['S'],'Max_A':[15.]},geometry=[Point(0,0)],crs=28992)
    cables=gpd.GeoDataFrame({'Kabel Subgroep':['A-00','B-00','B-00'],
        'Type':['150AL','150AL','6CU'],'_Aansluitkabel':[False,False,True],
        'master_asset_id':['physical-A','physical-B','service-B']},geometry=[main,main,service],crs=28992)
    prepared=prepare_retention(points,stations,cables,850.)
    assert prepared['retained_by_index']=={0:'S'},prepared
    def voronoi(adjacency,nodes,targets,loads,old_sources,proposed,old_capacity,new_capacity,regular,components,preferred):
        assert not len(old_sources)
        candidate=next(j for j,i in enumerate(proposed) if isinstance(nodes[i],CircuitNode))
        source=proposed[candidate]
        distances=dijkstra(adjacency,directed=False,indices=source)
        assert np.isfinite(distances[targets]).all()
        assert not np.isfinite(distances[nodes.index((100.,0.))])
        partition=np.full(len(nodes),-1,dtype=int);partition[np.isfinite(distances)]=0
        return np.array([0]),0.,partition,[candidate],distances[targets]
    result=solve_locked_voronoi(graph,nodes,indices,np.array([10.,20.]),np.array([0,1]),['S'],
        np.array([nodes.index((0.,0.))]),np.array([nodes.index((50.,0.))]),prepared,100.,850.,voronoi,lambda _:None)
    assert result['assignment'].tolist()==[0,1],result
    assert result['node_cluster'][nodes.index((100.,5.))]==-1,result

    assert isinstance(result['new_nodes'][0],CircuitNode)
    assert result['circuit_audit']['remapped_units']=={1:('S','B-00')}
    # A locally proven new-design wire is not proof of its historic station
    # feed. It can nevertheless serve a NEW station without borrowing old
    # capacity or fabricating a cabinet connection.
    from ls_netontwerp_wizard.existing_residual_circuits import prepare_new_design_evidence
    from ls_netontwerp_wizard.review_retention import ReviewOriginal
    unproven=points.iloc[1:].copy();unproven.index=[1]
    raw=cables.iloc[1:].copy();raw.loc[raw.index[0],'geometry']=LineString([(200,0),(250,0)])
    raw.loc[raw.index[1],'geometry']=LineString([(250,0),(250,5)])
    unproven.loc[1,'geometry']=Point(250,5)
    aux=dict(retained_by_index={},all_original_by_index={1:ReviewOriginal('free','S','B-00',('B-00',),'free')},
        retention={'whole_path_edge_ids':{}},physical_by_station={})
    design=prepare_new_design_evidence(unproven,raw,aux)
    assert design['connections'][1]['historical_station_path_proven'] is False
    assert design['connections'][1]['key']==('NIEUW','B-00')
    assert not aux['retention']['whole_path_edge_ids'] and not aux['physical_by_station']
    assert set(asset for row in design['edges'].values() for asset in row['assets'])=={'physical-B','service-B'}
    # A flat connection without an old station still has an explicit local
    # cabinet terminal usable for a NEW design. No old feed is inferred.
    flat_point=unproven.copy();flat_point['Station']=None;flat_point['multistory_connection_id']='flat'
    flat_point.geometry=[Point(240,15)]
    cabinet=gpd.GeoDataFrame({'Flatkast_ID':['flat'],'cable_subgroup':['B-00']},geometry=[Point(250,5)],crs=28992)
    design=prepare_new_design_evidence(flat_point,raw,aux,cabinet)
    assert design['connections'][1]['xy']==(250.,5.)
    assert design['connections'][1]['historical_station_path_proven'] is False
    assert flat_point['Station'].isna().all() and not aux['physical_by_station']
    # An unrated MAIN can prove a transfer terminal, never reusable capacity.
    import copy
    from dataclasses import replace
    bad=copy.deepcopy(info);bad_free=replace(free,edge_ids=('S|B-00|b',))
    bad['all_original_by_index'][1]=bad_free;bad['connections_by_index'][1]=[bad_free]
    bad['retention']['whole_path_edge_ids']['free']=bad_free.edge_ids
    bad['edge_rating_available']={'S|B-00|b':False}
    at_main=np.array([indices[0],nodes.index((100.,0.))])
    bm,bn,bu,br,ba=add_released_circuits(graph,nodes,at_main,np.array([0,1]),[1],[],bad,lambda _:None)
    terminal=bn[int(bu[1])]
    assert bm.nodes[terminal]['proposed_main_transfer'] and bm.degree(terminal)==0
    assert not any(d.get('source_asset_id')=='physical-B' for _,_,d in bm.edges(data=True))
    print('RESIDUAL_CIRCUIT_IDENTITY_OK (separate assets, same XY, unchanged source, no shared-asset reuse)')
if __name__=='__main__':test()

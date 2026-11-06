"""GEN multi-membership, real object identity and absent administrative -00."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import geopandas as gpd
from shapely.geometry import Point,LineString
from ls_netontwerp_wizard.existing_locked_clustering import prepare_retention

def test():
    p=gpd.GeoDataFrame({'Station':['S'],'Kabel Subgroep':['K01-01, K01-02'],
        'Master Asset ID':['one'],'Ontwerpstroom':[20.],'Opwek ontwerpstroom':[0.],
        'Ontwerpstroom kabel':[20.],'Kabel opwek ontwerpstroom':[0.]},geometry=[Point(80,20)],crs=28992)
    s=gpd.GeoDataFrame({'Stationsnaa':['S'],'Max_A':[30.]},geometry=[Point(0,0)],crs=28992)
    c=gpd.GeoDataFrame({'Kabel Subgroep':['K01-00','K01-01','K01-02'],
        'Type':['150AL']*3},geometry=[LineString([(0,0),(100,0)]),
        LineString([(40,0),(60,20),(80,20)]),LineString([(80,0),(80,20)])],crs=28992)
    result=prepare_retention(p,s,c,850.)
    assert result['retained_by_index']=={0:'S'}
    assert result['retention']['stations']['S']['belasting_a']==20.
    assert result['retention']['richtingen'][('S','K01-00')]['belasting_a']==20.
    for code in ['K01-01','K01-02']:
        assert result['retention']['richtingen'][('S',code)]['belasting_a']==20.
    assert result['records'][0]['Kabel_Subgroep']=='K01-01, K01-02'
    assert result['records'][0]['Aansluiting']=='one'
    # Rejecting one membership releases the WHOLE physical consumer.
    too_small=s.copy();too_small['Max_A']=10.
    release=prepare_retention(p,too_small,c,850.)
    assert not release['retained_by_index']
    assert len(release['records'])==1 and release['records'][0]['Besluit']=='Vrijgegeven'
    assert release['retention']['stations']['S']['belasting_a']==0.
    # A real independent '-01' can start at the station without a '-00'.
    independent=p.copy();independent['Kabel Subgroep']='Q-01';independent.geometry=[Point(80,0)]
    cable=c.iloc[:1].copy();cable['Kabel Subgroep']='Q-01'
    direct=prepare_retention(independent,s,cable,850.)
    assert direct['retained_by_index']=={0:'S'}
    assert direct['feeder_parents'][('S','Q-01')] is None
    assert direct['retention']['route_m']['one']==80.
    # Repeated display numbers are legal for DIFFERENT cabinet objects.
    boxes=gpd.GeoDataFrame({'number':['1','1'],'id':['unique-a','unique-b']},
        geometry=[Point(300,0),Point(400,0)],crs=28992)
    assert prepare_retention(independent,s,cable,850.,distribution_cabinets=boxes)['retained_by_index']=={0:'S'}
    boxes['id']=['duplicate','duplicate']
    try:prepare_retention(independent,s,cable,850.,distribution_cabinets=boxes)
    except ValueError as exc:assert 'dubbele' in str(exc)
    else:raise AssertionError('Duplicate actual objects accepted')
    # Explicit flat relation anchors the electrical route at its cabinet;
    # the source consumer geometry stays unchanged.
    flat_point=independent.copy();flat_point['Multistory']='flat-1';flat_point.geometry=[Point(80,3)]
    flats=gpd.GeoDataFrame({'Flatkast_ID':['flat-1'],'cable_subgroup':['Q-01']},geometry=[Point(80,0)],crs=28992)
    flat_result=prepare_retention(flat_point,s,cable,850.,flat_cabinets=flats)
    assert flat_result['equipment_terminal_indices']=={0}
    assert flat_result['retained_by_index']=={0:'S'}
    assert flat_point.geometry.iloc[0].equals(Point(80,3))
    from ls_netontwerp_wizard.existing_station_retention import type_key
    assert type_key('1018 V-VMvKhsas 4x150 mm2 Al+4x6 mm2 Cu')=='150AL'
    assert type_key('1253 GPLKh 4x50 mm2 Cu+4x6 mm2 Cu')=='50CU'
    try:type_key('4x6 mm2 Cu')
    except ValueError as exc:assert 'niet ondersteund' in str(exc)
    else:raise AssertionError('Unsupported electrical constants invented')
    from ls_netontwerp_wizard.test_existing_cabinet_feeders import fixture
    import pandas as pd
    name,fp,fs,fc,fb=fixture()
    extra=fc.iloc[:1].copy();extra['Kabel Subgroep']='S09-00'
    extra.geometry=[LineString([(0,0),(0,-10),(50,-10),(50,0)])]
    fc=gpd.GeoDataFrame(pd.concat([fc,extra],ignore_index=True),crs=fc.crs)
    try:prepare_retention(fp,fs,fc,850.,distribution_cabinets=fb)
    except ValueError as exc:assert '2 eenduidig' in str(exc)
    else:raise AssertionError('Ambiguous unswitched cabinet accepted')
    confirmed=prepare_retention(fp,fs,fc,850.,distribution_cabinets=fb,
        schema_paths={name+'|B99-00':['S07-00','B99-00']})
    assert confirmed['feeder_parents'][(name,'B99-00')]=='S07-00'
    from ls_netontwerp_wizard.existing_station_retention import Cable,cable_check
    service=Cable('service','Q-01','a','b','4x6 mm2 Cu',17.,0.)
    assert service.length_m==17. and service.calculation_length_m==0.
    assert cable_check([service])['uitgesloten_aansluitkabels']
    # The exact same unsupported section MUST still fail as a main cable.
    try:Cable('main','Q-01','a','b','4x6 mm2 Cu',17.)
    except ValueError:pass
    else:raise AssertionError('Main cable silently excluded by its diameter')
    service_frame=cable.copy();service_frame['Kabel Subgroep']='Q-01';service_frame['_Aansluitkabel']=True
    service_frame['Type']='4x6 mm2 Cu'
    # Only service branches are excluded, by original layer role, never size.
    service_result=prepare_retention(independent,s,service_frame,850.)
    assert service_result['retention']['route_m']['one']==0.
    assert service_result['retention']['richtingen'][('S','Q-01')]['aansluitkabels_m']==80.
    # Same-group cables can cross without a source joint at the crossing.
    # A planar union would create a false electrical loop at (50,10).
    from ls_netontwerp_wizard.existing_group_trace import _make_noded_group
    physical=[(LineString([(0,0),(100,20)]),'150AL'),
              (LineString([(100,20),(100,0),(0,20)]),'150AL')]
    graph,edges,_,_= _make_noded_group(physical,[])
    import networkx as nx
    assert nx.is_tree(graph) and len(edges)==2
    assert (50.,10.) not in graph
    print('EXPLICIT_MULTIPLE_MEMBERSHIPS_AND_OBJECT_IDS_OK')

if __name__=='__main__':test()

"""Only the explicit connection-cable source role is excluded from calculations."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import geopandas as gpd
from shapely.geometry import Point,LineString
from ls_netontwerp_wizard.existing_locked_clustering import prepare_retention
from ls_netontwerp_wizard.existing_station_retention import cable_check,Cable

def test():
    p=gpd.GeoDataFrame({'Station':['S'],'Kabel Subgroep':['K-00'],'Master Asset ID':['a'],
        'Ontwerpstroom':[20.],'Opwek ontwerpstroom':[0.],
        'Ontwerpstroom kabel':[25.],'Kabel opwek ontwerpstroom':[0.]},geometry=[Point(130,0)],crs=28992)
    s=gpd.GeoDataFrame({'Stationsnaa':['S'],'Max_A':[100.]},geometry=[Point(0,0)],crs=28992)
    cables=gpd.GeoDataFrame({'Kabel Subgroep':['K-00']*2,
        'Type':['4x150 mm2 Al','4x6 mm2 Cu'],'_Aansluitkabel':[False,True]},
        geometry=[LineString([(0,0),(100,0)]),LineString([(100,0),(130,0)])],crs=28992)
    r=prepare_retention(p,s,cables,110.)
    assert r['retained_by_index']=={0:'S'}
    assert r['retention']['route_m']['a']==100.
    d=r['retention']['richtingen'][('S','K-00')]
    assert d['fysiek_uniek_m']==130. and d['rekenlengte_m']==100. and d['aansluitkabels_m']==30.
    assert abs(d['impedantie_ohm']-cable_check([Cable('m','K-00','s','e','150AL',100.)])['impedantie_ohm'])<1e-12
    assert r['retention']['stations']['S']['belasting_a']==20.
    # Keep actual source geometries and design-current demand unchanged.
    assert cables.geometry.iloc[1].length==30. and p.geometry.iloc[0].x==130.
    unknown=cables.copy();unknown['_Aansluitkabel']=False
    unrated=prepare_retention(p,s,unknown,110.)
    assert not unrated['retained_by_index']
    assert 'buiten rekenbibliotheek' in unrated['retention']['redenen']['a']
    # An out-of-service parallel source feature must neither become supply
    # nor create a false active cable-type ambiguity on the same corridor.
    retired=cables.iloc[:1].copy();retired['Type']='95AL';retired['cable_status']='Buiten bedrijf schroot'
    active=cables.copy();active['cable_status']='In bedrijf'
    import pandas as pd
    mixed=gpd.GeoDataFrame(pd.concat([active,retired],ignore_index=True),crs=cables.crs)
    assert prepare_retention(p,s,mixed,110.)['retained_by_index']=={0:'S'}
    # Explicit reciprocal LS service identity distinguishes the LS conductor
    # from a separate coincident OV conductor. Never invent 6Cu LS ratings.
    channel=p.copy();channel['id']='customer';channel['connection_cable_id']='service'
    lines=cables.copy();lines['id']=['ls-main','service'];lines['master_asset_id']=['LS-asset','service-asset']
    lines['Function']='LS';lines['cable_status']='In bedrijf';lines['service_connections_id']=['','customer']
    ov_main=lines.iloc[:1].copy();ov_main['id']='ov-main';ov_main['master_asset_id']='OV-asset'
    ov_main['Function']='OV';ov_main['Type']='6CU';ov_main['_Historisch_OV']=True
    parallel=gpd.GeoDataFrame(pd.concat([lines,ov_main],ignore_index=True),crs=lines.crs)
    resolved_channel=prepare_retention(channel,s,parallel,110.)
    assert resolved_channel['retained_by_index']=={0:'S'}
    main_edge=next(e for e,v in resolved_channel['edge_calculation_factors'].items() if v)
    assert resolved_channel['edge_source_assets'][main_edge]==('LS-asset',),resolved_channel
    broken=channel.copy();broken['connection_cable_id']='missing'
    try:prepare_retention(broken,s,parallel,110.)
    except ValueError as e:assert 'conflicterend' in str(e)
    else:raise AssertionError('An unknown source channel was silently chosen as LS')
    # A finite zero current is a valid explicit input, not missing data.
    zero=p.copy()
    for field in ['Ontwerpstroom','Opwek ontwerpstroom','Ontwerpstroom kabel','Kabel opwek ontwerpstroom']:zero[field]=0.
    assert prepare_retention(zero,s,cables,110.)['retained_by_index']=={0:'S'}
    # A blank redundant cable-group attribute can be resolved only from
    # reciprocal, active GEN object IDs, without changing either source.
    offset=p.copy();offset['id']='point-id';offset['connection_cable_id']='wire-id'
    offset.geometry=[Point(130,2)]
    relation=cables.copy();relation['id']=['main-id','wire-id']
    relation['service_connections_id']=['','point-id']
    relation['cable_status']='In bedrijf';relation['change_state']='Active'
    relation.loc[1,'Kabel Subgroep']=None
    resolved=prepare_retention(offset,s,relation,110.)
    assert resolved['retained_by_index']=={0:'S'}
    assert resolved['retention']['route_m']['a']==100.
    assert offset.geometry.iloc[0].equals(Point(130,2))
    import pandas as pd
    assert pd.isna(relation.loc[1,'Kabel Subgroep'])
    relation.loc[1,'service_connections_id']='another-point'
    try:prepare_retention(offset,s,relation,110.)
    except ValueError:pass
    else:raise AssertionError('One-sided cable ID was accepted as proof')
    # A service lead on the cabinet must not hide the MAIN feeder endpoint.
    from ls_netontwerp_wizard.test_existing_cabinet_feeders import fixture
    name,fp,fs,fc,fb=fixture()
    house=fp.iloc[:1].copy();house['Master Asset ID']='at-cabinet';house['Kabel Subgroep']='S07-00'
    house['Ontwerpstroom']=10.;house['Ontwerpstroom kabel']=10.;house.geometry=[Point(50,10)]
    fp=gpd.GeoDataFrame(pd.concat([fp,house],ignore_index=True),crs=fp.crs)
    lead=fc.iloc[:1].copy();lead['Kabel Subgroep']='S07-00';lead['Type']='4x6 mm2 Cu';lead['_Aansluitkabel']=True
    lead.geometry=[LineString([(50,0),(50,10)])]
    fc=gpd.GeoDataFrame(pd.concat([fc,lead],ignore_index=True),crs=fc.crs)
    at_box=prepare_retention(fp,fs,fc,850.,distribution_cabinets=fb)
    assert len(at_box['retained_by_index'])==4
    assert at_box['retention']['stations'][name]['belasting_a']==85.
    assert at_box['retention']['richtingen'][(name,'S07-00')]['belasting_a']==60.
    # OV-only mains remain real measured route metres, with NO fabricated
    # LS properties and an explicit open electrical-review status.
    ov=cables.copy();ov['_Historisch_OV']=[False,True];ov['_Aansluitkabel']=False
    routed=prepare_retention(p,s,ov,140.)
    assert routed['retained_by_index']=={0:'S'}
    assert routed['retention']['route_m']['a']==130.
    direction=routed['retention']['richtingen'][('S','K-00')]
    assert direction['ov_elektrisch_onbeoordeeld'] and direction['ov_route_m']==30.
    assert routed['records'][0]['OV_controle_open']
    # A zero-metre service-only path cannot bypass a DIFFERENT, limiting
    # main-cable path belonging to the same direction.
    mixed=p.iloc[[0,0]].copy().reset_index(drop=True)
    mixed['Master Asset ID']=['far','at-root'];mixed['Ontwerpstroom']=[80.,50.];mixed['Ontwerpstroom kabel']=[80.,50.]
    mixed.geometry=[Point(700,0),Point(0,10)]
    long=cables.copy();long.geometry=[LineString([(0,0),(700,0)]),LineString([(0,0),(0,10)])]
    long.loc[0,'Type']='95AL'
    roomy=s.copy();roomy['Max_A']=1000.
    bounded=prepare_retention(mixed,roomy,long,850.,profile='evenredig')
    assert 0 not in bounded['retained_by_index']
    assert bounded['retained_by_index']=={1:'S'}
    print('SERVICE_CABLE_GEOMETRY_PRESERVED_CALCULATIONS_EXCLUDED_OK')

if __name__=='__main__':test()

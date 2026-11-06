"""Unverified original feeders are released, never given fabricated old routes."""
import sys
from pathlib import Path
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import geopandas as gpd
from shapely.geometry import Point,LineString
from ls_netontwerp_wizard.review_retention import prepare_review_retention

def test():
    p=gpd.GeoDataFrame({'Station':['S','S'],'Kabel Subgroep':['K01-00','B01-00'],
        'Master Asset ID':['verified','unverified'],'Ontwerpstroom':[10.,20.],
        'Opwek ontwerpstroom':[0.,0.],'Ontwerpstroom kabel':[12.,25.],
        'Kabel opwek ontwerpstroom':[0.,0.]},geometry=[Point(60,0),Point(160,0)],crs=28992)
    s=gpd.GeoDataFrame({'Stationsnaa':['S'],'Max_A':[100.]},geometry=[Point(0,0)],crs=28992)
    c=gpd.GeoDataFrame({'Kabel Subgroep':['K01-00'],'Type':['150AL']},geometry=[LineString([(0,0),(60,0)])],crs=28992)
    r=prepare_review_retention(p,s,c,850.)
    assert r['retained_by_index']=={0:'S'}
    assert set(r['all_original_by_index'])=={0,1}
    assert r['verification_failures'].keys()=={1}
    assert r['retention']['stations']['S']['belasting_a']==10.
    assert 'unverified' in r['retention']['vrijgegeven']
    row=next(x for x in r['records'] if x['Aansluiting']=='unverified')
    assert row['Bestaande_route_m'] is None
    assert row['Besluit']=='Vrijgegeven - broncontrole'
    assert all('B01' not in eid for eid in r['physical_by_station']['S'])
    # A failed subgroup must not automatically discard a verified sibling
    # belonging to the same base group.
    sibling=p.copy();sibling.loc[1,'Kabel Subgroep']='K01-01'
    partial=prepare_review_retention(sibling,s,c,850.)
    assert partial['retained_by_index']=={0:'S'},partial
    assert set(partial['verification_failures'])=={1},partial
    all_bad=p.copy();all_bad['Kabel Subgroep']='B01-00'
    empty=prepare_review_retention(all_bad,s,c,850.)
    assert not empty['retained_by_index'] and not empty['physical_by_station']
    assert len(empty['records'])==2
    duplicate=p.copy();duplicate['Master Asset ID']='duplicate'
    try:prepare_review_retention(duplicate,s,c,850.)
    except ValueError as exc:assert 'Dubbel aansluit-ID' in str(exc)
    else:raise AssertionError('Concept mode bypassed duplicate identity protection')
    print('REVIEW_FAILURES_NEW_ONLY_NO_FABRICATED_OLD_ROUTE_OK')

if __name__=='__main__':test()

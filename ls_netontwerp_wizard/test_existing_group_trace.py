"""Geometry regression for exact 'Kabel Subgroep' routing from GEN exports."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import geopandas as gpd
from shapely.geometry import Point, LineString
from ls_netontwerp_wizard.existing_group_trace import trace_group_cables
from ls_netontwerp_wizard.existing_station_retention import retain_original


def test():
    station="044.529"
    points=gpd.GeoDataFrame({
        "Station":[station]*4,
        "Kabel Subgroep":["K01-00","K01-01","K01-02","K01-03"],
        "Master Asset ID":["main","b01","b02","b03"],
        "Ontwerpstroom":[20.,15.,30.,25.],
        "Opwek ontwerpstroom":[0.]*4,
        "Ontwerpstroom kabel":[20.,15.,30.,25.],
        "Kabel opwek ontwerpstroom":[0.]*4,
    },geometry=[Point(95,0),Point(40,30),Point(80,20),Point(60,30)],
    crs="EPSG:28992")
    stations=gpd.GeoDataFrame({"Station":[station]},
                              geometry=[Point(0,0)],crs="EPSG:28992")
    cables=gpd.GeoDataFrame({
        "Kabel Subgroep":["K01-00","K01-01","K01-02","K01-03"],
        "Type":["4*150mm2 Al","4*95mm2 Al","4*50mm2 Cu","4*70mm2 Al"],
    },geometry=[
        LineString([(0,0),(100,0)]),
        LineString([(40,0),(40,30)]),
        LineString([(80,0),(80,20)]),
        LineString([(60,0),(60,30)]),
    ],crs="EPSG:28992")
    traced=trace_group_cables(points,stations,cables)
    r=retain_original(
        {station:217.},traced["connections"],traced["cables"],
        station_origins=traced["station_origins"],
        branch_roots=traced["branch_roots"],
        parent_routes=traced["parent_routes"],
    )
    assert r["behouden"]==("b01","b02","b03","main"),r
    g=r["richtingen"]
    assert g[(station,"K01-00")]["belasting_a"]==90.
    assert g[(station,"K01-00")]["length_m"]==95.
    assert g[(station,"K01-01")]["belasting_a"]==15.
    assert g[(station,"K01-01")]["length_m"]==30.
    assert g[(station,"K01-02")]["belasting_a"]==30.
    assert g[(station,"K01-02")]["length_m"]==20.
    assert g[(station,"K01-03")]["belasting_a"]==25.
    assert g[(station,"K01-03")]["length_m"]==30.
    assert g[(station,"K01-02")]["segmenten"][0][1]=="50CU"
    main_edges=g[(station,"K01-00")]["deel_belasting_a"]
    main_geoms=traced["edge_geometries"]
    left_to_right=sorted(
        [(round(main_geoms[edge_id].bounds[0]),round(main_geoms[edge_id].bounds[2]),load)
         for edge_id,load in main_edges.items()]
    )
    assert left_to_right==[(0,40,90.),(40,60,75.),(60,80,50.),(80,95,20.)],left_to_right
    assert r["stations"][station]["belasting_a"]==90.

    # Different stations may legitimately reuse K01-00/-01/-02/-03.
    # Both sets must trace only to their own physical connected component.
    import pandas as pd
    from shapely.affinity import translate
    station2="044.530"
    shifted_points=points.copy()
    shifted_points["Station"]=station2
    shifted_points["Master Asset ID"]=[
        value+"_2" for value in shifted_points["Master Asset ID"]
    ]
    shifted_points.geometry=[
        translate(geom,xoff=1000.) for geom in shifted_points.geometry
    ]
    shifted_cables=cables.copy()
    shifted_cables.geometry=[
        translate(geom,xoff=1000.) for geom in shifted_cables.geometry
    ]
    all_points=gpd.GeoDataFrame(
        pd.concat([points,shifted_points],ignore_index=True),
        geometry="geometry",crs="EPSG:28992",
    )
    all_cables=gpd.GeoDataFrame(
        pd.concat([cables,shifted_cables],ignore_index=True),
        geometry="geometry",crs="EPSG:28992",
    )
    all_stations=gpd.GeoDataFrame({
        "Station":[station,station2],
    },geometry=[Point(0,0),Point(1000,0)],crs="EPSG:28992")
    both=trace_group_cables(all_points,all_stations,all_cables)
    r2=retain_original(
        {station:217.,station2:217.},both["connections"],both["cables"],
        station_origins=both["station_origins"],
        branch_roots=both["branch_roots"],
        parent_routes=both["parent_routes"],
    )
    assert len(r2["behouden"])==8,r2
    assert r2["stations"][station]["belasting_a"]==90.
    assert r2["stations"][station2]["belasting_a"]==90.
    for owner in (station,station2):
        assert r2["richtingen"][(owner,"K01-00")]["belasting_a"]==90.
        assert r2["richtingen"][(owner,"K01-02")]["belasting_a"]==30.
    assert all(
        physical.id.startswith(physical.id.split("|",1)[0]+"|")
        for physical in both["cables"]
    )

    # If the group code is wrong, do not silently attach the consumer
    # to a nearest unrelated cable group.
    wrong=points.copy()
    wrong.loc[1,"Kabel Subgroep"]="K01-99"
    try:
        trace_group_cables(wrong,stations,cables)
    except ValueError as exc:
        assert "geen getypeerde kabeldelen" in str(exc),exc
    else:
        raise AssertionError("Unmatched subgroup passed physical topology checks")
    print("GEN_FULL_SUBGROUP_TRACE_AND_UPSTREAM_LOADS_OK")


if __name__=="__main__":
    test()

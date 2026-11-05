"""Real-geometry regression for switch/distribution cabinet-fed independent groups."""
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
import geopandas as gpd
from shapely.geometry import LineString, Point
from ls_netontwerp_wizard.existing_group_trace import trace_group_cables
from ls_netontwerp_wizard.existing_locked_clustering import prepare_retention
from ls_netontwerp_wizard.existing_station_retention import retain_original


def fixture():
    station = "044.529"
    points = gpd.GeoDataFrame({
        "Station": [station] * 3,
        "Kabel Subgroep": ["B99-00", "B99-01", "S03-00"],
        "Master Asset ID": ["cab-main", "cab-branch", "station-main"],
        "Ontwerpstroom": [20.,30.,25.],
        "Opwek ontwerpstroom": [0.,0.,0.],
        "Ontwerpstroom kabel": [20.,30.,25.],
        "Kabel opwek ontwerpstroom": [0.,0.,0.],
    }, geometry=[Point(100,0),Point(75,20),Point(0,60)],
    crs="EPSG:28992")
    stations = gpd.GeoDataFrame({
        "Stationsnaa": [station],
        "Max_A":[217.],
    }, geometry=[Point(0,0)], crs="EPSG:28992")
    # S07-00 has NO directly connected consumer. Its only demand
    # is from B99-00 and B99-01 behind the distribution cabinet.
    cables = gpd.GeoDataFrame({
        "Kabel Subgroep":["S07-00","B99-00","B99-01","S03-00","S03-00"],
        "Type":["4*150mm2 Al","4*95mm2 Al","4*50mm2 Cu",
                "4*150mm2 Al","4*120mm2 Al"],
    }, geometry=[
        LineString([(0,0),(50,0)]),
        LineString([(50,0),(100,0)]),
        LineString([(75,0),(75,20)]),
        LineString([(0,0),(0,30)]),
        LineString([(0,30),(0,60)]),
    ], crs="EPSG:28992")
    cabinets = gpd.GeoDataFrame({
        "Nummer":["LS-024709"],
    }, geometry=[Point(50,0)], crs="EPSG:28992")
    return station,points,stations,cables,cabinets


def test():
    station,points,stations,cables,cabinets=fixture()
    group=trace_group_cables(
        points,stations,cables,distribution_cabinets=cabinets,
    )
    assert group["feeder_parents"]=={(station,"B99-00"):"S07-00"}
    assert group["cabinet_metadata"]=={(station,"B99-00"):"0"}
    assert set(group["parent_routes"])=={
        (station,"B99-00"),(station,"B99-01"),
    }
    result=retain_original(
        {station:217.},group["connections"],group["cables"],
        station_origins=group["station_origins"],
        branch_roots=group["branch_roots"],
        parent_routes=group["parent_routes"],
        feeder_parents=group["feeder_parents"],
        max_route_m=850.,
    )
    assert result["behouden"]==("cab-branch","cab-main","station-main"),result
    groups=result["richtingen"]
    assert groups[(station,"S07-00")]["belasting_a"]==50.,groups
    assert groups[(station,"B99-00")]["belasting_a"]==50.,groups
    assert groups[(station,"B99-01")]["belasting_a"]==30.,groups
    assert groups[(station,"S03-00")]["belasting_a"]==25.,groups
    assert result["stations"][station]["belasting_a"]==75.
    assert result["route_m"]["cab-main"]==100.
    assert result["route_m"]["cab-branch"]==95.
    assert result["route_m"]["station-main"]==60.
    assert groups[(station,"S07-00")]["fysiek_uniek_m"]==50.
    assert groups[(station,"B99-00")]["fysiek_uniek_m"]==50.
    assert groups[(station,"B99-01")]["fysiek_uniek_m"]==20.
    # Direct station groups can be composed of multiple differently typed
    # successive cable sections, NOT mistaken for a cabinet-fed cable.
    assert len(groups[(station,"S03-00")]["segmenten"])==2
    assert {row[1] for row in groups[(station,"S03-00")]["segmenten"]}=={
        "150AL","120AL"
    }
    assert all(x["pass"] for x in groups.values()),groups
    # The group really starts AT the cabinet: it must not be silently
    # recast as an additional direct station feeder.
    assert (station,"B99-00") not in group["station_origins"]
    assert (station,"B99-00") in group["branch_roots"]

    prepared=prepare_retention(
        points,stations,cables,850.,distribution_cabinets=cabinets,
    )
    assert len(prepared["retained_by_index"])==3
    assert len(prepared["physical_by_station"][station])>0
    assert all(
        connection.id in {item["Aansluiting"] for item in prepared["records"]}
        for connection in group["connections"]
    )
    assert [rec["Via_verdeelkast"] for rec in prepared["records"]] == [
        "0","0",""
    ],prepared["records"]

    # No cabinet evidence: fail closed (rather than connect B99-00 by
    # nearest-cable distance or append its lengths to station S03-00).
    try:
        trace_group_cables(points,stations,cables)
    except ValueError as exc:
        assert "verdeelkastenlaag" in str(exc),exc
    else:
        raise AssertionError("Cabinet-fed group accepted without cabinet geometry")

    # A second physical feeder on the same distribution cabinet is ambiguous;
    # choosing one would be an uncontrolled electrical switch assumption.
    ambiguous=cables.copy()
    extra=ambiguous.iloc[[0]].copy()
    extra["Kabel Subgroep"]=["S08-00"]
    extra.geometry=[LineString([(0,5),(50,0)])]
    import pandas as pd
    ambiguous=gpd.GeoDataFrame(
        pd.concat([ambiguous,extra],ignore_index=True),
        geometry="geometry",crs="EPSG:28992",
    )
    try:
        trace_group_cables(points,stations,ambiguous,
                           distribution_cabinets=cabinets)
    except ValueError as exc:
        assert "2 eenduidig" in str(exc),exc
    else:
        raise AssertionError("Two possible cabinet suppliers accepted")

    # Transformer overload must remove from original station, never
    # add a NEW customer to the old original feeder.
    reduced=stations.copy()
    reduced["Max_A"]=[42.]
    reduced_result=prepare_retention(
        points,reduced,cables,850.,distribution_cabinets=cabinets,
    )
    assert reduced_result["retention"]["vrijgegeven"]
    assert set(reduced_result["retained_by_index"]).issubset({0,1,2})
    assert all(x["pass"] for x in
               reduced_result["retention"]["richtingen"].values())
    assert all(x["pass"] for x in
               reduced_result["retention"]["stations"].values())

    # Subfeed gG checked independently; the upstream line is NEVER a
    # justification for a more powerful cabinet branch fuse.
    blown_points=points.copy()
    blown_points["Ontwerpstroom"]=[100.,40.,25.]
    blown_points["Ontwerpstroom kabel"]=[100.,40.,25.]
    fused=prepare_retention(
        blown_points,stations,cables,850.,
        distribution_cabinets=cabinets,
        installed_fuses={
            (station,"S07-00"):63,(station,"B99-00"):63,
            (station,"B99-01"):63,(station,"S03-00"):63,
        },
    )
    assert len(fused["retention"]["vrijgegeven"])>=1
    assert all(g["belasting_a"]<=g["max_ontwerp_a"]+1e-7
               for g in fused["retention"]["richtingen"].values())
    print("DISTRIBUTION_CABINET_INDEPENDENT_FEEDER_OK")


if __name__=="__main__":
    test()

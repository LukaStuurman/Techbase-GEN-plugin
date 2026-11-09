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
    assert group["cabinet_metadata"]=={(station,"B99-00"):"LS-024709"}
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
        "LS-024709","LS-024709",""
    ],prepared["records"]

    # A cabinet can lie within the generous 15-m station snapping radius:
    # a genuinely independent B99-00 must still count the S07-00 supply.
    close_points=points.copy()
    close_points.loc[0,"geometry"]=Point(58,0)
    close_points.loc[1,"geometry"]=Point(33,20)
    close_cables=cables.copy()
    close_cables.loc[0,"geometry"]=LineString([(0,0),(8,0)])
    close_cables.loc[1,"geometry"]=LineString([(8,0),(58,0)])
    close_cables.loc[2,"geometry"]=LineString([(33,0),(33,20)])
    close_cabinets=cabinets.copy()
    close_cabinets.geometry=[Point(8,0)]
    near=prepare_retention(
        close_points,stations,close_cables,850.,
        distribution_cabinets=close_cabinets,
    )
    assert near["feeder_parents"]=={(station,"B99-00"):"S07-00"}
    assert near["retention"]["richtingen"][(station,"S07-00")]["belasting_a"]==50.
    assert near["retention"]["route_m"]["cab-main"]==58.

    # A cabinet may be fed by a branched station route S07-01, not directly
    # by S07-00. The cabinet's separate B99-00 still requires its own gG,
    # type, length and downstream current checks; upstream S07-00 and
    # S07-01 each carry that same 50 A ONCE.
    branched=cables.copy()
    branched.loc[0,"geometry"]=LineString([(0,0),(25,0)])
    import pandas as pd
    supplier=branched.iloc[[0]].copy()
    supplier["Kabel Subgroep"]=["S07-01"]
    supplier["Type"]=["4*70mm2 Al"]
    supplier.geometry=[LineString([(25,0),(50,0)])]
    branched=gpd.GeoDataFrame(
        pd.concat([branched,supplier],ignore_index=True),
        geometry="geometry",crs="EPSG:28992",
    )
    via_branch=prepare_retention(
        points,stations,branched,850.,distribution_cabinets=cabinets,
    )
    assert via_branch["feeder_parents"]=={
        (station,"B99-00"):"S07-01"
    },via_branch["feeder_parents"]
    assert via_branch["retention"]["route_m"]["cab-main"]==100.
    assert via_branch["retention"]["route_m"]["cab-branch"]==95.
    for subgroup in ("S07-00","S07-01","B99-00"):
        assert via_branch["retention"]["richtingen"][
            (station,subgroup)
        ]["belasting_a"]==50.,subgroup
    assert via_branch["retention"]["richtingen"][
        (station,"B99-01")
    ]["belasting_a"]==30.

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

    # Consumption and generation are separately aggregated at BOTH levels.
    # The main feeder's 85 A generation load includes only the B99-01
    # downstream generation once, also through the upstream S07-00 line.
    mixed=points.copy()
    mixed.loc[1,"Opwek ontwerpstroom"]=45.
    mixed.loc[1,"Kabel opwek ontwerpstroom"]=85.
    mixed_result=prepare_retention(
        mixed,stations,cables,850.,distribution_cabinets=cabinets,
    )["retention"]
    for subgroup in ("S07-00","B99-00","B99-01"):
        assert mixed_result["richtingen"][(station,subgroup)]["belasting_a"]==85.
    # Conservative pointwise Hoogste Trafo load 20+45+25 = 90 A,
    # not an unsafe netting of production against consumption.
    assert mixed_result["stations"][station]["belasting_a"]==90.

    # Only the cabinet offshoot fuse is too small. The old station must
    # release ONLY the cabinet-branch endpoint, not change its fuse or
    # move another station's endpoint onto this cable.
    branch_too_big=points.copy()
    branch_too_big.loc[1,"Ontwerpstroom"] = 60.
    branch_too_big.loc[1,"Ontwerpstroom kabel"] = 60.
    branch_limit=prepare_retention(
        branch_too_big,stations,cables,850.,
        distribution_cabinets=cabinets,
        installed_fuses={
            (station,"S07-00"):160,(station,"B99-00"):160,
            (station,"B99-01"):63,(station,"S03-00"):160,
        },
    )
    assert branch_limit["retention"]["vrijgegeven"]==("cab-branch",),branch_limit
    assert set(branch_limit["retention"]["behouden"])=={
        "cab-main","station-main"
    },branch_limit

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
    # Cabinet as a POLYGON: incoming S07-00 and outgoing B99-00 are
    # physically attached on different sides. Only an existing zero-cost
    # cabinet equipment route may join them in the clustering graph.
    import numpy as np
    import networkx as nx
    from ast import literal_eval
    from shapely.geometry import Polygon
    from ls_netontwerp_wizard.existing_locked_clustering import solve_locked_voronoi
    poly_cables=cables.copy()
    poly_cables.loc[0,"geometry"]=LineString([(0,0),(49,0)])
    poly_cables.loc[1,"geometry"]=LineString([(51,0),(100,0)])
    poly_cabinets=cabinets.copy()
    poly_cabinets.geometry=[
        Polygon([(49,-1),(51,-1),(51,1),(49,1)])
    ]
    prepared_poly=prepare_retention(
        points,stations,poly_cables,850.,
        distribution_cabinets=poly_cabinets,
    )
    assert len(prepared_poly["retained_by_index"])==3
    bridge=prepared_poly["cabinet_bridges"][(station,"B99-00")]
    assert bridge["incoming"].distance(bridge["outgoing"])==2.
    assert prepared_poly["retention"]["route_m"]["cab-main"]==98.
    traced_poly=trace_group_cables(
        points,stations,poly_cables,distribution_cabinets=poly_cabinets,
    )
    graph=nx.Graph()
    for cable in traced_poly["cables"]:
        u=literal_eval(cable.from_node)
        v=literal_eval(cable.to_node)
        graph.add_edge(
            u,v,weight=cable.length_m,
            route_geometry=traced_poly["edge_geometries"][cable.id],
            calculation_factor=1.,
        )
    # Actual cabinet outline and connection are 0-metre in the route
    # graph, but their physical geometric lengths are not 0 metres.
    cabinet_nodes=[(49.,0.),(49.,1.),(51.,1.),(51.,0.)]
    bare=graph.copy()
    for u,v in zip(cabinet_nodes[:-1],cabinet_nodes[1:]):
        graph.add_edge(
            u,v,weight=1e-6,calculation_factor=0.,
            route_geometry=LineString([u,v]),
        )
    def run_cabinet_lock(network):
        nodes=list(network.nodes)
        lookup={node:i for i,node in enumerate(nodes)}
        return solve_locked_voronoi(
            network,nodes,
            np.asarray([
                lookup[(100.,0.)],lookup[(75.,20.)],lookup[(0.,60.)],
            ],dtype=int),
            np.asarray([20.,30.,25.]),
            np.arange(3),[station],
            np.asarray([lookup[(0.,0.)]],dtype=int),
            np.asarray([],dtype=int),
            prepared_poly,250.,850.,
            lambda *args: (_ for _ in ()).throw(
                AssertionError("No new station should be needed")
            ),
            lambda message:None,
        )
    all_locked=run_cabinet_lock(graph)
    assert all_locked["assignment"].tolist()==[0,0,0]
    assert all_locked["reserved"]
    # Missing internal cabinet conductor must FAIL even when all
    # original consumers are still nominally below capacity.
    try:
        run_cabinet_lock(bare)
    except ValueError as exc:
        assert ("interne" in str(exc) or "niet via uitsluitend" in str(exc)),exc
    else:
        raise AssertionError(
            "Cabinet inlet/outlet accepted without physical internal links"
        )

    print("DISTRIBUTION_CABINET_INDEPENDENT_FEEDER_OK")


if __name__=="__main__":
    test()

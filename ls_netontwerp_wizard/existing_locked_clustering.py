"""Bridge from validated original GEN Kabel Subgroep to exclusive new-station clustering.

This optional mode is separate from the default auto-Voronoi algorithm.
Original cable segments are immutable/reserved; only original consumers
passing BOTH transformer and CableChecker limits are retained.
New facilities are installed exclusively on remaining cable graph edges.
A mixed reserved/new snap node, disconnected historic path, missing cable
type/group, or geometrically unsupported route fails instead of silently
restoring the legacy free-for-all assignment.
"""
from __future__ import annotations

from collections import defaultdict
import math

import networkx as nx
import numpy as np
import pandas as pd
from scipy.spatial import cKDTree
from shapely.geometry import Point
from shapely.ops import unary_union
from shapely.strtree import STRtree

from .existing_group_trace import (
    GROUP_FIELDS, STATION_FIELDS, required_column, trace_group_cables,
)
from .existing_station_retention import (
    parent_group, group_code, group_codes, retain_original,
)

class RetentionSeparationError(ValueError):
    def __init__(self,message,*,stations=(),edge_ids=(),point_indices=()):
        super().__init__(message)
        self.stations=set(stations);self.edge_ids=set(edge_ids);self.point_indices=set(point_indices)


def prepare_retention(points, stations, original_cables, max_route_m, *,
                      profile="both", installed_fuses=None,
                      distribution_cabinets=None,schema_paths=None,flat_cabinets=None,
                      equipment_tolerance_m=.20,end_muff_first=True):
    """Read original Station+Kabel Subgroep per connection; no guessed groups.

    Unassigned/new connections are *not* put on an existing station.
    An original station with missing Kabel Subgroep is also released to a new
    station rather than given a synthetic existing cable direction.
    """
    from .historical_terminals import original_terminals
    points,equipment_terminals,original_cables=original_terminals(points,flat_cabinets,original_cables,schema_paths)
    point_station=required_column(points, STATION_FIELDS, "oorspronkelijk station van aansluiting")
    point_group=required_column(points, GROUP_FIELDS, "Kabel Subgroep van aansluiting")
    station_field=required_column(stations, ("Stationsnaa","Stationsnaam","Station"), "bestaande station")
    capacity_field=required_column(stations, ("Max_A",), "berekende trafocapaciteit Max_A")
    names={str(row[station_field]).strip():float(row[capacity_field])
           for _,row in stations.iterrows()}
    original=[]
    unknown_station=[]
    missing_group=[]
    for index,row in points.iterrows():
        station=str(row[point_station] or "").strip()
        if not station or station.casefold() in ("none","nan","null","nieuw"):
            continue
        if station not in names:
            unknown_station.append(str(index))
            continue
        value=row[point_group]
        if value is None or str(value).strip().casefold() in ("","none","nan","null"):
            missing_group.append(str(index))
            continue
        group_codes(value)  # preserve every explicit original membership
        original.append(index)
    if not original:
        raise ValueError(
            "Geen LS-aansluitingen met zowel een bestaand Station als een "
            "geldige volledige Kabel Subgroep gevonden. Controleer de "
            "Lovion/CSV-koppeling vÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â³ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â³r deze behoudmodus."
        )
    traced=trace_group_cables(
        points.loc[original],stations,original_cables,
        point_station_field=point_station,point_group_field=point_group,
        distribution_cabinets=distribution_cabinets,
        schema_paths=schema_paths,
        equipment_tolerance_m=equipment_tolerance_m,
    )
    indivisible={}
    for c in traced['connections']:
        i=int(traced['point_id_to_index'][c.id])
        flat=equipment_terminals.get(i,{}).get('flatkast')
        if flat:indivisible[c.source_id or c.id]=c.station+'|flat|'+flat
    retained=retain_original(
        names,traced["connections"],traced["cables"],
        installed_fuses=installed_fuses,
        station_origins=traced["station_origins"],
        branch_roots=traced["branch_roots"],
        parent_routes=traced["parent_routes"],
        feeder_parents=traced["feeder_parents"],
        profile=profile,max_route_m=max_route_m,
        indivisible_connections=indivisible,end_muff_first=end_muff_first,
    )
    import ast
    for proposal in retained['eindmof_voorstellen']:
        proposal['Status']='CONCEPT - knip/eindmof; fysieke uitvoering te controleren'
        try:
            xy=ast.literal_eval(proposal['Voorstel_knoop'])
            geometry=traced['edge_geometries'][proposal['Kabeldeel']]
            point=Point(float(xy[0]),float(xy[1]))
            if point.distance(geometry)>.001:raise ValueError('node outside conductor')
            proposal['X']=point.x;proposal['Y']=point.y
        except (ValueError,TypeError,SyntaxError,KeyError,IndexError):
            proposal['X']=None;proposal['Y']=None
            proposal['Status']='OPEN - geen verifieerbare eindmoflocatie'
    retained_ids=set(retained["behouden"])
    active={connection.id:connection for connection in traced["connections"]
            if connection.id in retained_ids}
    routes=defaultdict(set)
    for connection in active.values():
        for edge_id in connection.edge_ids:
            routes[connection.station].add(edge_id)
        current=group_code(connection.group)
        while True:
            parent=traced["feeder_parents"].get(
                (connection.station,current),parent_group(current)
            )
            if parent is None:break
            routes[connection.station].update(
                traced["parent_routes"][(connection.station,current)]
            )
            current=parent
    physical_by_station={
        name:{eid:traced["edge_geometries"][eid] for eid in sorted(ids)}
        for name,ids in routes.items()
    }
    # Original current components are independently tracked; no exported
    # 'Hoogste Trafo' surrogate is silently substituted for actual verbruik.
    records=[]
    by_index=defaultdict(list)
    for c in traced['connections']:by_index[int(traced['point_id_to_index'][c.id])].append(c)
    originals={index:max(items,key=lambda c:retained['route_m'][c.id]) for index,items in by_index.items()}
    edge_by_id={e.id:e for e in traced['cables']}
    ov_points=set()
    for original_index,connection in originals.items():
        ov_open=any(edge_by_id[eid].ov_route for member in by_index[original_index]
                    for eid in retained['whole_path_edge_ids'][member.id])
        if ov_open:ov_points.add(original_index)
        records.append({
            "Aansluiting":connection.source_id or connection.id,
            "Orig_station":connection.station,
            "Kabel_Subgroep":", ".join(connection.source_groups or (connection.group,)),
            "Bron_kabelgroepen":str(points.loc[traced['point_id_to_index'][connection.id],'Orig_kabelgroepen_bron']),
            "Route_anker":str(equipment_terminals.get(int(traced['point_id_to_index'][connection.id]),{})),
            "Via_verdeelkast":next(
                (
                    str(cabinet_id) for (name,group),cabinet_id
                    in traced["cabinet_metadata"].items()
                    if name==connection.station and
                    (
                        group==connection.group or
                        parent_group(connection.group)==group
                    )
                ),""
            ),
            "Besluit":"Behouden" if connection.id in retained_ids else "Vrijgegeven",
            "Reden":retained["redenen"].get(connection.id,""),
            "Trafo_verbruik_A":connection.trafo_verbruik_a,
            "Trafo_opwek_A":connection.trafo_opwek_a,
            "Kabel_verbruik_A":connection.kabel_verbruik_a,
            "Kabel_opwek_A":connection.kabel_opwek_a,
            "Bestaande_route_m":retained["route_m"].get(connection.id,0.),
            "OV_controle_open":ov_open,
        })
    return {
        "retained_by_index":{
            int(traced["point_id_to_index"][id]): active[id].station
            for id in retained_ids
        },
        "all_original_by_index":originals,
        "connections_by_index":dict(by_index),
        "equipment_terminal_indices":set(equipment_terminals),
        "equipment_terminals":equipment_terminals,
        "ov_points":ov_points,
        "physical_by_station":physical_by_station,
        "edge_geometries":traced["edge_geometries"],
        "retention":retained,
        "cabinet_metadata":traced["cabinet_metadata"],
        "cabinet_bridges":traced["cabinet_bridges"],
        "feeder_parents":traced["feeder_parents"],
        "records":records,
        "unknown_stations":unknown_station,
        "missing_groups":missing_group,
        "group_field":point_group,
        "station_field":point_station,
    }


def _select_reserved_edges(graph,node_list,physical_by_station):
    """Locate real original typed segments on noded graph (not on proximity)."""
    from shapely.geometry import LineString
    originals=[]
    owners=[]
    original_ids=[]
    for station,segments in physical_by_station.items():
        for ident,line in segments.items():
            originals.append(line)
            owners.append(station)
            original_ids.append(ident)
    if not originals:
        # A transformer/direction may be so overloaded that retaining zero
        # old connections is the only safe choice. In that case every
        # original consumer is released; do not invent a retained cable.
        return {}
    tree=STRtree(originals)
    station_coverage={station:unary_union(list(segments.values())).buffer(.035)
                      for station,segments in physical_by_station.items()}
    owner_by_edge={}
    actual=[]
    for u,v,data in graph.edges(data=True):
        line=data.get("route_geometry")
        if line is None:
            line=LineString([u,v])
        if line.is_empty or line.length<1e-7:continue
        matched=set()
        matched_ids=set()
        candidates=[int(idx) for idx in tree.query(line.buffer(.035))]
        for i in candidates:
            # Entire graph conductor must lie on original cable geometry.
            if originals[i].buffer(.035).covers(line):
                matched.add(owners[i])
                matched_ids.add(original_ids[i])
        # Noding may merge collinear source sections across a cable-type
        # boundary. Reserve a graph edge only if its WHOLE geometry is on
        # this one station's verified original union; never bridge a gap or
        # include an unretained downstream tail.
        for station in {owners[i] for i in candidates} - matched:
            if station_coverage[station].covers(line):
                matched.add(station)
                matched_ids.update(original_ids[i] for i in candidates if owners[i]==station)
        if len(matched)>1:
            raise RetentionSeparationError(
                "Bestaande stations hebben hetzelfde fysieke kabeldeel "
                "in hun originele feeder; route-eigenaarschap niet eenduidig.",stations=matched,edge_ids=matched_ids,
            )
        if matched:
            owner=matched.pop()
            owner_by_edge[frozenset((u,v))]=owner
            actual.append(line)
    if not owner_by_edge:
        raise ValueError("Bestaande kabelgroepen niet teruggevonden in het sleuvennet.")
    covered=unary_union(actual).buffer(.055)
    missing=[(owners[i],original_ids[i],float(original.difference(covered).length))
             for i,original in enumerate(originals) if original.difference(covered).length>0.15]
    if missing:
        detail='; '.join(f'{station}/{ident}: {length:.3f} m' for station,ident,length in missing[:8])
        raise ValueError(
            "Niet alle oorspronkelijke kabeldelen zijn met het genode "
            "kabelnet te identificeren; controleer ontbrekende of "
            "anders gesplitste kabelgroepen. Ontbrekend: "+detail
        )
    return owner_by_edge


def solve_locked_voronoi(
    graph, node_list, unit_node_indices, unit_load, point_to_unit, old_station_names,
    existing_station_node_indices, regular_node_indices, original_info,
    new_capacity, max_route_m, voronoi, logger,
):
    """Enforce fixed old routes, then run new-only Voronoi on residual graph.

    Returns final assignment, node territories, new source nodes/indices,
    original physical lines and exact original distance per retained point.
    """
    names={name:i for i,name in enumerate(old_station_names)}
    retained_points=original_info["retained_by_index"]
    reserved=_select_reserved_edges(graph,node_list,
                                   original_info["physical_by_station"])
    owner_by_node={}
    by_station=defaultdict(set)
    for edge,station in reserved.items():
        if station not in names:
            raise ValueError(f"Station {station} niet aanwezig in clustering.")
        for node in edge:
            previous=owner_by_node.setdefault(node,station)
            if previous!=station:
                raise RetentionSeparationError(
                    "Twee oude stations delen een elektrisch knooppunt; "
                    "kan niet veilig bij beide worden behouden.",stations=(previous,station),
                )
            by_station[station].add(node)
    # Ensure the solver's station root is actually connected to its ORIGINAL
    # cable. An equipment link (zero calculation weight) is allowed; a
    # geometric nearest-neighbour shortcut is NOT a historic conductor.
    for station,root_index in zip(old_station_names,existing_station_node_indices):
        source=node_list[int(root_index)]
        if source in owner_by_node and owner_by_node[source]!=station:
            raise ValueError(f"Stationroot {station} op kabel van ander station.")
        own=by_station.get(station,set())
        if not own:continue  # no retained consumer: do not reserve an empty old root
        if own and source not in own:
            topology=nx.Graph()
            topology.add_nodes_from(graph.nodes)
            for u,v,data in graph.edges(data=True):
                owner=reserved.get(frozenset((u,v)))
                if owner is not None and owner!=station:continue
                internal=(
                    float(data.get("calculation_factor",1.0))<=1e-9
                    or float(data.get("weight",1.0))<=1e-5
                )
                if owner == station or internal:
                    topology.add_edge(u,v,**data)
            if source not in topology:
                raise ValueError(f"Bestaand stationsanker {station} niet in kabelnet.")
            lengths,paths=nx.single_source_dijkstra(topology,source,weight="weight")
            endpoints=[target for target in own if target in lengths]
            if not endpoints:
                raise ValueError(
                    f"Bestaande station {station}: geen bevestigde fysieke "
                    "of interne verbinding van station naar kabelgroep."
                )
            chosen=min(endpoints,key=lambda target:(lengths[target],str(target)))
            path=paths[chosen]
            if lengths[chosen]>1e-5:
                raise ValueError(
                    f"Station {station}: oorspronkelijke vertrekroute is geen "
                    "bevestigde kabel-/interne stationverbinding."
                )
            for u,v in zip(path[:-1],path[1:]):
                reserved[frozenset((u,v))]=station
                owner_by_node[u]=station
                owner_by_node[v]=station
                own.add(u);own.add(v)
        else:
            owner_by_node[source]=station
            by_station[station].add(source)

    # A distribution-box polygon can have different in- and outgoing
    # cable terminals. Confirm its existing equipment conductors IN THE
    # QGIS routing graph before electrically joining the two original
    # groups. These are 0-calculation-metre cabinet links, never invented
    # new trench cables or extensions.
    retained_cabinet_links=set()
    feeder_parents=original_info.get("feeder_parents",{})
    for point_index,station in retained_points.items():
        record=original_info["all_original_by_index"].get(point_index)
        if record is None:
            raise ValueError("Behouden oorspronkelijke aansluitingsrecord ontbreekt.")
        for member in original_info.get('connections_by_index',{}).get(point_index,[record]):
            code=group_code(member.group)
            visited=set()
            while code is not None:
                if code in visited:
                    raise ValueError(f"Voedingslus bij {station}/{code}.")
                visited.add(code)
                if (station,code) in original_info.get("cabinet_bridges",{}):
                    retained_cabinet_links.add((station,code))
                code=feeder_parents.get((station,code),parent_group(code))

    if retained_cabinet_links:
        snap_tree=cKDTree(np.asarray(node_list,dtype=float))
        from shapely.geometry import LineString
        for station,code in sorted(retained_cabinet_links):
            link=original_info["cabinet_bridges"][(station,code)]
            parent_point=link["incoming"]
            child_point=link["outgoing"]
            def confirmed_node(point):
                distance,position=snap_tree.query((point.x,point.y))
                if float(distance)>.20:
                    raise ValueError(
                        f"Verdeelkast {link['cabinet']}: een origineel "
                        "kabeleind is niet op een echte QGIS-netwerkknoop aanwezig."
                    )
                return node_list[int(position)]
            parent_node=confirmed_node(parent_point)
            child_node=confirmed_node(child_point)
            for node in (parent_node,child_node):
                if owner_by_node.get(node)!=station:
                    raise ValueError(
                        f"Verdeelkast {link['cabinet']}: fysiek kabeleind is "
                        "niet uitsluitend van zijn oorspronkelijk station."
                    )
            if parent_node==child_node:
                continue
            equipment_graph=nx.Graph()
            cabinet_boundary=link["geometry"].buffer(max(.25,float(link.get('tolerance_m',.20))+.05))
            for u,v,data in graph.edges(data=True):
                weight=float(data.get("weight",1.))
                if not (
                    float(data.get("calculation_factor",1.))<=1e-9
                    or weight<=1e-5
                ):
                    continue
                conductor=data.get("route_geometry") or LineString([u,v])
                if cabinet_boundary.covers(conductor):
                    equipment_graph.add_edge(u,v)
            if not (parent_node in equipment_graph and
                    child_node in equipment_graph and
                    nx.has_path(equipment_graph,parent_node,child_node)):
                raise ValueError(
                    f"Verdeelkast {link['cabinet']}: geen bestaande interne "
                    "0-meterverbinding tussen inkomende en uitgaande "
                    "Kabel Subgroep gevonden. Geen kabel verzinnen."
                )
            physical_nodes=nx.shortest_path(
                equipment_graph,parent_node,child_node,
            )
            for u,v in zip(physical_nodes[:-1],physical_nodes[1:]):
                edge=frozenset((u,v))
                previous=reserved.get(edge)
                if previous is not None and previous!=station:
                    raise ValueError(
                        f"Verdeelkast {link['cabinet']} deelt een interne "
                        "verbinding tussen twee oorspronkelijke stations."
                    )
                reserved[edge]=station
                for node in (u,v):
                    old=owner_by_node.setdefault(node,station)
                    if old!=station:
                        raise ValueError(
                            "Verschillende oude stations delen ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©ÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©n "
                            "verdeelkastknooppunt; controleer het schakelschema."
                        )
                    by_station[station].add(node)

    n=len(node_list)
    if n!=len(graph.nodes):
        raise ValueError("Graph nodes do not match route-index order.")
    old_count=len(old_station_names)
    locked=np.full(len(unit_load),-1,dtype=int)
    for point_index,station in retained_points.items():
        if station not in names:raise ValueError(f"Onbekend oud station {station}")
        unit=int(point_to_unit[point_index])
        wanted=names[station]
        if locked[unit] not in (-1,wanted):
            raise ValueError(
                "EÃƒÆ’Ã†â€™Ãƒâ€šÃ‚Â©n kabelknooppunt bevat oorspronkelijke aansluitingen "
                "van verschillende stations; splits/controleer brongeometrie."
            )
        locked[unit]=wanted
    # A unit is indivisible: if its node contains both an old retained
    # connection and a released/new connection, sharing one cable node would
    # violate the exclusive new-station territory.
    for unit in np.flatnonzero(locked>=0):
        members=np.flatnonzero(point_to_unit==unit)
        if any(int(member) not in retained_points for member in members):
            raise ValueError(
                "Behouden en vrijgegeven aansluiting liggen op dezelfde "
                "genode kabelknoop; zonder fysieke scheiding niet veilig "
                "toe te delen aan twee stations."
            )
        target=node_list[int(unit_node_indices[unit])]
        if owner_by_node.get(target)!=old_station_names[int(locked[unit])]:
            raise ValueError(
                "Historisch toegewezen aansluiting ligt niet op het "
                "aan zijn oude station voorbehouden kabelpad."
            )
    # Require an EXCLUSIVE, original-station-rooted path even if no
    # new station is necessary. The previous no-free-units shortcut could
    # return success on two disjoint old cable routes inside a cabinet.
    proof_graph=nx.Graph()
    proof_graph.add_nodes_from(owner_by_node)
    for owned_edge,station in reserved.items():
        u,v=tuple(owned_edge)
        if owner_by_node.get(u)==station and owner_by_node.get(v)==station:
            proof_graph.add_edge(u,v)
    by_name={}
    for station,index in names.items():
        start=node_list[int(existing_station_node_indices[index])]
        by_name[station]=(
            nx.node_connected_component(proof_graph,start)
            if start in proof_graph else set()
        )
    for unit in np.flatnonzero(locked>=0):
        station=old_station_names[int(locked[unit])]
        target=node_list[int(unit_node_indices[unit])]
        if target not in by_name[station]:
            raise ValueError(
                f"Oorspronkelijke aansluiting {unit} is niet via uitsluitend "
                f"bestaande kabeldelen en verdeelkastverbindingen vanaf "
                f"station {station} bereikbaar."
            )
    free_units=np.flatnonzero(locked<0)
    for unit in free_units:
        target=node_list[int(unit_node_indices[unit])]
        if target in owner_by_node:
            raise ValueError(
                "Vrijgegeven aansluiting ligt nog op een voorbehouden oud "
                "kabeldeel; een nieuw station zou dezelfde kabel moeten delen. "
                "Controleer waar de kabel elektrisch wordt gescheiden."
            )
    node_index={node:i for i,node in enumerate(node_list)}
    locked_nodes=set(owner_by_node)
    residual=nx.Graph()
    residual.add_nodes_from(graph.nodes)
    for u,v,data in graph.edges(data=True):
        if u not in locked_nodes and v not in locked_nodes:
            residual.add_edge(u,v,**data)
    # Entire old routes are immutable and cannot be used by new stations.
    free_regular=[
        int(idx) for idx in regular_node_indices
        if node_list[int(idx)] not in locked_nodes
    ]
    residual_component=np.full(n,-1,dtype=int)
    component_regular=defaultdict(list)
    for component_index,nodes in enumerate(nx.connected_components(residual)):
        for node in nodes:
            residual_component[node_index[node]]=component_index
    for idx in free_regular:
        component_regular[int(residual_component[idx])].append(idx)
    for unit in free_units:
        graph_index=int(unit_node_indices[unit])
        comp=int(residual_component[graph_index])
        if not component_regular[comp]:
            raise ValueError(
                f"Vrijgegeven aansluiting {unit} ligt in een resterende "
                "kabelcomponent zonder veilige nieuwe stationslocatie."
            )
    if not len(free_units):
        node_owner=np.full(n,-1,dtype=int)
        for node,station in owner_by_node.items():
            node_owner[node_index[node]]=names[station]
        # Unused unassigned cable pieces do not need a route/territory.
        return {
            "assignment":locked,"node_cluster":node_owner,
            "new_node_indices":[],"new_nodes":[],
            "new_labels":[],"new_unit_distances":{},
            "owner_by_node":owner_by_node,
            "reserved":reserved,
        }
    # Sites: one or more prospective main-cable locations per free component,
    # plus more for load-heavy components; adding sites only where needed is
    # much cheaper than solving with every available cable vertex.
    proposed=[]
    free_set=set(free_units)
    for comp,regular in sorted(component_regular.items()):
        members=[unit for unit in free_units
                 if residual_component[int(unit_node_indices[unit])]==comp]
        if not members:continue
        tree=cKDTree(np.asarray([node_list[index] for index in regular],dtype=float))
        required=max(1,math.ceil(float(unit_load[members].sum())/new_capacity))
        # Evenly sample demanded physical endpoint sites, while ensuring the
        # first is the most load-intensive demand in the component.
        ordering=sorted(members,key=lambda index:(-float(unit_load[index]),int(index)))
        quota=min(len(ordering),max(4,3*required))
        for pick in range(quota):
            unit=ordering[(pick*len(ordering))//quota]
            _distance,nearest=tree.query(
                np.asarray(node_list[int(unit_node_indices[unit])],dtype=float)
            )
            candidate=int(regular[int(nearest)])
            if candidate not in proposed:
                proposed.append(candidate)
    # Reuse the existing connected Voronoi solver on the residual graph,
    # explicitly with ZERO old station sources: old clusters can never
    # receive the released new-only demand by proximity.
    from scipy.sparse import csr_matrix
    adjacency=nx.to_scipy_sparse_array(
        residual,nodelist=node_list,weight="weight",format="csr",dtype=float,
    )
    free_regular_arr=np.asarray(free_regular,dtype=int)
    try:
        assign, _util, partition, selected, distances=voronoi(
            csr_matrix(adjacency),node_list,
            np.asarray(unit_node_indices[free_units],dtype=int),
            np.asarray(unit_load[free_units],dtype=float),
            np.asarray([],dtype=int),proposed,
            np.asarray([],dtype=float),float(new_capacity),
            free_regular_arr,residual_component,None,
        )
    except RuntimeError as exc:
        raise RuntimeError(
            "Na behoud van originele stationkabels kan de resterende "
            "aansluitingenverdeling niet volledig met nieuwe stations "
            f"worden bereikt: {exc}"
        ) from exc
    if np.any(~np.isfinite(distances)) or np.any(distances>max_route_m+1e-7):
        raise ValueError("Nieuwe stations overschrijden de routegrens.")
    new_indices=[proposed[int(i)] for i in selected]
    assignment=locked.copy()
    assignment[free_units]=old_count+assign
    if np.any(assignment<0):
        raise ValueError("Niet alle aansluitingen kregen een station.")
    node_owner=np.asarray(partition,dtype=int)+old_count
    for node,station in owner_by_node.items():
        node_owner[node_index[node]]=names[station]
    # Reserved stations still need a connected source-to-original-consumer
    # territory. New graph edges never pass through this territory.
    for name,index in names.items():
        if not np.any(locked==index):continue
        source=node_list[int(existing_station_node_indices[index])]
        own={node_list[i] for i in np.flatnonzero(node_owner==index)}
        if source not in own:
            raise ValueError(f"Stationsroot {name} is niet voorbehouden.")
        own_graph=graph.subgraph(own)
        for unit in np.flatnonzero(locked==index):
            target=node_list[int(unit_node_indices[unit])]
            if not nx.has_path(own_graph,source,target):
                raise ValueError(
                    f"Oud station {name} heeft geen exclusieve kabelroute "
                    f"naar behouden aansluitingseenheid {unit}."
                )
    logger(
        f"Behoudmodus: {int((locked>=0).sum())} bestaande aansluitingsknopen "
        f"vastgezet; {len(free_units)} knopen exclusief aan "
        f"{len(new_indices)} nieuwe stations toegewezen."
    )
    return {
        "assignment":assignment,
        "node_cluster":node_owner,
        "new_node_indices":new_indices,
        "new_nodes":[node_list[idx] for idx in new_indices],
        "new_labels":[f"Nieuwe kabelgroepcluster {i+1}" for i in range(len(new_indices))],
        "new_unit_distances":{int(u):float(d) for u,d in zip(free_units,distances)},
        "owner_by_node":owner_by_node,
        "reserved":reserved,
    }

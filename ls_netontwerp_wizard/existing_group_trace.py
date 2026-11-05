"""Trace ORIGINAL station + FULL Kabel Subgroep paths on typed GEN cable lines.

Each full subgroup value is a separate direction. A suffix like '-01' starts
at its verified parent junction, with its own cable length and cable sequence.
The upstream parent segment must carry the descendant load; see
existing_station_retention.add_branch_upstream_loads.

This does not use the synthetic nearest-trench links introduced for general
clustering and does not infer historical group membership from distance.
"""
from __future__ import annotations

from collections import defaultdict
import math
import re

import networkx as nx
from shapely.geometry import Point
from shapely.ops import substring, unary_union

from .existing_station_retention import (
    Cable, OriginalConnection, group_code, parent_group, type_key,
)

GROUP_FIELDS = ("Kabel Subgroep", "Kabel_Subgroep", "KabelSubgroep",
                "Kabelgroep", "Kabelgroepcode", "cable_subgroup",
                "cable_subgroup_code")
TYPE_FIELDS = ("Type", "Kabeltype", "CableType")
STATION_FIELDS = ("Station", "Stationsnaa", "Stationsnaam")


def _value(row, candidates):
    columns = list(row.index)
    def compact(text):
        return "".join(c for c in str(text).casefold() if c.isalnum())
    map_columns={compact(c):c for c in columns}
    for candidate in candidates:
        key=compact(candidate)
        if key in map_columns:
            value=row[map_columns[key]]
            if value is not None and str(value).strip().lower() not in ("", "null", "nan", "none"):
                return str(value).strip()
    return ""


def required_column(frame, candidates, purpose):
    names={"".join(c for c in str(x).casefold() if c.isalnum()):x
           for x in frame.columns}
    for name in candidates:
        key="".join(c for c in str(name).casefold() if c.isalnum())
        if key in names:
            return names[key]
    raise ValueError(
        f"Voor historische kabelgroeptracering ontbreekt {purpose}: "
        f"verwachte kolom uit {candidates}."
    )


def _parts(geometry):
    if geometry is None or geometry.is_empty:
        return
    if geometry.geom_type in ("LineString","LinearRing"):
        if geometry.length>1e-6:
            yield geometry
    elif hasattr(geometry,"geoms"):
        for g in geometry.geoms:
            yield from _parts(g)


def _points(geometry):
    if geometry is None or geometry.is_empty:
        return
    if geometry.geom_type=="Point":
        yield geometry
    elif geometry.geom_type=="MultiPoint":
        yield from geometry.geoms
    elif geometry.geom_type in ("LineString","LinearRing"):
        for coord in (geometry.coords[0],geometry.coords[-1]):
            yield Point(coord)
    elif hasattr(geometry,"geoms"):
        for g in geometry.geoms:
            yield from _points(g)


def _node(point):
    return tuple(round(float(v),4) for v in (point.x,point.y))


def _closest_unique(lines,point,limit,what):
    ranked=sorted(
        ((float(line.distance(point)),i) for i,line in enumerate(lines)),
        key=lambda t:(t[0],t[1]),
    )
    if not ranked or ranked[0][0]>limit:
        raise ValueError(
            f"{what} ligt niet op een kabel met de aangegeven groep "
            f"(afstand {ranked[0][0] if ranked else float('inf'):.2f} m)."
        )
    if len(ranked)>1 and abs(ranked[0][0]-ranked[1][0])<0.0001:
        nearest1=lines[ranked[0][1]].interpolate(
            lines[ranked[0][1]].project(point)
        )
        nearest2=lines[ranked[1][1]].interpolate(
            lines[ranked[1][1]].project(point)
        )
        if nearest1.distance(nearest2)>0.02:
            raise ValueError(f"{what}: twee even nabije, verschillende kabels; geen gok.")
    index=ranked[0][1]
    return index,lines[index].interpolate(lines[index].project(point))


def _make_noded_group(records, terminals):
    """Build source-preserving undirected physical graph (no fabricated wire)."""
    source=[row[0] for row in records]
    noded=list(_parts(unary_union(source)))
    if not noded:
        raise ValueError("Kabelgroep heeft geen fysieke lijnstukken.")
    measures=defaultdict(set)
    for terminal in terminals:
        ix,projected=_closest_unique(noded,terminal,0.20,"Aansluiting/aftakpunt")
        distance=float(noded[ix].project(projected))
        if 1e-6<distance<noded[ix].length-1e-6:
            measures[ix].add(distance)
    graph=nx.Graph()
    edges=[]
    for i,line in enumerate(noded):
        boundaries=[0.,*sorted(measures[i]),float(line.length)]
        for a,b in zip(boundaries[:-1],boundaries[1:]):
            if b-a<=1e-6:continue
            part=substring(line,a,b)
            # Source match must contain the WHOLE segment and may not yield
            # conflicting cable types. A midpoint-only match is not enough.
            matching=[
                type_key(cable_type)
                for original,cable_type in records
                if original.buffer(0.012).covers(part)
            ]
            if not matching or len(set(matching))!=1:
                raise ValueError(
                    "Kabelgroep heeft een ongedefinieerd of conflicterend "
                    "kabeltype op een geknipt deel; controleer GEN-kabels."
                )
            u=_node(Point(part.coords[0]))
            v=_node(Point(part.coords[-1]))
            if u==v:continue
            if graph.has_edge(u,v):
                raise ValueError("Dubbel fysiek kabeldeel; onbekend welke kabel actief is.")
            segment_id=f"g{len(edges):07d}"
            graph.add_edge(u,v,id=segment_id,length=float(part.length))
            edges.append((segment_id,u,v,matching[0],float(part.length)))
    if not graph.nodes:
        raise ValueError("Kabelgroep zonder knopen.")
    if not nx.is_forest(graph):
        raise ValueError(
            "Bestaande kabelgroep bevat een lus: meerdere routes naar dezelfde "
            "aansluiting. Geen willekeurige route kiezen."
        )
    return graph,edges,noded


def trace_group_cables(points,stations,cables, *,
                       cable_group_field=None,cable_type_field=None,
                       point_group_field=None,point_station_field=None,
                       terminal_tolerance_m=.20,station_anchor_tolerance_m=15.):
    """Return verified original-edge paths, per segment *real* material.

    Input is projected EPSG:28992 GeoDataFrames. Input cable features must
    carry Kabel Subgroep plus Type, e_lv_map_cable and e_lv_connection_cable.
    A station's group membership comes from its ORIGINAL member connections;
    nearest cables alone never assign stations.
    """
    if str(points.crs).upper()!="EPSG:28992" or str(cables.crs).upper()!="EPSG:28992" or str(stations.crs).upper()!="EPSG:28992":
        raise ValueError("Gebruik EPSG:28992 voor reproduceerbare kabel-lengtes.")
    pg=point_group_field or required_column(points,GROUP_FIELDS,"kabelgroep bij aansluiting")
    ps=point_station_field or required_column(points,STATION_FIELDS,"oorspronkelijk station")
    cg=cable_group_field or required_column(cables,GROUP_FIELDS,"Kabel Subgroep bij hoofdkabel/aansluitkabel")
    ct=cable_type_field or required_column(cables,TYPE_FIELDS,"fysiek kabeltype")
    sn=required_column(stations,STATION_FIELDS,"stationsnaam")
    point_members=defaultdict(list)
    for index,row in points.iterrows():
        group=group_code(row[pg])
        station=str(row[ps] or "").strip()
        if not station or station.lower() in ("nan","none","null"):
            raise ValueError(f"Aansluiting {index}: geen oorspronkelijke stationstoewijzing.")
        point_members[(station,group)].append((index,row))
    station_geoms={}
    for _,row in stations.iterrows():
        name=str(row[sn] or "").strip()
        if name in station_geoms:raise ValueError(f"Dubbel station {name}")
        station_geoms[name]=row.geometry
    records=defaultdict(list)
    for index,row in cables.iterrows():
        code=group_code(row[cg])
        cable_type=type_key(row[ct])
        for part in _parts(row.geometry):
            records[code].append((part,cable_type))
    for station,group in point_members:
        if station not in station_geoms:
            raise ValueError(f"Bestaand station {station} ontbreekt in de stationslaag.")
        if group not in records:
            raise ValueError(f"Kabelgroep {group} bij {station} heeft geen getypeerde kabeldelen.")

    # Every suffix level is a real direction, also when nobody is connected
    # directly to the parent and only a -01 or -01-02 descendant is used.
    pairs=set(point_members)
    for station,group in tuple(pairs):
        parent=parent_group(group)
        while parent:
            pairs.add((station,parent))
            parent=parent_group(parent)
    for station,group in pairs:
        if group not in records:
            raise ValueError(
                f"Kabelgroep {group} (station {station}) heeft geen fysieke GEN-kabeldelen."
            )
    unions={code:unary_union([geom for geom,_ in rows]) for code,rows in records.items()}
    junctions={}
    for station,group in sorted(pairs):
        parent=parent_group(group)
        if not parent:continue
        if parent not in unions:
            raise ValueError(
                f"Aftakking {group} bij station {station} heeft geen kabelgroep {parent} als parent."
            )
        intersection=unions[group].intersection(unions[parent])
        if intersection.length>0.01:
            raise ValueError(f"Aftakking {group} overlapt kabelgroep {parent}; niet eenduidig.")
        candidates={_node(p) for p in _points(intersection)}
        if len(candidates)!=1:
            raise ValueError(
                f"Aftakking {group} moet één fysiek aansluitpunt met parent {parent} "
                "hebben; geen afzonderlijk beginpunt of meerdere aftakpunten gevonden."
            )
        junctions[(station,group)]=Point(next(iter(candidates)))

    # Parent groups must be split at each child's tap, even if no direct
    # consumer belongs to the parent group (only -01 consumers).
    all_groups=defaultdict(list)
    for (station,group),members in point_members.items():
        all_groups[group].extend(members)
    for station,group in sorted(pairs):
        all_groups.setdefault(group,[])
    physical=[]
    result=[]
    origins={}
    roots={}
    group_graphs={}
    for group,members in all_groups.items():
        terminals=[row.geometry for _,row in members]
        roots_for_group={
            (station,code):point for (station,code),point in junctions.items()
            if code==group
        }
        terminals.extend(roots_for_group.values())
        terminals.extend(
            point for (station,code),point in junctions.items()
            if parent_group(code)==group
        )
        origin_station_names={name for name,g in pairs if g==group}
        if parent_group(group) is None:
            terminals.extend(station_geoms[s] for s in origin_station_names)
        # Stations can be outside the cable itself. Project main roots onto
        # the physical group, but do not create conductor between them.
        noded=list(_parts(unary_union([geom for geom,_ in records[group]])))
        if not noded:
            raise ValueError(f"Geen kabelgeometrie bij {group}")
        corrected=[]
        for point in terminals:
            main_station=any(
                p is point for s,p in station_geoms.items() if s in origin_station_names
            )
            limit=station_anchor_tolerance_m if main_station else terminal_tolerance_m
            _idx,pr=_closest_unique(noded,point,limit,f"Kabelgroep {group}")
            corrected.append(pr)
        graph,edge_rows,_noded=_make_noded_group(records[group],corrected)
        group_graphs[group]=(graph,edge_rows)
        for local_id,u,v,kind,length in edge_rows:
            physical.append(Cable(group+"|"+local_id,group,str(u),str(v),kind,length))
    edge_by_group={}
    for c in physical:edge_by_group.setdefault(c.group,{})[tuple(sorted((c.from_node,c.to_node)))]=c.id
    direction_roots={}
    for station,group in sorted(pairs):
        graph,_edges=group_graphs[group]
        root_point=(
            junctions[(station,group)] if parent_group(group)
            else station_geoms[station]
        )
        _,root_projection=_closest_unique(
            [p for p,_t in records[group]],root_point,
            station_anchor_tolerance_m if not parent_group(group)
            else terminal_tolerance_m,
            f"Begin {station}/{group}",
        )
        root=min(graph.nodes,key=lambda xy:Point(xy).distance(root_projection))
        if Point(root).distance(root_projection)>0.02:
            raise ValueError(f"Beginpunt {station}/{group} ligt niet op fysieke kabel.")
        direction_roots[(station,group)]=root
        if parent_group(group):
            roots[(station,group)]=str(root)
        else:
            origins[(station,group)]=str(root)

    parent_routes={}
    for station,group in sorted(pairs):
        parent=parent_group(group)
        if parent is None:
            continue
        graph,_edges=group_graphs[parent]
        root=direction_roots[(station,parent)]
        tap=junctions[(station,group)]
        target=min(graph.nodes,key=lambda xy:Point(xy).distance(tap))
        if Point(target).distance(tap)>0.02 or not nx.has_path(graph,root,target):
            raise ValueError(
                f"Aftakpunt {group} is niet verbonden met de parent {parent} van station {station}."
            )
        nodes=nx.shortest_path(graph,root,target,weight="length")
        ids=tuple(
            edge_by_group[parent][tuple(sorted((str(a),str(b))))]
            for a,b in zip(nodes[:-1],nodes[1:])
        )
        if not ids:
            raise ValueError(
                f"Aftakking {group} begint op de station-/parent-root zonder "
                "eigen bovenliggende kabelroute; valideer de schakelconfiguratie."
            )
        parent_routes[(station,group)]=ids

    point_id_to_index={}
    for (station,group),members in point_members.items():
        graph,_edges=group_graphs[group]
        root=direction_roots[(station,group)]
        for row_index,row in members:
            _,pr=_closest_unique(
                [p for p,_t in records[group]],row.geometry,
                terminal_tolerance_m,f"Aansluiting {row_index}/{group}"
            )
            end=min(graph.nodes,key=lambda xy:Point(xy).distance(pr))
            if Point(end).distance(pr)>0.02:
                raise ValueError(f"Aansluiting {row_index} niet op werkelijk getypeerde kabel.")
            if not nx.has_path(graph,root,end):
                raise ValueError(f"Aansluiting {row_index} hoort niet fysiek bij {station}/{group}.")
            nodes=nx.shortest_path(graph,root,end,weight="length")
            route=tuple(edge_by_group[group][tuple(sorted((str(a),str(b))))] for a,b in zip(nodes[:-1],nodes[1:]))
            if not route:
                raise ValueError(f"Aansluiting {row_index} ligt op feederroot; bevestig uitvoerveld.")
            def number(name):
                try:return float(row[name])
                except (TypeError,ValueError,KeyError):return 0.
            consumption=number("Ontwerpstroom")
            production=number("Opwek ontwerpstroom")
            cable_consumption=number("Ontwerpstroom kabel")
            cable_production=number("Kabel opwek ontwerpstroom")
            if not (consumption or production or cable_consumption or cable_production):
                raise ValueError(
                    f"Aansluiting {row_index} mist geldige trafo-/kabelontwerpstromen."
                )
            raw_id=_value(row,("master_asset_id","Master Asset ID","ID"))
            id=str(raw_id or f"IDX-{row_index}")
            if id in point_id_to_index:
                raise ValueError(
                    f"Dubbel Master Asset ID {id}; historische aansluiting niet uniek."
                )
            point_id_to_index[id]=row_index
            result.append(OriginalConnection(id,station,group,route,
                             consumption,production,cable_consumption,cable_production))
    return {
        "connections":result,
        "cables":physical,
        "station_origins":origins,
        "branch_roots":roots,
        "parent_routes":parent_routes,
        "point_id_to_index":point_id_to_index,
        "group_graphs":group_graphs,
        "point_members":point_members,
    }

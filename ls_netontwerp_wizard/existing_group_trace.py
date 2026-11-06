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
from functools import lru_cache
import math
import re

import networkx as nx
from shapely.geometry import Point
from shapely.ops import substring, unary_union
from shapely.strtree import STRtree

from .existing_station_retention import (
    Cable, OriginalConnection, group_code, group_codes, parent_group, type_key,
)

GROUP_FIELDS = ("Kabel Subgroep", "Kabel_Subgroep", "KabelSubgroep",
                "Kabelgroep", "Kabelgroepcode", "cable_subgroup",
                "cable_subgroup_code")
TYPE_FIELDS = ("Type", "Kabeltype", "CableType")
STATION_FIELDS = ("Station", "Stationsnaa", "Stationsnaam")
SERVICE_PREFIX='AANSLUITKABEL:'
OV_PREFIX='OV_ROUTE:'
UNRATED_PREFIX='ONGETOETSTE_LS:'

def _record_type(value):
    value=str(value)
    if value.startswith((SERVICE_PREFIX,OV_PREFIX,UNRATED_PREFIX)):return value
    try:return type_key(value)
    except ValueError as exc:
        if 'niet ondersteund door Enexis-checker' not in str(exc):raise
        return UNRATED_PREFIX+value


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


def source_cable_ov_only(row):
    marker=str(row.get('_Historisch_OV',False)).strip().casefold() in ('true','1')
    function=_value(row,('Function','function','omschrijving')).upper()
    return marker or ('OV' in function and 'LS' not in function)


def source_cable_in_service(row):
    """Never use explicitly retired/reserve source wires as active supply."""
    status=_value(row,('cable_status','operational_status')).casefold()
    compact=''.join(c for c in status if c.isalnum())
    return not (compact.startswith(('buitenbedrijf','outofservice')) or 'schroot' in compact or compact in ('reserve','removed','verwijderd'))


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


def _make_noded_group(records, terminals, prefer_ls=False):
    """Build source-preserving undirected physical graph (no fabricated wire)."""
    source=[row[0] for row in records]
    typed_buffers=[(line.buffer(.012),_record_type(kind)) for line,kind in records]
    buffer_tree=STRtree([shape for shape,_kind in typed_buffers])
    noded=_physical_parts(records)
    if not noded:
        raise ValueError("Kabelgroep heeft geen fysieke lijnstukken.")
    measures=defaultdict(set)
    # GEOS may merge adjacent collinear source lines during unary_union.
    # Restore every original endpoint before matching whole segment types;
    # otherwise successive 150Al/120Al sections become one untypable edge.
    source_endpoints=[Point(coord) for line in source
                      for coord in (line.coords[0],line.coords[-1])]
    for terminal in [*terminals,*source_endpoints]:
        ix,projected=_closest_unique(noded,terminal,0.20,"Aansluiting/aftakpunt")
        distance=float(noded[ix].project(projected))
        if 1e-6<distance<noded[ix].length-1e-6:
            measures[ix].add(distance)
    graph=nx.Graph()
    edges=[]
    geometries={}
    for i,line in enumerate(noded):
        boundaries=[0.,*sorted(measures[i]),float(line.length)]
        for a,b in zip(boundaries[:-1],boundaries[1:]):
            if b-a<=1e-6:continue
            part=substring(line,a,b)
            # Source match must contain the WHOLE segment and may not yield
            # conflicting cable types. A midpoint-only match is not enough.
            matching=[typed_buffers[int(j)][1] for j in buffer_tree.query(part,predicate='covered_by')]
            if prefer_ls and len(set(matching))>1:
                # An explicitly registered LS service is not on the separate
                # OV conductor merely because both share drawing coordinates.
                ls=[kind for kind in matching if not kind.startswith((OV_PREFIX,SERVICE_PREFIX+OV_PREFIX))]
                if ls and all(kind in ls or kind.startswith((OV_PREFIX,SERVICE_PREFIX+OV_PREFIX)) for kind in matching):matching=ls
            if not matching or len(set(matching))!=1:
                raise ValueError(
                    "Kabelgroep heeft een ongedefinieerd of conflicterend "
                    "kabeltype op een geknipt deel; controleer GEN-kabels."
                )
            u=_node(Point(part.coords[0]))
            v=_node(Point(part.coords[-1]))
            if u==v:continue
            if graph.has_edge(u,v):
                previous=graph[u][v]['id']
                old=next(e for e in edges if e[0]==previous)
                if old[3]==matching[0] and geometries[previous].hausdorff_distance(part)<=.00015:
                    # Repeated curved export vertices can quantize to the
                    # same 0.1-mm edge. Do not mistake that numerical copy
                    # for a second physically distinct cable.
                    continue
                raise ValueError("Dubbel fysiek kabeldeel; onbekend welke kabel actief is.")
            segment_id=f"g{len(edges):07d}"
            graph.add_edge(u,v,id=segment_id,length=float(part.length))
            edges.append((segment_id,u,v,matching[0],float(part.length)))
            geometries[segment_id]=part
    if not graph.nodes:
        raise ValueError("Kabelgroep zonder knopen.")
    if not nx.is_forest(graph):
        raise ValueError(
            "Bestaande kabelgroep bevat een lus: meerdere routes naar dezelfde "
            "aansluiting. Geen willekeurige route kiezen."
        )
    return graph,edges,noded,geometries


def _physical_parts(records):
    """Shared source endpoints are joints; interior crossings are not.

    A planar unary_union would electrically join crossing house leads and
    introduce fictitious loops. Split each original conductor only at real
    source endpoints lying on it. Keep all original type boundaries intact.
    """
    lines=[line for line,_kind in records]
    endpoints=[Point(xy) for xy in {tuple(xy) for line in lines for xy in (line.coords[0],line.coords[-1])}]
    endpoint_tree=STRtree(endpoints)
    result=[]
    for line in lines:
        boundaries={0.,float(line.length)}
        for j in endpoint_tree.query(line.buffer(1e-7)):
            endpoint=endpoints[int(j)]
            if line.distance(endpoint)<=1e-7:
                distance=float(line.project(endpoint))
                if 1e-6<distance<line.length-1e-6:boundaries.add(distance)
        ordered=sorted(boundaries)
        for a,b in zip(ordered[:-1],ordered[1:]):
            if b-a>1e-6:result.append(substring(line,a,b))
    return result


def trace_group_cables(points,stations,cables, *,
                       cable_group_field=None,cable_type_field=None,
                       point_group_field=None,point_station_field=None,
                       distribution_cabinets=None,
                       schema_paths=None,
                       equipment_tolerance_m=.20,
                       terminal_tolerance_m=.20,station_anchor_tolerance_m=15.):
    """Return verified original-edge paths, per segment *real* material.

    Input is projected EPSG:28992 GeoDataFrames. Input cable features must
    carry Kabel Subgroep plus Type, e_lv_map_cable and e_lv_connection_cable.
    A station's group membership comes from its ORIGINAL member connections;
    nearest cables alone never assign stations.
    """
    if (str(points.crs).upper()!="EPSG:28992" or
        str(cables.crs).upper()!="EPSG:28992" or
        str(stations.crs).upper()!="EPSG:28992" or
        (distribution_cabinets is not None and
         str(distribution_cabinets.crs).upper()!="EPSG:28992")):
        raise ValueError("Gebruik EPSG:28992 voor reproduceerbare kabel-lengtes.")
    pg=point_group_field or required_column(points,GROUP_FIELDS,"kabelgroep bij aansluiting")
    ps=point_station_field or required_column(points,STATION_FIELDS,"oorspronkelijk station")
    cg=cable_group_field or required_column(cables,GROUP_FIELDS,"Kabel Subgroep bij hoofdkabel/aansluitkabel")
    ct=cable_type_field or required_column(cables,TYPE_FIELDS,"fysiek kabeltype")
    sn=required_column(stations,STATION_FIELDS,"stationsnaam")
    point_members=defaultdict(list)
    source_rows={}
    for index,row in points.iterrows():
        asset=_value(row,('master_asset_id','Master Asset ID','ID'))
        if asset and asset in source_rows:
            raise ValueError(f'Dubbel Master Asset ID {asset}; historische aansluiting niet uniek.')
        if asset:source_rows[asset]=index
        groups=group_codes(row[pg])
        if not groups:raise ValueError(f"Aansluiting {index}: kabelgroep ontbreekt.")
        station=str(row[ps] or "").strip()
        if not station or station.lower() in ("nan","none","null"):
            raise ValueError(f"Aansluiting {index}: geen oorspronkelijke stationstoewijzing.")
        for group in groups:
            point_members[(station,group)].append((index,row))
    station_geoms={}
    for _,row in stations.iterrows():
        name=str(row[sn] or "").strip()
        if name in station_geoms:raise ValueError(f"Dubbel station {name}")
        station_geoms[name]=row.geometry
    # Keep ALL coded source cable geometries for detecting a distinct
    # cabinet feeder whose code does not occur on any end connection.
    # Material must be valid for a physically selected direction; unrelated
    # spare lines do not become evidence of a station's historical feeders.
    raw_records=defaultdict(list)
    for _index,row in cables.iterrows():
        if not source_cable_in_service(row):continue
        try:
            code=group_code(row[cg])
        except ValueError:
            continue
        for part in _parts(row.geometry):
            kind=row[ct]
            if source_cable_ov_only(row):
                kind=OV_PREFIX+str(kind)
            if str(row.get('_Aansluitkabel',False)).strip().casefold() in ('true','1'):
                kind=SERVICE_PREFIX+str(kind)
            raw_records[code].append((part,kind))
    feeder_parents={}
    pairs=set(point_members)
    for station,group in tuple(pairs):
        current=group
        parent=parent_group(group)
        while parent:
            if parent not in raw_records:
                # A suffix is an administrative identifier, not proof of a
                # missing -00 conductor. Treat the actual subgroup as an
                # independent direction; its physical station/cabinet root
                # must still pass all normal topology checks below.
                feeder_parents[(station,current)]=None
                break
            pairs.add((station,parent))
            current=parent
            parent=parent_group(parent)
    for station,group in pairs:
        if station not in station_geoms:
            raise ValueError(f"Bestaand station {station} ontbreekt in de stationslaag.")
        if group not in raw_records:
            raise ValueError(f"Kabelgroep {group} (station {station}) heeft geen getypeerde kabeldelen in GEN.")

    # Cabinet-backed directions are independent -00 feeders with a different
    # group code from the station's supply cable. Their physical feeding
    # relationship must be proven by the actual distribution cabinet layer.
    # Merely being geographically nearby is never enough.
    cabinet_links={}
    cabinet_geometries=(
        [
            (
                _value(row,("Nummer","number","ID","master_asset_id","Name"))
                or str(i),
                row.geometry,
            )
            for i,row in distribution_cabinets.iterrows()
            if row.geometry is not None and not row.geometry.is_empty
        ]
        if distribution_cabinets is not None else []
    )
    cabinet_ids=[id for id,_geometry in cabinet_geometries]
    if len(set(cabinet_ids))!=len(cabinet_ids) and distribution_cabinets is not None:
        # GEN number is a display label: two different boxes may both be
        # called '1'. Resolve those labels by their real unique object IDs.
        labels=cabinet_ids
        objects=[_value(row,('id','master_asset_id')) for _,row in distribution_cabinets.iterrows()
                 if row.geometry is not None and not row.geometry.is_empty]
        if all(objects) and len(set(objects))==len(objects):
            cabinet_geometries=[
                (label if labels.count(label)==1 else f'{label} [{ident}]',geom)
                for (label,geom),ident in zip(cabinet_geometries,objects)
            ]
            cabinet_ids=[ident for ident,_ in cabinet_geometries]
    if len(set(cabinet_ids))!=len(cabinet_ids):
        raise ValueError(
            "Verdeelkasten hebben dubbele of niet-eenduidige kastnummers; "
            "er kan geen betrouwbare originele voeding worden vastgesteld."
        )
    group_union={
        code:unary_union([geom for geom,_type in rows])
        for code,rows in raw_records.items()
    }
    @lru_cache(maxsize=None)
    def terminal_points(code):
        # A cabinet is an endpoint of original cable FEATURES, even when
        # another same-coded segment leaves the same field. Requiring degree
        # one for the whole group hides real through-cabinet connections.
        # Noded interior crossings are never added as candidate terminals.
        conductors=[(g,kind) for g,kind in raw_records[code]
                    if not str(kind).startswith(SERVICE_PREFIX)]
        ends={_node(Point(xy)) for line,_kind in (conductors or raw_records[code])
              for xy in (line.coords[0],line.coords[-1])}
        return [Point(xy) for xy in sorted(ends)]

    examined=set()
    while pairs-examined:
        station,group=min(pairs-examined)
        examined.add((station,group))
        if feeder_parents.get((station,group),parent_group(group)) is not None:
            continue
        source=group_union[group]
        # Select the ENTIRE connected conductor component containing the
        # direct customers. Checking only their last short physical segment
        # would make any ordinary multi-type station feeder appear to start at
        # a distant cabinet.
        direct=[row.geometry for _id,row in point_members.get((station,group),[])]
        if direct:
            segments=_physical_parts(raw_records[group])
            physical_graph=nx.Graph()
            for index,part in enumerate(segments):
                first=_node(Point(part.coords[0]))
                last=_node(Point(part.coords[-1]))
                physical_graph.add_edge(first,last,segment=index)
            matching=[]
            for component in nx.connected_components(physical_graph):
                indices={
                    data["segment"] for u,v,data
                    in physical_graph.edges(data=True)
                    if u in component and v in component
                }
                conductor=unary_union([segments[index] for index in indices])
                if all(conductor.distance(p)<=terminal_tolerance_m for p in direct):
                    matching.append(conductor)
            if len(matching)!=1:
                raise ValueError(
                    f"Station {station}/{group}: originele aansluitingen liggen "
                    "niet allemaal op precies één fysiek samenhangende "
                    "kabelgroep. Geen willekeurige verdeelkast kiezen."
                )
            source=matching[0]
        station_distance=float(source.distance(station_geoms[station]))
        def base(code):return re.sub(r'^(SMG\d+)-\d+$',r'\1',code)
        chain=(schema_paths or {}).get(station+'|'+base(group),[])
        if station_distance<=terminal_tolerance_m:
            # Genuine station outlet, not a nearby cabinet cable.
            continue
        if chain==[base(group)] and station_distance<=station_anchor_tolerance_m:
            # The schema explicitly shows a station outlet. A second cable
            # entering the remote end cabinet does not make this outlet a
            # child of that other cable (or create a fictional supply loop).
            continue
        if not cabinet_geometries:
            if station_distance<=station_anchor_tolerance_m:
                # The later graph ownership proof still requires an actual
                # zero-cost station/enclosure link; proximity alone is not
                # enough to energize a connection.
                continue
            raise ValueError(
                f"Kabelgroep {station}/{group} komt niet rechtstreeks uit het "
                "station. De verdeelkastenlaag is verplicht om de "
                "werkelijke voedingsroute te bewijzen."
            )
        candidates=[]
        confirmed_upstream=chain[-2] if len(chain)>1 else None
        outgoing_endpoints=terminal_points(group)
        for cabinet_id,cabinet_geom in cabinet_geometries:
            exits=[p for p in outgoing_endpoints
                   if cabinet_geom.distance(p)<=equipment_tolerance_m and
                   source.distance(p)<=terminal_tolerance_m]
            exact=[p for p in exits if cabinet_geom.distance(p)<=1e-7]
            if exact:exits=exact
            if len(exits)!=1:
                continue
            child_start=exits[0]
            for upstream,up_geom in group_union.items():
                if upstream==group:
                    continue
                if confirmed_upstream is not None and base(upstream)!=confirmed_upstream:
                    continue
                up_parent=parent_group(upstream)
                if up_parent is None:
                    proved_source=(
                        up_geom.distance(station_geoms[station])
                        <=station_anchor_tolerance_m
                    )
                else:
                    # A distribution cabinet may be supplied from a -01 or
                    # -02 offshoot rather than directly from a station -00.
                    # Prove its complete upstream path via the named parent
                    # and the physical source cable, not via code similarity.
                    parent_geom=group_union.get(up_parent)
                    if parent_geom is None:
                        continue
                    intersection=up_geom.intersection(parent_geom)
                    junctions_here={_node(p) for p in _points(intersection)}
                    proved_source=(
                        parent_geom.distance(station_geoms[station])
                        <=station_anchor_tolerance_m
                        and intersection.length<=.01
                        and len(junctions_here)==1
                    )
                if confirmed_upstream is not None:
                    # The complete exported, active LS-schema chain proves
                    # which group supplies this cabinet, even across several
                    # cabinets. Physical terminals are still mandatory here.
                    proved_source=base(upstream)==confirmed_upstream
                if not proved_source:
                    continue
                # The upstream cable must physically enter the SAME cabinet
                # and be uniquely rooted at the original station.
                source_ends=[
                    p for p in terminal_points(upstream)
                    if cabinet_geom.distance(p)<=equipment_tolerance_m
                    and up_geom.distance(p)<=terminal_tolerance_m
                ]
                exact=[p for p in source_ends if cabinet_geom.distance(p)<=1e-7]
                if exact:source_ends=exact
                if len(source_ends)!=1:
                    continue
                candidates.append((upstream,cabinet_id,child_start,source_ends[0]))
        unique={(upstream,cabinet_id) for upstream,cabinet_id,_child,_tap in candidates}
        if len(unique)==0 and station_distance<=station_anchor_tolerance_m:
            # No confirmed independent incoming cabinet supply. Defer to
            # the original actual station/enclosure-network proof instead
            # of pretending a very nearby main cable is necessarily a box.
            continue
        if len(unique)!=1:
            raise ValueError(
                f"Kabelgroep {station}/{group} heeft "
                f"{len(unique)} eenduidig met het station verbonden "
                "verdeelkast-voedingsrichting(en); een originele "
                "kabelroute mag niet op nabijheid worden gegokt. "
                f"Kandidaten: {sorted(unique)}. Stationsafstand {station_distance:.3f} m; schemapad {chain}."
            )
        upstream,cabinet_id,child_start,parent_tap=candidates[0]
        feeder_parents[(station,group)]=upstream
        cabinet_links[(station,group)]=(cabinet_id,child_start,parent_tap)
        pairs.add((station,upstream))
        # Preserve all physical -00/-01 parent edges of a cabinet's feeder.
        upstream_parent=parent_group(upstream)
        while upstream_parent:
            if upstream_parent not in raw_records:
                feeder_parents[(station,upstream)]=None
                break
            pairs.add((station,upstream_parent))
            upstream_parent=parent_group(upstream_parent)
    records={
        code:[(geom,_record_type(kind)) for geom,kind in raw_records[code]]
        for code in {group for _station,group in pairs}
    }
    # Kabel Subgroep numbering may repeat at DIFFERENT stations. Split the
    # original physical geometry into connected components BEFORE deciding
    # which station owns which K01-00/K01-01, using real member terminals and
    # station origins instead of globally joining equal subgroup codes.
    components_by_group={}
    for code,rows in records.items():
        parts=_physical_parts(rows)
        topology=nx.Graph()
        for i,part in enumerate(parts):
            start_node=_node(Point(part.coords[0]))
            end_node=_node(Point(part.coords[-1]))
            if start_node==end_node:continue
            topology.add_edge(start_node,end_node,part_id=i)
        components=[]
        for vertices in nx.connected_components(topology):
            selected={
                data["part_id"] for u,v,data in topology.edges(data=True)
                if u in vertices and v in vertices
            }
            union=unary_union([parts[i] for i in selected])
            physical=[
                (original,cable_type)
                for original,cable_type in rows
                if original.intersection(union).length>1e-6
            ]
            if not physical:
                raise ValueError(
                    f"Geometrie voor kabelgroep {code} heeft geen getypeerde delen."
                )
            components.append((union,physical))
        if not components:
            raise ValueError(f"Kabelgroep {code}: geen fysiek samenhangende delen.")
        components_by_group[code]=components

    records_by_pair={}
    for station,group in sorted(pairs):
        components=components_by_group[group]
        if len(components)==1:
            records_by_pair[(station,group)]=components[0][1]
            continue
        direct=[row.geometry for _,row in point_members.get((station,group),[])]
        if direct:
            distances=[
                max(float(geometry.distance(union)) for geometry in direct)
                for union,_physical in components
            ]
            allowed=.20
        elif parent_group(group) is None:
            distances=[
                float(station_geoms[station].distance(union))
                for union,_physical in components
            ]
            allowed=15.
        else:
            descendants=[
                row.geometry
                for (other_station,other_group),members in point_members.items()
                if other_station==station and
                other_group.startswith(group+"-")
                for _,row in members
            ]
            if descendants:
                distances=[
                    min(float(geometry.distance(union)) for geometry in descendants)
                    for union,_physical in components
                ]
                allowed=float("inf")
            else:
                distances=[
                    float(station_geoms[station].distance(union))
                    for union,_physical in components
                ]
                allowed=float("inf")
        ranked=sorted(
            [(distance,index) for index,distance in enumerate(distances)]
        )
        if not ranked or ranked[0][0]>allowed:
            raise ValueError(
                f"Station {station}/{group}: geen fysiek kabelcomponent "
                "binnen de afstandsgrens van oorspronkelijke aansluiting."
            )
        if len(ranked)>1 and abs(ranked[0][0]-ranked[1][0])<0.01:
            raise ValueError(
                f"Station {station}/{group}: meerdere even waarschijnlijke "
                "kabelcomponenten met dezelfde code; kies niet op nabijheid."
            )
        records_by_pair[(station,group)]=components[ranked[0][1]][1]

    unions={
        pair:unary_union([geom for geom,_type in rows])
        for pair,rows in records_by_pair.items()
    }
    junctions={}
    feeder_taps={}
    cabinet_metadata={}
    for station,group in sorted(pairs):
        parent=feeder_parents.get((station,group),parent_group(group))
        if not parent:continue
        parent_key=(station,parent)
        if parent_key not in unions:
            raise ValueError(
                f"Aftakking {group} van {station} heeft geen parent {parent}."
            )
        if (station,group) in cabinet_links:
            cabinet_id,child_point,parent_point=cabinet_links[(station,group)]
            if (unions[(station,group)].distance(child_point)>.02 or
                unions[parent_key].distance(parent_point)>.02):
                raise ValueError(
                    f"Verdeelkast {cabinet_id}: bronkabeldeel is niet op de "
                    "juiste station- en subgroepcomponent aangetroffen."
                )
            junctions[(station,group)]=child_point
            feeder_taps[(station,group)]=parent_point
            cabinet_metadata[(station,group)]=cabinet_id
            continue
        intersection=unions[(station,group)].intersection(unions[parent_key])
        if intersection.length>0.01:
            raise ValueError(
                f"Aftakking {station}/{group} overlapt de hoofdkabel; "
                "de gescheiden kabelrichting is niet eenduidig."
            )
        branch_ends=terminal_points(group)
        candidates={_node(p) for p in _points(intersection)
                    if any(p.distance(end)<=1e-7 for end in branch_ends)}
        if len(candidates)!=1:
            raise ValueError(
                f"Aftakking {station}/{group} moet precies één fysiek "
                f"aftakpunt op {parent} hebben; gevonden {len(candidates)}."
            )
        point=Point(next(iter(candidates)))
        junctions[(station,group)]=point
        feeder_taps[(station,group)]=point

    all_groups=defaultdict(list)
    for pair,members in point_members.items():
        all_groups[pair].extend(members)
    for pair in pairs:
        all_groups.setdefault(pair,[])
    physical=[]
    edge_geometries={}
    result=[]
    origins={}
    roots={}
    group_graphs={}
    service_by_id=defaultdict(list)
    service_by_flat=defaultdict(list)
    for _,wire in cables.iterrows():
        if not source_cable_in_service(wire):continue
        if str(wire.get('_Aansluitkabel',False)).strip().casefold() not in ('true','1'):continue
        ident=_value(wire,('id',))
        if ident:service_by_id[ident].append(wire)
        flat=_value(wire,('multistory_connection_id',))
        if flat:service_by_flat[flat].append(wire)
    point_channels={}
    for pair,members in point_members.items():
        for index,row in members:
            reference=_value(row,('connection_cable_id',))
            candidates=service_by_id.get(reference,[]) if reference else []
            object_id=_value(row,('id',))
            if len(candidates)==1:
                reverse={v.strip() for v in re.split('[,;]',_value(candidates[0],('service_connections_id',))) if v.strip()}
                if not object_id or object_id not in reverse:candidates=[]
            if not candidates:
                flat=_value(row,('Multistory','multistory_connection_id'))
                candidates=[wire for wire in service_by_flat.get(flat,[]) if pair[1] in group_codes(_value(wire,GROUP_FIELDS))]
            channel=None
            if len(candidates)==1:
                function=_value(candidates[0],('Function','function','omschrijving')).upper()
                if 'LS' in function and 'OV' not in function:channel='LS'
                elif 'OV' in function and 'LS' not in function:channel='OV'
            point_channels[(index,pair[0],pair[1])]=channel
    preferred_ls={}
    for pair in all_groups:
        channels=[]
        for (station,group),members in point_members.items():
            if station!=pair[0]:continue
            current=group;seen=set()
            while current is not None and current not in seen:
                if current==pair[1]:
                    channels.extend(point_channels[(index,station,group)] for index,_ in members);break
                seen.add(current);current=feeder_parents.get((station,current),parent_group(current))
        preferred_ls[pair]=bool(channels) and all(channel=='LS' for channel in channels)
    for (station,group),members in sorted(all_groups.items()):
        terminals=[row.geometry for _,row in members]
        child_junctions=[
            feeder_taps[(other_station,code)]
            for (other_station,code) in junctions
            if other_station==station and
            feeder_parents.get((other_station,code),parent_group(code))==group
        ]
        terminals.extend(child_junctions)
        if (station,group) in junctions:
            terminals.append(junctions[(station,group)])
        if feeder_parents.get((station,group),parent_group(group)) is None:
            terminals.append(station_geoms[station])
        rows=records_by_pair[(station,group)]
        noded=list(_parts(unary_union([geom for geom,_type in rows])))
        if not noded:
            raise ValueError(f"Geen kabelgeometrie bij {station}/{group}.")
        corrected=[]
        for point in terminals:
            is_station_root=(
                feeder_parents.get((station,group),parent_group(group)) is None
                and point is station_geoms[station]
            )
            limit=station_anchor_tolerance_m if is_station_root else terminal_tolerance_m
            _idx,pr=_closest_unique(noded,point,limit,f"Kabelgroep {station}/{group}")
            corrected.append(pr)
        try:graph,edge_rows,_noded,geo_by_edge=_make_noded_group(rows,corrected,prefer_ls=preferred_ls[(station,group)])
        except ValueError as exc:raise ValueError(f'Station {station}/{group}: {exc}') from exc
        group_graphs[(station,group)]=(graph,edge_rows)
        for local_id,u,v,kind,length in edge_rows:
            unique_id=station+"|"+group+"|"+local_id
            service=kind.startswith(SERVICE_PREFIX)
            if service:kind=kind[len(SERVICE_PREFIX):]
            ov=kind.startswith(OV_PREFIX)
            if ov:kind=kind[len(OV_PREFIX):]
            unrated=kind.startswith(UNRATED_PREFIX)
            if unrated:kind=kind[len(UNRATED_PREFIX):]
            physical.append(Cable(unique_id,group,str(u),str(v),
                kind,length,0. if service else 1.,not ov,ov,not unrated))
            edge_geometries[unique_id]=geo_by_edge[local_id]
    edge_by_group={}
    for c in physical:
        station,group,_local=c.id.split("|",2)
        edge_by_group.setdefault((station,group),{})[
            tuple(sorted((c.from_node,c.to_node)))
        ]=c.id
    direction_roots={}
    for station,group in sorted(pairs):
        graph,_edges=group_graphs[(station,group)]
        has_parent=feeder_parents.get((station,group),parent_group(group))
        root_point=(
            junctions[(station,group)] if has_parent
            else station_geoms[station]
        )
        _,root_projection=_closest_unique(
            [p for p,_type in records_by_pair[(station,group)]],
            root_point,
            station_anchor_tolerance_m if has_parent is None
            else terminal_tolerance_m,
            f"Begin {station}/{group}",
        )
        root=min(graph.nodes,key=lambda xy:Point(xy).distance(root_projection))
        if Point(root).distance(root_projection)>0.02:
            raise ValueError(f"Beginpunt {station}/{group} niet op genode kabel.")
        direction_roots[(station,group)]=root
        if has_parent:
            roots[(station,group)]=str(root)
        else:
            origins[(station,group)]=str(root)

    parent_routes={}
    for station,group in sorted(pairs):
        parent=feeder_parents.get((station,group),parent_group(group))
        if parent is None:continue
        graph,_edges=group_graphs[(station,parent)]
        root=direction_roots[(station,parent)]
        tap=feeder_taps[(station,group)]
        target=min(graph.nodes,key=lambda xy:Point(xy).distance(tap))
        if Point(target).distance(tap)>0.02 or not nx.has_path(graph,root,target):
            raise ValueError(
                f"Aftakpunt {station}/{group} is niet verbonden met parent {parent}."
            )
        nodes=nx.shortest_path(graph,root,target,weight="length")
        ids=tuple(
            edge_by_group[(station,parent)][tuple(sorted((str(a),str(b))))]
            for a,b in zip(nodes[:-1],nodes[1:])
        )
        if not ids:
            raise ValueError(f"Aftakking {station}/{group} heeft geen parentkabeltraject.")
        parent_routes[(station,group)]=ids

    # Preserve both actual endpoints and original cabinet geometry. A
    # polygon's incoming and outgoing cables can touch different sides:
    # only a *real existing* 0-cost equipment conductor may connect them
    # in the QGIS graph. Do not invent an in-cabinet connection at a distance.
    cabinet_geom_by_id=dict(cabinet_geometries)
    cabinet_bridges={
        (station,group):{
            "cabinet":cabinet_id,
            "incoming":feeder_taps[(station,group)],
            "outgoing":junctions[(station,group)],
            "geometry":cabinet_geom_by_id[cabinet_id],
            "tolerance_m":equipment_tolerance_m,
        }
        for (station,group),cabinet_id in cabinet_metadata.items()
    }
    point_id_to_index={}
    for (station,group),members in point_members.items():
        graph,_edges=group_graphs[(station,group)]
        root=direction_roots[(station,group)]
        for row_index,row in members:
            _,pr=_closest_unique(
                [p for p,_t in records_by_pair[(station,group)]],row.geometry,
                terminal_tolerance_m,f"Aansluiting {row_index}/{group}"
            )
            end=min(graph.nodes,key=lambda xy:Point(xy).distance(pr))
            if Point(end).distance(pr)>0.02:
                raise ValueError(f"Aansluiting {row_index} niet op werkelijk getypeerde kabel.")
            if not nx.has_path(graph,root,end):
                raise ValueError(f"Aansluiting {row_index} hoort niet fysiek bij {station}/{group}.")
            nodes=nx.shortest_path(graph,root,end,weight="length")
            route=tuple(edge_by_group[(station,group)][tuple(sorted((str(a),str(b))))] for a,b in zip(nodes[:-1],nodes[1:]))
            if not route:
                raise ValueError(f"Aansluiting {row_index} ligt op feederroot; bevestig uitvoerveld.")
            def number(name):
                if name not in row.index:
                    raise ValueError(
                        f"Aansluiting {row_index}: verplichte originele "
                        f"ontwerpstroomkolom {name} ontbreekt."
                    )
                raw=row[name]
                try:
                    value=float(raw)
                except (TypeError,ValueError) as exc:
                    raise ValueError(
                        f"Aansluiting {row_index}: ontwerpstroom {name} "
                        f"is geen getal ({raw!r}); controleer de bron."
                    ) from exc
                if not math.isfinite(value) or value<0:
                    raise ValueError(
                        f"Aansluiting {row_index}: ongeldige stroom "
                        f"in {name}: {value!r}."
                    )
                return value
            # Prepared QGIS inputs preserve these four ORIGINAL electrical
            # components explicitly, because the general clustering field
            # "Ontwerpstroom" is a transformed 'Hoogste Trafo' surrogate.
            if "Orig_Trafo_Verbruik" in row.index:
                consumption=number("Orig_Trafo_Verbruik")
                production=number("Orig_Trafo_Opwek")
                cable_consumption=number("Orig_Kabel_Verbruik")
                cable_production=number("Orig_Kabel_Opwek")
            else:
                # Direct imported GeoPackage tests need no QGIS processing.
                consumption=number("Ontwerpstroom")
                production=number("Opwek ontwerpstroom")
                cable_consumption=number("Ontwerpstroom kabel")
                cable_production=number("Kabel opwek ontwerpstroom")
            # Four explicit finite zero values are valid zero demand. Missing,
            # non-numeric and negative currents were rejected by number().
            raw_id=_value(row,("master_asset_id","Master Asset ID","ID"))
            source_id=str(raw_id or f"IDX-{row_index}")
            source_groups=group_codes(row[pg])
            id=source_id if len(source_groups)==1 else source_id+'::'+group
            if id in point_id_to_index:
                raise ValueError(
                    f"Dubbel Master Asset ID {id}; historische aansluiting niet uniek."
                )
            point_id_to_index[id]=row_index
            result.append(OriginalConnection(id,station,group,route,
                             consumption,production,cable_consumption,cable_production,
                             source_id,source_groups))
    return {
        "connections":result,
        "cables":physical,
        "station_origins":origins,
        "branch_roots":roots,
        "parent_routes":parent_routes,
        "feeder_parents":feeder_parents,
        "cabinet_metadata":cabinet_metadata,
        "cabinet_bridges":cabinet_bridges,
        "point_id_to_index":point_id_to_index,
        "edge_geometries":edge_geometries,
        "group_graphs":group_graphs,
        "point_members":point_members,
    }

"""Keep distinct GEN conductors separate when their drawing shares a trench."""
from collections import defaultdict
from math import hypot
import networkx as nx
import numpy as np
from shapely.geometry import Point,LineString
from shapely.ops import unary_union

class CircuitNode(tuple):
    """An electrical terminal with real XY and a separate circuit identity."""
    def __new__(cls,xy,circuit):
        obj=super().__new__(cls,xy);obj.circuit=circuit;return obj
    def __hash__(self):return hash((tuple(self),self.circuit))
    def __eq__(self,other):
        return isinstance(other,CircuitNode) and self.circuit==other.circuit and tuple.__eq__(self,other)
    def __ne__(self,other):return not self.__eq__(other)
    def __getnewargs__(self):return (tuple(self),self.circuit)


def add_released_circuits(graph,node_list,unit_node_indices,point_to_unit,free_units,
                          regular_node_indices,info,logger,placement_check=None):
    """Overlay only proven free wires, with no connection to coincident old wires.

    Original node indices stay stable. New terminals have exactly the same
    physical XY as their source; no offset or fictitious conductor is drawn.
    Same-asset retained sections are never cloned into the new-only graph.
    """
    assets=info.get('edge_source_assets',{})
    factors=info.get('edge_calculation_factors',{})
    geometries=dict(info['edge_geometries']);assets=dict(assets);factors=dict(factors)
    design=info.get('new_design_evidence',{})
    for eid,record in design.get('edges',{}).items():
        geometries[eid]=record['geometry'];assets[eid]=record['assets'];factors[eid]=record['factor']
    whole=info['retention']['whole_path_edge_ids']
    held_ids=set()
    for i in info['retained_by_index']:
        for c in info.get('connections_by_index',{}).get(i,[]):held_ids.update(whole[c.id])
    held_by_asset=defaultdict(list)
    for eid in held_ids:
        for asset in assets.get(eid,()):held_by_asset[asset].append(geometries[eid])
    held_by_asset={asset:unary_union(lines) for asset,lines in held_by_asset.items()}
    families=defaultdict(set);unit_family={};unit_anchor={};reasons={}
    for unit in free_units:
        members=np.flatnonzero(point_to_unit==unit);keys=set();paths=[];anchors=[]
        for i in members:
            c=info.get('all_original_by_index',{}).get(int(i))
            if c is None or c.id not in whole:continue
            ids=whole[c.id]
            if not ids:continue
            key=(c.station,ids[0].split('|')[1]);keys.add(key);paths.extend(ids)
            anchors.append(info.get('equipment_terminals',{}).get(int(i),{}).get('netanker_xy',tuple(node_list[int(unit_node_indices[unit])])))
        if len(keys)!=1 or not anchors:continue
        if len(anchors)!=len(members):continue
        if any(Point(xy).distance(Point(anchors[0]))>.11 for xy in anchors):continue
        key=next(iter(keys));families[key].update(paths)
        unit_family[int(unit)]=key;unit_anchor[int(unit)]=anchors[0]
    design_by_key=defaultdict(set)
    for eid,record in design.get('edges',{}).items():design_by_key[record['key']].add(eid)
    for unit in free_units:
        if int(unit) in unit_family:continue
        members=np.flatnonzero(point_to_unit==unit)
        entries=[design.get('connections',{}).get(int(i)) for i in members]
        if not entries or any(e is None for e in entries):continue
        keys={e['key'] for e in entries}
        if len(keys)!=1:continue
        key=next(iter(keys));xy=entries[0]['xy']
        if any(Point(e['xy']).distance(Point(xy))>.11 for e in entries):continue
        families[key].update(design_by_key[key]);unit_family[int(unit)]=key;unit_anchor[int(unit)]=xy
    if not unit_family:return graph,node_list,unit_node_indices,regular_node_indices,{}
    model=graph.copy();nodes=list(node_list);indices={n:i for i,n in enumerate(nodes)}
    original_regular={tuple(node_list[int(i)]) for i in regular_node_indices}
    new_regular=set(map(int,regular_node_indices));new_unit_indices=np.array(unit_node_indices,copy=True)
    circuit_nodes=defaultdict(set);circuit_main=defaultdict(set)
    def terminal(xy,key,round_xy=True):
        node=CircuitNode(tuple(float(x) for x in (np.round(xy,1) if round_xy else xy)),key)
        if node not in indices:indices[node]=len(nodes);nodes.append(node);model.add_node(node,physical_xy=tuple(float(x) for x in xy))
        circuit_nodes[key].add(node);return node
    for key,ids in families.items():
        for eid in sorted(ids-held_ids):
            identities=assets.get(eid,())
            if len(identities)!=1 or eid not in factors:
                reasons[eid]='Geen unieke bronkabel-ID voor elektrisch gescheiden hergebruik';continue
            line=geometries[eid];asset=identities[0]
            if asset in held_by_asset and line.intersection(held_by_asset[asset]).length>.05:
                reasons[eid]='Hetzelfde bronkabeldeel blijft in gebruik bij een bestaand station';continue
            factor=float(factors[eid])
            ov=info.get('edge_ov_routes',{}).get(eid,design.get('edges',{}).get(eid,{}).get('ov_route',False))
            if factor and ov:
                reasons[eid]='OV uitsluitend als trace; OV-geleider niet als nieuwe LS-voeding hergebruiken'
                continue
            rated=info.get('edge_rating_available',{}).get(eid,design.get('edges',{}).get(eid,{}).get('rating_available',True))
            if factor and not rated:
                reasons[eid]='Hoofdkabel zonder rekenwaarden niet als nieuwe LS-voeding hergebruiken; nieuwe 150Al nodig'
                continue
            coords=list(line.coords)
            for a,b in zip(coords[:-1],coords[1:]):
                u=terminal(a,key);v=terminal(b,key)
                if u==v:continue
                physical=LineString([a,b]);length=float(physical.length)
                data=dict(weight=max(1e-6,length*factor),physical_length=length,
                    calculation_factor=factor,route_geometry=physical,
                    source_asset_id=asset,source_edge_id=eid,circuit_key=key,
                    cable_type=info.get('edge_types',{}).get(eid,design.get('edges',{}).get(eid,{}).get('cable_type')),
                    rating_available=info.get('edge_rating_available',{}).get(eid,design.get('edges',{}).get(eid,{}).get('rating_available',True)),
                    ov_route=info.get('edge_ov_routes',{}).get(eid,design.get('edges',{}).get(eid,{}).get('ov_route',False)),
                    construction_cost=0.)
                if not model.has_edge(u,v):model.add_edge(u,v,**data)
                if factor:
                    circuit_main[key].update((u,v))
                    for node in (u,v):
                        if tuple(node) in original_regular:new_regular.add(indices[node])
    remapped={}
    for unit,key in unit_family.items():
        candidates=circuit_nodes[key]
        anchor=unit_anchor[unit]
        def ranked_candidates():return sorted((hypot(float(node[0])-anchor[0],float(node[1])-anchor[1]),indices[node]) for node in candidates)
        ranked=ranked_candidates()
        if not ranked or ranked[0][0]>.11:
            # A registered terminal on an OV/unrated MAIN may be transferred
            # to explicit NEW 150Al. Preserve the contact evidence without
            # treating that source conductor as reusable LS capacity.
            point=Point(unit_anchor[unit])
            proof=[eid for eid in families[key] if factors.get(eid) and len(assets.get(eid,()))==1 and geometries[eid].distance(point)<=.001]
            if proof:
                node=terminal(unit_anchor[unit],key)
                model.nodes[node]['proposed_main_transfer']=True
                model.nodes[node]['terminal_source_assets']=tuple(sorted({a for eid in proof for a in assets[eid]}))
            else:continue
            ranked=ranked_candidates()
        if ranked[0][0]>.11:continue
        if len(ranked)>1 and abs(ranked[1][0]-ranked[0][0])<1e-8:continue
        new_unit_indices[unit]=ranked[0][1];remapped[unit]=key
    # Existing graph vertices often coincide with service taps and are
    # excluded for station placement. Search actual main-cable interiors
    # before declaring that this new-only component has no safe site.
    added_sites=[]
    if placement_check is not None:
        demanded={nodes[int(new_unit_indices[u])] for u in remapped}
        for key,owned in circuit_nodes.items():
            for component in list(nx.connected_components(model.subgraph(owned))):
                if not component.intersection(demanded):continue
                if any(indices[n] in new_regular for n in component):continue
                candidates=[]
                for u,v,data in list(model.subgraph(component).edges(data=True)):
                    if not data.get('calculation_factor'):continue
                    line=data['route_geometry']
                    for fraction in (.5,.25,.75):
                        point=line.interpolate(fraction,normalized=True)
                        if placement_check((point.x,point.y)):
                            candidates.append((line.length,u,v,data,point))
                if not candidates:continue
                _,u,v,data,point=max(candidates,key=lambda item:item[0])
                node=terminal((point.x,point.y),key,round_xy=False)
                if node in (u,v):continue
                # Geometry and weights split the original source segment;
                # no bridge, changed cable length or invented wire is added.
                line=data['route_geometry'];distance=line.project(point)
                from shapely.ops import substring
                first=substring(line,0,distance);second=substring(line,distance,line.length)
                # route_geometry may run opposite the graph edge iteration.
                if Point(u).distance(Point(first.coords[0]))>Point(u).distance(Point(second.coords[-1])):
                    first,second=second,first
                model.remove_edge(u,v)
                for a,b,part in ((u,node,first),(node,v,second)):
                    attrs=dict(data);attrs['route_geometry']=part
                    attrs['physical_length']=part.length
                    attrs['weight']=max(1e-6,part.length*data['calculation_factor'])
                    model.add_edge(a,b,**attrs)
                new_regular.add(indices[node]);added_sites.append(dict(circuit=key,source_asset_id=data['source_asset_id'],x=point.x,y=point.y))
    if added_sites:logger(f'Stationsplaatsing: {len(added_sites)} veilige punten binnen bestaande hoofdkabelsegmenten toegevoegd; bronlengtes behouden.')
    logger(f'GEN-kabelidentiteit: {len(remapped)} vrijgegeven aansluitingsknopen op afzonderlijke bronkabels; gedeeld tracé verbindt geen verschillende kabelgroepen.')
    return model,nodes,new_unit_indices,np.asarray(sorted(new_regular),dtype=int),dict(remapped_units=remapped,open_edges=reasons,new_station_candidates=added_sites)


def prepare_new_design_evidence(points,cables,info,flat_cabinets=None,schema_paths=None):
    """Prove local consumer-to-wire geometry without asserting an old station feed.

    This is new-design evidence only. A missing historical station/cabinet
    path remains an open issue and is never promoted to retained supply.
    """
    from .historical_terminals import original_terminals
    from .existing_group_trace import (_parts,_value,_closest_unique,_make_noded_group,
        _record_type,GROUP_FIELDS,TYPE_FIELDS,required_column,SERVICE_PREFIX,OV_PREFIX,UNRATED_PREFIX)
    from .existing_station_retention import group_codes
    from .existing_group_trace import source_cable_in_service
    cables=cables.loc[[source_cable_in_service(row) for _,row in cables.iterrows()]].copy()
    points,anchors,cables=original_terminals(points,flat_cabinets,cables,schema_paths,require_station=False)
    gf=required_column(points,GROUP_FIELDS,'bron-kabelgroep')
    cg=required_column(cables,GROUP_FIELDS,'bron-kabelgroep kabel');ct=required_column(cables,TYPE_FIELDS,'kabeltype')
    members=defaultdict(list)
    for i,row in points.iterrows():
        if i in info['retained_by_index']:continue
        # Verified released paths already have stronger exact station-to-wire
        # evidence. Do not replace them with a nearest-cable interpretation.
        c=info.get('all_original_by_index',{}).get(i)
        if c is not None and c.id in info['retention']['whole_path_edge_ids']:continue
        codes=group_codes(_value(row,(gf,)))
        if len(codes)==1:members[codes[0]].append((int(i),row.geometry))
    records=defaultdict(list);sources=defaultdict(list)
    for _,row in cables.iterrows():
        codes=group_codes(_value(row,(cg,)))
        if len(codes)!=1 or codes[0] not in members:continue
        group=codes[0];kind=row[ct]
        if str(row.get('_Historisch_OV',False)).casefold() in ('true','1'):kind=OV_PREFIX+str(kind)
        if str(row.get('_Aansluitkabel',False)).casefold() in ('true','1'):kind=SERVICE_PREFIX+str(kind)
        for line in _parts(row.geometry):
            records[group].append((line,_record_type(kind)))
            sources[group].append((line.buffer(.002),_value(row,('master_asset_id','Master Asset ID','id')),kind.startswith(SERVICE_PREFIX)))
    group_keys=defaultdict(set)
    for c in info.get('all_original_by_index',{}).values():
        ids=info['retention']['whole_path_edge_ids'].get(c.id,())
        if ids:
            key=(c.station,ids[0].split('|')[1])
            for eid in ids:group_keys[eid.split('|')[1]].add(key)
    held_vertices=[]
    for segments in info['physical_by_station'].values():
        for line in segments.values():held_vertices.extend((Point(line.coords[0]),Point(line.coords[-1])))
    from shapely.strtree import STRtree
    held_tree=STRtree(held_vertices) if held_vertices else None
    edges={};connections={};issues={}
    for group,group_members in members.items():
        rows=records[group]
        if not rows:
            for i,_ in group_members:issues[i]='Geen getypeerde bronkabel met aansluitgroep '+group
            continue
        lines=[g for g,_ in rows];valid=[];terminals=[]
        for i,point in group_members:
            try:_,projected=_closest_unique(lines,point,.20,'Nieuw ontwerp aansluiting '+str(i))
            except ValueError as e:issues[i]=str(e);continue
            valid.append((i,projected));terminals.append(projected)
        if not valid:continue
        union=unary_union(lines)
        if held_tree is not None:
            terminals.extend(held_vertices[int(j)] for j in held_tree.query(union,predicate='dwithin',distance=.001)
                             if union.distance(held_vertices[int(j)])<.001)
        try:_,parts,_,geometries=_make_noded_group(rows,terminals)
        except ValueError as e:
            # A conflict in the MAIN layer must not erase a separately
            # identifiable service wire. Such a wire can be transferred to
            # a planned new feeder; this does not prove the old main path.
            service_rows=[(line,SERVICE_PREFIX+'Aansluitkabel') for line,kind in rows if kind.startswith(SERVICE_PREFIX)]
            if not service_rows:
                for i,_ in valid:issues[i]=str(e)
                continue
            service_union=unary_union([line for line,_ in service_rows])
            service_targets=[(i,point) for i,point in valid if service_union.distance(point)<=.001]
            try:_,parts,_,geometries=_make_noded_group(service_rows,[point for _,point in service_targets])
            except ValueError:
                for i,_ in valid:issues[i]=str(e)
                continue
            for i,_ in valid:issues[i]='Historische hoofdkabel onduidelijk; nieuwe voeding nodig: '+str(e)
            valid=service_targets
        key=next(iter(group_keys[group])) if len(group_keys[group])==1 else ('NIEUW',group)
        for ident,_,_,kind,_ in parts:
            line=geometries[ident];asset_ids=tuple(sorted({asset for buffer,asset,is_service in sources[group] if asset and is_service==kind.startswith(SERVICE_PREFIX) and buffer.covers(line)}))
            eid='NIEUW|'+group+'|'+ident
            service=kind.startswith(SERVICE_PREFIX)
            bare=kind[len(SERVICE_PREFIX):] if service else kind
            ov=bare.startswith(OV_PREFIX)
            if ov:bare=bare[len(OV_PREFIX):]
            unrated=bare.startswith(UNRATED_PREFIX)
            if unrated:bare=bare[len(UNRATED_PREFIX):]
            edges[eid]=dict(geometry=line,assets=asset_ids,factor=0. if service else 1.,key=key,
                cable_type=bare,rating_available=not unrated,ov_route=ov)
        for i,point in valid:connections[i]=dict(key=key,xy=(point.x,point.y),historical_station_path_proven=False)
    return dict(edges=edges,connections=connections,open_points=issues)


def distinct_conductor_overlap(shared,first,second):
    """A shared drawing is allowed only with complete, distinct asset proof."""
    if shared.is_empty or shared.length<=1e-6:return True
    if not first or not second:return False
    a=unary_union(list(first.values()));b=unary_union(list(second.values()))
    if not a.buffer(.002).covers(shared) or not b.buffer(.002).covers(shared):return False
    for asset in set(first)&set(second):
        if first[asset].intersection(second[asset]).intersection(shared).length>1e-6:return False
    return True

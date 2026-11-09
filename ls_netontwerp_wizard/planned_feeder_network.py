"""Explicit 150Al design corridors; never relabel an existing GEN conductor."""
from collections import defaultdict
import math
import networkx as nx
import numpy as np
from shapely.geometry import Point,LineString
from shapely.ops import unary_union
from shapely.strtree import STRtree
from .existing_residual_circuits import CircuitNode


def add_planned_feeders(graph,nodes,unit_indices,free_units,regular_indices,
                        corridor_lines,placement_check,logger,connection_geometry_check=None,protected_equipment=None):
    if not corridor_lines:return graph,nodes,unit_indices,regular_indices,{}
    from .existing_group_trace import _parts
    lines=list(_parts(unary_union(corridor_lines)))
    segments=[]
    for line in lines:
        for a,b in zip(line.coords[:-1],line.coords[1:]):
            part=LineString([a,b])
            if part.length>1e-6:segments.append(part)
    if not segments:return graph,nodes,unit_indices,regular_indices,{}
    tree=STRtree(segments)
    model=graph.copy();nodes=list(nodes);indices={n:i for i,n in enumerate(nodes)}
    isolations=[]
    if protected_equipment is not None and not protected_equipment.is_empty:
        # Reusing an outside cable does not authorize routing a new feeder
        # through the live busbars of an existing station.
        from .existing_group_trace import _parts
        for u,v,data in list(model.edges(data=True)):
            if not data.get('source_asset_id') or not data.get('calculation_factor',1.):continue
            line=data['route_geometry'];outside=line.difference(protected_equipment)
            if line.length-outside.length<1e-6:continue
            model.remove_edge(u,v)
            for part in _parts(outside):
                ends=[]
                for xy in (part.coords[0],part.coords[-1]):
                    if Point(xy).distance(Point(model.nodes[u].get('physical_xy',u)))<1e-6:n=u
                    elif Point(xy).distance(Point(model.nodes[v].get('physical_xy',v)))<1e-6:n=v
                    else:
                        n=CircuitNode(tuple(xy),u.circuit)
                        if n not in indices:indices[n]=len(nodes);nodes.append(n);model.add_node(n,physical_xy=tuple(xy))
                        isolations.append(dict(source_asset_id=data['source_asset_id'],x=xy[0],y=xy[1],status='Nieuw eindmof-/scheidingsvoorstel buiten bestaand station'))
                    ends.append(n)
                attrs=dict(data);attrs['route_geometry']=part;attrs['physical_length']=part.length
                attrs['weight']=max(1e-6,part.length*data.get('calculation_factor',1.))
                model.add_edge(*ends,**attrs)
    unit_indices=np.array(unit_indices,copy=True)
    regular={int(i) for i in regular_indices if placement_check is None or placement_check(tuple(nodes[int(i)]))}
    positive=set();service=nx.Graph()
    for u,v,d in model.edges(data=True):
        if not d.get('source_asset_id'):continue
        if d.get('calculation_factor',1.):positive.update((u,v))
        else:service.add_edge(u,v,**d)
    demanded=defaultdict(list)
    for unit in free_units:demanded[nodes[int(unit_indices[unit])]].append(int(unit))
    def physical(node):return tuple(model.nodes[node].get('physical_xy',tuple(node)))
    def projection(xy,limit=1.):
        point=Point(xy);j=int(tree.nearest(point));line=segments[j]
        if line.distance(point)>limit:return None
        d=round(float(line.project(point)),6)
        d=0. if d<1e-6 else (float(line.length) if line.length-d<1e-6 else d)
        p=line.interpolate(d)
        return j,d,(p.x,p.y)
    requests=[];transfers=[];target_by_unit={};handled=set();issues={}
    for component in nx.connected_components(service):
        units=[u for n in component for u in demanded.get(n,())]
        if not units:continue
        candidates=list(component&positive)
        if not candidates:
            # Endpoints of a proven service network can be transferred to
            # the new main; interior service vertices are not main corridors.
            candidates=[n for n in component if service.degree(n)==1 and projection(physical(n),.20) is not None]
        if not candidates:
            for u in units:issues[u]='Geen bewezen hoofdkabelcontact voor de aansluitkabel'
            continue
        customer_nodes={n for n in component if n in demanded}
        preferred=[n for n in candidates if n not in customer_nodes]
        if preferred:candidates=preferred
        contact=min(candidates,key=lambda n:(projection(physical(n))[0] if projection(physical(n)) else math.inf,tuple(n)))
        # This is a proposed reconnection, never an assertion about a
        # currently active old feeder when several contacts are present.
        assets=sorted({d['source_asset_id'] for _,_,d in service.subgraph(component).edges(data=True)})
        service_lines={asset:unary_union([d['route_geometry'] for _,_,d in service.subgraph(component).edges(data=True) if d['source_asset_id']==asset]) for asset in assets}
        transfers.append(dict(units=units,contact=physical(contact),service_assets=assets,
            service_geometries=service_lines,other_contacts=[physical(n) for n in candidates if n!=contact],
            status='Ontwerp: bestaande aansluitkabel overzetten waar nieuwe hoofdkabel wordt gebruikt'))
        for u in units:target_by_unit[u]=contact;handled.add(u)
    # Registered direct main/cabinet terminals do not need an invented
    # service cable. Their connection location stays on that source wire.
    for node,units in demanded.items():
        if node in positive or model.nodes[node].get('proposed_main_transfer'):
            for u in units:
                if u not in handled:target_by_unit[u]=node;handled.add(u)
            if model.nodes[node].get('proposed_main_transfer'):
                transfers.append(dict(units=units,contact=physical(node),service_assets=[],service_geometries={},
                    source_main_assets=model.nodes[node].get('terminal_source_assets',()),
                    status='Ontwerp: geregistreerd hoofdkabelcontact overzetten op nieuwe 150Al; brongeleider niet hergebruikt'))
    # Service wires are endpoint evidence, not zero-metre transit shortcuts.
    for u,v,d in list(model.edges(data=True)):
        if d.get('source_asset_id') and not d.get('calculation_factor',1.):model.remove_edge(u,v)
    # Connect new mains to actually free main sections, or to the one selected
    # service transfer. Retained old wires have ordinary nodes and are absent.
    contact_nodes=positive|set(target_by_unit.values())
    split=defaultdict(set)
    for n in contact_nodes:
        pr=projection(physical(n))
        if pr is None:continue
        j,d,xy=pr;split[j].add(d);requests.append((n,j,d,xy))
    for j,line in enumerate(segments):
        if line.length>=5.:
            count=max(1,int(math.ceil(line.length/25.)))
            for k in range(count):split[j].add((k+.5)/count*line.length)
    node_at={};new_key=('ONTWERP','150AL')
    def add_node(xy):
        node=CircuitNode(tuple(float(x) for x in xy),new_key)
        if node not in indices:indices[node]=len(nodes);nodes.append(node);model.add_node(node,physical_xy=tuple(node))
        if placement_check is not None and placement_check(tuple(node)):regular.add(indices[node])
        return node
    from shapely.ops import substring
    for j,line in enumerate(segments):
        boundaries=sorted({0.,float(line.length),*split[j]})
        for d in boundaries:
            p=line.interpolate(d);node_at[(j,d)]=add_node((p.x,p.y))
        for a,b in zip(boundaries[:-1],boundaries[1:]):
            if b-a<=0:continue
            u=node_at[(j,a)];v=node_at[(j,b)];part=substring(line,a,b)
            if u==v:continue
            ident=f'ONTWERP-150AL-{j:06d}-{a:.6f}-{b:.6f}'
            model.add_edge(u,v,weight=float(part.length),physical_length=float(part.length),
                calculation_factor=1.,route_geometry=part,cable_type='150AL',
                rating_available=True,ov_route=False,planned_cable_id=ident,
                is_planned=True,construction_cost=float(part.length))
    joins=[]
    for old,j,d,xy in requests:
        new=node_at[(j,d)];start=physical(old);part=LineString([start,xy])
        # Tiny differences belong to the real proposed connection geometry;
        # non-zero approach length is counted as new 150Al, never free cable.
        if connection_geometry_check is not None and not connection_geometry_check(part):continue
        ident='ONTWERP-AANLOOP-'+str(len(joins)+1)
        model.add_edge(old,new,weight=max(1e-6,part.length),physical_length=part.length,
            calculation_factor=1. if part.length>1e-6 else 0.,route_geometry=part,
            cable_type='150AL',rating_available=True,ov_route=False,
            planned_cable_id=ident,is_planned=True,construction_cost=float(part.length),
            proposed_joint=True)
        joins.append(dict(source_node=old,planned_node=new,x=xy[0],y=xy[1],length_m=part.length))
    for unit,node in target_by_unit.items():unit_indices[unit]=indices[node]
    model.graph['planned_150al_network']=True
    logger(f'Nieuwe voeding: 150Al-ontwerpcorridors en {len(joins)} mogelijke mofcontacten; {len(target_by_unit)} aansluitingsknopen op bewezen hoofdkabel-/servicecontact. Aansluitkabels zijn geen doorvoerroute.')
    return model,nodes,unit_indices,np.asarray(sorted(regular),dtype=int),dict(
        cable_type='150AL',transfers=transfers,contacts=joins,open_units=issues,
        remapped_units=sorted(target_by_unit),isolations=isolations,status='Concept; nieuwe kabels en verbindingen nog aan te leggen')

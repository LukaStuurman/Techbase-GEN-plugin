"""Electrical gate for prospective directions, including reused conductors.

The station capacity and 850 m limit alone do not validate a 150Al feeder.
This checks one actual rooted tree. Parallel future circuits must first be
modelled explicitly; extra imaginary outgoing ports cannot make it pass.
"""
from collections import defaultdict
from .existing_station_retention import Cable,cable_check
from .reuse_first_routing import route_tree


def validate_new_directions(graph,nodes,owners,sources,targets,assignment,
                            demand_a,generation_a,first_new,max_route_m=850.):
    results=[]
    for station in range(first_new,len(sources)):
        units=[i for i,owner in enumerate(assignment) if owner==station]
        if not units:continue
        own=graph.subgraph([n for n,owner in zip(nodes,owners) if owner==station])
        root=sources[station]
        predecessors,distances=route_tree(own,root,[targets[i] for i in units],max_route_m)
        branches=defaultdict(list)
        for unit in units:
            current=targets[unit];path=[];seen=set()
            while current!=root:
                if current in seen or not predecessors.get(current):
                    path=None;break
                seen.add(current);previous=predecessors[current][0]
                path.append((previous,current));current=previous
            if path is None:
                branches[('ONBEREIKBAAR',unit)].append((unit,None));continue
            if not path:
                # A consumer at the station is still a load. It needs an
                # explicit direction terminal, not a zero-length free pass.
                branches[None].append((unit,[]));continue
            path=list(reversed(path))
            first=next(((u,v) for u,v in path if own[u][v].get('physical_length',own[u][v].get('weight',0.))>1e-8),None)
            branches[first].append((unit,path))
        for number,members in enumerate(branches.values(),1):
            checks=[];lengths=[];issues=[];assets=set()
            for unit,path in members:
                if path is None:
                    issues.append('Geen bereikbare route zonder OV of niet toetsbare hoofdkabel')
                    lengths.append(float('inf'));continue
                segments=[]
                for j,(u,v) in enumerate(path):
                    d=own[u][v];factor=float(d.get('calculation_factor',1.))
                    length=float(d.get('physical_length',d.get('weight',0.)))
                    if not factor or length<=1e-8:continue
                    ident=d.get('source_asset_id') or d.get('planned_cable_id')
                    if not ident:issues.append('Kabelidentiteit ontbreekt')
                    else:assets.add(str(ident))
                    if d.get('ov_route'):issues.append('OV-geleider mag geen nieuwe LS-voeding zijn')
                    kind=d.get('cable_type')
                    if not kind:issues.append('Werkelijk kabeltype ontbreekt');continue
                    segments.append(Cable(str(j),'NIEUW',str(j),str(j+1),kind,length,
                        electrical_check=not d.get('ov_route',False),
                        ov_route=bool(d.get('ov_route',False)),rating_available=d.get('rating_available',True)))
                if segments:checks.append(cable_check(segments))
                else:issues.append('Geen toetsbaar hoofdkabelpad')
                lengths.append(float(distances.get(targets[unit],float('inf'))))
            demand=sum(float(demand_a[i]) for i,_ in members)
            generation=sum(float(generation_a[i]) for i,_ in members)
            limiting=min(checks,key=lambda c:c['max_ontwerp_a']) if checks else {}
            maximum=float(limiting.get('max_ontwerp_a',0.))
            passed=not issues and max(demand,generation)<=maximum+1e-7 and max(lengths)<=max_route_m+1e-7
            results.append(dict(station_index=station,direction=number,connections=len(members),
                demand_a=demand,generation_a=generation,load_a=max(demand,generation),
                max_design_a=maximum,proposed_gg_a=limiting.get('gg_a'),
                longest_path_m=max(lengths),passed=passed,
                source_assets=';'.join(sorted(assets)),
                reason='; '.join(sorted(set(issues))) or ('Berekend passend; gG ontwerpvoorstel' if passed else 'Richting opsplitsen of voedingsplaats aanpassen; huidige richting onvoldoende')))
    return results

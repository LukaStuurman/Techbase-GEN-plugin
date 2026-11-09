"""Pack explicit new directions; shared trench never implies shared conductor."""
from collections import defaultdict
import networkx as nx
from .existing_station_retention import Cable,cable_check,CATALOG,type_key
from .reuse_first_routing import route_tree


def direction_design_graph(graph,node_owners,station):
    """New independent cables may share a corridor across scalar territories.

    Existing source wires remain reserved to their assigned station. The
    planned mesh is a corridor opportunity, never one installed common wire.
    """
    def allowed(u,v):
        data=graph[u][v]
        if not data.get('is_planned'):
            return node_owners.get(u)==station and node_owners.get(v)==station
        for node in (u,v):
            if getattr(node,'circuit',None)!=('ONTWERP','150AL') and node_owners.get(node)!=station:return False
        return True
    return nx.subgraph_view(graph,filter_edge=allowed).copy()


def design_station_directions(graph,root,targets,demand,generation,max_route_m=850.,geometry_check=None):
    """Keep each proven service terminal indivisible and reuse free mains first.

    A source edge may belong to one direction only. Other directions require
    explicit parallel 150Al, checked against the same geometry exclusions.
    This is a design proposal, not a claim that those cables already exist.
    """
    bundles=defaultdict(list)
    for unit,node in targets.items():bundles[node].append(unit)
    pred,_=route_tree(graph,root,list(bundles),max_route_m)
    shortest=nx.dijkstra_predecessor_and_distance(graph,root,weight='weight')[0]
    def impedance_weight(u,v,data):
        if not data.get('calculation_factor',1.):return 1e-9
        try:r=CATALOG[type_key(data.get('cable_type'))][0]
        except ValueError:return float('inf')
        return max(1e-9,float(data.get('physical_length',data.get('weight',0.)))*r)
    impedance=nx.dijkstra_predecessor_and_distance(graph,root,weight=impedance_weight)[0]
    def path_to(node,predecessors):
        path=[];seen=set()
        while node!=root:
            if node in seen or not predecessors.get(node):return None
            seen.add(node);parent=predecessors[node][0]
            path.append((parent,node));node=parent
        return list(reversed(path))
    path_cache={};geometry_cache={}
    def evaluate(paths,units,replaced):
        dv=sum(float(demand[u]) for u in units);gv=sum(float(generation[u]) for u in units)
        if max(dv,gv)>225.+1e-7:return None
        checks=[];used={};lengths=[]
        for path in paths:
            path_key=(tuple(path),frozenset(frozenset((u,v)) for u,v in path)&frozenset(replaced))
            if path_key in path_cache:
                cached=path_cache[path_key]
                if cached is None:return None
                check,length,path_used=cached
                checks.append(check);lengths.append(length);used.update(path_used);continue
            path_cache[path_key]=None
            path_used={}
            segments=[];length=0.
            for u,v in path:
                data=graph[u][v];factor=float(data.get('calculation_factor',1.))
                if not factor:continue
                metres=float(data.get('physical_length',data.get('weight',0.)))
                if metres<=1e-8:continue
                edge=frozenset((u,v));planned=bool(data.get('is_planned')) or edge in replaced
                if planned and geometry_check is not None:
                    if edge not in geometry_cache:geometry_cache[edge]=geometry_check(data['route_geometry'])
                    if not geometry_cache[edge]:return None
                if not planned and (data.get('ov_route') or not data.get('rating_available',True)):return None
                kind='150AL' if planned else data.get('cable_type')
                if not kind:return None
                try:c= Cable(str(len(segments)),'NIEUW',str(len(segments)),str(len(segments)+1),kind,metres)
                except ValueError:return None
                segments.append(c);length+=metres;path_used[edge]=(u,v,planned)
            if not segments:return None
            check=cable_check(segments);checks.append(check);lengths.append(length);used.update(path_used)
            path_cache[path_key]=(check,length,path_used)
        if not checks:return None
        limiting=min(checks,key=lambda c:c['max_ontwerp_a'])
        if max(dv,gv)>limiting['max_ontwerp_a']+1e-7 or max(lengths)>max_route_m+1e-7:return None
        union=nx.Graph()
        for path in paths:union.add_edges_from(path)
        if not nx.is_forest(union):return None
        return dict(demand_a=dv,generation_a=gv,load_a=max(dv,gv),max_design_a=limiting['max_ontwerp_a'],
            proposed_gg_a=limiting['gg_a'],longest_path_m=max(lengths),edges=used,
            new_length_m=sum(float(graph[u][v].get('physical_length',graph[u][v].get('weight',0.))) for u,v,planned in used.values() if planned),
            reused_length_m=sum(float(graph[u][v].get('physical_length',graph[u][v].get('weight',0.))) for u,v,planned in used.values() if not planned))
    bins=[];claimed=set();unresolved={}
    ordered=sorted(bundles,key=lambda n:-max(sum(float(demand[u]) for u in bundles[n]),sum(float(generation[u]) for u in bundles[n])))
    for node in ordered:
        units=bundles[node];candidate_paths=[]
        for predecessor in (pred,shortest,impedance):
            path=path_to(node,predecessor)
            if path is not None and path not in candidate_paths:candidate_paths.append(path)
        choices=[]
        def consider(path):
            source_edges={frozenset((u,v)) for u,v in path if graph[u][v].get('source_asset_id') and graph[u][v].get('calculation_factor',1.)}
            for index in range(len(bins)+1):
                b=bins[index] if index<len(bins) else dict(paths=[],units=[],replaced=set(),assessment=None)
                own_source=set() if b['assessment'] is None else {e for e,(_u,_v,planned) in b['assessment']['edges'].items() if not planned}
                conflict=source_edges & (claimed-own_source)
                # First retain actual source material. Replacing a source
                # path is considered only if reuse cannot carry this bundle.
                for replacement in (conflict,source_edges):
                    replaced=b['replaced']|replacement
                    assessment=evaluate(b['paths']+[path],b['units']+units,replaced)
                    if assessment is None:continue
                    previous_new=0. if b['assessment'] is None else b['assessment']['new_length_m']
                    choices.append((assessment['new_length_m']-previous_new,index,path,replaced,assessment))
                    break
        for path in candidate_paths:consider(path)
        if not choices and claimed:
            # A previously reused wire cannot become a second circuit under
            # a building. Search another real corridor before rejecting the
            # consumer; the initially cheapest path need not be feasible.
            def available(u,v):
                edge=frozenset((u,v))
                if edge not in claimed or geometry_check is None:return True
                if edge not in geometry_cache:geometry_cache[edge]=geometry_check(graph[u][v]['route_geometry'])
                return geometry_cache[edge]
            alternative=nx.subgraph_view(graph,filter_edge=available)
            try:
                path=nx.shortest_path(alternative,root,node,weight=impedance_weight)
                consider(list(zip(path[:-1],path[1:])))
            except (nx.NetworkXNoPath,nx.NodeNotFound):pass
        if not choices:
            for u in units:unresolved[u]='Ondeelbaar aansluitpunt past niet op een getoetste richting; voedingsplaats of aansluitontwerp aanpassen'
            continue
        _,index,path,replaced,assessment=min(choices,key=lambda c:(c[0],c[1]))
        if index==len(bins):bins.append(dict(paths=[],units=[],unit_paths={},replaced=set(),assessment=None))
        b=bins[index];b['paths'].append(path);b['units'].extend(units);b['replaced']=replaced;b['assessment']=assessment
        b['unit_paths'].update({u:path for u in units})
        claimed={e for bucket in bins for e,(_u,_v,planned) in bucket['assessment']['edges'].items() if not planned}
    return dict(directions=bins,unresolved=unresolved,ports=len(bins),ports_within_ten=len(bins)<=10)

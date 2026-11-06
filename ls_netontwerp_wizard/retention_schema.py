"""Verified schema cable chains for historical physical-group tracing."""
from .schema_linking import build_mapping,station_lookup

def unique_schema_path(mapping,source,code):
    """A unique station name alone does NOT prove a unique cabinet feeder."""
    import networkx as nx
    graph=nx.DiGraph(mapping.get('electrical_edges',[]))
    roots=set(mapping.get('source_roots',{}).get(source,[]));target='c:'+code
    if target not in graph or not roots:return False
    reached=set()
    for root in roots:
        if root in graph:reached.update(nx.descendants(graph,root)|{root})
    relevant=reached&(nx.ancestors(graph,target)|{target})
    if not relevant:return False
    graph=graph.subgraph(relevant)
    condensed=nx.condensation(graph)
    # Closed K rail bridges are legitimate, but a cable cycle does not
    # establish how parallel feeders carry the load.
    if any(len(d['members'])>1 and any(n.startswith('c:') for n in d['members'])
           for _,d in condensed.nodes(data=True)):return False
    lookup=condensed.graph['mapping'];counts={n:0 for n in condensed}
    for r in {lookup[r] for r in roots if r in lookup}:counts[r]=1
    for n in nx.topological_sort(condensed):
        for child in condensed.successors(n):counts[child]=min(2,counts[child]+counts[n])
    return counts[lookup[target]]==1

def build_retention_schema(xml,excel,dxf,stations):
    mapping=build_mapping(xml,excel,dxf)
    aliases=station_lookup(stations)
    paths={}
    for code,record in mapping['groups'].items():
        sources=record['stations']; chain=record.get('cable_path',[])
        if len(sources)!=1 or not chain or not unique_schema_path(mapping,sources[0],code):continue
        names=aliases.get(sources[0],set())
        if len(names)!=1:continue
        paths[next(iter(names))+'|'+code]=chain
    return dict(paths=paths,files=mapping['files'],mode=mapping['mode'])

"""Prefer reused conductor, while retaining the hard physical route limit."""
import networkx as nx


def route_tree(graph, source, targets, max_route_m):
    """Return one coherent tree; never mix two paths into an electrical loop.

    Construction metres dominate the secondary physical-length preference.
    If that tree violates the route limit, use the physical shortest tree.
    Invalid electrical source conductors are never offered for reuse.
    """
    usable = nx.subgraph_view(graph, filter_edge=lambda u,v: not (
        graph[u][v].get('source_asset_id') and
        graph[u][v].get('calculation_factor',1.) and
        (graph[u][v].get('ov_route',False) or not graph[u][v].get('rating_available',True))))
    physical = lambda u,v,d: float(d.get('weight',1.))
    if not graph.graph.get('planned_150al_network'):
        return nx.dijkstra_predecessor_and_distance(usable,source,weight=physical)
    # A bounded secondary term keeps a metre of new cable more expensive
    # than any possible saving in existing route length in this graph.
    scale = 1. + sum(max(0.,physical(u,v,d)) for u,v,d in usable.edges(data=True))
    cost = lambda u,v,d: max(0.,float(d.get('construction_cost',0.))) + physical(u,v,d)/scale
    predecessors, _ = nx.dijkstra_predecessor_and_distance(usable,source,weight=cost)
    distances = {source:0.}
    def distance(node):
        pending=[];current=node
        while current not in distances:
            if not predecessors.get(current):return float('inf')
            pending.append(current);current=predecessors[current][0]
        for child in reversed(pending):
            parent=predecessors[child][0]
            distances[child]=distances[parent]+physical(parent,child,usable[parent][child])
        return distances[node]
    if any(distance(target)>max_route_m+1e-6 for target in targets):
        return nx.dijkstra_predecessor_and_distance(usable,source,weight=physical)
    for node in predecessors:distance(node)
    return predecessors,distances

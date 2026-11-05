"""Station internal conductors must join their perimeter at real vertices."""
import os,sys
from pathlib import Path


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    import geopandas as gpd
    import pandas as pd
    import networkx as nx
    from shapely.geometry import Point,LineString
    from ls_netontwerp_wizard.algorithms.laagspanning_clustering_lib import maak_clustering_engine as e
    outline=LineString([(153645.54,409158.705),(153647.183,409159.485),
        (153647.751,409158.337),(153648.067,409157.699),
        (153646.413,409156.869),(153645.54,409158.705)])
    station=Point(153646.79925752824,409158.18553413474)
    demand=Point(153660,409170)
    frame=lambda data,geometry:gpd.GeoDataFrame(data,geometry=geometry,crs=e.CRS_RD)
    stations=frame({'Stationsnaa':['S1']},[station])
    enclosures=frame({'Stationsnaa':['S1']},[outline])
    cables=frame({},[LineString([(153647.751,409158.337),demand.coords[0]])])
    links=e.make_equipment_network_links(cables,stations,enclosures,None,1.)
    spur=links.loc[links.Element=='Stationpunt-omtrek','geometry'].iloc[0]
    assert tuple(spur.coords[-1]) in list(outline.coords)
    assert links.loc[links.Element=='Stationpunt-omtrek','Reken_m'].iloc[0]==0
    all_lines=frame({},list(cables.geometry)+list(links.geometry))
    noded=e.node_cable_network(all_lines,frame({},[demand]),stations,1.)
    graph=e.build_network(noded)
    a=tuple(round(x,1) for x in station.coords[0]);b=tuple(round(x,1) for x in demand.coords[0])
    assert nx.has_path(graph,a,b)
    import numpy as np
    graph=nx.path_graph([(float(x),0.) for x in range(6)])
    nx.set_edge_attributes(graph,1.,'weight')
    nodes=list(graph);owners=np.array([0,0,0,1,1,1]);assignment=np.array([0,1])
    sources=[nodes[0],nodes[5]];units=[nodes[1],nodes[4]]
    result=e.absorb_new_territories_into_existing(graph,nodes,owners,sources,units,assignment,np.array([519.,51.]),np.array([580.,913.]),1)
    assert result[2]==[0] and list(result[0])==[0,0]
    rejected=e.absorb_new_territories_into_existing(graph,nodes,owners,sources,units,assignment,np.array([540.,51.]),np.array([580.,913.]),1)
    assert rejected[2]==[0,1]
    graph.remove_edge(nodes[2],nodes[3])
    rejected=e.absorb_new_territories_into_existing(graph,nodes,owners,sources,units,assignment,np.array([519.,51.]),np.array([580.,913.]),1)
    assert rejected[2]==[0,1]
    print('STATION_ENCLOSURE_CONNECTION_OK (non-axis-aligned outline, exact shared vertex, reachable demand, zero internal calculation length)',flush=True)
    os._exit(0)


if __name__=='__main__':main()

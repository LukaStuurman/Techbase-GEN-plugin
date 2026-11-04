"""Route corridor repair must never leave overlapping cluster territories."""
import os
import sys
from pathlib import Path


def main():
    plugin = Path(__file__).resolve().parent
    sys.path.insert(0,str(plugin/'algorithms/laagspanning_clustering_lib'))
    from qgis.core import QgsApplication
    app=QgsApplication([],False);app.initQgis()
    import maak_clustering_engine as engine
    import numpy as np
    from shapely.geometry import Point,LineString,box
    from shapely.ops import unary_union
    def validate(polygons,study,supports,points):
        coverage=unary_union(polygons)
        assert abs(sum(p.area for p in polygons)-coverage.area) < 1e-7
        assert coverage.symmetric_difference(study).area < 1e-7
        assert all(p.is_valid and not p.is_empty for p in polygons)
        for index,geometry in enumerate(supports):
            assert geometry.intersection(study).difference(polygons[index].buffer(.05)).length < .1
            assert all(polygons[index].covers(p) for p in points[index])
    # Parallel physical cables closer than two repair-corridor widths.
    routes=[LineString([(0,0),(10,0)]),LineString([(0,.8),(10,.8)])]
    points=np.asarray([(8.,0.),(8.,.8)])
    assignments=np.asarray([0,1])
    stations=np.asarray([(0.,0.),(0.,.8)])
    plan=box(-1,-1,11,2)
    polygons,study=engine.make_cable_based_cluster_polygons(routes,points,points,assignments,
                                                         stations,stations,2,plan,allow_external_routes=True)
    validate(polygons,study,routes,[[Point(8,0)],[Point(8,.8)]])
    assert routes[0].equals(LineString([(0,0),(10,0)]))
    # Two real routes inside one overlap face require a split, not first-owner
    # wins. Each cable and customer's location must retain its own territory.
    originals=[box(0,0,6,10),box(4,0,10,10)]
    supports=[LineString([(4.5,0),(4.5,10)]),LineString([(5.5,0),(5.5,10)])]
    partition=engine.partition_cluster_overlaps(originals,supports,box(0,0,10,10))
    validate(partition,box(0,0,10,10),supports,[[Point(4.5,5)],[Point(5.5,5)]])
    assert all(abs(p.area-50.)<1e-6 for p in partition)
    assert originals[0].area==60. and originals[1].area==60.
    # An inactive station can lose a route-free fragment when its neighbour's
    # corridor is cut out. Keep its anchor and join the empty fragment to the
    # edge-adjacent neighbour; never strand an unconnected fragment.
    originals=[box(0,0,10,10),box(4,0,6,10)]
    supports=[Point(1,1),LineString([(5,0),(5,10)])]
    partition=engine.partition_cluster_overlaps(originals,supports,box(0,0,10,10))
    validate(partition,box(0,0,10,10),supports,[[Point(1,1)],[Point(5,5)]])
    assert all(p.geom_type=='Polygon' for p in partition)
    # Already-disjoint coverages keep the original objects and coordinates.
    originals=[box(0,0,5,10),box(5,0,10,10)]
    assert engine.partition_cluster_overlaps(originals,supports,box(0,0,10,10)) is originals
    # Narrow kinked corridors at projected-coordinate scale. Classifying a
    # disputed face must preserve both nearby routes and their endpoint dots.
    from shapely.affinity import translate
    routes=[LineString([(0,0),(.2,1.4),(.2,2),(.3,2.2),(.3,2.8)]),
            LineString([(.9,0),(1.1,1.5),(1.1,2.7)])]
    routes=[translate(route,160000.,390000.) for route in routes]
    dots=[[Point(160000.331,390002.764)],[Point(160001.105,390002.692)]]
    supports=[unary_union([route,*points]) for route,points in zip(routes,dots)]
    study=box(159999.,389999.,160003.,390004.)
    originals=[study.intersection(box(159999.,389999.,160000.7,390004.)).union(routes[0].buffer(.75)),
               study.intersection(box(160000.7,389999.,160003.,390004.)).union(routes[1].buffer(.75))]
    originals=[p.intersection(study) for p in originals]
    partition=engine.partition_cluster_overlaps(originals,supports,study)
    validate(partition,study,supports,dots)
    print('CLUSTER_BOUNDARY_PARTITION_TEST_OK (parallel routes, overlap face splitting, point/route ownership, orphan fragment, conservation, unchanged valid input)',flush=True)
    os._exit(0)


if __name__=='__main__':
    main()

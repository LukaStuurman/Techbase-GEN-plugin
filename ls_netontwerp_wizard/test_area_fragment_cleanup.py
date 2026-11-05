"""Final boundary cleanup must preserve anchored areas and full coverage."""
import os,sys
from pathlib import Path


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from shapely.geometry import box,MultiPolygon,Point,LineString
    from shapely.ops import unary_union
    from ls_netontwerp_wizard.algorithms.laagspanning_clustering_lib import maak_clustering_engine as e
    main=box(0,0,2,2);fragment=box(3,0,4,1);neighbour=box(2,0,5,2).difference(fragment)
    before=[MultiPolygon([main,fragment]),neighbour]
    after,count=e.transfer_unanchored_area_fragments(before,[Point(1,1),Point(4.5,1.5)])
    assert count==1 and after[0].equals(main)
    assert unary_union(before).symmetric_difference(unary_union(after)).area<1e-9
    assert after[0].intersection(after[1]).area<1e-9
    # A real customer/route on the detached part makes transfer forbidden.
    anchored,count=e.transfer_unanchored_area_fragments(before,[unary_union([Point(1,1),LineString([(3.1,.5),(3.9,.5)])]),Point(4.5,1.5)])
    assert count==0 and anchored[0].equals(before[0])
    print('AREA_FRAGMENT_CLEANUP_OK (unanchored fragment transferred, anchored route retained, full coverage and disjointness unchanged)',flush=True)
    os._exit(0)


if __name__=='__main__':main()

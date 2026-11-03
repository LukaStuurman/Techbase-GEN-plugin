"""Regression checks for batched cluster edits, station retirement and exact undo."""
import os
import sys
import tempfile
from pathlib import Path


def fixture_frames():
    import geopandas as gpd
    from shapely.geometry import Point, LineString, box
    crs='EPSG:28992'
    summary={'Volgnummer':[1,2,3],'Cluster':['A','B','C'],'Type':['Bestaand','Bestaand','Nieuw'],'KVA':[630.]*3,'Max_A':[630/.23/3]*3,'Belast_A':[10.]*3,'Benut_pct':[1.]*3,'Aantal':[1]*3,'Gem_route':[10.]*3,'Max_route':[10.]*3,'Route_km':[.01]*3,'__src_fid':[1,2,3]}
    frames={
    'connections':gpd.GeoDataFrame({'Cluster':['A','B','C'],'Ontwerp_A':[10.]*3,'Route_m':[10.]*3,'__src_fid':[1,2,3]},geometry=[Point(x,10) for x in (0,10,20)],crs=crs),
    'stations':gpd.GeoDataFrame(summary,geometry=[Point(x,0) for x in (0,10,20)],crs=crs),
    'areas':gpd.GeoDataFrame(summary,geometry=[box(-5,-5,5,15),box(5,-5,15,15),box(15,-5,25,15)],crs=crs),
    'routes':gpd.GeoDataFrame(summary,geometry=[LineString([(x,0),(x,10)]) for x in (0,10,20)],crs=crs),
    'cables':gpd.GeoDataFrame({'__src_fid':[1,2,3,4,5]},geometry=[LineString([(0,0),(0,10)]), LineString([(10,0),(10,10)]),
            LineString([(20,0),(20,5),(20,10)]),
            LineString([(0,10),(10,10)]), LineString([(10,10),(20,10)])],crs=crs)}
    for name, values in {"Stat_type":["Bestaand","Bestaand","Nieuw"], "Stat_KVA":[630.]*3,
                         "Max_A":[630/.23/3]*3,"Clust_A":[10.]*3,"Benut_pct":[1.]*3,"Snap_m":[0.]*3}.items():
        frames['connections'][name]=values
    return frames


def main():
    plugin = Path(__file__).resolve().parent
    sys.path.insert(0, str(plugin.parent))
    sys.path.insert(0, str(plugin/'algorithms/laagspanning_clustering_lib'))
    from qgis.core import QgsApplication, QgsProject, QgsVectorLayer, QgsProcessingFeedback
    from qgis.PyQt.QtCore import QCoreApplication
    app = QgsApplication([], False)
    app.initQgis()
    QCoreApplication.setOrganizationName('LSClusterManagementTests')
    QCoreApplication.setApplicationName('Isolated')
    import maak_clustering_engine as engine
    from batch_correction_runner import calculate
    from ls_netontwerp_wizard.batch_editing import run_batch, apply_snapshot, station_rules
    from ls_netontwerp_wizard.cluster_management import fingerprint
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    frames = fixture_frames()
    operations = [{'kind':'retire','source':'A','target':'B'}, {'kind':'retire','source':'C','target':'B'}]
    count = [0]
    original = engine.make_cable_based_cluster_polygons
    def counted(*args, **kwargs):
        count[0] += 1
        return original(*args, **kwargs)
    engine.make_cable_based_cluster_polygons = counted
    state, summary = calculate(engine,frames,operations,850)
    assert count[0] == 1
    assert state[1].Cluster.tolist() == ['B']
    assert summary['station_rules']['A']['status'] == 'Te verwijderen'
    assert summary['station_rules']['C']['status'] == 'Vervallen'
    count[0] = 0
    state, summary = calculate(engine,frames,[{'kind':'retire','source':'A','target':None}],850,preview=True)
    assert count[0] == 0 and not (state[0].Cluster=='A').any()
    try:
        calculate(engine,frames,[{'kind':'protect','station':'A'}, operations[0]],850)
    except ValueError as exc:
        assert 'beschermd' in str(exc)
    else:
        raise AssertionError('Protected station was removed')
    assert frames['connections'].Cluster.tolist() == ['A','B','C']
    # Relocating a new station must modify its actual geometry and route, never
    # just its map symbol. The route solver must use the selected cable vertex.
    from shapely.geometry import LineString
    relocation_input = fixture_frames()
    relocation_input['cables'].at[2, 'geometry'] = LineString(
        [(20, 0), (20, 5), (20, 10)]
    )
    relocation = [{'kind':'relocate','source':'C','x':20.0,'y':5.0}]
    moved_state, changed = calculate(engine, relocation_input, relocation, 850)
    moved_station = moved_state[1].loc[moved_state[1].Cluster=='C'].iloc[0]
    moved_route = moved_state[3].loc[moved_state[3].Cluster=='C'].iloc[0].geometry
    assert moved_station.geometry.distance(relocation_input['stations'].iloc[2].geometry)==5.0
    assert moved_station.geometry.y == 5.0
    assert moved_route.distance(moved_station.geometry) < 0.02
    assert moved_state[0].loc[moved_state[0].Cluster=='C','Route_m'].iloc[0] <= 5.01
    assert changed['relocated_stations']==['C']
    assert changed['station_rules']['C']['protected'] is True
    assert relocation_input['stations'].iloc[2].geometry.y == 0.0
    before_preview = relocation_input['stations'].geometry.copy()
    _preview_state, preview_change = calculate(
        engine, relocation_input, relocation, 850, preview=True
    )
    assert preview_change['relocated_stations']==['C']
    assert relocation_input['stations'].geometry.equals(before_preview)
    for forbidden, expected_error in (
        ([{'kind':'relocate','source':'A','x':0.0,'y':5.0}], 'nieuw geplaatste'),
        ([{'kind':'relocate','source':'C','x':10.0,'y':10.0}], 'buiten het clustergebied'),
        ([{'kind':'relocate','source':'C','x':20.0,'y':6.0}], 'netwerkknoop'),
    ):
        try:
            calculate(engine, relocation_input, forbidden, 850, preview=True)
        except ValueError as exc:
            assert expected_error in str(exc), (expected_error, str(exc))
        else:
            raise AssertionError(f"Unsafe relocation was allowed: {forbidden}")
    # Capacity failure must reject a complete queue without mutating inputs.
    too_small=fixture_frames()
    too_small['stations'].loc[too_small['stations'].Cluster=='B','KVA']=10
    try:
        calculate(engine,too_small,[operations[0]],850)
    except RuntimeError as exc:
        assert 'stationcapaciteit' in str(exc)
    else:
        raise AssertionError('Overload accepted')
    import numpy as np
    assert engine.excluded_station_mask(np.asarray([[0,0],[10,0],[30,0]]), [{'x':0,'y':0,'radius':20}]).tolist()==[True,True,False]
    pinned=engine.include_pinned_stations(frames['stations'].rename(columns={'Cluster':'Stationsnaa'}),[{'name':'N-99','x':50,'y':50,'kva':630}])
    assert len(pinned)==4 and pinned.iloc[-1].Stationsnaa=='N-99'
    engine.make_cable_based_cluster_polygons = original
    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        directory=Path(directory)
        source=directory/'test.gpkg'
        tables={'connections':'aansluitingen_geclusterd','stations':'stations_ontwerp','areas':'clustergebieden','routes':'cluster_kabelroutes','cables':'sleuven_genood'}
        names={'connections':'Aansluitingen geclusterd','stations':'Stations ontwerp','areas':'Clustergebieden','routes':'Kabelroutes per cluster','cables':'Sleuven geknipt/genood'}
        for key,table in tables.items():
            frames[key].drop(columns=['__src_fid']).to_file(source,layer=table,driver='GPKG')
        layers={key:QgsVectorLayer(f'{source}|layername={table}',names[key],'ogr') for key,table in tables.items()}
        project=QgsProject.instance()
        for layer in layers.values():
            assert layer.isValid()
            project.addMapLayer(layer)
        layers['plan']=None
        before=fingerprint(layers)
        summary,backup,result=run_batch(layers,operations,directory,850,True,QgsProcessingFeedback())
        assert fingerprint(layers)==before
        summary,backup,result=run_batch(layers,operations,directory,850,False,QgsProcessingFeedback())
        assert layers['stations'].featureCount()==1
        apply_snapshot(layers,backup)
        assert fingerprint(layers)==before
        # Geometry and routes are written together, and an exact snapshot
        # restores both the moved station and its old cable route.
        new_position = [{'kind':'relocate','source':'C','x':20.0,'y':5.0}]
        relocation_summary, relocation_backup, _result = run_batch(
            layers, new_position, directory, 850, False, QgsProcessingFeedback()
        )
        assert relocation_summary['relocated_stations'] == ['C']
        station_c = next(f for f in layers['stations'].getFeatures() if f['Cluster']=='C')
        assert abs(station_c.geometry().asPoint().y()-5.0) < 0.02
        route_c = next(f for f in layers['routes'].getFeatures() if f['Cluster']=='C')
        assert route_c.geometry().distance(station_c.geometry()) < 0.02
        apply_snapshot(layers, relocation_backup)
        assert fingerprint(layers) == before
        # Roll back every table when a later write is rejected by SQLite.
        import sqlite3
        connection=sqlite3.connect(source)
        connection.execute("CREATE TRIGGER test_abort BEFORE UPDATE ON clustergebieden BEGIN SELECT RAISE(ABORT,'rollback test'); END")
        connection.commit(); connection.close()
        try:
            apply_snapshot(layers,result)
        except sqlite3.DatabaseError as exc:
            assert 'rollback test' in str(exc)
        else:
            raise AssertionError('Injected write failure was not reached')
        assert fingerprint(layers)==before
        connection=sqlite3.connect(source)
        connection.execute('DROP TRIGGER test_abort');connection.commit();connection.close()
        cancelled=QgsProcessingFeedback()
        cancelled.cancel()
        try:
            run_batch(layers,operations,directory,850,False,cancelled)
        except ValueError as exc:
            assert 'geannuleerd' in str(exc)
        else:
            raise AssertionError('Cancelled operation applied')
        assert fingerprint(layers)==before
        dialog=LSNetontwerpDashboardDialog(None)
        dialog.show_manual_page()
        page=dialog.cluster_management_page
        assert project.write(str(directory/'project.qgz'))
        page.add_operation(operations[0],'A to B')
        page.add_operation(operations[1],'C to B')
        page.execute(False)
        assert page.queue.count()==0,page.status.text()
        assert station_rules()['A']['status']=='Te verwijderen'
        assert layers['stations'].featureCount()==1,page.status.text()
        project_path=project.fileName()
        project.clear()
        assert project.read(project_path)
        page.refresh()
        assert station_rules()['A']['status']=='Te verwijderen'
        page.undo()
        assert page.layers['stations'].featureCount()==3,page.status.text()
        assert fingerprint(page.layers)==before,page.status.text()
        assert station_rules()=={}
        # Pending changes become invalid if someone edits the source meanwhile.
        page.add_operation({'kind':'move','point_ids':[1],'target':'B'},'test')
        layer=page.layers['connections']
        index=layer.fields().lookupField('Ontwerp_A')
        layer.dataProvider().changeAttributeValues({1:{index:11.}})
        page.execute(True)
        assert 'tussentijds' in page.status.text(),page.status.text()
        project.clear()
    print('CLUSTER_MANAGEMENT_TEST_OK (batch, station relocation, strict route rebuild, auto redistribution, protection, capacity, rollback, exact undo, stale queue)',flush=True)
    os._exit(0)


if __name__=='__main__':
    main()

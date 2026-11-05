"""Outside-plan detours, real option defaults and safe later recalculation."""
import json
import os
import sys
import tempfile
from pathlib import Path


def main():
    plugin = Path(__file__).resolve().parent
    sys.path.insert(0, str(plugin.parent))
    sys.path.insert(0, str(plugin/'algorithms/laagspanning_clustering_lib'))
    from qgis.core import QgsApplication, QgsProject, QgsVectorLayer, QgsProcessingFeedback, QgsProcessingContext
    from qgis.PyQt.QtGui import QFont, QFontDatabase
    from qgis.PyQt.QtWidgets import QScrollArea
    app = QgsApplication([], False)
    app.initQgis()
    app.setOrganizationName('LSExternalRouteTests')
    app.setApplicationName('Isolated')
    for filename in ('segoeui.ttf', 'segoeuib.ttf'):
        QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts')/filename))
    app.setFont(QFont('Segoe UI', 10))
    import geopandas as gpd
    import numpy as np
    from shapely.geometry import Point, LineString, box, MultiPolygon
    from ls_netontwerp_wizard.algorithms.laagspanning_clustering_tool import LaagspanningClusteringAlgorithm
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    from ls_netontwerp_wizard.clustering_options import ClusteringOptionsDialog
    from ls_netontwerp_wizard.workflow import WorkflowRunner
    from ls_netontwerp_wizard.batch_editing import run_batch, apply_snapshot
    from ls_netontwerp_wizard.cluster_management import fingerprint
    from batch_correction_runner import calculate

    with tempfile.TemporaryDirectory(prefix='ls_external_', dir=plugin.parent.parent, ignore_cleanup_errors=True) as directory:
        root = Path(directory)
        crs = 'EPSG:28992'
        # A U-shaped cable leaves the rectangular plan at y=5 and returns.
        # The only connection between the two in-plan legs is OUTSIDE it.
        cable = LineString([(0,0),(0,1),(0,2),(0,3),(0,4),(0,5),(0,10),
                            (20,10),(20,5),(20,4),(20,3),(20,2),(20,1),(20,0),(30,0)])
        plan = box(-5,-5,25,5)
        paths = {name:root/f'{name}.gpkg' for name in ('points','cables','stations','plan')}
        points = gpd.GeoDataFrame({'Ontwerpstroom':[10.,5.,999.], 'Hoogste Trafo':[10.,5.,999.], 'GebiedLabel':['']*3},
                                 geometry=[Point(20,0),Point(0,2),Point(30,0)], crs=crs)
        points.to_file(paths['points'], layer='points', driver='GPKG')
        gpd.GeoDataFrame(geometry=[cable], crs=crs).to_file(paths['cables'], driver='GPKG')
        gpd.GeoDataFrame({'Stationsnaa':['S1','outside'], 'Status':['630Kva','10Kva']},
                        geometry=[Point(0,0),Point(30,0)], crs=crs).to_file(paths['stations'], driver='GPKG')
        gpd.GeoDataFrame(geometry=[plan], crs=crs).to_file(paths['plan'], layer='plangebied', driver='GPKG')

        def engine_for(name, allow=True, maximum=850):
            engine = LaagspanningClusteringAlgorithm._load_engine()
            engine.POINTS_PATH, engine.CABLES_PATH, engine.STATIONS_PATH = paths['points'], paths['cables'], paths['stations']
            engine.PLANGEBIED_PATH = paths['plan']
            engine.CONNECTION_CABLES_PATH = engine.FLAT_CABINETS_PATH = engine.STATION_ENCLOSURES_PATH = engine.DISTRIBUTION_CABINETS_PATH = None
            engine.OUT = root/name
            engine.AUTO_NEW_STATIONS, engine.N_NEW = False, 0
            engine.ALLOW_EXTERNAL_ROUTES = allow
            engine.ONLY_WITHIN_PLAN_AREA = True
            engine.AUTO_NODE_CABLES = True
            engine.NODE_TOLERANCE_M = 0.
            engine.CREATE_QGIS_PROJECT = engine.WRITE_SHAPEFILES = False
            engine.CPU_THREADS = 1
            engine.MAX_ROUTE_M = maximum
            engine.make_map = lambda *_: None
            return engine

        engine = engine_for('allowed')
        engine.main()
        gpkg = engine.OUT/'clustering_ontwerp.gpkg'
        connections = gpd.read_file(gpkg, layer='aansluitingen_geclusterd')
        routes = gpd.read_file(gpkg, layer='cluster_kabelroutes')
        areas = gpd.read_file(gpkg, layer='clustergebieden')
        stations = gpd.read_file(gpkg, layer='stations_ontwerp')
        assert len(connections) == 2 and connections.Ontwerp_A.sum() == 15.
        assert stations.Cluster.tolist() == ['S1'] and stations.Belast_A.iloc[0] == 15.
        assert abs(connections.Route_m.max()-40.) < .01
        assert routes.iloc[0].geometry.difference(plan).length > 20
        assert areas.iloc[0].geometry.difference(plan).area < 1e-8
        assert engine.external_routing_enabled(routes)
        for name, allow, maximum in [('strict',False,850), ('too_long',True,30)]:
            try:
                engine_for(name, allow, maximum).main()
            except RuntimeError:
                assert not (root/name/'clustering_ontwerp.gpkg').exists()
            else:
                raise AssertionError(f'Unsafe route accepted: {name}')
        # New sites remain inside the plan even though most routing cable is
        # outside; extra demand forces one new site into the selected network.
        heavier = gpd.GeoDataFrame({'Ontwerpstroom':[800.,500.,1.,1.,1.,1.,999.], 'GebiedLabel':['']*7},
            geometry=[Point(20,0),Point(0,2),Point(0,6),Point(20,6),Point(0,10),Point(20,10),Point(30,0)],crs=crs)
        heavier.to_file(root/'heavier.gpkg', driver='GPKG')
        heavy_plan = box(-5,-5,25,15)
        gpd.GeoDataFrame(geometry=[heavy_plan],crs=crs).to_file(root/'heavy_plan.gpkg',driver='GPKG')
        heavy_cable=LineString([(0,float(y)) for y in range(16)]+[(0,30),(20,30)]+
                              [(20,float(y)) for y in range(15,-1,-1)]+[(30,0)])
        gpd.GeoDataFrame(geometry=[heavy_cable],crs=crs).to_file(root/'heavy_cables.gpkg',driver='GPKG')
        new_engine = engine_for('with_new_station')
        new_engine.POINTS_PATH = root/'heavier.gpkg'
        new_engine.PLANGEBIED_PATH = root/'heavy_plan.gpkg'
        new_engine.CABLES_PATH = root/'heavy_cables.gpkg'
        new_engine.N_NEW = 1
        new_engine.main()
        new_stations = gpd.read_file(new_engine.OUT/'clustering_ontwerp.gpkg', layer='stations_ontwerp')
        assert (new_stations.Type=='Nieuw').sum() == 1
        assert all(heavy_plan.buffer(.05).covers(g) for g in new_stations.geometry)
        # A multipart plan can be connected by an outside route. Disconnected
        # service fragments are accepted only when every piece touches it.
        pieces = MultiPolygon([box(-2,-2,2,4), box(18,-2,22,4)])
        assert not engine.invalid_disconnected_area(pieces, routes.iloc[0].geometry, pieces, True)
        assert engine.invalid_disconnected_area(pieces, routes.iloc[0].geometry, pieces, False)
        orphan = MultiPolygon([box(-2,-2,2,4), box(50,50,55,55)])
        assert engine.invalid_disconnected_area(orphan, routes.iloc[0].geometry, pieces, True)
        gpd.GeoDataFrame(geometry=[pieces],crs=crs).to_file(root/'multipart_plan.gpkg',driver='GPKG')
        multipart_engine = engine_for('multipart')
        multipart_engine.PLANGEBIED_PATH = root/'multipart_plan.gpkg'
        multipart_engine.main()
        multipart_areas = gpd.read_file(multipart_engine.OUT/'clustering_ontwerp.gpkg',layer='clustergebieden')
        assert multipart_areas.iloc[0].geometry.geom_type == 'MultiPolygon'
        assert multipart_areas.iloc[0].geometry.difference(pieces).area < 1e-8
        # Later edits must retain the full outside route rather than silently
        # clipping the saved network back to the plan boundary.
        tables = {'connections':'aansluitingen_geclusterd','stations':'stations_ontwerp','areas':'clustergebieden',
                  'routes':'cluster_kabelroutes','cables':'sleuven_genood','plan':'plangebied'}
        frames = {key:gpd.read_file(gpkg, layer=table) for key,table in tables.items()}
        for key, frame in frames.items():
            if key!='plan':frame['__src_fid']=np.arange(1,len(frame)+1)
        updated, _ = calculate(engine, frames, [{'kind':'current','point_ids':[1],'amps':20}],850)
        assert updated[3].iloc[0].geometry.equals(routes.iloc[0].geometry)
        rebuilt, _ = calculate(engine, frames, [{'kind':'rebuild','stations':['S1']}],850)
        assert abs(rebuilt[0].Route_m.max()-40) < .01
        multipart_frames = {key:gpd.read_file(multipart_engine.OUT/'clustering_ontwerp.gpkg',layer=table)
                            for key,table in tables.items()}
        for key, frame in multipart_frames.items():
            if key!='plan':frame['__src_fid']=np.arange(1,len(frame)+1)
        multipart_rebuilt, _ = calculate(engine,multipart_frames,[{'kind':'rebuild','stations':['S1']}],850)
        assert multipart_rebuilt[2].iloc[0].geometry.geom_type == 'MultiPolygon'
        layers = {key:QgsVectorLayer(f'{gpkg}|layername={table}',table,'ogr') for key,table in tables.items()}
        assert all(layer.isValid() for layer in layers.values())
        original_fingerprint = fingerprint(layers)
        selected_fid = next(f.id() for f in layers['connections'].getFeatures()
                            if abs(f.geometry().asPoint().x()-20.) < .01)
        _summary, backup, _result = run_batch(layers,[{'kind':'current','point_ids':[selected_fid],'amps':20.}],
                                             root/'batch',850,False,QgsProcessingFeedback())
        assert max(float(f['Route_m']) for f in layers['connections'].getFeatures()) == 40.
        apply_snapshot(layers,backup)
        assert fingerprint(layers) == original_fingerprint
        # Actual Processing defaults and actual 3a option dialog, including
        # migration from a state written before this setting existed.
        algorithm = LaagspanningClusteringAlgorithm();algorithm.initAlgorithm()
        assert algorithm.parameterDefinition(algorithm.KABELROUTES_BUITEN_PLANGEBIED).defaultValue() is False
        assert not algorithm.parameterAsBool({}, algorithm.KABELROUTES_BUITEN_PLANGEBIED, QgsProcessingContext())
        project = QgsProject.instance();project.clear()
        project.setFileName(str(root/'project.qgz'))
        source = QgsVectorLayer(f'{paths["points"]}|layername=points','LS-aansluitingen ontwerpstroom','ogr')
        source.setCustomProperty('LSNetontwerp/review_current_layer',True)
        project.addMapLayer(source)
        plan_layer = QgsVectorLayer(f'{paths["plan"]}|layername=plangebied','Plangebied','ogr')
        plan_layer.setCustomProperty('LSNetontwerp/plan_layer',True)
        project.addMapLayer(plan_layer)
        dialog = LSNetontwerpDashboardDialog(None)
        values = dialog.values();values.pop('allow_external_routes',None)
        values.update(open_project=False,field_design_current='Hoogste Trafo',plan=str(paths['plan']),only_plan=True)
        state={'values':values,'result_dir':str(root),'work_project':str(root/'project.qgz'),
               'points_gpkg':str(paths['points']),'points_layer':'points','import_gpkg':str(root/'import.gpkg'),
               'plan_gpkg':str(paths['plan']),'clustering_dir':str(root/'clusters')}
        dialog.prepared_state=state
        option = ClusteringOptionsDialog(dialog)
        option.show();app.processEvents()
        assert not option.allow_external_routes.isChecked() and option.allow_external_routes.isEnabled()
        assert option.allow_external_routes.isVisible()
        option.allow_external_routes.setChecked(False)
        assert option.save(),option.status.text()
        assert dialog.prepared_state['values']['allow_external_routes'] is False
        assert dialog.widgets['allow_external_routes'].isChecked() is False
        reopened = ClusteringOptionsDialog(dialog)
        assert not reopened.allow_external_routes.isChecked()
        captured={}
        final_project=root/'captured.qgz';final_project.write_text('test')
        class CaptureRunner(WorkflowRunner):
            def _validate_layer(self,uri,label):return uri
            def _run_algorithm(self,key,parameters,*args):
                captured.update(parameters)
                return {'QGIS_PROJECT':str(final_project)}
        CaptureRunner(values,lambda *_:None).cluster(dialog.prepared_state)
        assert captured['KABELROUTES_BUITEN_PLANGEBIED'] is False
        reopened.plan_combo.setCurrentIndex(0)
        assert not reopened.allow_external_routes.isEnabled()
        reopened.close()
        option.allow_external_routes.setChecked(True)
        if '--captures' in sys.argv:
            target=Path(sys.argv[sys.argv.index('--captures')+1]);target.mkdir(parents=True,exist_ok=True)
            option.show();app.processEvents();option.grab().save(str(target/'automatische-clustering-buitenplan.png'))
        option.close();dialog.close();project.clear()
    print('EXTERNAL_PLAN_ROUTES_TEST_OK (default UI, persistence, true 40m detour, strict off, route limit, outside point/station exclusion, new site inside, multipart safety, post-edit and rebuild)',flush=True)
    os._exit(0)


if __name__=='__main__':
    main()

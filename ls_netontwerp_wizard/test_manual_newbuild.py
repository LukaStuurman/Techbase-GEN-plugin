"""Real Qt map picker and persistent non-BAG planned connection records."""
import os
import sys
import tempfile
from pathlib import Path


def main():
    plugin = Path(__file__).resolve().parent
    sys.path.insert(0, str(plugin.parent))
    from qgis.core import (QgsApplication, QgsProject, QgsVectorLayer, QgsFeature, QgsField,
        QgsGeometry, QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform, QgsVectorFileWriter)
    from qgis.PyQt.QtCore import QVariant
    from qgis.PyQt.QtGui import QFont, QFontDatabase
    from qgis.PyQt.QtWidgets import QPushButton, QScrollArea
    from qgis.gui import QgsMapCanvas
    app = QgsApplication([], False)
    app.initQgis()
    app.setOrganizationName('LSManualNewBuildTests')
    app.setApplicationName('Isolated')
    for filename in ('segoeui.ttf', 'segoeuib.ttf'):
        QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts')/filename))
    app.setFont(QFont('Segoe UI', 10))
    from ls_netontwerp_wizard.connection_sources import CURRENT_FIELDS
    from ls_netontwerp_wizard.manual_newbuild import add_manual_connections, undo_manual_connections
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    from ls_netontwerp_wizard.algorithms.laagspanning_clustering_tool import LaagspanningClusteringAlgorithm
    with tempfile.TemporaryDirectory(prefix='ls_newbuild_', dir=plugin.parent.parent, ignore_cleanup_errors=True) as folder:
        root = Path(folder)
        project = QgsProject.instance()
        project.clear()
        memory = QgsVectorLayer('Point?crs=EPSG:28992', 'source', 'memory')
        memory.dataProvider().addAttributes([QgsField(name, QVariant.Double) for name in CURRENT_FIELDS])
        memory.updateFields()
        feature = QgsFeature(memory.fields())
        feature.setGeometry(QgsGeometry.fromWkt('POINT(155000 463000)'))
        feature.setAttributes([10.] * len(CURRENT_FIELDS))
        assert memory.dataProvider().addFeature(feature)
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName, options.layerName = 'GPKG', 'points'
        source = root/'points.gpkg'
        assert QgsVectorFileWriter.writeAsVectorFormatV3(memory, str(source), project.transformContext(), options)[0] == 0
        target = QgsVectorLayer(f'{source}|layername=points', 'LS-aansluitingen ontwerpstroom', 'ogr')
        target.setCustomProperty('LSNetontwerp/review_current_layer', True)
        project.addMapLayer(target)
        project.setFileName(str(root/'project.qgz'))
        dialog = LSNetontwerpDashboardDialog(None)
        dialog.show_connection_sources_page()
        dialog.show()
        app.processEvents()
        page = dialog.connection_sources_page
        assert page.manual_build_group.isVisible()
        household = dialog.zero_current_page
        rd = target.crs()
        geographic = QgsCoordinateReferenceSystem('EPSG:4326')
        transform = QgsCoordinateTransform(rd, geographic, project)
        locations = [transform.transform(QgsPointXY(155010, 463000)), transform.transform(QgsPointXY(155020, 463000))]
        result = add_manual_connections(target, locations, geographic, household,
            mode='manual', currents=[8., 10., 15., 4.], label='Gepland project', station='S1')
        assert result == {'added':2, 'missing':0}
        added = list(target.selectedFeatures())
        assert len({f['NWB_ID'] for f in added}) == 2
        assert all(str(f['NWB_ID']).startswith('NWB-') and f['BAG_VBO_ID'] == '' and f['BAG_PAND_ID'] == '' for f in added)
        assert all(f['Hoogste Trafo'] == 15. and f['Hoogste Kabel'] == 10. for f in added)
        assert all(f['Bron'] == 'Handmatig nieuwbouw (zonder BAG)' and f['Nieuwbouw'] == '1' for f in added)
        assert abs(min(f.geometry().asPoint().x() for f in added)-155010) < .02
        assert undo_manual_connections(target) == 2 and target.featureCount() == 1
        add_manual_connections(target, [QgsPointXY(155010,463000)], rd, household,
            mode='housing', house_type='tussenwoning', year=2026)
        planned = list(target.selectedFeatures())[0]
        assert planned['Hoogste Trafo'] > 0 and 'Type 3:' in planned['OntwerpstroomType']
        assert undo_manual_connections(target) == 1
        add_manual_connections(target, [QgsPointXY(155010,463000)], rd, household, mode='later')
        assert list(target.selectedFeatures())[0]['Hoogste Trafo'] == 0.
        assert undo_manual_connections(target) == 1
        count = target.featureCount()
        for arguments in ({'mode':'manual', 'currents':[float('nan'),1,1,1]},
                          {'mode':'manual', 'currents':[-1,1,1,1]}, {'mode':'housing', 'house_type':None}):
            try:
                add_manual_connections(target, [QgsPointXY(155010,463000)], rd, household, **arguments)
            except ValueError:
                pass
            else:
                raise AssertionError('Invalid new-build input accepted')
            assert target.featureCount() == count and not target.isEditable()
        # Exact same coordinates can be distinct planned connections, with
        # separate identities. Later edits protect the last addition from undo.
        add_manual_connections(target, [QgsPointXY(155010,463000)]*2, rd, household,
                               mode='manual', currents=[10.,10.,0.,0.])
        assert target.selectedFeatureCount() == 2
        saved = next(target.getSelectedFeatures())
        target.dataProvider().changeAttributeValues({saved.id():{target.fields().lookupField('Hoogste Trafo'):11.}})
        try:
            undo_manual_connections(target)
        except ValueError as error:
            assert 'daarna gewijzigd' in str(error)
        else:
            raise AssertionError('Undo discarded a later edit')
        # Exercise the same UI map callbacks used by QGIS Desktop.
        class Iface:
            def __init__(self):
                self.canvas = QgsMapCanvas()
                self.canvas.setDestinationCrs(geographic)
            def mapCanvas(self):
                return self.canvas
        dialog.iface = Iface()
        page.refresh()
        page.start_manual_points()
        assert page._manual_tool is not None, page.status.text()
        page._manual_point_clicked(transform.transform(QgsPointXY(155030,463000)))
        page._manual_point_clicked(transform.transform(QgsPointXY(155040,463000)))
        assert len(page._manual_points) == len(page._manual_markers) == 2
        page.remove_manual_point()
        page._finish_manual_points()
        page.manual_current_mode.setCurrentIndex(page.manual_current_mode.findData('manual'))
        for spin, value in zip(page.manual_build_currents, [12.,13.,0.,0.]):
            spin.setValue(value)
        page.add_manual_points()
        assert '1 handmatige' in page.status.text(), page.status.text()
        assert not page._manual_points and target.selectedFeatureCount() == 1
        assert abs(next(target.getSelectedFeatures()).geometry().asPoint().x()-155030) < .02
        page.undo_manual_addition()
        page.start_manual_points()
        page._manual_point_clicked(transform.transform(QgsPointXY(155050,463000)))
        page._cancel_manual_drawing()
        assert not page._manual_points and page._manual_tool is None
        # New-build provenance must survive the actual automatic clustering
        # output writer, not just exist in the input table.
        import geopandas as gpd
        from shapely.geometry import Point, LineString
        inputs = root/'engine_inputs'
        inputs.mkdir()
        gpd.GeoDataFrame({'Ontwerpstroom':[10.], 'GebiedLabel':[''], 'Nieuwbouw':['1'],
            'HandmatigNieuwbouw':['1'], 'NWB_ID':['NWB-test'], 'Bron':['Handmatig nieuwbouw (zonder BAG)'],
            'Nieuwbouwproject':['Project']}, geometry=[Point(155010,463000)], crs='EPSG:28992').to_file(inputs/'points.gpkg', driver='GPKG')
        gpd.GeoDataFrame(geometry=[LineString([(155000,463000),(155010,463000)])], crs='EPSG:28992').to_file(inputs/'cables.gpkg', driver='GPKG')
        gpd.GeoDataFrame({'Stationsnaa':['S1'], 'Status':['630Kva']}, geometry=[Point(155000,463000)], crs='EPSG:28992').to_file(inputs/'stations.gpkg', driver='GPKG')
        engine = LaagspanningClusteringAlgorithm._load_engine()
        engine.POINTS_PATH, engine.CABLES_PATH, engine.STATIONS_PATH = inputs/'points.gpkg', inputs/'cables.gpkg', inputs/'stations.gpkg'
        engine.CONNECTION_CABLES_PATH = engine.FLAT_CABINETS_PATH = engine.STATION_ENCLOSURES_PATH = engine.DISTRIBUTION_CABINETS_PATH = engine.PLANGEBIED_PATH = None
        engine.OUT = root/'engine_result'
        engine.AUTO_NEW_STATIONS, engine.AUTO_NODE_CABLES, engine.CREATE_QGIS_PROJECT, engine.WRITE_SHAPEFILES = True, True, False, False
        engine.make_map = lambda *_: None
        engine.main()
        output = gpd.read_file(engine.OUT/'clustering_ontwerp.gpkg', layer='aansluitingen_geclusterd')
        assert output.NWB_ID.tolist() == ['NWB-test'] and output.Cluster.tolist() == ['S1']
        if '--captures' in sys.argv:
            captures = Path(sys.argv[sys.argv.index('--captures')+1]);captures.mkdir(parents=True,exist_ok=True)
            dialog.resize(1280,960)
            for scroll in page.findChildren(QScrollArea):
                if scroll.isAncestorOf(page.manual_build_group):scroll.ensureWidgetVisible(page.manual_build_group)
            app.processEvents()
            dialog.grab().save(str(captures/'nieuwbouw-zelf-punten.png'))
        assert project.write()
        dialog.close()
        project.clear()
        assert project.read(str(root/'project.qgz'))
        reopened = project.mapLayersByName('LS-aansluitingen ontwerpstroom')[0]
        before_reload_undo = reopened.featureCount()
        add_manual_connections(reopened, [QgsPointXY(155060,463000)], rd, household,
                               mode='manual', currents=[10.,10.,0.,0.])
        assert project.write()
        project.clear()
        assert project.read(str(root/'project.qgz'))
        reopened = project.mapLayersByName('LS-aansluitingen ontwerpstroom')[0]
        assert undo_manual_connections(reopened) == 1 and reopened.featureCount() == before_reload_undo
        project.clear()
    print('MANUAL_NEWBUILD_TEST_OK (no BAG IDs, currents, CRS, unique identities, cancel, persistent records, guarded undo, actual UI, automatic clustering provenance)',flush=True)
    os._exit(0)


if __name__ == '__main__':
    main()

"""Real PyQGIS/Qt and GeoPackage regression for dashboard cluster extensions."""
import os
import sys
import tempfile
from pathlib import Path


def main():
    plugin = Path(__file__).resolve().parent
    sys.path.insert(0, str(plugin.parent))
    sys.path.insert(0, str(plugin / "algorithms/laagspanning_clustering_lib"))
    from qgis.core import QgsApplication, QgsProject, QgsVectorLayer, QgsProcessingFeedback, QgsPointXY, QgsCoordinateReferenceSystem, QgsCoordinateTransform
    from qgis.gui import QgsMapCanvas
    from qgis.PyQt.QtWidgets import QPushButton, QScrollArea
    from qgis.PyQt.QtGui import QFont, QFontDatabase
    app = QgsApplication([], False)
    app.initQgis()
    app.setOrganizationName('LSClusterExtensionTests')
    app.setApplicationName('Isolated')
    for filename in ("segoeui.ttf", "segoeuib.ttf"):
        QFontDatabase.addApplicationFont(str(Path("C:/Windows/Fonts") / filename))
    app.setFont(QFont("Segoe UI", 10))
    import geopandas as gpd
    import pandas as pd
    from shapely.geometry import Point, LineString
    import maak_clustering_engine as engine
    from batch_correction_runner import calculate
    from ls_netontwerp_wizard.test_cluster_management import fixture_frames
    from ls_netontwerp_wizard.batch_editing import run_batch, apply_snapshot, save_station_rules, station_rules
    from ls_netontwerp_wizard.cluster_management import fingerprint
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog

    frames = fixture_frames()
    extra = frames['connections'].iloc[[2]].copy()
    extra['__src_fid'] = 4
    extra.geometry = [Point(20, 2)]
    extra['Route_m'] = 2.
    frames['connections'] = gpd.GeoDataFrame(pd.concat([frames['connections'], extra], ignore_index=True), crs=extra.crs)
    frames['cables'].at[2, 'geometry'] = LineString([(20, 0), (20, 2), (20, 5), (20, 10)])
    create = {'kind': 'create', 'name': 'N-extra', 'kva': 400., 'point_ids': [3], 'x': 20., 'y': 5.}

    def rejected(operations, fragment, data=None, rules=None):
        try:
            calculate(engine, data or frames, operations, 850, rules=rules)
        except (RuntimeError, ValueError) as exc:
            assert fragment in str(exc), (fragment, str(exc))
        else:
            raise AssertionError(f'Unsafe operation accepted: {operations}')

    before = [frame.copy() for frame in frames.values()]
    state, summary = calculate(engine, frames, [create], 850)
    assert summary['created_stations'] == ['N-extra']
    assert len(state[1]) == 4
    assert state[0].loc[state[0].__src_fid == 3, 'Cluster'].iloc[0] == 'N-extra'
    assert state[0].loc[state[0].__src_fid == 4, 'Cluster'].iloc[0] == 'C'
    new_station = state[1].loc[state[1].Cluster == 'N-extra'].iloc[0]
    new_route = state[3].loc[state[3].Cluster == 'N-extra'].iloc[0].geometry
    assert new_station.geometry.equals(Point(20, 5))
    assert new_route.distance(new_station.geometry) < .02
    assert state[0].loc[state[0].__src_fid == 3, 'Route_m'].iloc[0] == 5.
    for frame in state[1:4]:
        assert frame.__src_fid.is_unique
    assert all(a.equals(b) for a, b in zip(before, frames.values()))
    assert 'plan' not in frames
    preview, _ = calculate(engine, frames, [create], 850, preview=True)
    assert len(preview[1]) == 4 and frames['stations'].shape[0] == 3
    rejected([{**create, 'name': 'A'}], 'bestaat al')
    rejected([{**create, 'point_ids': [3, 4]}], 'minstens één')
    rejected([{**create, 'point_ids': [1, 3]}], 'precies één')
    rejected([{**create, 'x': 10.}], 'binnen het broncluster')
    rejected([{**create, 'y': 6.}], 'netwerkknoop')
    rejected([{**create, 'kva': float('nan')}], 'capaciteit')
    disconnected = {key: frame.copy() for key, frame in frames.items()}
    disconnected['cables'].at[2, 'geometry'] = LineString([(20, 0), (20, 2)])
    isolated = disconnected['cables'].iloc[[2]].copy()
    isolated['__src_fid'] = 6
    isolated.geometry = [LineString([(20, 5), (20, 10)])]
    disconnected['cables'] = gpd.GeoDataFrame(pd.concat([disconnected['cables'], isolated], ignore_index=True), crs=extra.crs)
    rejected([{**create, 'y': 2.}], 'kabelroute', disconnected)
    flat = {key: frame.copy() for key, frame in frames.items()}
    flat['connections']['Multistory'] = ['', '', 'flat-1', 'flat-1']
    rejected([create], 'flatgroep', flat)
    rejected([{'kind': 'capacity', 'station': 'C', 'kva': 1}], 'stationcapaciteit')
    rejected([{'kind': 'capacity', 'station': 'unknown', 'kva': 630}], 'ontbreekt')
    rules = {'C': {'protected': True}}
    capacity, summary = calculate(engine, frames, [{'kind': 'capacity', 'station': 'C', 'kva': 400}], 850, rules=rules)
    assert rules == {'C': {'protected': True}}
    assert summary['station_rules']['C']['protected']
    assert summary['station_rules']['C']['capacity_override']
    for frame in capacity[1:4]:
        assert frame.loc[frame.Cluster == 'C', 'KVA'].iloc[0] == 400.
    assert set(capacity[0].loc[capacity[0].Cluster == 'C', 'Stat_KVA']) == {400.}
    assert capacity[3].geometry.equals(frames['routes'].geometry)
    merged, merge_summary = calculate(engine, frames, [
        {'kind': 'capacity', 'station': 'B', 'kva': 400},
        {'kind': 'retire', 'source': 'A', 'target': 'B'},
    ], 850)
    assert 'A' not in set(merged[1].Cluster)
    assert merge_summary['removed_source_clusters'] == ['A']
    rebuilt, summary = calculate(engine, frames, [{'kind': 'rebuild', 'stations': ['C']}], 850)
    assert summary['refreshed_stations'] == ['C']
    assert rebuilt[0].Cluster.tolist() == frames['connections'].Cluster.tolist()
    # Even when the engine can preserve an old route, this explicit request
    # must report failure rather than claim that new routing succeeded.
    original = engine.recalculate_manual_assignment
    def fallback(*args, **kwargs):
        result = list(original(*args, **kwargs))
        result[5]['preserved_route_clusters'] = ['C']
        return tuple(result)
    engine.recalculate_manual_assignment = fallback
    rejected([{'kind': 'rebuild', 'stations': ['C']}], 'Geen volledige nieuwe route')
    engine.recalculate_manual_assignment = original
    original_areas = engine.make_cable_based_cluster_polygons
    def overlapping(*args, **kwargs):
        polygons, details = original_areas(*args, **kwargs)
        polygons[1] = polygons[0]
        return polygons, details
    engine.make_cable_based_cluster_polygons = overlapping
    rejected([{'kind': 'rebuild', 'stations': ['C']}], 'overlappen')
    engine.make_cable_based_cluster_polygons = original_areas

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as directory:
        folder = Path(directory)
        source = folder / 'test.gpkg'
        tables = {'connections':'aansluitingen_geclusterd','stations':'stations_ontwerp','areas':'clustergebieden','routes':'cluster_kabelroutes','cables':'sleuven_genood'}
        names = {'connections':'Aansluitingen geclusterd','stations':'Stations ontwerp','areas':'Clustergebieden','routes':'Kabelroutes per cluster','cables':'Sleuven geknipt/genood'}
        for key, table in tables.items():
            frames[key].drop(columns=['__src_fid']).to_file(source, layer=table, driver='GPKG')
        layers = {key: QgsVectorLayer(f'{source}|layername={table}', names[key], 'ogr') for key, table in tables.items()}
        project = QgsProject.instance()
        project.clear()
        for layer in layers.values():
            assert layer.isValid()
            project.addMapLayer(layer)
        layers['plan'] = None
        snapshot = fingerprint(layers)
        summary, backup, result = run_batch(layers, [create], folder, 850, False, QgsProcessingFeedback())
        assert layers['stations'].featureCount() == 4
        apply_snapshot(layers, backup)
        assert fingerprint(layers) == snapshot

        # Use the actual colored dashboard, actual Qt buttons, and a real map
        # canvas. The small iface supplies only the Desktop shell integration.
        class Iface:
            def __init__(self):
                self.canvas = QgsMapCanvas()
                self.canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:28992'))
            def mapCanvas(self):
                return self.canvas
            def setActiveLayer(self, layer):
                self.layer = layer
        dialog = LSNetontwerpDashboardDialog(None)
        iface = Iface()
        dialog.iface = iface
        dialog.resize(1450, 1000)
        dialog.show_home_page()
        dialog.show()
        app.processEvents()
        capture = Path(sys.argv[sys.argv.index('--captures') + 1]) if '--captures' in sys.argv else None
        if capture:
            capture.mkdir(parents=True, exist_ok=True)
            for edit, placeholder in ((dialog.xml_edit, 'GEN-aansluitingen.xml'), (dialog.excel_edit, 'Kabelgegevens.xlsx'), (dialog.plan_edit, 'Plangebied.gpkg'), (dialog.output_edit, 'Ontwerpmap')):
                edit.setText(placeholder)
            first = next(b for b in dialog._dashboard_widget.findChildren(QPushButton) if b.text().startswith('4a.'))
            last = next(b for b in dialog._dashboard_widget.findChildren(QPushButton) if b.text().startswith('4h.'))
            for scroll in dialog.main_page.findChildren(QScrollArea):
                scroll.ensureWidgetVisible(last)
            app.processEvents()
            for button in (first, last):
                scroll = next(s for s in dialog.main_page.findChildren(QScrollArea) if s.isAncestorOf(button))
                top = button.mapTo(scroll.viewport(), button.rect().topLeft()).y()
                assert 0 <= top < scroll.viewport().height(), (button.text(), top)
            dialog.grab().save(str(capture / 'dashboard.png'))
        for prefix, section in [('4e.', 'capacity_group'), ('4f.', 'merge_group'), ('4g.', 'create_group'), ('4h.', 'validation_group')]:
            dialog.show_home_page()
            app.processEvents()
            button = next(b for b in dialog._dashboard_widget.findChildren(QPushButton) if b.text().startswith(prefix))
            assert button.isVisible() and button.isEnabled()
            button.click()
            app.processEvents()
            page = dialog.cluster_management_page
            assert dialog.page_stack.currentWidget() is page
            group = getattr(page, section)
            assert group.isVisible()
            scroll = page.findChildren(QScrollArea)[0]
            top = group.mapTo(scroll.viewport(), group.rect().topLeft()).y()
            assert top < scroll.viewport().height() and top + group.height() > 0
            if capture:
                dialog.grab().save(str(capture / f'{prefix[:2]}-{section}.png'))
        page.refresh()
        assert project.write(str(folder / 'project.qgz'))
        row = next(i for i in range(page.table.rowCount()) if page.table.item(i, 0).text() == 'C')
        page.table.selectRow(row)
        page.capacity.setValue(400)
        page.queue_capacity()
        assert '579.7' in page.preview.text(), page.preview.text()
        page.execute(True)
        assert 'akkoord' in page.status.text(), page.status.text()
        assert fingerprint(layers) == snapshot
        page.execute(False)
        assert page.queue.count() == 0, page.status.text()
        applied_rules = station_rules()
        save_station_rules({})
        page.undo()
        assert 'latere keuzes' in page.status.text(), page.status.text()
        save_station_rules(applied_rules)
        page.undo()
        assert fingerprint(layers) == snapshot, page.status.text()
        page.refresh()
        layer = layers['connections']
        selected = next(f.id() for f in layer.getFeatures() if str(f['Cluster']) == 'C' and f.geometry().asPoint().y() == 10.)
        layer.selectByIds([selected])
        page.start_station_creation()
        assert page._location_tool is not None, page.create_status.text()
        page._creation_location_canceled()
        assert page._location_tool is None and page._creation_candidate is None
        page.start_station_creation()
        assert page._location_tool is not None, page.create_status.text()
        # Picking is expressed in the canvas CRS, independently of layer CRS.
        iface.canvas.setDestinationCrs(QgsCoordinateReferenceSystem('EPSG:3857'))
        transformed = QgsCoordinateTransform(QgsCoordinateReferenceSystem('EPSG:28992'), iface.canvas.mapSettings().destinationCrs(), project).transform(QgsPointXY(20, 5))
        page._creation_location_clicked(transformed)
        assert page._creation_candidate is not None, page.create_status.text()
        page.new_name.setText('N-extra')
        page.queue_creation()
        page.execute(False)
        assert layers['stations'].featureCount() == 4, page.status.text()
        page.undo()
        assert fingerprint(layers) == snapshot, page.status.text()
        row = next(i for i in range(page.table.rowCount()) if page.table.item(i, 0).text() == 'C')
        page.table.selectRow(row)
        page.select_cluster_products()
        assert layers['areas'].selectedFeatureCount() == layers['routes'].selectedFeatureCount() == 1
        page.maximum_route.setValue(1)
        page.select_issues('route')
        assert layer.selectedFeatureCount() == 4
        page.maximum_route.setValue(850)
        page.select_issues('zero')
        assert layer.selectedFeatureCount() == 0
        page.select_issues('assignment')
        assert layer.selectedFeatureCount() == 0
        page.queue_rebuild(True)
        save_station_rules({'C': {'protected': True}})
        page.execute(False)
        assert 'stationskeuzes' in page.status.text(), page.status.text()
        page.clear_queue()
        save_station_rules({})
        assert fingerprint(layers) == snapshot
        dialog.close()
        project.clear()
    print('CLUSTER_EXTENSIONS_OK: split, capacity, strict rebuild, validation, real dashboard buttons, map picker, GeoPackage apply/undo and stale rules', flush=True)
    os._exit(0)


if __name__ == '__main__':
    main()

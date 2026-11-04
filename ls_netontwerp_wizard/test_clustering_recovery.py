"""No-plan retries, recoverable presentation errors and post-cluster currents."""
import json
import os
import sys
import tempfile
from pathlib import Path


def main():
    plugin = Path(__file__).resolve().parent
    sys.path.insert(0, str(plugin.parent))
    sys.path.insert(0, str(plugin / 'algorithms/laagspanning_clustering_lib'))
    from qgis.core import QgsApplication, QgsProject, QgsVectorLayer, QgsProcessingContext, QgsProcessingException
    app = QgsApplication([], False)
    app.initQgis()
    app.setOrganizationName('LSRecoveryTests')
    app.setApplicationName('Isolated')
    from qgis.PyQt.QtGui import QFont, QFontDatabase
    for name in ('segoeui.ttf', 'segoeuib.ttf'):
        QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts') / name))
    app.setFont(QFont('Segoe UI', 10))
    import geopandas as gpd
    from shapely.geometry import Point, LineString
    from ls_netontwerp_wizard.algorithms.laagspanning_clustering_tool import LaagspanningClusteringAlgorithm
    from ls_netontwerp_wizard.test_cluster_management import fixture_frames
    from ls_netontwerp_wizard.clustering_diagnostics import save_failure, explain_failure
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    from ls_netontwerp_wizard.cluster_management import fingerprint
    from batch_correction_runner import calculate
    from qgis.PyQt.QtWidgets import QPushButton
    from qgis.core import QgsProcessingFeedback
    from ls_netontwerp_wizard.batch_editing import run_batch, apply_snapshot

    engine = LaagspanningClusteringAlgorithm._load_engine()
    engine._AUTO_TOPOLOGY_MINIMUM_NEW = 32
    counts = engine.automatic_new_station_count_options(29978.7, 18782.6, 630/.69)
    assert min(counts) == 32 and 33 in counts and not any(c < 32 for c in counts)
    engine._AUTO_TOPOLOGY_MINIMUM_NEW = 0
    assert engine.indivisible_capacity_issues([20.], [0], [0], [0], [0], [10.], 100.)[0]['station_root']
    assert engine.indivisible_capacity_issues([20.], [1], [0], [0], [0], [10.], 100.) == []
    assert engine.indivisible_capacity_issues([200.], [1], [0], [0], [0], [10.], 100.)[0]['maximum_a'] == 100.
    frames = fixture_frames()
    current = [{'kind': 'current', 'point_ids': [1, 2], 'amps': 20.}]
    state, summary = calculate(engine, frames, current, 850)
    assert summary['current_changed_count'] == 2
    assert state[0].Ontwerp_A.tolist() == [20., 20., 10.]
    assert frames['connections'].Ontwerp_A.tolist() == [10., 10., 10.]
    for frame in state[1:4]:
        assert frame.loc[frame.Cluster == 'A', 'Belast_A'].iloc[0] == 20.
        assert frame.loc[frame.Cluster == 'B', 'Belast_A'].iloc[0] == 20.
    assert state[0].Clust_A.tolist() == [20., 20., 10.]
    assert state[3].geometry.equals(frames['routes'].geometry)
    for operation in ({'kind': 'current', 'point_ids': [1], 'amps': -1},
                      {'kind': 'current', 'point_ids': [1], 'amps': float('nan')},
                      {'kind': 'current', 'point_ids': [999], 'amps': 20},
                      {'kind': 'current', 'point_ids': [1], 'amps': 10000}):
        try:
            calculate(engine, frames, [operation], 850)
        except (ValueError, RuntimeError):
            pass
        else:
            raise AssertionError('Invalid or overloaded current change was accepted')
    # The wrapper deliberately redirects outputs out of the OS temp tree;
    # use a workspace test directory to exercise explicit output paths.
    with tempfile.TemporaryDirectory(prefix='ls_recovery_', dir=plugin.parent.parent,
                                     ignore_cleanup_errors=True) as directory:
        folder = Path(directory)
        source = folder / 'source.gpkg'
        tables = {'connections':'aansluitingen_geclusterd', 'stations':'stations_ontwerp',
                  'areas':'clustergebieden', 'routes':'cluster_kabelroutes', 'cables':'sleuven_genood'}
        names = {'connections':'Aansluitingen geclusterd', 'stations':'Stations ontwerp',
                 'areas':'Clustergebieden', 'routes':'Kabelroutes per cluster', 'cables':'Sleuven geknipt/genood'}
        for key, table in tables.items():
            frames[key].drop(columns='__src_fid').to_file(source, layer=table, driver='GPKG')
        layers = {key: QgsVectorLayer(f'{source}|layername={table}', names[key], 'ogr') for key, table in tables.items()}
        project = QgsProject.instance()
        for layer in layers.values():
            project.addMapLayer(layer)
        layers['plan'] = None
        project.setFileName(str(folder / 'project.qgz'))
        assert project.write()
        before = fingerprint(layers)
        dialog = LSNetontwerpDashboardDialog(None)
        dialog.show_home_page()
        dialog.show()
        app.processEvents()
        button = next(b for b in dialog._dashboard_widget.findChildren(QPushButton) if b.text().startswith('4i.'))
        assert button.isVisible() and button.isEnabled()
        button.click()
        app.processEvents()
        dialog.resize(1280, 900)
        app.processEvents()
        page = dialog.cluster_management_page
        assert dialog.page_stack.currentWidget() is page and page.current_group.isVisible()
        if '--captures' in sys.argv:
            captures = Path(sys.argv[sys.argv.index('--captures') + 1])
            captures.mkdir(parents=True, exist_ok=True)
            dialog.grab().save(str(captures/'ontwerpstroom-na-clustering.png'))
        layers['connections'].selectByIds([1, 2])
        page.design_current.setValue(20)
        page.queue_current()
        page.execute(True)
        assert 'akkoord' in page.status.text(), page.status.text()
        assert fingerprint(layers) == before
        page.execute(False)
        assert not page.queue.count(), page.status.text()
        assert [f['Ontwerp_A'] for f in layers['connections'].getFeatures()] == [20., 20., 10.]
        page.undo()
        assert fingerprint(layers) == before, page.status.text()
        dialog.close()
        project.clear()
        # A layout worker failure can fall back to a valid five-layer project.
        path = LaagspanningClusteringAlgorithm._create_basic_result_project(folder, source)
        standalone = QgsProject()
        assert standalone.read(path) and len(standalone.mapLayers()) == 5
        assert standalone.readEntry('LSNetontwerp', 'presentation_warning', '')[0]
        # The review package must survive input-temp cleanup, contain a full
        # technical error and be clearly distinguished from a finished design.
        temp_inputs = folder / 'temporary_inputs'
        temp_inputs.mkdir()
        import shutil
        shutil.copy2(source, temp_inputs / 'aansluitingen.gpkg')
        try:
            raise RuntimeError('Geen geldige selectie van 32 nieuwe stations gevonden')
        except RuntimeError as error:
            message = save_failure(error, folder, temp_inputs, ['berekening gestart', 'stationskeuze'])
        report_dir = next(folder.glob('controle_*'))
        data = json.loads((report_dir / 'diagnose.json').read_text(encoding='utf-8'))
        assert data['status'] == 'niet_afgerond' and 'Traceback' in data['traceback']
        assert Path(data['project']).exists() and (report_dir / 'aansluitingen.gpkg').exists()
        assert 'controleproject' in (report_dir / 'LEESMIJ.txt').read_text(encoding='utf-8').casefold()
        assert 'capaciteit' in message and str(report_dir) in message
        assert 'locatie' in explain_failure('geen geschikte stationslocatie')[0]

        # End-to-end tiny no-plan engine run with a disconnected, completely
        # excluded spare cable and an injected map export error.
        inputs = folder / 'engine_inputs'
        inputs.mkdir()
        gpd.GeoDataFrame({'Ontwerpstroom': [10., 10.], 'GebiedLabel': ['', '']},
                         geometry=[Point(10, 0), Point(20, 0)], crs='EPSG:28992').to_file(inputs/'points.gpkg', driver='GPKG')
        gpd.GeoDataFrame({'Function': ['LS', 'LS']}, geometry=[LineString([(0, 0), (10, 0), (20, 0)]),
                         LineString([(100, 100), (110, 100)])], crs='EPSG:28992').to_file(inputs/'cables.gpkg', driver='GPKG')
        gpd.GeoDataFrame({'Stationsnaa': ['S1'], 'Status': ['630Kva']}, geometry=[Point(0, 0)],
                         crs='EPSG:28992').to_file(inputs/'stations.gpkg', driver='GPKG')
        engine = LaagspanningClusteringAlgorithm._load_engine()
        engine.POINTS_PATH, engine.CABLES_PATH, engine.STATIONS_PATH = inputs/'points.gpkg', inputs/'cables.gpkg', inputs/'stations.gpkg'
        engine.CONNECTION_CABLES_PATH = engine.FLAT_CABINETS_PATH = engine.STATION_ENCLOSURES_PATH = engine.DISTRIBUTION_CABINETS_PATH = engine.PLANGEBIED_PATH = None
        engine.OUT = folder / 'engine_result'
        engine.AUTO_NEW_STATIONS = True
        engine.AUTO_NODE_CABLES = True
        engine.WRITE_SHAPEFILES = False
        engine.CREATE_QGIS_PROJECT = False
        engine.CPU_THREADS = 1
        engine.EXCLUDED_STATION_AREAS = [{'x': 105., 'y': 100., 'radius': 30.}]
        def render_failure(*_args):
            raise RuntimeError('injected PNG export failure')
        engine.make_map = render_failure
        engine.main()
        result = engine.gpd.read_file(engine.OUT/'clustering_ontwerp.gpkg', layer='aansluitingen_geclusterd')
        assert len(result) == 2 and set(result.Cluster) == {'S1'}
        warnings = json.loads((engine.OUT/'clustering_waarschuwingen.json').read_text(encoding='utf-8'))
        assert 'PNG export failure' in warnings[0]
        assert (engine.OUT/'cluster_overzicht.csv').exists()
        # Exercise the actual Processing wrapper, including both independent
        # presentation failures and the returned warnings/optional artifacts.
        algorithm = LaagspanningClusteringAlgorithm()
        algorithm.initAlgorithm()
        algorithm._load_engine = lambda: engine
        def project_failure(*_args):
            raise RuntimeError('injected layout worker failure')
        algorithm._create_qgis_project_with_retries = project_failure
        parameters = {'AANSLUITINGEN': str(inputs/'points.gpkg'), 'KABELS': str(inputs/'cables.gpkg'),
                      'STATIONS': str(inputs/'stations.gpkg'), 'ONTWERPSTROOM_VELD': 'Ontwerpstroom',
                      'STATION_NAAM_VELD': 'Stationsnaa', 'STATION_CAPACITEIT_VELD': 'Status',
                      'AUTOMATISCH_AANTAL': True, 'NIEUW_KVA': 630, 'VOORKEUR_BENUTTING': 80,
                      'MAX_ROUTE_M': 850, 'REKEN_THREADS': 1, 'SLEUVEN_NODEN': True,
                      'UITVOERMAP': str(folder/'wrapper_result')}
        result = algorithm.processAlgorithm(parameters, QgsProcessingContext(), QgsProcessingFeedback())
        assert Path(result['QGIS_PROJECT']).exists() and Path(result['GEOPACKAGE']).exists()
        assert result['LAYOUT_TEMPLATE'] == '' and result['CONTROLEKAART'] == ''
        assert len(json.loads((folder/'wrapper_result/clustering_waarschuwingen.json').read_text(encoding='utf-8'))) == 2
        # An actual solver error is not disguised as success. The wrapper
        # writes a durable review project before deleting its temp directory.
        def core_failure():
            raise RuntimeError('stationcapaciteit onvoldoende voor kabelcomponent')
        engine.main = core_failure
        parameters['UITVOERMAP'] = str(folder/'wrapper_failed')
        try:
            algorithm.processAlgorithm(parameters, QgsProcessingContext(), QgsProcessingFeedback())
        except QgsProcessingException as error:
            assert 'Controle en technisch rapport' in str(error), str(error)
            dialog = LSNetontwerpDashboardDialog(None)
            dialog.resize(1280, 900)
            dialog.show()
            dialog._show_clustering_diagnostic(error, folder/'wrapper_failed')
            assert dialog.clustering_issue_group.isVisible()
            assert dialog.open_diagnostics_button.isEnabled() and dialog.open_control_project_button.isEnabled()
            if '--captures' in sys.argv:
                app.processEvents()
                dialog.grab().save(str(captures/'clustering-fout-uitleg.png'))
            dialog.close()
        else:
            raise AssertionError('Solver failure reported success')
    print('CLUSTER_RECOVERY_TEST_OK (retry floor, unused cable, map failure retained, basic project, persistent diagnostics, 4i current edit/apply/undo)', flush=True)
    os._exit(0)


if __name__ == '__main__':
    main()

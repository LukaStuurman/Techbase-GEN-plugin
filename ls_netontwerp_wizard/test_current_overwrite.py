"""Regression: overwrite selected currents without adding fields, including project reload."""
import os
import sys
import tempfile
from pathlib import Path


def main():
    sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
    from qgis.core import (QgsApplication, QgsProject, QgsVectorLayer, QgsField,
                           QgsFeature, QgsGeometry, QgsVectorFileWriter)
    from qgis.PyQt.QtCore import QVariant
    app = QgsApplication([], False)
    app.initQgis()
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    from ls_netontwerp_wizard.connection_sources import CURRENT_FIELDS
    from ls_netontwerp_wizard.current_edit_metadata import current_choice

    with tempfile.TemporaryDirectory(ignore_cleanup_errors=True) as folder:
        project = QgsProject.instance()
        project.clear()
        source = QgsVectorLayer('Point?crs=EPSG:28992', 'test', 'memory')
        source.dataProvider().addAttributes(
            [QgsField(n, QVariant.Double) for n in CURRENT_FIELDS] +
            [QgsField(n, QVariant.String) for n in
             ('Gevonden_Woningtype', 'Gevonden_Bouwjaar', 'Gebruiksdoel', 'G_Type')])
        source.updateFields()
        for x in (1, 2):
            f = QgsFeature(source.fields())
            f.setGeometry(QgsGeometry.fromWkt(f'POINT({x} 0)'))
            for name in CURRENT_FIELDS:
                f[name] = 1.0
            f['Gebruiksdoel'] = 'bedrijf'
            source.dataProvider().addFeature(f)
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = 'GPKG'
        options.layerName = 'connections'
        gpkg = str(Path(folder)/'test.gpkg')
        assert QgsVectorFileWriter.writeAsVectorFormatV3(
            source, gpkg, project.transformContext(), options)[0] == QgsVectorFileWriter.NoError
        layer = QgsVectorLayer(gpkg+'|layername=connections', 'connections', 'ogr')
        assert layer.isValid()
        layer.setCustomProperty('LSNetontwerp/review_current_layer', True)
        project.addMapLayer(layer)
        names = [field.name() for field in layer.fields()]
        selected, other = [f.id() for f in layer.getFeatures()]
        dialog = LSNetontwerpDashboardDialog(None)
        page = dialog.zero_current_page
        def apply(values):
            return page.apply_values_to_layer(layer, [selected], 'Zakelijk',
                dict(zip(('consumption_trafo','consumption_cable',
                          'generation_trafo','generation_cable'), values)),
                unit_name='Zelf invullen', gas_category='G10-G25', manual_override=True)
        assert apply((11, 12, 13, 14)) == 1
        assert apply((21, 22, 23, 24)) == 1
        assert [field.name() for field in layer.fields()] == names
        assert not any(name.startswith('Herstel') for name in names)
        assert [layer.getFeature(selected)[name] for name in CURRENT_FIELDS] == [21,22,23,24,23,24]
        assert [layer.getFeature(other)[name] for name in CURRENT_FIELDS] == [1]*6
        path = str(Path(folder)/'project.qgz')
        layer_id = layer.id()
        assert project.write(path)
        project.clear()
        assert project.read(path)
        layer = project.mapLayer(layer_id)
        assert layer is not None and layer.isValid()
        saved = layer.getFeature(selected)
        assert [saved[name] for name in CURRENT_FIELDS] == [21,22,23,24,23,24]
        assert current_choice(layer, saved, 'HerstelHandmatig') == '1'
        assert current_choice(layer, saved, 'HerstelCat') == 'Zakelijk'
        assert current_choice(layer, saved, 'HerstelType') == 'Zelf invullen'
        assert [field.name() for field in layer.fields()] == names
        project.clear()
        del layer
    print('CURRENT_OVERWRITE_PERSISTENCE_TEST_OK', flush=True)
    os._exit(0)


if __name__ == '__main__':
    main()

from pathlib import Path
import sys,pickle,os
sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
from qgis.core import QgsApplication,QgsProject,QgsVectorLayer
from qgis.PyQt.QtCore import QCoreApplication
from qgis.PyQt.QtGui import QFont,QFontDatabase
app=QgsApplication([],False);app.initQgis()
QCoreApplication.setOrganizationName('LSAreasRepeatTest'); QCoreApplication.setApplicationName('Isolated')
for name in ('segoeui.ttf','segoeuib.ttf'):QFontDatabase.addApplicationFont(str(Path('C:/Windows/Fonts')/name))
app.setFont(QFont('Segoe UI',10))
sys.path.insert(0,str(Path(QgsApplication.prefixPath())/'python/plugins'))
from processing.core.Processing import Processing
Processing.initialize()
from ls_netontwerp_wizard.provider import LSNetontwerpProvider
provider=LSNetontwerpProvider(); QgsApplication.processingRegistry().addProvider(provider)
from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
import tempfile
folder=Path(tempfile.mkdtemp(prefix='ls_area_mode_test_'))
from ls_netontwerp_wizard.test_cluster_management import fixture_frames
frames=fixture_frames()
from shapely.geometry import Polygon
frames['areas'].geometry = [Polygon([(-5,-5),(5,-5),(6,5),(4,15),(-5,15)]), Polygon([(5,-5),(15,-5),(15,15),(4,15),(6,5)]), frames['areas'].geometry.iloc[2]]
file=folder/'original.gpkg'
if file.exists():file.unlink()
for key,table in [('areas','clustergebieden'),('connections','aansluitingen_geclusterd')]:frames[key].drop(columns=['__src_fid']).to_file(file,layer=table,driver='GPKG')
project=QgsProject.instance()
areas=QgsVectorLayer(f'{file}|layername=clustergebieden','Clustergebieden','ogr')
points=QgsVectorLayer(f'{file}|layername=aansluitingen_geclusterd','Aansluitingen geclusterd','ogr')
project.addMapLayer(areas);project.addMapLayer(points)
original=[bytes(f.geometry().asWkb()) for f in areas.getFeatures()]
d=LSNetontwerpDashboardDialog(None);d.show_areas_page()
previous=None
for mode in ['min_vertices','right_angles','min_vertices','right_angles']:
    d.areas_shape_mode.setCurrentIndex(d.areas_shape_mode.findData(mode))
    d.run_area_simplification()
    print('RUN',mode,d.areas_status_label.text(),flush=True)
    assert d.areas_status_label.text().startswith('Gereed:'),d.areas_status_label.text()
    result=d._areas_selected_layer()
    assert result.isValid() and result.featureCount()==3
    assert result.customProperty('LSNetontwerp/areas_base_uri')==areas.source()
    assert result.source()!=previous
    assert len([l for l in project.mapLayers().values() if l.customProperty('LSNetontwerp/simplified_cluster_areas',False)])==1
    if mode=='right_angles':
        from shapely import from_wkb
        geoms={f['Cluster']:from_wkb(bytes(f.geometry().asWkb())) for f in result.getFeatures()}
        shared=geoms['A'].intersection(geoms['B'])
        parts=list(shared.geoms) if hasattr(shared,'geoms') else [shared]
        for part in parts:
            if part.geom_type!='LineString':continue
            for first,second in zip(list(part.coords),list(part.coords)[1:]):
                assert abs(first[0]-second[0])<1e-6 or abs(first[1]-second[1])<1e-6,(first,second)
    previous=result.source()
assert [bytes(f.geometry().asWkb()) for f in areas.getFeatures()]==original
# A failed later attempt keeps the last good visible result and its file intact.
last=d._areas_selected_layer(); last_id=last.id()
d.areas_cluster_field.setText('does_not_exist')
d.run_area_simplification()
assert project.mapLayer(last_id) is last and last.isValid()
assert Path(last.source().split('|')[0]).exists()
print('AREAS_REPEAT_AND_FAILURE_PRESERVATION_OK',flush=True)
# Capture the new management page on a complete fixture in the other test.
os._exit(0)

"""Explicit, persistent user-drawn links for another automatic clustering run."""
from pathlib import Path
from datetime import datetime
from qgis.core import (QgsFeature,QgsGeometry,QgsProject,QgsVectorLayer,
                       QgsVectorFileWriter,QgsCoordinateTransform,QgsRectangle)
from qgis.PyQt.QtCore import QTimer


def merged_cables(source, repair_uri, function_field):
    if not repair_uri:return source
    base=source if isinstance(source,QgsVectorLayer) else QgsVectorLayer(source,'Kabels bron','ogr')
    repair=QgsVectorLayer(repair_uri,'Getekende verbindingssleuven','ogr')
    if not base.isValid() or not repair.isValid():raise ValueError('De kabelbron of opgeslagen verbindingssleuven kunnen niet worden geopend.')
    result=QgsVectorLayer('MultiLineString?crs='+base.crs().authid(),'Kabels met getekende sleuven','memory')
    provider=result.dataProvider();provider.addAttributes(list(base.fields()));result.updateFields()
    for layer in (base,repair):
        for feature in layer.getFeatures():
            geom=QgsGeometry(feature.geometry())
            if layer.crs()!=base.crs():geom.transform(QgsCoordinateTransform(layer.crs(),base.crs(),QgsProject.instance()))
            geom.convertToMultiType();new=QgsFeature(result.fields());new.setGeometry(geom)
            if layer is base:new.setAttributes(feature.attributes())
            elif function_field in result.fields().names():new[function_field]='LS'
            if not provider.addFeatures([new])[0]:raise ValueError('Samenvoegen van de getekende sleuf met kabelinvoer mislukt.')
    result.updateExtents();return result


def validate_link(geometry, cables, plan, tolerance):
    from shapely import from_wkb
    from shapely.ops import unary_union
    line=from_wkb(bytes(geometry.asWkb()))
    if line.is_empty or not line.is_valid or line.geom_type!='LineString' or line.length<=.1:
        raise ValueError('Teken één geldige sleuf met minimaal twee verschillende punten.')
    area=unary_union([from_wkb(bytes(f.geometry().asWkb())) for f in plan.getFeatures()])
    if area.is_empty or not area.buffer(.001).covers(line):raise ValueError('De volledige verbindingssleuf moet binnen het plangebied liggen.')
    network=unary_union([from_wkb(bytes(f.geometry().asWkb())) for f in cables.getFeatures()])
    from shapely.geometry import Point
    if any(Point(xy).distance(network)>tolerance+1e-8 for xy in (line.coords[0],line.coords[-1])):
        raise ValueError(f'Beide uiteinden moeten op bestaande sleuven eindigen (maximaal {tolerance:g} m afstand).')


class RepairDrawing:
    def __init__(self,host):self.host=host;self.layer=None;self.zoom_index=0

    def zoom(self):
        host=self.host;folder=host._clustering_diagnostic_folder
        if host.iface is None or folder is None:raise ValueError('Zoom naar een knelpunt vereist een controleverslag en QGIS Desktop.')
        path=folder/'netwerkcontrole.gpkg'
        if not path.exists():raise ValueError('Dit verslag bevat geen gelokaliseerde netwerkcontrole. Open het controleproject voor de invoerlagen.')
        import sqlite3
        with sqlite3.connect(path) as db:tables=db.execute("select table_name from gpkg_contents where data_type='features'").fetchall()
        for table, in tables:
            layer=QgsVectorLayer(f'{path}|layername={table}','Kabeldelen om te controleren','ogr')
            if not layer.isValid():continue
            QgsProject.instance().addMapLayer(layer)
            features=[f for f in layer.getFeatures() if 'Controle' in layer.fields().names() and str(f['Controle'])=='Zonder bestaand station']
            if not features:features=list(layer.getFeatures())
            if not features:continue
            features.sort(key=lambda f:f.id());feature=features[self.zoom_index % len(features)];self.zoom_index+=1
            layer.selectByIds([feature.id()]);host.iface.setActiveLayer(layer)
            extent=QgsRectangle(feature.geometry().boundingBox());extent.grow(25)
            if layer.crs()!=host.iface.mapCanvas().mapSettings().destinationCrs():
                extent=QgsCoordinateTransform(layer.crs(),host.iface.mapCanvas().mapSettings().destinationCrs(),QgsProject.instance()).transformBoundingBox(extent)
            host.iface.mapCanvas().setExtent(extent);host.iface.mapCanvas().refresh()
            host.clustering_issue_label.setText(f'Kabeldeel {(self.zoom_index-1)%len(features)+1} van {len(features)} geselecteerd. Klik nogmaals op Zoom voor het volgende deel. Teken alleen een werkelijk ontbrekende verbinding en start daarna opnieuw. Een los deel hoeft geen fout te zijn.')
            return
        raise ValueError('Geen controle-geometrie beschikbaar.')

    def start(self):
        host=self.host;state=host.prepared_state
        if host.iface is None or not state:raise ValueError('Open het voorbereide werkproject in QGIS Desktop.')
        if self.layer is not None:
            if self.layer.isEditable():self.layer.rollBack()
            QgsProject.instance().removeMapLayer(self.layer.id());self.layer=None
            host.iface.actionPan().trigger();host.clustering_issue_label.setText('Tekenen geannuleerd; geen verbindingssleuf opgeslagen.');return
        if not state.get('plan_gpkg'):raise ValueError('Kies eerst een plangebied voor deze herstelroute.')
        base=QgsVectorLayer(f"{state['import_gpkg']}|layername={state['values']['layer_main_cables']}",'Kabels bron','ogr')
        plan=QgsVectorLayer(str(state['plan_gpkg'])+'|layername=plangebied','Herstelplangebied','ogr')
        if not base.isValid() or not plan.isValid():raise ValueError('Kabelbron of plangebied kan niet worden geopend.')
        if base.crs()!=plan.crs():raise ValueError('De kabelbron en het herstelplangebied moeten hetzelfde coördinatenstelsel hebben.')
        previous=state.get('repair_trenches','')
        cables=merged_cables(base,previous,state['values']['field_main_function'])
        drawing=QgsVectorLayer('LineString?crs='+base.crs().authid(),'Ontbrekende sleuf tekenen','memory')
        QgsProject.instance().addMapLayer(drawing);drawing.startEditing();self.layer=drawing
        done={'busy':False}
        def added(fid):
            if not done['busy']:done['busy']=True;QTimer.singleShot(0,save)
        def save():
            host.showNormal()
            try:
                features=list(drawing.getFeatures())
                if len(features)!=1:raise ValueError('Teken één verbindingssleuf per keer.')
                geometry=features[0].geometry()
                validate_link(geometry,cables,plan,float(state['values'].get('node_tolerance',1.)))
                drawing.commitChanges()
                target=Path(state['clustering_dir'])/('verbindingssleuven_'+datetime.now().strftime('%Y%m%d_%H%M%S_%f')+'.gpkg')
                combined=QgsVectorLayer('LineString?crs='+base.crs().authid(),'Verbindingssleuven','memory')
                for layer in ([QgsVectorLayer(previous,'vorige','ogr')] if previous else [])+[drawing]:
                    for feature in layer.getFeatures():
                        copy=QgsFeature();copy.setGeometry(feature.geometry());combined.dataProvider().addFeatures([copy])
                options=QgsVectorFileWriter.SaveVectorOptions();options.driverName='GPKG';options.layerName='verbindingssleuven'
                error=QgsVectorFileWriter.writeAsVectorFormatV3(combined,str(target),QgsProject.instance().transformContext(),options)
                if error[0]!=QgsVectorFileWriter.NoError:raise ValueError('Verbindingssleuf opslaan mislukt: '+str(error))
                state['repair_trenches']=str(target)+'|layername=verbindingssleuven'
                from .workflow import WorkflowRunner
                WorkflowRunner(state['values'],lambda *_:None)._write_state(state)
                QgsProject.instance().addMapLayer(QgsVectorLayer(state['repair_trenches'],'Getekende verbindingssleuven','ogr'))
                host.clustering_issue_label.setText('Verbindingssleuf opgeslagen. Klik Automatische clustering om opnieuw te controleren en te berekenen. De bronkabels zijn niet aangepast.')
            except Exception as exc:host.clustering_issue_label.setText(str(exc))
            finally:
                if drawing.isEditable():drawing.rollBack()
                QgsProject.instance().removeMapLayer(drawing.id());self.layer=None
                host.iface.actionPan().trigger()
        drawing.featureAdded.connect(added);host.iface.setActiveLayer(drawing);host.iface.actionAddFeature().trigger();host.showMinimized()

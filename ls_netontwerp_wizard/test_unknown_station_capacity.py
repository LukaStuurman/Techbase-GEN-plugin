"""An unknown transformer power must not hide an existing review station."""
import os
from pathlib import Path
import sys
import tempfile


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from qgis.PyQt.QtCore import QVariant
    from qgis.core import (QgsApplication,QgsFeature,QgsField,QgsGeometry,QgsVectorLayer,
        QgsProject,QgsVectorFileWriter,QgsExpression,QgsExpressionContext,QgsExpressionContextUtils,
        QgsVariantUtils,QgsRuleBasedRenderer,QgsMarkerSymbol)
    app=QgsApplication([],False);app.initQgis()
    from ls_netontwerp_wizard.workflow import WorkflowRunner
    from ls_netontwerp_wizard.project_presentation import repair_generated_project,PRESENTATION_VERSION
    layer=QgsVectorLayer('Point?crs=EPSG:28992','Bestaande stations (bron)','memory')
    layer.dataProvider().addAttributes([QgsField('Station',QVariant.String),QgsField('trafo_power',QVariant.String)])
    layer.updateFields()
    for i,(name,power) in enumerate((('044.532',None),('001.001','630'),('',None),('', '250'),('001.002','onbekend'),('001.003','0'))):
        f=QgsFeature(layer.fields());f.setGeometry(QgsGeometry.fromWkt(f'POINT({154000+i*10} 408000)'));f.setAttributes([name,power]);layer.dataProvider().addFeatures([f])
    WorkflowRunner._ensure_station_max_current(layer)
    WorkflowRunner._style_review_stations(layer)
    def verify(layer):
        context=QgsExpressionContext();context.appendScopes(QgsExpressionContextUtils.globalProjectLayerScopes(layer))
        for f in layer.getFeatures():
            context.setFeature(f)
            matches=[r for r in layer.renderer().rootRule().children() if bool(QgsExpression(r.filterExpression()).evaluate(context))]
            assert len(matches)==1,(f.attributes(),len(matches))
            label=QgsExpression(layer.labeling().settings().fieldName).evaluate(context)
            assert label
            if str(f['Station'])=='044.532':
                assert QgsVariantUtils.isNull(f['trafo_power']) and QgsVariantUtils.isNull(f['Max_A'])
                assert '044.532' in label and 'Capaciteit onbekend' in label
                assert matches[0].symbol().color().getRgb()[:3]==(255,140,0)
            elif str(f['Station'])=='001.001':
                assert '913' in label and 'onbekend' not in label
                assert matches[0].symbol().color().getRgb()[:3]==(227,26,28)
    verify(layer)
    root=Path(tempfile.mkdtemp(prefix='ls_station_null_'));gpkg=root/'stations.gpkg'
    options=QgsVectorFileWriter.SaveVectorOptions();options.driverName='GPKG';options.layerName='stations'
    assert QgsVectorFileWriter.writeAsVectorFormatV3(layer,str(gpkg),QgsProject.instance().transformContext(),options)[0]==QgsVectorFileWriter.NoError
    saved=QgsVectorLayer(str(gpkg)+'|layername=stations','Bestaande stations (bron)','ogr')
    saved.setCustomProperty('LSNetontwerp/review_station_layer',True)
    # Reproduce the old project style which has no rule for NULL Max_A.
    old=QgsRuleBasedRenderer.Rule(None)
    rule=QgsRuleBasedRenderer.Rule(QgsMarkerSymbol.createSimple({'name':'square'}));rule.setFilterExpression('"Max_A" > 0');old.appendChild(rule)
    saved.setRenderer(QgsRuleBasedRenderer(old))
    project=QgsProject.instance();project.clear();project.addMapLayer(saved)
    project.writeEntry('LSNetontwerp','presentation_version',147);assert project.write(str(root/'work.qgz'))
    repair_generated_project(project);verify(saved)
    assert project.readNumEntry('LSNetontwerp','presentation_version',0)[0]==PRESENTATION_VERSION
    assert project.write();project.clear();assert project.read(str(root/'work.qgz'))
    reopened=next(iter(project.mapLayers().values()));verify(reopened)
    assert reopened.featureCount()==6
    # Rendering and labels do not supply a made-up capacity to the calculation.
    assert WorkflowRunner._parse_station_kva(None) is None
    assert WorkflowRunner._parse_station_kva('onbekend') is None
    print('UNKNOWN_STATION_CAPACITY_TEST_OK (NULL visible/labeled, valid/planned/invalid/zero styles, no invented capacity, old project migration, GPKG and QGZ persistence)',flush=True)
    os._exit(0)


if __name__=='__main__':main()

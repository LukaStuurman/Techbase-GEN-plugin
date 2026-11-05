"""Real QGIS source merging and inside-plan repair geometry validation."""
import os,sys,tempfile
from pathlib import Path


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from qgis.core import QgsApplication,QgsVectorLayer,QgsFeature,QgsGeometry,QgsProject,QgsVectorFileWriter
    app=QgsApplication([],False);app.initQgis()
    from ls_netontwerp_wizard.network_repair import merged_cables,validate_link
    def layer(kind,geometries,fields=''):
        result=QgsVectorLayer(kind+'?crs=EPSG:28992'+fields,'test','memory')
        for wkt in geometries:
            feature=QgsFeature(result.fields());feature.setGeometry(QgsGeometry.fromWkt(wkt));result.dataProvider().addFeatures([feature])
        return result
    cables=layer('LineString',['LINESTRING(0 0,10 0)','LINESTRING(20 0,30 0)'],'&field=Functie:string')
    plan=layer('Polygon',['POLYGON((-1 -1,31 -1,31 10,-1 10,-1 -1))'])
    good=QgsGeometry.fromWkt('LINESTRING(10 0,20 0)');validate_link(good,cables,plan,1.)
    for wkt in ('LINESTRING(10 0,15 20,20 0)','LINESTRING(10 0,15 5)','LINESTRING(10 0,10 0)'):
        try:validate_link(QgsGeometry.fromWkt(wkt),cables,plan,1.)
        except ValueError:pass
        else:raise AssertionError('Invalid repair accepted: '+wkt)
    root=Path(tempfile.mkdtemp(prefix='repair_test_'));repair=layer('LineString',[good.asWkt()])
    options=QgsVectorFileWriter.SaveVectorOptions();options.driverName='GPKG';options.layerName='repair'
    assert QgsVectorFileWriter.writeAsVectorFormatV3(repair,str(root/'repair.gpkg'),QgsProject.instance().transformContext(),options)[0]==0
    merged=merged_cables(cables,str(root/'repair.gpkg')+'|layername=repair','Functie')
    assert merged.featureCount()==3 and cables.featureCount()==2
    assert [f['Functie'] for f in merged.getFeatures()][-1]=='LS'
    from types import SimpleNamespace
    from qgis.PyQt.QtWidgets import QLabel
    from ls_netontwerp_wizard.network_repair import RepairDrawing
    def save(layer,path,name):
        options.layerName=name
        assert QgsVectorFileWriter.writeAsVectorFormatV3(layer,str(path),QgsProject.instance().transformContext(),options)[0]==0
    save(cables,root/'base.gpkg','cables');save(plan,root/'plan.gpkg','plangebied')
    class Action:
        def trigger(self):pass
    class Interface:
        def setActiveLayer(self,layer):self.layer=layer
        def actionAddFeature(self):return Action()
        def actionPan(self):return Action()
    state={'import_gpkg':str(root/'base.gpkg'),'plan_gpkg':str(root/'plan.gpkg'),
           'clustering_dir':str(root),'result_dir':str(root),'status':'voorbereid',
           'values':{'layer_main_cables':'cables','field_main_function':'Functie','node_tolerance':1.}}
    host=SimpleNamespace(prepared_state=state,iface=Interface(),showNormal=lambda:None,
                         showMinimized=lambda:None,clustering_issue_label=QLabel())
    QgsProject.instance().setFileName(str(root/'project.qgz'))
    tool=RepairDrawing(host);tool.start()
    feature=QgsFeature();feature.setGeometry(good);assert tool.layer.addFeature(feature)
    app.processEvents();app.processEvents()
    assert tool.layer is None and 'repair_trenches' in state,host.clustering_issue_label.text()
    assert Path(state['repair_trenches'].split('|')[0]).exists()
    assert (root/'ls_netontwerp_workflow.json').exists()
    print('NETWORK_REPAIR_TEST_OK (inside plan, both endpoints connected, invalid/outside/zero links rejected, persistent supplement merged, source unchanged)',flush=True)
    os._exit(0)


if __name__=='__main__':main()

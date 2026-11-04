"""Real data-independent topology, reference, atomic storage and dashboard tests."""
import csv
import json
import os
from pathlib import Path
import sqlite3
import sys
import tempfile
import time
import xml.etree.ElementTree as ET
import zipfile


def fixture(root, closed=False):
    tables = {'LS Veld': [], 'LS Railsectie': [], 'LS Smeltveiligheid': []}
    rails = [('ra', 'MS-000001-L01-RS01', 0), ('rb', 'MS-000002-L01-RS01', 4),
             ('r1', 'LS-000001-L01-RS01', 10), ('r2', 'LS-000001-L01-RS02', 14)]
    fields = [('a', '1', 'Kabelveld', 'MS-000001-L01-VE01', 'ra', 'SMG1', 160, 'mespatroon', 1, 0),
        ('b', '1', 'Kabelveld', 'MS-000002-L01-VE01', 'rb', 'SMG2', 160, 'mespatroon', 1, 4),
        ('i1', '1', 'Kabelveld', 'LS-000001-L01-VE01', 'r1', 'SMG1', 9999, 'doorverbindingsmes', 2, 10),
        ('o1', '2', 'Kabelveld', 'LS-000001-L01-VE02', 'r1', 'SMG3', 80, 'mespatroon', 8, 10),
        ('i2', '3', 'Kabelveld', 'LS-000001-L01-VE03', 'r1', 'SMG2', 9999, 'doorverbindingsmes', 2, 14),
        ('o2', '4', 'Kabelveld', 'LS-000001-L01-VE04', 'r1', 'SMG4', 100, 'onbekend', 8, 14),
        ('k', 'K', 'Koppelveld', 'LS-000001-L01-VE05', 'r1', '0', 9999, 'doorverbindingsmes', 5, 12)]
    exp = ET.Element('Explorer')
    collections = {}
    for kind in ('e_lv_field', 'e_lv_rail_section', 'e_lv_fuse'):
        coll = ET.SubElement(ET.SubElement(exp, 'featureMember'), 'FeatureCollection', identifier=kind)
        collections[kind] = coll
    def obj(kind, properties, xy=None):
        node = ET.SubElement(ET.SubElement(collections[kind], 'featureMember'), 'Feature', typeName=kind)
        for key, value in properties.items():ET.SubElement(node, 'property', typeName=key).text=str(value)
        if xy is not None:
            geom = ET.SubElement(node, 'geometricProperty', typeName='position_schematic' if kind=='e_lv_fuse' else 'location_schematic')
            shape = ET.SubElement(geom, 'Point' if kind=='e_lv_fuse' else 'LineString')
            shape.set('{http://www.gesmallworld.com/gml_extension}world','schematic')
            ET.SubElement(shape, 'coordinates').text=' '.join(f'{(154000+x)*1000},{(408000+y)*1000}' for x,y in xy)
    for ident, sap, y in rails:
        row={'Id':ident,'Status':'in bedrijf','Change State':'Active','[SAP R3] Functieplaatsnummer':sap,'Rail Id':'asset-'+ident}
        tables['LS Railsectie'].append(row)
        obj('e_lv_rail_section',{'id':ident,'status':'in bedrijf','change_state':'Active'},[(0,y),(10,y)])
    for ident, number, kind, sap, rail, code, amps, fusekind, x, y in fields:
        tables['LS Veld'].append({'Id':ident,'Nummer':number,'Soort':kind,'Status':'in bedrijf','Change State':'Active',
            '[SAP R3] Functieplaatsnummer':sap,'Bovenliggend Asset Id':rail,'Kabelgroepnummer':code})
        obj('e_lv_field',{'id':ident,'status':'in bedrijf','change_state':'Active','structure_parent_id':rail})
        if ident=='k' and not closed:continue
        tables['LS Smeltveiligheid'].append({'Id':'f'+ident,'Status':'in bedrijf','Change State':'Active',
            'Bovenliggend Asset Id':ident,'Smeltveiligheid soort':fusekind,'LS Smeltveiligheid I Nominaal':str(amps)})
        obj('e_lv_fuse',{'id':'f'+ident,'status':'in bedrijf','change_state':'Active','structure_parent_id':ident,'kind':fusekind},[(x,y)])
    xml=root/('closed.xml' if closed else 'open.xml');ET.ElementTree(exp).write(xml,encoding='utf-8',xml_declaration=True)
    excel=root/('closed.xlsx' if closed else 'open.xlsx')
    with zipfile.ZipFile(excel,'w') as z:
        wb=ET.Element('workbook',xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main');sheets=ET.SubElement(wb,'sheets')
        rels=ET.Element('Relationships',xmlns='http://schemas.openxmlformats.org/package/2006/relationships')
        for i,(name,rows) in enumerate(tables.items(),1):
            ET.SubElement(sheets,'sheet',name=name,attrib={'{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id':f'r{i}'})
            ET.SubElement(rels,'Relationship',Id=f'r{i}',Target=f'worksheets/sheet{i}.xml')
            sheet=ET.Element('worksheet',xmlns='http://schemas.openxmlformats.org/spreadsheetml/2006/main');sd=ET.SubElement(sheet,'sheetData')
            headers=list(dict.fromkeys(k for row in rows for k in row))
            for ridx,values in enumerate([headers]+[[r.get(h,'') for h in headers] for r in rows],1):
                row=ET.SubElement(sd,'row',r=str(ridx))
                for col,v in enumerate(values):
                    cell=ET.SubElement(row,'c',r=f'{chr(65+col)}{ridx}',t='inlineStr')
                    ET.SubElement(ET.SubElement(cell,'is'),'t').text=str(v)
            z.writestr(f'xl/worksheets/sheet{i}.xml',ET.tostring(sheet))
        z.writestr('xl/workbook.xml',ET.tostring(wb));z.writestr('xl/_rels/workbook.xml.rels',ET.tostring(rels))
    # A drawn K bridge exists whether its mes is installed or not. Only an
    # active mes is allowed to turn it into an electrical edge.
    dxf=root/('closed.dxf' if closed else 'open.dxf');pairs=[(0,'SECTION'),(2,'ENTITIES')]
    for ident,sap,y in rails:
        pairs += [(0,'LINE'),(8,'E_LV_RAIL_SECTION'),(10,154000),(20,408000+y),(11,154010),(21,408000+y)]
    pairs += [(0,'LINE'),(8,'E_LV_FIELD_LOCATION'),(10,154005),(20,408010),(11,154005),(21,408014)]
    for ident,number,kind,sap,rail,code,amps,fusekind,x,y in fields:
        if ident=='k' and not closed:continue
        pairs += [(0,'INSERT'),(8,'E_LV_FUSE'),(2,'symbol'),(10,154000+x),(20,408000+y)]
    pairs += [(0,'ENDSEC'),(0,'EOF')]
    dxf.write_text('\n'.join(str(v) for pair in pairs for v in pair)+'\n')
    return str(xml),str(excel),str(dxf)


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from qgis.PyQt.QtCore import QVariant
    from qgis.PyQt.QtGui import QFont,QFontDatabase
    from qgis.PyQt.QtWidgets import QPushButton
    from qgis.core import QgsApplication,QgsFeature,QgsField,QgsGeometry,QgsProject,QgsVectorLayer,QgsVectorFileWriter
    app=QgsApplication([],False);app.initQgis()
    for name in ('segoeui.ttf','segoeuib.ttf'):
        font=Path('C:/Windows/Fonts')/name
        if font.exists():QFontDatabase.addApplicationFont(str(font))
    app.setFont(QFont('Segoe UI',10))
    from ls_netontwerp_wizard.schema_linking import build_mapping,compare_connections,cable_code
    from ls_netontwerp_wizard.schema_link_io import connection_records,station_records,apply_proposal,undo_proposal,layer_hash,value
    root=Path(tempfile.mkdtemp(prefix='ls_schema_'));paths=fixture(root)
    xmlmap=build_mapping(*paths[:2]);mapping=build_mapping(*paths)
    assert xmlmap['groups']==mapping['groups']
    assert mapping['groups']['SMG3']['stations']==['MS-000001']
    assert mapping['groups']['SMG4']['stations']==['MS-000002']
    assert len(mapping['corrected_rails'])==2
    closed=build_mapping(*fixture(root,True))
    assert closed['groups']['SMG3']['stations']==['MS-000001','MS-000002']
    assert closed['groups']['SMG4']['stations']==['MS-000001','MS-000002']
    assert cable_code('smg3-00')=='SMG3' and cable_code('SMG30')!='SMG3' and cable_code('0')==''
    source=QgsVectorLayer('Point?crs=EPSG:28992','connections','memory')
    source.dataProvider().addAttributes([QgsField(n,QVariant.String) for n in ('master_asset_id','Kabel Subgroep','Station','Keep')]);source.updateFields()
    ids=['9000000000000000001','9000000000000000002','9000000000000000003']
    for i,(ident,code) in enumerate(zip(ids,('SMG3-00','SMG4-00','SMG999-00'))):
        f=QgsFeature(source.fields());f.setGeometry(QgsGeometry.fromWkt(f'POINT({154000+i} 408000)'))
        f.setAttributes([ident,code,None,'unchanged']);assert source.dataProvider().addFeatures([f])[0]
    db=root/'points.gpkg';opts=QgsVectorFileWriter.SaveVectorOptions();opts.driverName='GPKG';opts.layerName='connections'
    assert QgsVectorFileWriter.writeAsVectorFormatV3(source,str(db),QgsProject.instance().transformContext(),opts)[0]==QgsVectorFileWriter.NoError
    target=QgsVectorLayer(str(db)+'|layername=connections','target','ogr');assert target.isValid()
    stations=QgsVectorLayer('Point?crs=EPSG:28992','stations','memory')
    stations.dataProvider().addAttributes([QgsField(n,QVariant.String) for n in ('Station','trafo_sap_structure_indicator')]);stations.updateFields()
    for name,sap in (('001.001','MS-000001-T01'),('002.001','MS-000002-T01')):
        f=QgsFeature(stations.fields());f.setAttributes([name,sap]);stations.dataProvider().addFeatures([f])
    ref=root/'reference.csv';ref.write_text('Master Asset ID;SourceFile\n'+ids[0]+';001.001\n'+ids[1]+';WRONG\n'+ids[2]+';001.001\n',encoding='utf-8')
    records,digest=connection_records(target,'master_asset_id','Kabel Subgroep')
    result=compare_connections(mapping,records,station_records(stations),str(ref));result['layer_hash']=digest
    assert result['comparison']=={'Gelijk':1,'Afwijkend':1,'Niet herleid':1}
    assert result['rows'][2]['Station']==''  # Reference must not fill predictions.
    duplicates=compare_connections(mapping,[records[0],records[0]],station_records(stations))
    assert all(r['Status']=='Dubbel ID' and not r['Station'] for r in duplicates['rows'])
    duplicate_ref=root/'duplicate.csv';duplicate_ref.write_text(ref.read_text()+ids[0]+';001.001\n')
    assert compare_connections(mapping,records,station_records(stations),str(duplicate_ref))['rows'][0]['Controle']=='Dubbel referentie-ID'
    geometries=[f.geometry().asWkb() for f in target.getFeatures()]
    # A real SQLite write failure must roll back new columns, values and undo.
    with sqlite3.connect(db) as c:c.execute("CREATE TRIGGER fail_schema BEFORE UPDATE ON connections BEGIN SELECT RAISE(ABORT,'injected failure'); END")
    try:apply_proposal(target,result,'master_asset_id',True,True)
    except sqlite3.IntegrityError:pass
    else:raise AssertionError('Injected database failure was accepted')
    with sqlite3.connect(db) as c:
        assert 'Schema_station' not in [r[1] for r in c.execute('pragma table_info(connections)')]
        c.execute('DROP TRIGGER fail_schema')
    assert layer_hash(target)==digest
    assert apply_proposal(target,result,'master_asset_id',True,True)==1
    assert [f['Station'] for f in target.getFeatures()][0]=='001.001'
    assert [f.geometry().asWkb() for f in target.getFeatures()]==geometries
    reopened=QgsVectorLayer(str(db)+'|layername=connections','reopened','ogr')
    assert undo_proposal(reopened)==1
    assert all(value(f,'Station')=='' for f in reopened.getFeatures()),[repr(f['Station']) for f in reopened.getFeatures()]
    assert all(f['Keep']=='unchanged' for f in reopened.getFeatures())
    reopened.setReadOnly(True)
    try:apply_proposal(reopened,result,'master_asset_id',True,True)
    except ValueError:pass
    else:raise AssertionError('Read-only layer was changed')
    reopened.setReadOnly(False)
    fresh,digest=connection_records(reopened,'master_asset_id','Kabel Subgroep')
    proposal=compare_connections(mapping,fresh,station_records(stations),str(ref));proposal['layer_hash']=digest
    assert apply_proposal(reopened,proposal,'master_asset_id',True,True)==1
    assert reopened.startEditing();f=next(reopened.getFeatures());reopened.changeAttributeValue(f.id(),reopened.fields().lookupField('Keep'),'changed');assert reopened.commitChanges()
    try:undo_proposal(reopened)
    except ValueError:pass
    else:raise AssertionError('Stale undo accepted')
    try:apply_proposal(reopened,proposal,'master_asset_id',True,True)
    except ValueError:pass
    else:raise AssertionError('Stale preview accepted')
    xmlfile=Path(paths[0]);original=xmlfile.read_text();xmlfile.write_text(original+'\n')
    try:apply_proposal(reopened,proposal,'master_asset_id',True,True)
    except ValueError as exc:assert 'schemabron' in str(exc)
    else:raise AssertionError('Changed input accepted')
    xmlfile.write_text(original)
    try:build_mapping(*paths,canceled=lambda:True)
    except ValueError as exc:assert 'geannuleerd' in str(exc)
    else:raise AssertionError('Canceled calculation accepted')
    # The actual colored dashboard must expose and execute the asynchronous page.
    project=QgsProject.instance();project.clear();project.addMapLayer(reopened);project.addMapLayer(stations)
    from ls_netontwerp_wizard.dashboard_warning_dialog import LSNetontwerpDashboardDialog
    dialog=LSNetontwerpDashboardDialog(None);dialog.resize(1450,950);dialog.show_home_page();dialog.show();app.processEvents()
    button=next(b for b in dialog._dashboard_widget.findChildren(QPushButton) if b.text()=='1.4. Voedend station uit LS-schema')
    assert button.isVisible() and button.isEnabled();button.click();app.processEvents()
    page=dialog.schema_link_page;assert dialog.page_stack.currentWidget() is page
    for key,path in zip(('xml','excel','dxf'),paths):page.files[key].setText(path)
    page.files['reference'].setText(str(ref));page.target.setCurrentIndex(page.target.findData(reopened.id()));page.stations.setCurrentIndex(page.stations.findData(stations.id()))
    page.check_button.click();deadline=time.monotonic()+30
    while page.task and time.monotonic()<deadline:app.processEvents();time.sleep(.01)
    assert page.proposal is not None,page.status.text()
    assert page.proposal['comparison']=={'Gelijk':1,'Afwijkend':1,'Niet herleid':1}
    page.filter.setCurrentIndex(1);assert page.table.rowCount()==1
    page.table.selectRow(0);page.map_button.click();assert len(reopened.selectedFeatureIds())==1
    capture=os.environ.get('LS_SCHEMA_TEST_CAPTURE')
    if capture:
        out=Path(capture);out.mkdir(parents=True,exist_ok=True);page.filter.setCurrentIndex(0);app.processEvents();dialog.grab().save(str(out/'schema-page.png'))
        dialog.show_home_page();app.processEvents();dialog.grab().save(str(out/'dashboard.png'))
    print('SCHEMA_LINKING_TEST_OK (isolated feeds, K ambiguity, physical rail correction, exact IDs, reference independence, duplicate IDs, atomic rollback, persistent undo, stale protections, real dashboard, task and map selection)',flush=True)
    os._exit(0)


if __name__=='__main__':main()

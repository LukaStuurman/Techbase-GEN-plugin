"""Synthetic drawing topology and annotation tests, without source XML or CSV labels."""
import os
from pathlib import Path
import sys
import tempfile


def pair(kind, layer='', **values):
    tags=[(0,kind)]
    if layer:tags.append((8,layer))
    tags.extend((int(k[1:]),v) for k,v in values.items())
    return ''.join(f'{k}\n{v}\n' for k,v in tags)


def drawing(path, opened=False, broken_bundle=False, reversed_bundle=False, blank_slot=False, conflicting=False):
    p='E_LV'
    def line(layer,a,b):return pair('LINE',p+layer,c10=a[0],c20=a[1],c11=b[0],c21=b[1])
    def text(layer,label,x,y,rot=0,h=.789474):return pair('TEXT',p+layer,c1=label,c10=x,c20=y,c40=h,c50=rot)
    def ins(layer,block,x,y):return pair('INSERT',p+layer,c2=block,c10=x,c20=y,c41=.001,c42=.001)
    block=pair('BLOCK',c2='F')+pair('CIRCLE',c10=0,c20=0,c40=800)+pair('LINE',c10=-560,c20=-560,c11=560,c21=560)+pair('LINE',c10=-560,c20=560,c11=560,c21=-560)+pair('ENDBLK')
    block+=pair('BLOCK',c2='OPEN')+pair('CIRCLE',c10=0,c20=0,c40=800)+pair('ENDBLK')
    entities=''
    for y in (0,30):entities+=line('_RAIL_SECTION',(0,y),(10,y))
    entities+=text('_SCHEMATIC_STATION_LOCATION','001.001',5,10)+text('_SCHEMATIC_STATION_LOCATION','002.001',5,40)
    for x,y,code in ((2,0,'1'),(4,0,'2'),(6,30,'3')):
        entities+=line('_FIELD_LOCATION',(x,y),(x,y-1))+line('_SCHEMATIC_SUBGROUP_LOCATION',(x,y-1),(x,-10))
        entities+=ins('_FUSE','OPEN' if opened and x==4 else 'F',x,y)+text('_FUSE','100',x,y+1)
        if x!=4:entities+=text('_SCHEMATIC_CABLE_LABEL',code+' / 95 Al',x,-5 if x==2 else 20,90)
    a,b=((2,-3),(8,-3)) if not reversed_bundle else ((8,-3),(2,-3))
    # Third cable crosses this annotation line too: three slots, including a blank.
    entities+=line('_SCHEMATIC_LABEL_BUNDLE',a,(12,-3) if not reversed_bundle else b)
    if not reversed_bundle:
        entities+=text('_SCHEMATIC_CABLE_LABEL','9 / 95 Al' if conflicting else '1 / 95 Al',7.5,-2.5,90)
        if not broken_bundle:entities+=text('_SCHEMATIC_CABLE_LABEL','4x6' if blank_slot else '2 / 95 Al',9.5,-2.5,90)
        entities+=text('_SCHEMATIC_CABLE_LABEL','3 / 95 Al',11.5,-2.5,90)
    path.write_text('0\nSECTION\n2\nBLOCKS\n'+block+'0\nENDSEC\n0\nSECTION\n2\nENTITIES\n'+entities+'0\nENDSEC\n0\nEOF\n',encoding='utf-8')


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from qgis.core import QgsApplication,QgsVectorLayer
    app=QgsApplication([],False);app.initQgis()
    from ls_netontwerp_wizard.schema_dxf import build_dxf_mapping,physical_field_numbers
    from ls_netontwerp_wizard.schema_linking import build_mapping,compare_connections
    from ls_netontwerp_wizard.test_schema_linking import fixture
    from ls_netontwerp_wizard.schema_link_io import station_spatial_records
    root=Path(tempfile.mkdtemp(prefix='schema_dxf_'));path=root/'drawing.dxf'
    anchors=[{'Station':'001.001','ms':'MS-000001','x':5,'y':0},{'Station':'002.001','ms':'MS-000002','x':5,'y':30}]
    drawing(path);mapping=build_dxf_mapping(str(path),'',anchors)
    assert mapping['groups']['SMG1']['stations']==['MS-000001']
    assert mapping['groups']['SMG2']['stations']==['MS-000001']
    assert mapping['groups']['SMG3']['stations']==['MS-000002']  # Crossing the other rail is not a contact.
    assert mapping['counts']['accepted_bundles']==1
    drawing(path,opened=True);opened=build_dxf_mapping(str(path),'',anchors)
    assert opened['groups']['SMG2']['stations']==[]
    for options in ({'broken_bundle':True},{'reversed_bundle':True},{'blank_slot':True},{'conflicting':True}):
        drawing(path,**options);result=build_dxf_mapping(str(path),'',anchors)
        assert 'SMG2' not in result['groups']
        assert result['groups']['SMG1']['stations']==['MS-000001']
    try:build_dxf_mapping('',str(path),anchors)
    except ValueError as exc:assert 'E_SL' in str(exc)
    else:raise AssertionError('LS file accepted as OV drawing')
    drawing(path);ambiguous=[dict(anchors[0],y=15),anchors[1]]
    assert build_dxf_mapping(str(path),'',ambiguous)['groups']['SMG1']['stations']==[]
    try:build_dxf_mapping(str(path),'',anchors,lambda:True)
    except ValueError as exc:assert 'geannuleerd' in str(exc)
    else:raise AssertionError('Cancellation ignored')
    wrong=QgsVectorLayer('Point?crs=EPSG:4326&field=Station:string&field=trafo_sap_structure_indicator:string','wrong CRS','memory')
    try:station_spatial_records(wrong)
    except ValueError as exc:assert '28992' in str(exc)
    else:raise AssertionError('Non-RD anchors accepted')
    # A drawn field number corrects an inconsistent administrative fuse parent.
    paths=fixture(root,extra_fields=[('a2','2','Kabelveld','MS-000001-L01-VE02','ra','SMG5',0,'',3,0)])
    dxf=Path(paths[2]);raw=dxf.read_text()
    extra=pair('INSERT','E_LV_FIELD_LOCATION',c2='FIELD',c10=154001,c20=408000)+pair('TEXT','E_LV_FIELD_LOCATION',c1='2',c10=154002.2,c20=407999.1,c40=.789474,c50=0)
    raw=raw.replace('0\nENDSEC\n0\nEOF',extra+'0\nENDSEC\n0\nEOF');dxf.write_text(raw)
    assert physical_field_numbers(str(dxf))[0][1]=='2'
    corrected=build_mapping(*paths)
    assert corrected['counts']['corrected_fields']==1
    assert corrected['groups']['SMG5']['stations']==['MS-000001']
    assert corrected['groups']['SMG1']['stations']==[]
    no_dxf=build_mapping(*paths[:2]);assert no_dxf['groups']['SMG1']['stations']==['MS-000001']
    dxf.write_text(raw.replace('154002.2','154003.2'))
    assert not physical_field_numbers(str(dxf))  # Moved text does not define a field identity.
    print('SCHEMA_DXF_TEST_OK (direct anchors, ordered bundles, missing/reversed slots, isolated rails, open fields, ambiguous station anchors, cancellation, RD guard, physical field-parent correction and moved-label rejection)',flush=True)
    os._exit(0)


if __name__=='__main__':main()

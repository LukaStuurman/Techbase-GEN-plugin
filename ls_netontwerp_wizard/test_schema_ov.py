"""Independent OV registration, cable consensus and reciprocal relation tests."""
import os
from pathlib import Path
import sys
import tempfile


def main():
    sys.path.insert(0,str(Path(__file__).resolve().parent.parent))
    from qgis.core import QgsApplication
    app=QgsApplication([],False);app.initQgis()
    from ls_netontwerp_wizard.test_schema_linking import fixture
    from ls_netontwerp_wizard.schema_linking import build_mapping,compare_connections,attach_connection_cables,cable_codes,file_digest
    from ls_netontwerp_wizard.schema_link_io import eligible
    root=Path(tempfile.mkdtemp(prefix='ls_ov_'))
    extra=[('ov1','2','OV-veld','MS-000001-L01-VE02','ra','SMG5',0,'',3,0),
           ('ov2','2','Kabelveld','MS-000002-L01-VE02','rb','SMG3',0,'',3,4),
           ('ov3','3','OV-veld','MS-000001-L01-VE03','ra','SMG6',0,'',4,0),
           ('ov4','3','OV-veld','MS-000002-L01-VE03','rb','SMG6',0,'',4,4),
           ('ov5','4','Reserveveld','MS-000001-L01-VE04','ra','SMG7',0,'',5,0)]
    paths=fixture(root,extra_fields=extra)
    ov=root/'ov.dxf';pairs=[(0,'SECTION'),(2,'ENTITIES'),(0,'LINE'),(8,'E_SL_RAIL_SECTION'),
        (10,154000),(20,408000),(11,154010),(21,408000),
        (0,'INSERT'),(8,'E_SL_FUSE'),(2,'symbol'),(10,154001),(20,408000)]
    for code in (3,5,6,7):pairs.extend([(0,'TEXT'),(8,'E_SL_SCHEMATIC_CABLE_LABEL'),(10,154001),(20,408001),(1,f'{code} / 4x6 +')])
    pairs.extend([(0,'TEXT'),(8,'E_SL_SCHEMATIC_CABLE_LABEL'),(1,'4x6'),(0,'ENDSEC'),(0,'EOF')])
    ov.write_text('\n'.join(str(v) for pair in pairs for v in pair)+'\n')
    baseline=build_mapping(*paths);mapping=build_mapping(*paths,ov_dxf_path=str(ov))
    assert baseline['groups']['SMG5']['stations']==[]
    assert mapping['groups']['SMG5']['stations']==['MS-000001']
    assert 'OV-code' in mapping['groups']['SMG5']['evidence']
    assert mapping['groups']['SMG3']['stations']==['MS-000001']  # A weaker OV record must not replace a proven LS path.
    assert mapping['groups']['SMG3']['ov_registered_stations']==['MS-000002']
    assert mapping['groups']['SMG3']['ov_notice']
    assert mapping['groups']['SMG6']['stations']==['MS-000001','MS-000002']
    assert mapping['groups']['SMG7']['stations']==[]  # Reserve field is not a source.
    assert mapping['counts']['ov_codes']==4
    assert mapping['files'][str(ov.resolve())]==file_digest(ov)
    stations=[{'Station':'001.001','trafo_sap_structure_indicator':'MS-000001-T01'},
              {'Station':'002.001','trafo_sap_structure_indicator':'MS-000002-T01'}]
    def row(cable,asset='9000000000000000001'):
        return {'fid':1,'asset':asset,'cable':cable,'station':'','object_id':'point-1','connection_id':'wire-1'}
    direct=compare_connections(mapping,[row('SMG5')],stations)
    assert direct['rows'][0]['Station']=='001.001'
    assert eligible(direct['rows'][0],False,False)
    ref=root/'wrong-reference.csv';ref.write_text('Master Asset ID;SourceFile\n9000000000000000001;999.999\n')
    checked=compare_connections(mapping,[row('SMG5')],stations,str(ref))
    assert checked['rows'][0]['Station']==direct['rows'][0]['Station']
    assert checked['rows'][0]['Controle']=='Afwijkend' and not eligible(checked['rows'][0],False,True)
    assert cable_codes('SMG3-00, SMG3-01')==['SMG3']
    assert compare_connections(mapping,[row('SMG3-00, SMG3-01')],stations)['rows'][0]['Station']=='001.001'
    for codes in ('SMG3, SMG4','SMG3, SMG999','SMG6'):
        assert compare_connections(mapping,[row(codes)],stations)['rows'][0]['Station']==''
    def wire(code,reverse='point-1'):
        return {'id':'wire-1','Kabel Subgroep':code,'service_connections_id':reverse,'cable_status':'In bedrijf','change_state':'Active'}
    enriched=attach_connection_cables([row('SMG3, SMG4')],[wire('SMG3')])
    assert enriched[0]['cable']=='SMG3'
    assert compare_connections(mapping,enriched,stations)['rows'][0]['Station']=='001.001'
    for cables in ([wire('SMG3','another-point')],[wire('SMG3'),wire('SMG3')]):
        records=attach_connection_cables([row('SMG3, SMG4')],cables)
        assert compare_connections(mapping,records,stations)['rows'][0]['Station']==''
    duplicate_objects=attach_connection_cables([row('SMG3, SMG4'),row('SMG3, SMG4','9000000000000000002')],[wire('SMG3')])
    assert all(r['cable']=='SMG3, SMG4' for r in duplicate_objects)
    same=attach_connection_cables([row('SMG3')],[wire('SMG5')])
    assert compare_connections(mapping,same,stations)['rows'][0]['Station']=='001.001'  # Both independently agree.
    conflict=attach_connection_cables([row('SMG3')],[wire('SMG4')])
    assert compare_connections(mapping,conflict,stations)['rows'][0]['Station']==''
    assert same[0]['original_cable']=='SMG3'
    try:build_mapping(*paths,ov_dxf_path=paths[2])
    except ValueError as exc:assert 'E_SL' in str(exc)
    else:raise AssertionError('An LS drawing was accepted as an OV drawing')
    print('SCHEMA_OV_TEST_OK (independent OV station registration, LS priority, conflicting sources, reserve exclusion, exact labels, multi-code consensus, reciprocal cable IDs, duplicate/reverse-link protection, reference independence and CSV-free eligibility)',flush=True)
    os._exit(0)


if __name__=='__main__':main()

"""Original route terminals from explicit GEN equipment/object relationships."""
from .existing_group_trace import _value
from .existing_station_retention import group_codes

def original_terminals(points,cabinets,cables=None,schema_paths=None,*,require_station=True):
    result=points.copy();anchors={}
    cables=cables.copy() if cables is not None else None
    result['Orig_kabelgroepen_bron']=result['Kabel Subgroep']
    index={}
    for _,row in (cabinets.iterrows() if cabinets is not None else []):
        ident=_value(row,('Flatkast_ID','id'))
        if ident in index:raise ValueError('Dubbel oorspronkelijk flatkast-ID '+ident)
        if ident:index[ident]=row
    for i,row in result.iterrows():
        ident=_value(row,('Multistory','multistory_connection_id'))
        if not ident:continue
        cabinet=index.get(ident)
        if cabinet is None:continue # original trace will reject unsupported geometry
        station=_value(row,('Station',))
        if require_station and not station:continue
        declared=set(group_codes(_value(row,('Kabel Subgroep',))))
        cabinet_codes=set(group_codes(_value(cabinet,('cable_subgroup','Kabel Subgroep'))))
        if not declared or not cabinet_codes or not declared.issubset(cabinet_codes):
            raise ValueError(f'Flatkast {ident}: bron-kabelgroepen verschillen van aansluiting {i}.')
        geometry=cabinet.geometry
        if geometry is None or geometry.is_empty or geometry.geom_type!='Point':
            raise ValueError(f'Flatkast {ident}: geen unieke oorspronkelijke puntgeometrie.')
        anchors[int(i)]={'flatkast':ident,'afstand_m':float(row.geometry.distance(geometry))}
        result.at[i,'geometry']=geometry
    cable_index={}
    if cables is not None:
        for ci,cable in cables.iterrows():
            ident=_value(cable,('id',))
            if ident:cable_index.setdefault(ident,[]).append(ci)
    for i,row in result.iterrows():
        if int(i) in anchors:continue
        ident=_value(row,('connection_cable_id',))
        matches=cable_index.get(ident,[])
        if len(matches)!=1:continue
        ci=matches[0]
        cable=cables.loc[ci].copy()
        import re
        reverse={v.strip() for v in re.split('[,;]',_value(cable,('service_connections_id',))) if v.strip()}
        object_id=_value(row,('id',))
        if not object_id or object_id not in reverse:continue
        if _value(cable,('cable_status',)).casefold()!='in bedrijf' or _value(cable,('change_state',)).casefold()!='active':continue
        declared=set(group_codes(_value(row,('Kabel Subgroep',))))
        specific=group_codes(_value(cable,('Kabel Subgroep',)))
        if not specific and len(declared)==1:
            # Explicit reciprocal service/cable IDs prove this existing
            # conductor's group when the redundant cable attribute is blank.
            specific=tuple(declared)
            cable['Kabel Subgroep']=specific[0]
            cables.at[ci,'Kabel Subgroep']=specific[0]
        if specific and not set(specific).issubset(declared) and len(declared)==1:
            def base(code):return re.sub(r'^(SMG\d+)-\d+$',r'\1',code)
            station=_value(row,('Station',))
            codes=set(specific)|declared
            same_source=all(station+'|'+base(code) in (schema_paths or {}) for code in codes)
            is_service=str(cable.get('_Aansluitkabel',False)).strip().casefold() in ('true','1')
            if same_source and is_service:
                # The requested authoritative grouping is the CONNECTION
                # record. Resolve only a reciprocal service wire, with both
                # codes independently proving the same station. Preserve the
                # conflicting wire attribute for the control report.
                legacy=', '.join(specific)
                cables.at[ci,'Orig_kabelgroep_kabel']=legacy
                specific=tuple(declared)
                cable['Kabel Subgroep']=specific[0]
                cables.at[ci,'Kabel Subgroep']=specific[0]
                anchors[int(i)]={'aansluitkabel':ident,'broncode_kabel':legacy,
                    'aansluitgroep':specific[0],'relatie':'wederzijdse GEN-object-ID; beide schema-groepen bij hetzelfde station'}
        if not specific or not set(specific).issubset(declared):continue
        result.at[i,'Kabel Subgroep']=', '.join(specific)
        geometry=cable.geometry
        if geometry.geom_type!='LineString':continue
        if geometry.distance(row.geometry)<=.20:continue
        from shapely.geometry import Point
        ends=[Point(geometry.coords[0]),Point(geometry.coords[-1])]
        ranked=sorted((row.geometry.distance(p),j) for j,p in enumerate(ends))
        if ranked[0][0]>15 or abs(ranked[1][0]-ranked[0][0])<.20:
            raise ValueError(f'Aansluitkabel {ident}: geen eenduidig bron-eindpunt voor aansluiting {i}.')
        result.at[i,'geometry']=ends[ranked[0][1]]
        anchors[int(i)]={**anchors.get(int(i),{}),'aansluitkabel':ident,'afstand_m':float(ranked[0][0]),'relatie':anchors.get(int(i),{}).get('relatie','wederzijdse GEN-object-ID')}
    return result,anchors,cables

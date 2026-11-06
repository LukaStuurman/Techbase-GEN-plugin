"""Explicit CONCEPT mode: unverified old feeders never become retained supply.

No fabricated conductor or electrical capacity is used. Failed original
families are recorded as requiring new design and offered only to new sites.
Strict historical verification remains the default outside this opt-in mode.
"""
from dataclasses import dataclass
import re
from .existing_group_trace import GROUP_FIELDS,STATION_FIELDS,required_column,_value
from .existing_station_retention import group_codes

@dataclass(frozen=True)
class ReviewOriginal:
    id:str
    station:str
    group:str
    source_groups:tuple
    source_id:str

def prepare_review_retention(points,stations,cables,max_route_m,logger=None,forced_release=None,**kwargs):
    from .existing_locked_clustering import prepare_retention
    sf=required_column(points,STATION_FIELDS,'oorspronkelijk station')
    gf=required_column(points,GROUP_FIELDS,'oorspronkelijke kabelgroep')
    seen=set()
    for i,row in points.iterrows():
        ident=_value(row,('master_asset_id','Master Asset ID','id')) or f'IDX-{i}'
        if ident in seen:raise ValueError(f'Dubbel aansluit-ID {ident}; geen concepttoedeling mogelijk.')
        seen.add(ident)
    failures=dict(forced_release or {})
    remaining=set(points.index)-set(failures);schema=kwargs.get('schema_paths') or {}
    def base(code):return re.sub(r'^(SMG\d+)-\d+$',r'\1',code)
    known=set(stations[next(c for c in ('Stationsnaa','Stationsnaam','Station') if c in stations)].astype(str))
    original={i for i,row in points.iterrows() if str(row[sf]).strip() in known and group_codes(row[gf])}
    while original&remaining:
        try:
            result=prepare_retention(points.loc[sorted(remaining)],stations,cables,max_route_m,**kwargs)
            break
        except ValueError as exc:
            message=str(exc)
            # Do not mask invalid station capacities, missing schema sources,
            # duplicate identities or coding/runtime errors as a cable issue.
            codes=re.findall(r'\b[A-Z][A-Z0-9._]*-\d{2}\b',message.upper())
            names={str(points.loc[i,sf]).strip() for i in original&remaining}
            affected_names={n for n in names if n+'/' in message or 'station '+n.casefold() in message.casefold()}
            if not codes:
                match=re.search(r'Aansluiting (\d+)',message)
                if match and int(match.group(1)) in remaining:
                    idx=int(match.group(1));codes=list(group_codes(points.loc[idx,gf]));affected_names={str(points.loc[idx,sf]).strip()}
            if not codes:raise
            bad=set(codes)
            upstream_bad={base(c) for c in bad if c.endswith("-00")}
            dropped=[]
            for i in original&remaining:
                row=points.loc[i];name=str(row[sf]).strip()
                if affected_names and name not in affected_names:continue
                groups=group_codes(row[gf])
                belongs=any(g in bad or upstream_bad.intersection(schema.get(name+'|'+base(g),[])[:-1]) for g in groups)
                if belongs:dropped.append(i)
            if not dropped:raise
            for i in dropped:failures[int(i)]=message
            remaining.difference_update(dropped)
            if logger:logger(f'CONCEPT broncontrole: {len(dropped)} aansluiting(en) uit richting(en) {", ".join(sorted(bad))} niet behouden; alleen nieuwe stations. Nog {len(original&remaining)} oorspronkelijke aansluitingen te toetsen.')
    else:
        names={str(r[next(c for c in ('Stationsnaa','Stationsnaam','Station') if c in stations)]):float(r['Max_A']) for _,r in stations.iterrows()}
        result=dict(retained_by_index={},all_original_by_index={},connections_by_index={},
            equipment_terminal_indices=set(),equipment_terminals={},ov_points=set(),physical_by_station={},edge_geometries={},
            retention=dict(behouden=(),vrijgegeven=(),redenen={},stations={n:dict(belasting_a=0.,maximum_a=v,pass_=True) for n,v in names.items()},richtingen={},route_m={},whole_path_edge_ids={},waarschuwingen=[]),
            cabinet_metadata={},cabinet_bridges={},feeder_parents={},records=[],unknown_stations=[],missing_groups=[],group_field=gf,station_field=sf)
        for v in result['retention']['stations'].values():v['pass']=v.pop('pass_')
    for i,reason in sorted(failures.items()):
        row=points.loc[i];ident=_value(row,('master_asset_id','Master Asset ID','id')) or f'IDX-{i}'
        codes=group_codes(row[gf]);name=str(row[sf]).strip()
        result['all_original_by_index'][i]=ReviewOriginal(ident,name,codes[0],codes,ident)
        result['retention']['vrijgegeven']+= (ident,)
        result['retention']['redenen'][ident]='Eindmof niet betrouwbaar te plaatsen: bronroute niet bewezen; nieuw ontwerp en broncontrole nodig: '+reason
        def current(original,prepared):
            value=row.get(prepared,row.get(original))
            try:return float(value)
            except (TypeError,ValueError):return None
        result['records'].append(dict(Aansluiting=ident,Orig_station=name,Kabel_Subgroep=', '.join(codes),
            Bron_kabelgroepen=str(row[gf]),Route_anker='',Via_verdeelkast='',Besluit='Vrijgegeven - broncontrole',
            Reden=result['retention']['redenen'][ident],Trafo_verbruik_A=current('Ontwerpstroom','Orig_Trafo_Verbruik'),
            Trafo_opwek_A=current('Opwek ontwerpstroom','Orig_Trafo_Opwek'),Kabel_verbruik_A=current('Ontwerpstroom kabel','Orig_Kabel_Verbruik'),
            Kabel_opwek_A=current('Kabel opwek ontwerpstroom','Orig_Kabel_Opwek'),Bestaande_route_m=None,OV_controle_open=False))
    result['verification_failures']=failures
    if failures:result['retention']['waarschuwingen'].append(f'CONCEPT: {len(failures)} oorspronkelijke aansluitingen niet aantoonbaar te behouden; uitsluitend nieuwe stations toegestaan. Bron-/herontwerpcontrole blijft open.')
    return result

"""Explainable station tracing. No reference labels are used to predict a station."""
from collections import Counter, defaultdict, deque
import csv
import hashlib
import json
import posixpath
import re
from pathlib import Path
import xml.etree.ElementTree as ET
import zipfile

from .station_name_csv import read_station_csv, normalize_asset_id

TOLERANCE = .002  # metres in the schematic coordinate world, not geographic snapping
NS = {'m': 'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}


def text(value):
    return '' if value is None else str(value).strip()


def cable_code(value):
    value = text(value).upper()
    if value in ('', '0', 'NULL', 'NONE', 'ONBEKEND'):
        return ''
    # Exact GEN subgroup-to-group convention; never fuzzy/prefix-match numbers.
    return re.sub(r'^(SMG\d+)-\d+$', r'\1', value)


def cable_codes(value):
    """Keep every explicitly supplied cable group; do not pick the first."""
    return list(dict.fromkeys(code for part in re.split(r'[,;\n]+', text(value)) if (code := cable_code(part))))


def attach_connection_cables(records, cables):
    """Prefer only a unique, reciprocal source-object relationship, never distance."""
    index = defaultdict(list)
    for cable in cables: index[text(cable.get('id'))].append(cable)
    object_counts = Counter(text(row.get('object_id')) for row in records)
    result = []
    for original in records:
        row = dict(original); row['original_cable'] = row.get('cable', '')
        identifiers = [x.strip() for x in re.split(r'[,;]', text(row.get('connection_id'))) if x.strip()]
        matches = index.get(identifiers[0], []) if len(identifiers) == 1 else []
        if len(matches) == 1 and text(row.get('object_id')) and object_counts[text(row['object_id'])] == 1:
            cable = matches[0]
            reverse_ids = {x.strip() for x in re.split(r'[,;]', text(cable.get('service_connections_id'))) if x.strip()}
            if (text(row['object_id']) in reverse_ids and text(cable.get('cable_status')).casefold() == 'in bedrijf'
                    and text(cable.get('change_state')).casefold() == 'active'):
                specific, registered = cable_codes(cable.get('Kabel Subgroep')), cable_codes(row.get('cable'))
                if specific and (not registered or set(specific).issubset(set(registered))):
                    row['cable'] = ', '.join(specific)
                    row['cable_evidence'] = f"Aansluitkabel {identifiers[0]} via wederzijdse object-ID-relatie"
                elif specific:
                    row['cable_conflict'] = True
                    row['cable'] = ', '.join(dict.fromkeys(registered + specific))
                    row['cable_evidence'] = f"Aansluitkabel {identifiers[0]} via wederzijdse object-ID-relatie; afwijkende broncodes vereisen overeenstemmende herleiding"
        result.append(row)
    return result


def station_code(value):
    match = re.match(r'^((?:MS|LS)-\d+)(?:-|$)', text(value).upper())
    return match.group(1) if match else ''


def file_digest(path):
    digest = hashlib.sha256()
    with Path(path).open('rb') as stream:
        for chunk in iter(lambda: stream.read(1024 * 1024), b''):
            digest.update(chunk)
    return digest.hexdigest()


def read_tables(path):
    """Read raw XLSX values, retaining full 64-bit identifiers without floats."""
    result = {}
    with zipfile.ZipFile(path) as archive:
        strings = []
        if 'xl/sharedStrings.xml' in archive.namelist():
            strings = [''.join(n.itertext()) for n in ET.fromstring(archive.read('xl/sharedStrings.xml')).findall('m:si', NS)]
        relations = {n.get('Id'): n.get('Target') for n in ET.fromstring(archive.read('xl/_rels/workbook.xml.rels'))}
        for sheet in ET.fromstring(archive.read('xl/workbook.xml')).find('m:sheets', NS):
            if sheet.get('name') not in ('LS Veld', 'LS Railsectie', 'LS Smeltveiligheid'):
                continue
            target = relations[sheet.get('{http://schemas.openxmlformats.org/officeDocument/2006/relationships}id')]
            target = target.lstrip('/') if target.startswith('/') else posixpath.normpath('xl/' + target)
            rows = []
            for row in ET.fromstring(archive.read(target)).findall('m:sheetData/m:row', NS):
                values = {}
                for cell in row:
                    col = re.sub(r'\d+$', '', cell.get('r', ''))
                    value = cell.find('m:v', NS)
                    value = value.text if value is not None else ''
                    if cell.get('t') == 's':
                        value = strings[int(value)]
                    elif cell.get('t') == 'inlineStr':
                        value = ''.join(cell.find('m:is', NS).itertext())
                    if value:
                        values[col] = value
                if values:
                    rows.append(values)
            if not rows:
                raise ValueError(f"Werkblad {sheet.get('name')} is leeg.")
            headers = rows[0]
            if len(set(headers.values())) != len(headers):
                raise ValueError(f"Dubbele kolomkoppen in {sheet.get('name')}.")
            records = [{headers[k]: v for k, v in row.items() if k in headers} for row in rows[1:]]
            if any(not r.get('Id') for r in records) or len({r['Id'] for r in records}) != len(records):
                raise ValueError(f"Ontbrekende of dubbele object-ID in {sheet.get('name')}.")
            result[sheet.get('name')] = records
    for name in ('LS Veld', 'LS Railsectie', 'LS Smeltveiligheid'):
        if name not in result:
            raise ValueError(f"Werkblad '{name}' ontbreekt. Exporteer veld, railsectie en smeltveiligheid samen.")
    return result


def read_schema_xml(path):
    from shapely.geometry import LineString, Point
    objects = defaultdict(dict)
    for _event, node in ET.iterparse(path, events=('end',)):
        if node.tag != 'Feature' or node.find('property[@typeName="id"]') is None:
            continue
        kind = node.get('typeName')
        if kind in ('e_lv_field', 'e_lv_rail_section', 'e_lv_fuse'):
            record = {p.get('typeName'): p.text or '' for p in node.findall('property')}
            shape_name = 'position_schematic' if kind == 'e_lv_fuse' else 'location_schematic'
            coordinate = node.find(f'geometricProperty[@typeName="{shape_name}"]//coordinates')
            if coordinate is not None and coordinate.text:
                xy = [tuple(float(v) / 1000. for v in pair.split(',')[:2]) for pair in coordinate.text.split()]
                record['_geometry'] = Point(xy[0]) if kind == 'e_lv_fuse' else LineString(xy) if len(xy) > 1 else None
            record['_world'] = next((p.get('{http://www.gesmallworld.com/gml_extension}world', '') for p in node.findall(f'geometricProperty[@typeName="{shape_name}"]/*')), '')
            if record['id'] in objects[kind]:
                raise ValueError(f"Dubbel XML-object {kind}/{record['id']}.")
            objects[kind][record['id']] = record
        node.clear()
    return objects


def read_dxf(path, prefix='E_LV', include_codes=False):
    """ASCII DXF geometry needed for checks, without an optional CAD dependency.

    This checks actual LINE/POLYLINE vertices and INSERT positions in modelspace.
    It does not infer electrical identity from block names or drawing colours.
    """
    from shapely.geometry import LineString, Point
    raw = Path(path).read_bytes()
    if raw.startswith(b'AutoCAD Binary DXF'):
        raise ValueError('Gebruik een ASCII-DXF; binaire DXF wordt niet ondersteund.')
    lines = raw.decode('utf-8-sig' if raw.startswith(b'\xef\xbb\xbf') else 'cp1252').splitlines()
    if len(lines) % 2:
        raise ValueError('Onvolledig ASCII-DXF: een groepscode mist zijn waarde.')
    section = ''; entity = None; tags = []; poly = None
    rails, bridges, fuses = [], [], []
    codes = set()
    rail_layer, field_layer, internal_layer = (prefix + suffix for suffix in ('_RAIL_SECTION', '_FIELD_LOCATION', '_INTERNAL_CONNECTION'))
    def finish(kind, values):
        nonlocal poly
        value = lambda code, default='': next((v for c, v in values if c == code), default)
        layer = value(8).upper()
        if kind == 'POLYLINE':
            poly = (layer, [])
        elif kind == 'VERTEX' and poly is not None:
            if poly[0] in (rail_layer, field_layer, internal_layer) and float(value(42, '0')) != 0:
                raise ValueError('Gebogen DXF-polylijn: gebruik XML-posities zonder DXF-controle of een rechte schematische export.')
            poly[1].append((float(value(10)), float(value(20))))
        elif kind == 'SEQEND' and poly is not None:
            pl, points = poly; poly = None
            if len(points) > 1:
                shape = LineString(points)
                if pl == rail_layer: rails.append(shape)
                if pl in (field_layer, internal_layer): bridges.append(shape)
        elif kind == 'LINE' and layer in (rail_layer, field_layer, internal_layer):
            shape = LineString([(float(value(10)), float(value(20))), (float(value(11)), float(value(21)))])
            (rails if layer == rail_layer else bridges).append(shape)
        elif kind == 'INSERT' and layer == prefix + '_FUSE':
            fuses.append(Point(float(value(10)), float(value(20))))
        elif kind == 'TEXT' and layer == prefix + '_SCHEMATIC_CABLE_LABEL':
            match = re.match(r'^\s*(?:SMG)?(\d+)(?:-\d+)?\s*/', value(1), flags=re.I)
            if match: codes.add('SMG' + match.group(1))
    for index in range(0, len(lines), 2):
        code, value = int(lines[index].strip()), lines[index + 1].strip()
        if code == 0:
            if section == 'ENTITIES' and entity:
                finish(entity, tags)
            entity, tags = value, []
            if value == 'SECTION':
                section = lines[index + 3].strip()
            elif value == 'ENDSEC':
                section = ''
        else:
            tags.append((code, value))
    if not rails or not fuses:
        raise ValueError(f'DXF mist de lagen {prefix}_RAIL_SECTION en/of {prefix}_FUSE. Gebruik de juiste schematische export.')
    return (rails, bridges, fuses, codes) if include_codes else (rails, bridges, fuses)


def active(row):
    return text(row.get('Status')).casefold() == 'in bedrijf' and text(row.get('Change State')).casefold() == 'active'


def fuse_role(rows):
    roles = set()
    for row in rows:
        if text(row.get('Smeltveiligheid soort')).casefold() in ('doorverbindingsmes', 'doorverbinding'):
            roles.add('invoer')
        else:
            try:
                amps = float(text(row.get('LS Smeltveiligheid I Nominaal')).replace(',', '.'))
            except ValueError:
                continue
            if 0 < amps < 9999:
                roles.add('afgaand')
    return next(iter(roles)) if len(roles) == 1 else 'onzeker'


def build_mapping(xml_path, excel_path, dxf_path='', administrative=False, canceled=lambda: False, ov_dxf_path=''):
    # Keep the rest of the dashboard usable on installations where the
    # optional scientific environment has not yet been installed/configured.
    try:
        import shapely
        from shapely.strtree import STRtree
        from shapely.ops import unary_union
    except ImportError as exc:
        raise ValueError('Stationsherleiding vereist Shapely 2 in de QGIS-Pythonomgeving.') from exc
    if int(shapely.__version__.split('.')[0]) < 2:
        raise ValueError('Stationsherleiding vereist Shapely 2; de overige wizardfuncties blijven beschikbaar.')
    files = {str(Path(p).resolve()): file_digest(p) for p in (xml_path, excel_path, dxf_path, ov_dxf_path) if p}
    tables, xml = read_tables(excel_path), read_schema_xml(xml_path)
    def check():
        if canceled(): raise ValueError('Herleiding geannuleerd; niets gewijzigd.')
    check()
    for sheet, kind in (('LS Veld', 'e_lv_field'), ('LS Railsectie', 'e_lv_rail_section'), ('LS Smeltveiligheid', 'e_lv_fuse')):
        if {r['Id'] for r in tables[sheet]} != set(xml[kind]):
            raise ValueError(f"XML en Excel bevatten niet dezelfde objectselectie voor {sheet}. Exporteer ze samen.")
        for row in tables[sheet]:
            record = xml[kind].get(row['Id'])
            if record is None:
                raise ValueError(f"XML mist object {row['Id']} uit {sheet}. Gebruik bij elkaar horende exports.")
            for key, column in (('status', 'Status'), ('change_state', 'Change State'), ('structure_parent_id', 'Bovenliggend Asset Id')):
                if key in record and record[key] != row.get(column, ''):
                    raise ValueError(f"XML en Excel verschillen voor {sheet}, ID {row['Id']}, kolom {column}.")
            column = 'Smeltveiligheid soort' if kind == 'e_lv_fuse' else 'Soort' if kind == 'e_lv_field' else None
            if column and 'kind' in record and text(record['kind']).casefold() != text(row.get(column)).casefold():
                raise ValueError(f"XML en Excel verschillen voor {sheet}, ID {row['Id']}, kolom {column}.")
    fields = {r['Id']: dict(r) for r in tables['LS Veld']}
    rails = {r['Id']: r for r in tables['LS Railsectie']}
    fuses = defaultdict(list)
    for f in tables['LS Smeltveiligheid']:
        if active(f): fuses[f.get('Bovenliggend Asset Id')].append(f)
    panel = lambda row: text(row.get('[SAP R3] Functieplaatsnummer')).rsplit('-RS', 1)[0]
    panels = defaultdict(list)
    for ident, row in rails.items():
        if panel(row): panels[panel(row)].append(ident)
    dxf = read_dxf(dxf_path) if dxf_path else None
    corrected_fields = []
    if dxf_path:
        from .schema_dxf import physical_field_numbers
        positions = physical_field_numbers(dxf_path)
        position_tree = STRtree([p for p,number in positions]) if positions else None
        # A fuse's administrative parent can name a different physical field.
        # Trust a drawn number only at its exact reconstructed field symbol.
        for parent, items in list(fuses.items()):
            for fuse in list(items):
                point = xml['e_lv_fuse'].get(fuse['Id'], {}).get('_geometry')
                if point is None or position_tree is None:continue
                numbers = {positions[int(i)][1] for i in position_tree.query(point.buffer(TOLERANCE))
                           if positions[int(i)][0].distance(point)<=TOLERANCE}
                field = fields.get(parent, {})
                stem = text(field.get('[SAP R3] Functieplaatsnummer')).rsplit('-VE',1)[0]
                if len(numbers)!=1 or not stem:continue
                number = next(iter(numbers))
                if number == field.get('Nummer'):continue
                targets = [ident for ident,row in fields.items() if active(row) and row.get('Nummer')==number
                           and text(row.get('[SAP R3] Functieplaatsnummer')).rsplit('-VE',1)[0]==stem]
                if len(targets)!=1:continue
                target=targets[0];fuses[parent].remove(fuse);fuses[target].append(fuse)
                corrected_fields.append({'smeltobject':fuse['Id'],'asset_veld':parent,'schema_veld':target,
                    'installatie':stem,'getekend_veldnummer':number})
    fuse_tree = STRtree(dxf[2]) if dxf else None
    rail_tree = STRtree(dxf[0]) if dxf else None
    rail_checks = {}
    def confirmed_rail(ident, shape):
        if not dxf: return True
        if ident not in rail_checks:
            candidates = rail_tree.query(shape.buffer(TOLERANCE))
            cover = unary_union([dxf[0][int(i)] for i in candidates])
            rail_checks[ident] = shape.difference(cover.buffer(TOLERANCE)).length <= TOLERANCE
        return rail_checks[ident]
    bridge_tree = STRtree(dxf[1]) if dxf and dxf[1] else None
    graph = defaultdict(dict); issues = [{'veld':row['installatie'], 'reden':f"Smeltobject {row['smeltobject']}: bovenliggend veld verschilt van getekend veld {row['getekend_veldnummer']}; fysieke veldkoppeling gebruikt."} for row in corrected_fields]; corrected = []; valid_fields = {}; couplings = 0
    def link(start, end, label): graph[start][end] = label
    for ident, field in fields.items():
        check()
        if not active(field) or not fuses[ident]: continue
        asset_rail = field.get('Bovenliggend Asset Id')
        label = f"{station_code(field.get('[SAP R3] Functieplaatsnummer'))}/veld {field.get('Nummer', '?')}"
        def issue(reason): issues.append({'veld': label, 'reden': reason})
        if asset_rail not in rails:
            issue('Bovenliggende railsectie ontbreekt.'); continue
        siblings = panels[panel(rails[asset_rail])]
        shapes = {r: xml['e_lv_rail_section'].get(r, {}).get('_geometry') for r in siblings}
        role = fuse_role(fuses[ident]); is_coupling = field.get('Soort') == 'Koppelveld'
        matched = set(); coupling_checked = False
        for fuse in fuses[ident]:
            raw = xml['e_lv_fuse'].get(fuse['Id'], {}); point = raw.get('_geometry')
            if administrative:
                matched.add(asset_rail); continue
            if point is None:
                issue('Schematische smeltpositie ontbreekt.'); break
            if dxf and point.distance(dxf[2][int(fuse_tree.nearest(point))]) > TOLERANCE:
                issue('Smeltpositie niet bevestigd in DXF.'); break
            same_world = {r: shape for r, shape in shapes.items() if shape is not None and xml['e_lv_rail_section'][r].get('_world') == raw.get('_world')}
            if dxf:
                same_world = {r: shape for r, shape in same_world.items() if confirmed_rail(r, shape)}
            hits = [r for r, shape in same_world.items() if shape.distance(point) <= TOLERANCE]
            if is_coupling and role == 'invoer' and len(siblings) == 2:
                if dxf:
                    candidates = bridge_tree.query(point.buffer(TOLERANCE)) if bridge_tree is not None else []
                    coupling_checked = any(dxf[1][int(i)].distance(point) <= TOLERANCE and
                        all(r in same_world and dxf[1][int(i)].distance(same_world[r]) <= TOLERANCE for r in siblings) for i in candidates)
                else:
                    # Explicit coupling asset + exactly two rails in this
                    # installation. Unlike CAD mode this is an inferred bridge.
                    coupling_checked = len(same_world) == 2
                if coupling_checked and not hits: hits = [asset_rail]
            if len(hits) != 1:
                issue('Geen eenduidige schematische rail; geen nabije rail geraden.'); break
            matched.add(hits[0])
        else:
            if len(matched) != 1 or role == 'onzeker':
                issue('Meerdere schakelposities of onbekende/tegenstrijdige veldrol.'); continue
            rail = next(iter(matched))
            if not active(rails[rail]): continue
            valid_fields[ident] = rail
            if rail != asset_rail: corrected.append({'veld': label, 'asset_rail': asset_rail, 'schema_rail': rail})
            code = cable_code(field.get('Kabelgroepnummer'))
            if code:
                if role == 'invoer': link('c:' + code, 'r:' + rail, label + ' (mes naar rail)')
                else: link('r:' + rail, 'c:' + code, label + ' (afgezekerd afgaand)')
            if is_coupling:
                if role != 'invoer' or len(siblings) != 2 or (not administrative and not coupling_checked):
                    issue('Koppelbrug niet eenduidig bevestigd.'); continue
                other = next(r for r in siblings if r != rail)
                if active(rails[other]):
                    link('r:' + rail, 'r:' + other, 'K: ' + label)
                    link('r:' + other, 'r:' + rail, 'K: ' + label); couplings += 1
    roots = defaultdict(set); transformer_roots = {}
    for ident, rail in valid_fields.items():
        field = fields[ident]; station = station_code(field.get('[SAP R3] Functieplaatsnummer'))
        if station.startswith('MS-'): roots[station].add('r:' + rail)
        if field.get('Soort') == 'Transformatorveld': transformer_roots[ident] = ('r:' + rail, station, field.get('Nummer', ''))
    def walk(nodes):
        previous = {n: None for n in sorted(nodes)}; queue = deque(previous)
        while queue:
            check(); start = queue.popleft()
            for end in sorted(graph[start]):
                if end not in previous: previous[end] = start; queue.append(end)
        return previous
    paths = {name: walk(nodes) for name, nodes in roots.items()}
    trafo_paths = {ident: walk([value[0]]) for ident, value in transformer_roots.items()}
    mappings = {}
    for code in sorted({cable_code(f.get('Kabelgroepnummer')) for f in fields.values()} - {''}):
        check(); node = 'c:' + code; candidates = sorted(name for name, previous in paths.items() if node in previous)
        route = []; node_route = [node]
        if len(candidates) == 1:
            previous = paths[candidates[0]]
            while previous[node] is not None:
                parent = previous[node]; route.append(graph[parent][node]); node = parent
                node_route.append(node)
        mappings[code] = {'stations': candidates, 'path': ' → '.join(reversed(route)),
                          'transformers': [f'{transformer_roots[i][1]}/{transformer_roots[i][2]}' for i, prev in trafo_paths.items() if 'c:' + code in prev],
                          'evidence': 'LS-schakelpad',
                          'cable_path': [n[2:] for n in reversed(node_route) if n.startswith('c:')]}
    ov_new, ov_conflicts, ov_labels = 0, 0, 0
    if ov_dxf_path:
        check()
        *_, codes_in_ov = read_dxf(ov_dxf_path, prefix='E_SL', include_codes=True)
        ov_labels = len(codes_in_ov)
        # This supplements registration of origin; it does not invent a closed
        # OV switching path from nearby text, wire crossings or station names.
        registered = defaultdict(lambda: defaultdict(list))
        for field in fields.values():
            source = station_code(field.get('[SAP R3] Functieplaatsnummer'))
            code = cable_code(field.get('Kabelgroepnummer'))
            if (active(field) and source.startswith('MS-') and code in codes_in_ov
                    and field.get('Soort') in ('Kabelveld', 'OV-veld', 'OV/Installatieveld')):
                registered[code][source].append(field.get('[SAP R3] Functieplaatsnummer', ''))
        for code, origins in registered.items():
            check()
            group = mappings[code]; candidates = set(origins); ls_sources = set(group['stations'])
            group['ov_registered_stations'] = sorted(candidates)
            if ls_sources:
                if ls_sources != candidates:
                    group['ov_notice'] = 'Afwijkende OV-stationregistratie zonder bewezen schakelpad; het bestaande LS-schakelpad blijft leidend.'
                    issues.append({'veld': code, 'reden': group['ov_notice']})
                    ov_conflicts += 1
            elif len(candidates) != 1:
                group['stations'] = sorted(ls_sources | candidates)
                group['path'] = ''; group['evidence'] = 'Tegenstrijdige LS/OV-registratie'
                issues.append({'veld': code, 'reden': 'OV-code bevestigd, maar meerdere of tegenstrijdige geregistreerde bronstations.'})
                ov_conflicts += 1
            else:
                source = next(iter(candidates)); group['stations'] = [source]
                group['path'] = f"{source} → {', '.join(origins[source])} (kabelgroep op actief stationveld; code in OV-schema) → {code}"
                group['evidence'] = 'OV-code + geregistreerd stationveld; schakeling niet vastgesteld'
                ov_new += 1
    if any(file_digest(p) != digest for p, digest in files.items()):
        raise ValueError('Een schemabron veranderde tijdens de berekening. Probeer opnieuw met vaste exports.')
    return {'groups': mappings, 'issues': issues, 'corrected_rails': corrected, 'corrected_fields':corrected_fields,
            'electrical_edges': [[u,v] for u,adj in graph.items() for v in adj],
            'source_roots': {name:sorted(nodes) for name,nodes in roots.items()},
            'counts': {'fields': len(fields), 'rails': len(rails), 'fuses': len(tables['LS Smeltveiligheid']), 'couplings': couplings,
                       'ov_codes': ov_labels, 'ov_added_groups': ov_new, 'ov_conflicts': ov_conflicts, 'corrected_fields':len(corrected_fields)},
            'files': files,
            'mode': ('Administratieve rail (vergelijking)' if administrative else 'XML/Excel + DXF-controle' if dxf else 'XML/Excel met schematische posities') + (' + OV-registratie' if ov_dxf_path else '')}


def station_lookup(records):
    aliases = defaultdict(set)
    for row in records:
        name = text(row.get('Station'))
        if not name: continue
        for column in ('trafo_sap_structure_indicator', 'sap_structure_indicator', 'trafo_hana_structure_indicator'):
            code = station_code(row.get(column))
            if code.startswith('MS-'): aliases[code].add(name)
    return aliases


def compare_connections(mapping, records, station_records, reference_path=''):
    aliases = station_lookup(station_records)
    reference = defaultdict(set); ref_counts = Counter(); ref_missing = 0
    reference_digest = file_digest(reference_path) if reference_path else ''
    if reference_path:
        headers, data = read_station_csv(reference_path)
        from .station_name_csv import find_master_asset_id_column, guess_station_name_column
        key, name = find_master_asset_id_column(headers), guess_station_name_column(headers)
        if not key or not name: raise ValueError('Controle-CSV mist Master Asset ID en een stationskolom (bijvoorbeeld SourceFile).')
        for row in data:
            values = dict(zip(headers, row)); ident = normalize_asset_id(values[key])
            if not ident: ref_missing += 1; continue
            ref_counts[ident] += 1
            if text(values[name]): reference[ident].add(text(values[name]))
    counts = Counter(normalize_asset_id(r.get('asset')) for r in records)
    rows = []
    for item in records:
        ident = normalize_asset_id(item.get('asset')); codes = cable_codes(item.get('cable')); code = ', '.join(codes)
        groups = [mapping['groups'].get(c, {}) for c in codes]
        sources = sorted({s for group in groups for s in group.get('stations', [])})
        station = ''; status = 'Niet herleid'; reason = ''
        if not ident: status, reason = 'ID ontbreekt', 'Master Asset ID ontbreekt.'
        elif counts[ident] != 1: status, reason = 'Dubbel ID', 'Master Asset ID is niet uniek in de aansluitingenlaag.'
        elif not code: reason = 'Kabelgroep ontbreekt.'
        elif any(not group for group in groups): reason = 'Niet alle kabelgroepen staan in de veldexport.'
        elif any(not group.get('stations') for group in groups): reason = 'Niet alle kabelgroepen hebben een bronstation binnen de geleverde schemaselectie; bekijk de schema-controles.'
        elif len(sources) > 1: status, reason = 'Meerdere voedingen', 'Meer dan één MS-station bereikbaar.'
        elif len(sources) == 1:
            names = aliases.get(sources[0], set())
            if len(names) == 1: station = next(iter(names)); status = 'Herleid'
            else: status, reason = 'Stationsnaam onbekend', 'Geen eenduidige SAP/Station-koppeling in de gekozen stationslaag.'
        expected = sorted(reference.get(ident, set())); comparison = 'Geen referentie'
        if reference_path:
            if ref_counts[ident] > 1: comparison = 'Dubbel referentie-ID'
            elif len(expected) == 1: comparison = 'Gelijk' if station == expected[0] else 'Afwijkend' if station else 'Niet herleid'
            elif expected: comparison = 'Tegenstrijdige referentie'
        if comparison == 'Afwijkend': reason = 'Schema en controle-CSV noemen verschillende stations; deze koppeling wordt niet toegepast.'
        elif comparison == 'Dubbel referentie-ID': reason = 'Master Asset ID staat meermaals in de controle-CSV; deze koppeling wordt niet toegepast.'
        if not reason: reason = '; '.join(sorted({g['ov_notice'] for g in groups if g.get('ov_notice')}))
        if not reason and item.get('cable_conflict') and station:
            reason = 'De broncodes verschillen, maar alle afzonderlijke herleidingen noemen hetzelfde station.'
        rows.append({'fid': item['fid'], 'Master Asset ID': ident, 'Kabelgroep': code, 'Station': station,
                     'Bestaand station': text(item.get('station')), 'MS-station': '; '.join(sources),
                     'Transformatorvelden': '; '.join(sorted({t for group in groups for t in group.get('transformers', [])})), 'Status': status,
                     'Controle': comparison, 'Referentiestation': '; '.join(expected), 'Reden': reason,
                     'Herkomst': '; '.join(sorted({g.get('evidence', 'LS-schakelpad') for g in groups if g})),
                     'OV-registratiekandidaten': '; '.join(sorted({s for g in groups for s in g.get('ov_registered_stations', [])})),
                     'Originele kabelcodes': text(item.get('original_cable', item.get('cable'))),
                     'Kabelkoppeling': item.get('cable_evidence', 'Kabelcode uit aansluitingenlaag'),
                     'Pad': (item['cable_evidence'] + ' → ' if item.get('cable_evidence') else '') +
                            ' | '.join(f"{c}: {g.get('path', '')}" for c, g in zip(codes, groups))})
    unmatched = sorted(ident for ident in reference if counts[ident] == 0)
    if reference_path and file_digest(reference_path) != reference_digest:
        raise ValueError('De controle-CSV veranderde tijdens het inlezen.')
    return {'rows': rows, 'summary': dict(Counter(r['Status'] for r in rows)),
            'comparison': dict(Counter(r['Controle'] for r in rows)), 'reference_missing_in_layer': unmatched,
            'reference_rows_without_id': ref_missing, 'reference_duplicate_ids': sum(v > 1 for v in ref_counts.values()),
            'reference_file': str(Path(reference_path).resolve()) if reference_path else '',
            'reference_digest': reference_digest, 'mapping': mapping}


def export_report(result, directory):
    directory = Path(directory); directory.mkdir(parents=True, exist_ok=True)
    for name, rows in (('Aansluitingen.csv', result['rows']), ('Schema-controles.csv', result['mapping']['issues']),
                       ('Railcorrecties.csv', result['mapping']['corrected_rails']), ('Veldcorrecties.csv',result['mapping'].get('corrected_fields',[])),
                       ('Stationsankers.csv',result['mapping'].get('station_anchors',[]))):
        with (directory / name).open('w', encoding='utf-8-sig', newline='') as stream:
            fields = list(dict.fromkeys(key for row in rows for key in row))
            if fields:
                writer = csv.DictWriter(stream, fieldnames=fields, delimiter=';'); writer.writeheader(); writer.writerows(rows)
    summary = {k: v for k, v in result.items() if k not in ('rows', 'mapping')}
    summary.update(schema_mode=result['mapping']['mode'], schema_counts=result['mapping']['counts'],
                   schema_source_digests=result['mapping']['files'])
    (directory / 'Vergelijking.json').write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding='utf-8')
    (directory / 'LEESMIJ.txt').write_text(
        'Herleiding volgens geregistreerde smeltposities en de gebruikersregel: mes voedt rail, numerieke zekering voert af. '
        'Rails blijven gescheiden zonder K. Geen actuele vermogensstroom of bewijs van live schakelstand. '
        'De controle-CSV wordt uitsluitend op Master Asset ID vergeleken en levert geen voorspellingen. '
        'Bij XML/Excel controleert LS-DXF ook fysieke veldnummers; een administratief bovenliggend veld kan onjuist zijn. '
        'De afzonderlijke DXF-route gebruikt geografische stationsankers in RD New, exacte kabeltekstankers en volledige tekstvolgorde langs verwijslijnen. '
        'Een verwijslijn of gewone kruising vormt geen elektrische verbinding. Onzekere koppelingen blijven onbehandeld. '
        'Een optionele OV-DXF bevestigt kabelcodes bij een uniek geregistreerd actief stationveld; dit bewijst geen OV-schakelstand. '
        'Een bewezen LS-pad blijft leidend bij een afwijkende OV-registratie. Herkomst en kandidaten staan per aansluiting vermeld. '
        'Meerdere kabelgroepen moeten dezelfde bron aanwijzen. Een unieke wederzijdse object-ID-relatie met een actieve aansluitkabel kan de specifieke groep bepalen. '
        'Een station kan meerdere fysieke trafos hebben. Bekijk afwijkingen en schema-controles vóór toepassen.\n', encoding='utf-8')
    return str(directory)

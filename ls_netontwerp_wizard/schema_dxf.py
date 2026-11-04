"""Conservative station tracing from schematic DXF and geographical station anchors.

No field/rail XML, schema workbook or reference labels are used here.
Label bundles are annotation only. Crossings never form electrical edges.
"""
import collections
import hashlib
import json
import math
import re
from pathlib import Path
from .schema_linking import file_digest

def closed_mes(block):
    """Recognize the filled GEN glyph by geometry, independently of block names."""
    try:
        geometry = [(e['type'], [(c, float(v)) for c, v in e['tags'] if c not in (8, 6, 62)]) for e in block]
        digest = hashlib.sha256(json.dumps(geometry, separators=(',', ':')).encode()).hexdigest()
        return digest == '96ef95db5b2cbd7b38f0feee3d06692311d5e8c4c3f0bfe582b51655ddc2dbc1'
    except (ValueError, TypeError):
        return False

def read_ascii_dxf(path):
    raw = Path(path).read_bytes()
    if raw.startswith(b'AutoCAD Binary DXF'):
        raise ValueError('Gebruik een schematische ASCII-DXF; binaire DXF wordt niet ondersteund.')
    try:
        data = raw.decode('utf-8-sig')
    except UnicodeDecodeError:
        data = raw.decode('cp1252')
    lines = data.splitlines()
    if len(lines) % 2:
        raise ValueError('Onvolledige DXF: groepscode zonder waarde.')
    section = ''
    block = None
    record = None
    entities = []
    blocks = collections.defaultdict(list)

    def save(item):
        nonlocal block
        if not item:
            return
        kind = item['type']
        tags = dict(item['tags'])
        if section == 'ENTITIES':
            if tags.get(67, '0') != '1':
                entities.append(item)
        elif section == 'BLOCKS':
            if kind == 'BLOCK':
                block = tags.get(2, '')
            elif kind == 'ENDBLK':
                block = None
            elif block:
                blocks[block].append(item)
    for i in range(0, len(lines), 2):
        try:
            code = int(lines[i].strip())
        except ValueError as exc:
            raise ValueError('Ongeldige DXF-groepscode.') from exc
        value = lines[i + 1].strip()
        if code == 0:
            save(record)
            record = {'type': value, 'tags': []}
            if value == 'SECTION':
                section = lines[i + 3].strip() if i + 3 < len(lines) else ''
            elif value == 'ENDSEC':
                section = ''
        elif record:
            record['tags'].append((code, value))
    save(record)
    if not entities:
        raise ValueError('DXF bevat geen modelruimte-objecten.')
    return {'entities': entities, 'blocks': blocks}

def physical_field_numbers(path):
    """GEN drawing template: field text offset is (1.52h, -1.14h).

    Accept only when the reconstructed point touches exactly one field symbol.
    Moved labels and different drafting templates produce no identity guess.
    """
    from shapely.geometry import Point
    from shapely.strtree import STRtree
    data = read_ascii_dxf(path)
    get = lambda e, k, z='': next((v for c, v in e['tags'] if c == k), z)
    symbols = [Point(float(get(e, 10)), float(get(e, 20))) for e in data['entities'] if e['type'] == 'INSERT' and get(e, 8) == 'E_LV_FIELD_LOCATION']
    tree = STRtree(symbols)
    result = []
    for e in data['entities']:
        if e['type'] != 'TEXT' or get(e, 8) != 'E_LV_FIELD_LOCATION' or (not re.fullmatch('\\d+|K|TR|OV', get(e, 1))):
            continue
        h = float(get(e, 40, '0'))
        angle = math.radians(float(get(e, 50, '0')))
        dx, dy = (1.52 * h, -1.14 * h)
        expected = Point(float(get(e, 10)) - dx * math.cos(angle) + dy * math.sin(angle), float(get(e, 20)) - dx * math.sin(angle) - dy * math.cos(angle))
        hits = [int(i) for i in tree.query(expected.buffer(0.002)) if symbols[int(i)].distance(expected) <= 0.002]
        if len(hits) == 1:
            result.append((symbols[hits[0]], get(e, 1)))
    return result

def build_dxf_mapping(dxf_path, ov_dxf_path, geostations, canceled=lambda: False):
    """Trace drawing conductors and leave incomplete evidence unresolved.

    Direct text anchors and complete ordered bundles annotate cable polylines.
    Shared endpoints and explicit joint symbols connect cables; ordinary
    crossings do not. A mes feeds its own rail, a numeric fuse feeds its cable.
    A drawn two-rail bridge needs only recognized closed mes contacts.
    Geographical anchors require the same station name in the DXF, bounded
    distances and at least a 3 m margin over the next candidate rail.
    """
    try:
        import shapely
        from shapely.geometry import Point, LineString
        from shapely.strtree import STRtree
        if int(shapely.__version__.split('.')[0]) < 2:
            raise ImportError()
    except ImportError as exc:
        raise ValueError('DXF-stationsherleiding vereist Shapely 2 in QGIS.') from exc
    sources = [(prefix, path) for prefix, path in (('E_LV', dxf_path), ('E_SL', ov_dxf_path)) if path]
    if not sources:
        raise ValueError('Kies een schematische LS- en/of OV-DXF.')
    if not geostations:
        raise ValueError('Kies geografische stations met stationsnaam en SAP-nummer in RD New.')
    digests = {str(Path(path).resolve()): file_digest(path) for _, path in sources}
    geostations = [(r['Station'], r['ms'], Point(r['x'], r['y'])) for r in geostations]

    def check():
        if canceled():
            raise ValueError('DXF-herleiding geannuleerd; niets gewijzigd.')
    get = lambda e, k, z='': next((v for c, v in e['tags'] if c == k), z)

    def pos(e):
        return Point(float(get(e, 10)), float(get(e, 20)))

    def angle(l):
        a, b = (l.coords[0], l.coords[-1])
        return math.degrees(math.atan2(b[1] - a[1], b[0] - a[0])) % 180

    def da(a, b):
        return abs((a - b + 90) % 180 - 90)

    def parse_lines(entities):
        lines = collections.defaultdict(list)
        poly = None
        for e in entities:
            typ = e['type']
            layer = get(e, 8)
            if typ == 'POLYLINE':
                poly = (layer, [])
            elif typ == 'VERTEX' and poly is not None:
                if float(get(e, 42, '0')) != 0:
                    raise ValueError('Gebogen DXF-polylijnen worden in deze schemaroute niet ondersteund.')
                poly[1].append(tuple(pos(e).coords)[0])
            elif typ == 'SEQEND' and poly is not None:
                if len(poly[1]) > 1:
                    lines[poly[0]].append(LineString(poly[1]))
                poly = None
            elif typ == 'LINE':
                lines[layer].append(LineString([tuple(pos(e).coords)[0], (float(get(e, 11)), float(get(e, 21)))]))
            elif typ in ('LWPOLYLINE', 'ARC', 'SPLINE') and any((layer.endswith(s) for s in ('_RAIL_SECTION', '_FIELD_LOCATION', '_INTERNAL_CONNECTION', '_SCHEMATIC_SUBGROUP_LOCATION', '_SCHEMATIC_LABEL_BUNDLE'))):
                raise ValueError('Niet-ondersteunde DXF-geometrie op een schema- of verwijslijnlaag; exporteer rechte LINE/POLYLINE-geometrie.')
        return lines
    graph = collections.defaultdict(dict)
    codes = set()
    issues = []
    counts = collections.Counter()

    def link(a, b, label):
        graph[a][b] = label

    def both(a, b, label):
        link(a, b, label)
        link(b, a, label)
    roots = collections.defaultdict(set)
    anchors_report = []
    for prefix, file in sources:
        check()
        data = read_ascii_dxf(file)
        es = data['entities']
        lines = parse_lines(es)
        cables = lines[prefix + '_SCHEMATIC_SUBGROUP_LOCATION']
        ct = STRtree(cables)
        rails = lines[prefix + '_RAIL_SECTION']
        rt = STRtree(rails)
        if not cables or not rails:
            raise ValueError(f'DXF mist de schematische kabel- en raillagen van {prefix}.')
        cn = lambda i: f'{prefix}:c:{i}'
        rn = lambda i: f'{prefix}:r:{i}'
        annotations = collections.defaultdict(set)
        labels = []
        for e in es:
            if e['type'] == 'TEXT' and get(e, 8) == prefix + '_SCHEMATIC_CABLE_LABEL':
                m = re.match('^\\s*(?:SMG)?(\\d+)(?:-\\d+)?\\s*/', get(e, 1), re.I)
                labels.append(('SMG' + m[1] if m else '', pos(e), float(get(e, 50, '0')), get(e, 1)))
        for code, p, rotation, label in labels:
            if not code:
                continue
            hits = [int(i) for i in ct.query(p.buffer(0.002)) if cables[int(i)].distance(p) <= 0.002]
            if len(hits) == 1:
                annotations[hits[0]].add(code)
                counts['direct_labels'] += 1
        bundles = lines[prefix + '_SCHEMATIC_LABEL_BUNDLE']
        for bundle_index, bundle in enumerate(bundles):
            check()
            crosses = []
            for i in ct.query(bundle.buffer(0.002)):
                cable = cables[int(i)]
                x = bundle.intersection(cable)
                if x.is_empty:
                    for p in (Point(bundle.coords[0]), Point(bundle.coords[-1])):
                        if cable.distance(p) <= 0.002:
                            x = p
                            break
                if x.geom_type == 'Point' and (not x.is_empty):
                    crosses.append((bundle.project(x), int(i)))
            crosses.sort()
            last = LineString(list(bundle.coords)[-2:])
            rot = angle(last)
            texts = sorted(((bundle.project(p), code, label) for code, p, rotation, label in labels if 0.0 <= p.distance(bundle) <= 0.502 and da(rot, rotation) > 89))
            if len(crosses) < 2 or len(crosses) != len(texts) or len({i for _, i in crosses}) != len(crosses):
                if crosses or texts:
                    issues.append({'veld': f'{prefix} verwijslijn {bundle_index}', 'reden': 'Aantal kabelkruisingen en tekstposities niet eenduidig; geen volgordekoppeling.'})
                continue
            if min((t[0] for t in texts)) <= max((c[0] for c in crosses)) + 0.2:
                continue
            pairs = list(zip(crosses, texts))
            if any((code and annotations[i] and (annotations[i] != {code}) for (_, i), (_, code, _) in pairs)):
                counts['bundle_conflicts'] += 1
                issues.append({'veld': f'{prefix} verwijslijn {bundle_index}', 'reden': 'Volgorde botst met een rechtstreeks kabeltekstanker.'})
                continue
            for (_, i), (_, code, _) in pairs:
                if code:
                    annotations[i].add(code)
                    counts['bundle_labels'] += 1
            counts['accepted_bundles'] += 1
        for i, labels_on_cable in annotations.items():
            if len(labels_on_cable) == 1:
                code = next(iter(labels_on_cable))
                codes.add(code)
                both(cn(i), 'c:' + code, f'{prefix} kabel {i} / {code}')
            else:
                issues.append({'veld': cn(i), 'reden': 'Tegenstrijdige kabelteksten'})
        joints = [pos(e) for e in es if e['type'] == 'INSERT' and get(e, 8) == prefix + '_SCHEMATIC_CABLE_JOINT']
        for p in joints:
            hits = [int(i) for i in ct.query(p.buffer(0.002)) if cables[int(i)].distance(p) <= 0.002]
            for i in hits:
                for j in hits:
                    if i != j:
                        both(cn(i), cn(j), f'{prefix} getekende mof')
        for i, cable in enumerate(cables):
            for xy in (cable.coords[0], cable.coords[-1]):
                p = Point(xy)
                for j in ct.query(p.buffer(0.002)):
                    j = int(j)
                    if i != j and min(p.distance(Point(cables[j].coords[0])), p.distance(Point(cables[j].coords[-1]))) <= 0.002:
                        both(cn(i), cn(j), f'{prefix} gedeeld kabeleindpunt')
        for i, rail in enumerate(rails):
            for xy in (rail.coords[0], rail.coords[-1]):
                p = Point(xy)
                for j in rt.query(p.buffer(0.002)):
                    j = int(j)
                    if i != j and rails[j].distance(p) <= 0.002:
                        both(rn(i), rn(j), f'{prefix} rail-eindpunt')
        branches = lines[prefix + '_FIELD_LOCATION'] + lines[prefix + '_FUSE'] + lines[prefix + '_INTERNAL_CONNECTION']
        bt = STRtree(branches)
        inserts = [e for e in es if e['type'] == 'INSERT' and get(e, 8) == prefix + '_FUSE']
        mes_blocks = {name for name, block in data['blocks'].items() if closed_mes(block)}
        numeric = [(pos(e), get(e, 1)) for e in es if e['type'] == 'TEXT' and get(e, 8) == prefix + '_FUSE' and re.fullmatch('\\d+(?:[.,]\\d+)?', get(e, 1)) and (0 < float(get(e, 1).replace(',', '.')) < 9999)]
        for e in inserts:
            check()
            p = pos(e)
            block = data['blocks'].get(get(e, 2), [])
            kind = collections.Counter((x['type'] for x in block))
            role = 'in' if get(e, 2) in mes_blocks else 'out' if dict(kind) == {'CIRCLE': 1, 'LINE': 2} and sum((abs(q.distance(p) - 1) < 0.005 for q, _ in numeric)) == 1 else ''
            if not role:
                counts['unknown_fuses'] += 1
                continue
            rs = [int(i) for i in rt.query(p.buffer(0.002)) if rails[int(i)].distance(p) <= 0.002]
            bs = {int(i) for i in bt.query(p.buffer(0.002)) if branches[int(i)].distance(p) <= 0.002}
            pending = list(bs)
            while pending:
                i = pending.pop()
                for xy in (branches[i].coords[0], branches[i].coords[-1]):
                    q = Point(xy)
                    for j in bt.query(q.buffer(0.002)):
                        j = int(j)
                        if j not in bs and min(q.distance(Point(branches[j].coords[0])), q.distance(Point(branches[j].coords[-1]))) <= 0.002:
                            bs.add(j)
                            pending.append(j)
            cs = set()
            bridge_rails = set(rs)
            for i in bs:
                for xy in (branches[i].coords[0], branches[i].coords[-1]):
                    q = Point(xy)
                    cs.update((int(j) for j in ct.query(q.buffer(0.002)) if cables[int(j)].distance(q) <= 0.002))
                    bridge_rails.update((int(j) for j in rt.query(q.buffer(0.002)) if rails[int(j)].distance(q) <= 0.002))
            contacts = [other for other in inserts if any((branches[i].distance(pos(other)) <= 0.002 for i in bs))] if len(bridge_rails) == 2 else []
            closed_contacts = all((get(other, 2) in mes_blocks for other in contacts))
            if len(bridge_rails) == 2 and role == 'in' and (not cs) and closed_contacts:
                a, b = sorted(bridge_rails)
                both(rn(a), rn(b), f'{prefix} gesloten getekende K-brug bij {p.x:.3f}, {p.y:.3f}')
                counts['couplings'] += 1
                continue
            if len(rs) != 1 or len(cs) != 1:
                counts['unmatched_fuses'] += 1
                continue
            a, b = (rn(rs[0]), cn(next(iter(cs))))
            link(b, a, f'{prefix} mes naar rail bij {p.x:.3f}, {p.y:.3f}') if role == 'in' else link(a, b, f'{prefix} afgezekerd afgaand bij {p.x:.3f}, {p.y:.3f}')
            counts['connected_fuses'] += 1
        names = [e for e in es if e['type'] == 'TEXT' and get(e, 8) == prefix + '_SCHEMATIC_STATION_LOCATION' and re.fullmatch('\\d{3}\\.\\d+', get(e, 1))]
        for name, ms, p in geostations:
            titles = [e for e in names if get(e, 1) == name and pos(e).distance(p) < 100]
            if len(titles) != 1:
                issues.append({'veld': name, 'reden': 'DXF-stationsnaam ontbreekt of is niet uniek nabij het geografische station.'})
                continue
            title = titles[0]
            q = pos(title)
            candidates = sorted(((rail.distance(p), i) for i, rail in enumerate(rails) if rail.distance(p) < 50 and rail.distance(q) < 100 and graph[rn(i)]))
            if not candidates:
                issues.append({'veld': name, 'reden': 'Geen rail binnen 50 m van het geografische station en binnen 100 m van de DXF-stationsnaam.'})
                continue
            if len(candidates) > 1 and candidates[1][0] - candidates[0][0] < 3:
                issues.append({'veld': name, 'reden': 'Geografisch stationanker heeft meerdere nabije rails; afstandsverschil kleiner dan 3 m.'})
                continue
            root = f's:{prefix}:{ms}:{candidates[0][1]}'
            roots[ms].add(root)
            link(root, rn(candidates[0][1]), f'{name} / {ms}, geografisch stationanker {candidates[0][0]:.2f} m van rail, naam bevestigd in DXF')
            counts['root_rails'] += 1
            anchors_report.append({'Station':name,'MS':ms,'tekening':prefix,'station_x':p.x,'station_y':p.y,
                'rail':candidates[0][1],'afstand_m':candidates[0][0],
                'volgende_rail_m':candidates[1][0] if len(candidates)>1 else '',
                'stationsnaam_in_DXF':get(title,1)})
        counts['drawings'] += 1
    paths = {}
    for source, nodes in sorted(roots.items()):
        previous = {n: None for n in nodes}
        queue = collections.deque(nodes)
        while queue:
            start = queue.popleft()
            for end in sorted(graph[start]):
                if end not in previous:
                    previous[end] = start
                    queue.append(end)
        paths[source] = previous
    mapping = {'groups': {}, 'counts': dict(counts), 'issues': issues, 'corrected_rails': [], 'station_anchors':anchors_report, 'files': digests, 'mode': 'DXF-schema met geografische stationsankers (RD New)'}
    for code in sorted(codes):
        node = 'c:' + code
        sources = sorted((s for s, previous in paths.items() if node in previous))
        route = []
        if len(sources) == 1:
            previous = paths[sources[0]]
            while previous[node] is not None:
                parent = previous[node]
                route.append(graph[parent][node])
                node = parent
        mapping['groups'][code] = {'stations': sources, 'path': ' → '.join(reversed(route)), 'evidence': 'DXF-schakelpad + geografisch stationanker', 'transformers': []}
    check()
    if any((file_digest(p) != digest for p, digest in digests.items())):
        raise ValueError('Een DXF veranderde tijdens de analyse; bereken opnieuw met vaste exports.')
    return mapping

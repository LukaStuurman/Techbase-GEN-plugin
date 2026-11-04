"""QGIS snapshots and atomic, reversible GeoPackage attribute application."""
import hashlib
import json
from pathlib import Path
import sqlite3
import struct
from qgis.core import QgsGeometry, QgsProject, QgsVariantUtils

from .schema_linking import file_digest, normalize_asset_id, text

AUDIT = ('Schema_station', 'Schema_MS', 'Schema_code', 'Schema_status', 'Schema_pad')
UNDO_TABLE = '_ls_schema_link_undo'


def quote(name):
    return '"' + str(name).replace('"', '""') + '"'


def storage(layer):
    if layer is None or not layer.isValid(): raise ValueError('Kies een geldige aansluitingenlaag.')
    if layer.isEditable(): raise ValueError('Sla bestaande laagbewerkingen eerst op.')
    if layer.subsetString(): raise ValueError('Verwijder het laagfilter zodat Master Asset ID in de volledige laag wordt gecontroleerd.')
    if {'Cluster', 'Ontwerp_A'}.issubset(set(layer.fields().names())):
        raise ValueError('Kies de bron-/ontwerpstroomlaag. Een clusterresultaat mag niet zonder clusterherberekening worden gewijzigd.')
    parts = layer.source().split('|')
    path = Path(parts[0])
    table = next((p.split('=', 1)[1] for p in parts if p.startswith('layername=')), '')
    if not path.is_file() or path.suffix.casefold() != '.gpkg' or not table:
        raise ValueError('Gebruik de blijvende aansluitingenlaag uit een GeoPackage met een laagnaam.')
    return path, table


def db_hash(connection, table):
    columns = connection.execute(f'PRAGMA table_info({quote(table)})').fetchall()
    primary = [r[1] for r in columns if r[5]]
    if len(primary) != 1: raise ValueError('De aansluitingenlaag mist één vaste objectsleutel.')
    digest = hashlib.sha256(json.dumps(columns).encode())
    for row in connection.execute(f'SELECT * FROM {quote(table)} ORDER BY {quote(primary[0])}'):
        for value in row:
            data = value if isinstance(value, bytes) else json.dumps(value, ensure_ascii=False).encode()
            digest.update(len(data).to_bytes(8, 'little')); digest.update(data)
    return digest.hexdigest()


def layer_hash(layer):
    path, table = storage(layer)
    with sqlite3.connect(path) as connection: return db_hash(connection, table)


def value(feature, field):
    if not field or feature.fields().lookupField(field) < 0: return ''
    result = feature[field]
    return '' if result is None or QgsVariantUtils.isNull(result) else result


def connection_records(layer, asset_field, cable_field):
    before = layer_hash(layer)
    for field in (asset_field, cable_field):
        if field not in layer.fields().names(): raise ValueError(f"Kolom '{field}' ontbreekt.")
    layer.dataProvider().forceReload()
    rows = []
    for feature in layer.getFeatures():
        asset = value(feature, asset_field)
        if isinstance(asset, float) and abs(asset) >= 2 ** 53:
            asset = ''  # A rounded floating-point identifier must never match.
        rows.append({'fid': feature.id(), 'asset': asset, 'cable': value(feature, cable_field), 'station': value(feature, 'Station')})
    if before != layer_hash(layer): raise ValueError('De laag veranderde tijdens het inlezen; controleer opnieuw.')
    return rows, before


def station_records(layer):
    if layer is None or not layer.isValid(): raise ValueError('Kies de stationslaag met Station en trafo-SAP-nummer.')
    if layer.isEditable(): raise ValueError('Sla bestaande bewerkingen in de stationslaag eerst op.')
    names = layer.fields().names()
    if 'Station' not in names or not any(n in names for n in ('trafo_sap_structure_indicator', 'sap_structure_indicator')):
        raise ValueError('Stationslaag mist Station en een SAP-nummer voor de MS-koppeling.')
    return [{n: value(f, n) for n in names if n in ('Station', 'trafo_sap_structure_indicator', 'sap_structure_indicator', 'trafo_hana_structure_indicator')} for f in layer.getFeatures()]


def eligible(row, reference_only=True, replace=False):
    if row['Status'] != 'Herleid' or not row['Station']: return False
    if row['Controle'] in ('Afwijkend', 'Dubbel referentie-ID', 'Tegenstrijdige referentie'): return False
    if reference_only and row['Controle'] != 'Gelijk': return False
    if not replace and row['Bestaand station'] and row['Bestaand station'] != row['Station']: return False
    return True


def sqlite_functions(connection):
    # Native GeoPackage spatial-index triggers may refer to these functions
    # even when only attributes are updated. Geometry is never changed here.
    def geometry(blob):
        if not blob: return QgsGeometry()
        data = bytes(blob)
        if data[:2] == b'GP':
            envelope = (data[3] >> 1) & 7
            count = {0: 0, 1: 4, 2: 6, 3: 6, 4: 8}.get(envelope)
            if count is None: raise ValueError('Ongeldige GeoPackage-geometrie.')
            data = data[8 + count * 8:]
        geom = QgsGeometry(); geom.fromWkb(data); return geom
    connection.create_function('ST_IsEmpty', 1, lambda b: int(not b or geometry(b).isEmpty()))
    connection.create_function('ST_SRID', 1, lambda b: struct.unpack('<i' if bytes(b)[3] & 1 else '>i', bytes(b)[4:8])[0] if b else None)
    for name, getter in (('ST_MinX', 'xMinimum'), ('ST_MaxX', 'xMaximum'), ('ST_MinY', 'yMinimum'), ('ST_MaxY', 'yMaximum')):
        connection.create_function(name, 1, lambda b, getter=getter: None if not b else getattr(geometry(b).boundingBox(), getter)())


def apply_proposal(layer, proposal, asset_field, reference_only=True, replace=False):
    path, table = storage(layer)
    if layer.readOnly(): raise ValueError('Deze laag staat op alleen-lezen; er wordt niets gewijzigd.')
    for source, digest in proposal['mapping']['files'].items():
        if file_digest(source) != digest: raise ValueError('Een schemabron is gewijzigd; maak een nieuw voorstel.')
    if proposal.get('reference_file') and file_digest(proposal['reference_file']) != proposal['reference_digest']:
        raise ValueError('De controle-CSV is gewijzigd; maak een nieuw voorstel.')
    changes = [r for r in proposal['rows'] if eligible(r, reference_only, replace)]
    if not changes: raise ValueError('Geen toepasbare koppelingen onder de gekozen controles.')
    with sqlite3.connect(path, timeout=20) as connection:
        sqlite_functions(connection); connection.execute('BEGIN IMMEDIATE')
        if db_hash(connection, table) != proposal['layer_hash']:
            raise ValueError('De aansluitingenlaag is gewijzigd; maak een nieuw voorstel.')
        columns = connection.execute(f'PRAGMA table_info({quote(table)})').fetchall()
        names = {r[1] for r in columns}; primary = next(r[1] for r in columns if r[5])
        for column in columns:
            if column[1] in ('Station', *AUDIT) and not any(t in column[2].upper() for t in ('TEXT', 'CHAR', 'CLOB')):
                raise ValueError(f"Kolom {column[1]} moet tekst zijn; geen stationsnummer naar een getal omzetten.")
        added = [n for n in ('Station', *AUDIT) if n not in names]
        existing = [n for n in ('Station', *AUDIT) if n in names]
        before = []
        for row in changes:
            found = connection.execute(f'SELECT {quote(asset_field)}' + ''.join(',' + quote(n) for n in existing) +
                                       f' FROM {quote(table)} WHERE {quote(primary)}=?', (row['fid'],)).fetchone()
            if found is None or normalize_asset_id(found[0]) != row['Master Asset ID']:
                raise ValueError('Object-ID past niet meer bij het gecontroleerde voorstel.')
            before.append({'fid': row['fid'], 'values': dict(zip(existing, found[1:]))})
        for name in added: connection.execute(f'ALTER TABLE {quote(table)} ADD COLUMN {quote(name)} TEXT')
        columns_to_write = ('Station', *AUDIT)
        for row in changes:
            values = (row['Station'], row['Station'], row['MS-station'], row['Kabelgroep'], row['Controle'] if row['Controle'] != 'Geen referentie' else 'Herleid uit schema', row['Pad'])
            connection.execute(f'UPDATE {quote(table)} SET ' + ','.join(quote(n) + '=?' for n in columns_to_write) +
                               f' WHERE {quote(primary)}=?', (*values, row['fid']))
        after = db_hash(connection, table)
        undo = {'before': before, 'added': added, 'after': after, 'primary': primary}
        connection.execute(f'CREATE TABLE IF NOT EXISTS {quote(UNDO_TABLE)} (layer TEXT PRIMARY KEY, snapshot TEXT NOT NULL)')
        connection.execute(f'INSERT OR REPLACE INTO {quote(UNDO_TABLE)} VALUES (?,?)', (table, json.dumps(undo, ensure_ascii=False)))
    layer.dataProvider().forceReload(); layer.updateFields(); layer.triggerRepaint()
    from .station_symbology import color_connections_by_station
    color_connections_by_station(layer)
    project = QgsProject.instance(); project.setDirty(True)
    if project.fileName(): project.write()
    return len(changes)


def undo_proposal(layer):
    path, table = storage(layer)
    if layer.readOnly(): raise ValueError('Deze laag staat op alleen-lezen; er wordt niets gewijzigd.')
    with sqlite3.connect(path, timeout=20) as connection:
        sqlite_functions(connection); connection.execute('BEGIN IMMEDIATE')
        try: found = connection.execute(f'SELECT snapshot FROM {quote(UNDO_TABLE)} WHERE layer=?', (table,)).fetchone()
        except sqlite3.OperationalError: found = None
        if not found: raise ValueError('Geen stationsherleiding om terug te draaien.')
        undo = json.loads(found[0])
        if db_hash(connection, table) != undo['after']:
            raise ValueError('De laag is na toepassen veranderd; undo wordt geweigerd om andere wijzigingen te behouden.')
        for row in undo['before']:
            values = {**row['values'], **{n: None for n in undo['added']}}
            connection.execute(f'UPDATE {quote(table)} SET ' + ','.join(quote(n) + '=?' for n in values) +
                               f' WHERE {quote(undo["primary"])}=?', (*values.values(), row['fid']))
        connection.execute(f'DELETE FROM {quote(UNDO_TABLE)} WHERE layer=?', (table,))
    layer.dataProvider().forceReload(); layer.updateFields(); layer.triggerRepaint()
    from .station_symbology import color_connections_by_station
    color_connections_by_station(layer)
    project = QgsProject.instance(); project.setDirty(True)
    if project.fileName(): project.write()
    return len(undo['before'])

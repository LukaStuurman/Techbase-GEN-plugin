"""Planned connections without a BAG identity, in the persistent source layer."""
import hashlib
import json
import math
from uuid import uuid4

from qgis.PyQt.QtCore import QVariant, Qt
from qgis.core import (QgsCoordinateTransform, QgsFeature, QgsField, QgsGeometry,
                       QgsPointXY, QgsProject, QgsVectorLayer, QgsWkbTypes)
from qgis.gui import QgsMapTool

from .connection_sources import CURRENT_FIELDS, _begin, _commit, _ensure_fields
from .bag_current_rules import NEW_BUILD_TYPE_3, has_residential_usage

UNDO_PROPERTY = 'LSNetontwerp/manual_newbuild_undo'
LEFT = Qt.MouseButton.LeftButton if hasattr(Qt, 'MouseButton') else Qt.LeftButton
RIGHT = Qt.MouseButton.RightButton if hasattr(Qt, 'MouseButton') else Qt.RightButton
KEYS = Qt.Key if hasattr(Qt, 'Key') else Qt


class NewBuildPointTool(QgsMapTool):
    def __init__(self, canvas, clicked, finished, canceled):
        super().__init__(canvas)
        self.clicked, self.finished, self.canceled = clicked, finished, canceled

    def canvasReleaseEvent(self, event):
        if event.button() == LEFT:
            self.clicked(self.toMapCoordinates(event.pos()))
        elif event.button() == RIGHT:
            self.finished()

    def keyPressEvent(self, event):
        if event.key() == KEYS.Key_Escape:
            self.canceled()
            event.accept()
        elif event.key() in (KEYS.Key_Return, KEYS.Key_Enter):
            self.finished()
            event.accept()
        else:
            super().keyPressEvent(event)


def _signature(features):
    digest = hashlib.sha256()
    for feature in sorted(features, key=lambda f: str(f['NWB_ID'])):
        digest.update(json.dumps(feature.attributes(), ensure_ascii=False, default=str).encode('utf-8'))
        digest.update(bytes(feature.geometry().asWkb()))
    return digest.hexdigest()


def add_manual_connections(target, locations, source_crs, household_page, *,
                           label='', station='', house_type=None, year=2026,
                           usage='woonfunctie', passthrough='3 x 25 A',
                           mode='housing', currents=None):
    """Validate before starting the edit; a batch is saved or rolled back."""
    if target is None or not target.isValid() or target.isEditable():
        raise ValueError('Kies een geldige ontwerpstroomlaag en sla bestaande bewerkingen eerst op.')
    if QgsWkbTypes.geometryType(target.wkbType()) != QgsWkbTypes.PointGeometry:
        raise ValueError('De ontwerpstroomlaag moet een puntenlaag zijn.')
    if not source_crs.isValid() or not target.crs().isValid():
        raise ValueError('Kaart en aansluitingenlaag moeten een geldig coördinatenstelsel hebben.')
    locations = list(locations)
    if not locations or len(locations) > 10000:
        raise ValueError('Plaats minimaal één en maximaal 10000 aansluitpunten per toevoeging.')
    residential = has_residential_usage(usage)
    if mode not in ('housing', 'manual', 'later'):
        raise ValueError('Kies hoe de ontwerpstroom wordt bepaald.')
    if mode == 'housing' and (not residential or not house_type):
        raise ValueError('Kies een woningtype, vul handmatig stromen in of kies later bepalen.')
    if not 2022 <= int(year) <= 2200:
        raise ValueError('Kies een gepland nieuwbouwjaar tussen 2022 en 2200.')
    context = household_page._household_context()
    defaults = context[1]
    pass_field = defaults.get('field_passthrough', 'service_connection_type_type')
    if mode == 'housing':
        calculation = QgsVectorLayer('Point', 'nieuwbouwberekening', 'memory')
        calculation.dataProvider().addAttributes([QgsField('Gevonden_Bouwjaar', QVariant.String),
            QgsField('Nieuwbouw', QVariant.String), QgsField(pass_field, QVariant.String)])
        calculation.updateFields()
        sample = QgsFeature(calculation.fields())
        sample['Gevonden_Bouwjaar'], sample['Nieuwbouw'], sample[pass_field] = str(year), '1', passthrough
        currents = household_page._household_currents(calculation, sample, house_type, context)
    elif mode == 'later':
        currents = [0.] * 4
    if currents is None or len(currents) != 4:
        raise ValueError('Vul vier stroomwaarden in.')
    currents = [float(v) for v in currents]
    if any(not math.isfinite(v) or v < 0 for v in currents):
        raise ValueError('Stroomwaarden moeten eindig en minimaal 0 A zijn.')
    transform = QgsCoordinateTransform(source_crs, target.crs(), QgsProject.instance())
    geometries = []
    for location in locations:
        point = QgsPointXY(location)
        if not (math.isfinite(point.x()) and math.isfinite(point.y())):
            raise ValueError('Een van de gekozen locaties is ongeldig.')
        geometry = QgsGeometry.fromPointXY(point)
        geometry.transform(transform)
        if geometry.isEmpty() or not geometry.isGeosValid():
            raise ValueError('Een gekozen locatie kon niet naar de aansluitingenlaag worden omgezet.')
        if QgsWkbTypes.isMultiType(target.wkbType()):
            geometry.convertToMultiType()
        geometries.append(geometry)
    common = {'Nieuwbouw':'1', 'HandmatigNieuwbouw':'1', 'Bron':'Handmatig nieuwbouw (zonder BAG)',
              'Nieuwbouwproject':str(label).strip(), 'Plan_bouwjaar':int(year),
              'BAG_VBO_ID':'', 'BAG_PAND_ID':'', 'BAG_Status':'Niet gekoppeld aan BAG',
              'Station':str(station).strip(), 'Gebruiksdoel':usage,
              defaults.get('field_usage', 'Gebruiksdoel'):usage,
              pass_field:str(passthrough).strip(), 'Gevonden_Woningtype':house_type or '',
              'Gevonden_Bouwjaar':str(year), 'HerstelHandmatig':'1' if mode == 'manual' else '0',
              'OntwerpstroomType':NEW_BUILD_TYPE_3 if residential and house_type and 'appartement' not in str(house_type).casefold() else ''}
    common.update(zip(CURRENT_FIELDS, currents + [max(currents[0], currents[2]), max(currents[1], currents[3])]))
    new_ids = [f'NWB-{uuid4().hex}' for _ in geometries]
    _begin(target)
    try:
        _ensure_fields(target, [*common, 'NWB_ID'], (*CURRENT_FIELDS, 'Plan_bouwjaar'))
        features = []
        for geometry, unique in zip(geometries, new_ids):
            feature = QgsFeature(target.fields())
            feature.setGeometry(geometry)
            for name, val in common.items():
                feature[name] = val
            feature['NWB_ID'] = unique
            features.append(feature)
        if not target.addFeatures(features):
            raise ValueError('De handmatige nieuwbouwaansluitingen konden niet worden toegevoegd.')
        _commit(target)
    except Exception:
        target.rollBack()
        raise
    added = [f for f in target.getFeatures() if str(f['NWB_ID']) in set(new_ids)]
    if len(added) != len(new_ids):
        raise ValueError('Niet alle opgeslagen nieuwbouwpunten konden opnieuw worden gelezen; controleer de laag.')
    target.setCustomProperty(UNDO_PROPERTY, json.dumps({'ids':new_ids, 'signature':_signature(added)}))
    target.selectByIds([f.id() for f in added])
    from .connection_sources import save_project
    save_project()
    return {'added':len(added), 'missing':len(added) if max(currents[0], currents[2]) <= 0 else 0}


def undo_manual_connections(target):
    if target is None or target.isEditable():
        raise ValueError('Kies de oorspronkelijke laag en sla bestaande bewerkingen eerst op.')
    record = str(target.customProperty(UNDO_PROPERTY, ''))
    if not record:
        raise ValueError('Er is geen handmatige toevoeging om ongedaan te maken.')
    record = json.loads(record)
    ids = set(record['ids'])
    added = [f for f in target.getFeatures() if str(f['NWB_ID']) in ids]
    if len(added) != len(ids) or _signature(added) != record['signature']:
        raise ValueError('De toegevoegde punten zijn daarna gewijzigd. Undo zou latere wijzigingen verwijderen.')
    _begin(target)
    try:
        if not target.deleteFeatures([f.id() for f in added]):
            raise ValueError('De handmatige toevoeging kon niet worden teruggedraaid.')
        _commit(target)
    except Exception:
        target.rollBack()
        raise
    target.removeCustomProperty(UNDO_PROPERTY)
    from .connection_sources import save_project
    save_project()
    return len(added)

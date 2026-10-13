"""Station assignments and selected BAG objects in the persistent review layer."""
from __future__ import annotations

import math

from qgis.PyQt.QtCore import QVariant
from qgis.core import (
    QgsCoordinateTransform, QgsFeature, QgsField, QgsGeometry, QgsProject,
    QgsSpatialIndex, QgsVectorLayer, QgsWkbTypes, QgsVariantUtils,
)

CURRENT_FIELDS = (
    "Ontwerpstroom", "Ontwerpstroom kabel", "Opwek ontwerpstroom",
    "Kabel opwek ontwerpstroom", "Hoogste Trafo", "Hoogste Kabel",
)
ADDRESS_FIELDS = {
    "city": ("bronhouder_naam",), "parish": ("woonplaats_naam",),
    "housenumber": ("huisnummer",), "toevoeging": ("huisletter",),
    "zip_code": ("postcode",), "street": ("openbare_ruimte_naam", "straatnaam"),
    "huisnummertoevoeging": ("toevoeging", "huisnummertoevoeging"),
}


def value(feature, *names):
    for name in names:
        index = feature.fields().lookupField(name)
        if index >= 0:
            result = feature[index]
            if result is not None and not QgsVariantUtils.isNull(result):
                return result
    return ""


def text_value(feature, *names):
    return str(value(feature, *names)).strip()


def save_project():
    project = QgsProject.instance()
    project.setDirty(True)
    if project.fileName():
        project.write()


def _begin(layer):
    if layer is None or not layer.isValid():
        raise ValueError("Kies een geldige aansluitingenlaag.")
    if layer.isEditable():
        raise ValueError("Sla bestaande bewerkingen in de aansluitingenlaag eerst op.")
    if not layer.startEditing():
        raise ValueError("De aansluitingenlaag kan niet worden bewerkt.")


def _ensure_fields(layer, names, numeric=()):
    for name in names:
        if layer.fields().lookupField(name) < 0:
            kind = QVariant.Double if name in numeric else QVariant.String
            if not layer.addAttribute(QgsField(name, kind)):
                raise ValueError(f"Kolom '{name}' kon niet worden toegevoegd.")
    layer.updateFields()


def _commit(layer):
    if not layer.commitChanges():
        raise ValueError("Opslaan mislukt: " + "; ".join(layer.commitErrors()))
    layer.updateExtents()
    layer.triggerRepaint()
    save_project()


def assign_station(layer, station):
    station = str(station or "").strip()
    if not station:
        raise ValueError("Vul een stationsnummer in.")
    ids = layer.selectedFeatureIds()
    if not ids:
        raise ValueError("Selecteer eerst aansluitingen op de kaart.")
    _begin(layer)
    try:
        _ensure_fields(layer, ["Station"])
        index = layer.fields().lookupField("Station")
        for fid in ids:
            if not layer.changeAttributeValue(fid, index, station):
                raise ValueError("Het stationsnummer kon niet worden gewijzigd.")
        _commit(layer)
    except Exception:
        layer.rollBack()
        raise
    return len(ids)


def pdok_objects_layer(api_url):
    # The provider follows OGC API pagination and requests only the map extent.
    url = str(api_url).rstrip("/").replace("'", "%27")
    layer = QgsVectorLayer(
        f"url='{url}' typename='verblijfsobject' restrictToRequestBBOX='1'",
        "BAG verblijfsobjecten (PDOK)", "OAPIF",
    )
    if not layer.isValid():
        raise ValueError("PDOK-verblijfsobjecten konden niet worden geladen.")
    layer.setCustomProperty("LSNetontwerp/bag_objects", True)
    return layer


def _address_key(feature, source=False):
    if source:
        parts = [text_value(feature, "postcode"), text_value(feature, "huisnummer"),
                 text_value(feature, "huisletter"), text_value(feature, "toevoeging")]
    else:
        parts = [text_value(feature, "zip_code"), text_value(feature, "housenumber"),
                 text_value(feature, "toevoeging"), text_value(feature, "huisnummertoevoeging")]
    if not parts[0] or not parts[1]:
        return None
    return tuple(part.casefold().replace(" ", "") for part in parts)


def add_selected_objects(source, target, housing, household_page,
                         fallback_type=None, manual_currents=None, station=""):
    """Build first, then add atomically. Keep apartments distinct by BAG ID."""
    selected = list(source.selectedFeatures())
    if not selected:
        raise ValueError("Selecteer eerst verblijfsobjecten in de BAG-laag.")
    if source == target or QgsWkbTypes.geometryType(source.wkbType()) != QgsWkbTypes.PointGeometry:
        raise ValueError("Kies een BAG-verblijfsobjectenlaag met punten.")
    if source.fields().lookupField("identificatie") < 0:
        raise ValueError("De bronlaag mist BAG-identificatie.")
    if target.isEditable():
        raise ValueError("Sla bestaande bewerkingen in de aansluitingenlaag eerst op.")
    if manual_currents is not None:
        if len(manual_currents) != 4 or any(not math.isfinite(float(v)) or float(v) < 0 for v in manual_currents):
            raise ValueError("Vul vier geldige, niet-negatieve stroomwaarden in.")
    existing_ids, existing_addresses = set(), set()
    for feature in target.getFeatures():
        existing_ids.add(text_value(feature, "BAG_VBO_ID"))
        key = _address_key(feature)
        if key:
            existing_addresses.add(key)

    buildings = {}
    spatial = QgsSpatialIndex()
    if housing is not None:
        for feature in housing.getFeatures():
            if feature.hasGeometry():
                buildings[feature.id()] = feature
                spatial.addFeature(feature)
    project = QgsProject.instance()
    to_target = QgsCoordinateTransform(source.crs(), target.crs(), project)
    to_housing = QgsCoordinateTransform(source.crs(), housing.crs(), project) if housing else None
    config = household_page._household_context()
    field_defaults = config[1]
    calculation_layer = QgsVectorLayer("Point", "calculation", "memory")
    calculation_layer.dataProvider().addAttributes([QgsField("Gevonden_Bouwjaar", QVariant.String)])
    calculation_layer.updateFields()
    plans, skipped, missing = [], 0, 0
    for original in selected:
        bag_id = text_value(original, "identificatie")
        address = _address_key(original, True)
        if not bag_id or bag_id in existing_ids or (address and address in existing_addresses):
            skipped += 1
            continue
        geom = QgsGeometry(original.geometry())
        if geom.isEmpty():
            raise ValueError(f"Verblijfsobject {bag_id} heeft geen geometrie.")
        building = None
        if to_housing:
            local = QgsGeometry(geom)
            local.transform(to_housing)
            matches = [buildings[fid] for fid in spatial.intersects(local.boundingBox())
                       if buildings[fid].geometry().intersects(local)]
            # No arbitrary inheritance if multiple overlapping buildings disagree.
            types = {text_value(f, field_defaults.get("field_building_type", "Woningtype")) for f in matches}
            if len(types) == 1 and matches:
                building = sorted(matches, key=lambda f: (f.geometry().area(), f.id()))[0]
        house_type = text_value(building, field_defaults.get("field_building_type", "Woningtype")) if building else ""
        if not house_type and fallback_type is not None:
            house_type = fallback_type
        year = value(building, field_defaults.get("field_build_year", "bouwjaar")) if building else ""
        attrs = {name: value(original, *sources) for name, sources in ADDRESS_FIELDS.items()}
        attrs.update({"BAG_VBO_ID": bag_id, "BAG_PAND_ID": text_value(building, "identificatie") if building else "",
                      "Gebruiksdoel": value(original, "gebruiksdoel"), "Gevonden_Woningtype": house_type,
                      "Gevonden_Bouwjaar": str(year), "Station": station,
                      "service_co": "verblijfsobject",
                      "Bron": "PDOK BAG verblijfsobject", "BAG_Status": value(original, "status")})
        attrs[field_defaults.get("field_usage", "Gebruiksdoel")] = attrs["Gebruiksdoel"]
        inherited = None
        if building and all(building.fields().lookupField(name) >= 0 for name in CURRENT_FIELDS[:4]):
            try:
                inherited = [float(value(building, name)) for name in CURRENT_FIELDS[:4]]
            except (TypeError, ValueError):
                pass
        currents = inherited
        if currents is None and house_type and ("woon" in text_value(original, "gebruiksdoel").casefold() or fallback_type is not None):
            sample = QgsFeature(calculation_layer.fields())
            sample["Gevonden_Bouwjaar"] = str(year)
            currents = household_page._household_currents(calculation_layer, sample, house_type, config)
        if currents is not None and any(not math.isfinite(float(v)) or float(v) < 0 for v in currents):
            currents = None
        if currents is None or max(currents) <= 0:
            currents = manual_currents if manual_currents is not None else [0.0] * 4
        if max(currents[0], currents[2]) <= 0:
            missing += 1
        attrs.update(zip(CURRENT_FIELDS, list(currents) + [max(currents[0], currents[2]), max(currents[1], currents[3])]))
        geom.transform(to_target)
        if QgsWkbTypes.isMultiType(target.wkbType()):
            geom.convertToMultiType()
        plans.append((geom, attrs))
        existing_ids.add(bag_id)
        if address:
            existing_addresses.add(address)
    if not plans:
        return {"added": 0, "skipped": skipped, "missing": 0}
    _begin(target)
    try:
        _ensure_fields(target, list(plans[0][1]), CURRENT_FIELDS)
        features = []
        for geom, attrs in plans:
            feature = QgsFeature(target.fields())
            feature.setGeometry(geom)
            for name, val in attrs.items():
                feature[name] = val
            features.append(feature)
        if not target.addFeatures(features):
            raise ValueError("De nieuwe aansluitingen konden niet worden toegevoegd.")
        _commit(target)
    except Exception:
        target.rollBack()
        raise
    added_ids = {attrs["BAG_VBO_ID"] for _, attrs in plans}
    ids = [f.id() for f in target.getFeatures() if text_value(f, "BAG_VBO_ID") in added_ids]
    target.selectByIds(ids)
    return {"added": len(plans), "skipped": skipped, "missing": missing}

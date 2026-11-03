"""Persist station decisions separately from the original station inventory."""
import json
from pathlib import Path
from uuid import uuid4

from qgis.PyQt.QtCore import QVariant
from qgis.core import (QgsFeature, QgsField, QgsMarkerSymbol, QgsProject,
                       QgsVectorFileWriter, QgsVectorLayer, QgsGeometry)


def apply_input_policy(parameters):
    from .batch_editing import station_rules
    rules = station_rules()
    excluded = {name for name, rule in rules.items()
                if rule.get("type", "").casefold() == "bestaand" and rule.get("status") == "Te verwijderen"}
    if not excluded:
        return parameters
    original = parameters["STATIONS"]
    layer = original if isinstance(original, QgsVectorLayer) else QgsVectorLayer(str(original), "stations", "ogr")
    if not layer.isValid():
        raise ValueError("De bestaande stationslaag kon niet worden geopend.")
    field = parameters.get("STATION_NAAM_VELD", "Station")
    copy = QgsVectorLayer(f"Point?crs={layer.crs().authid()}", "Stations voor ontwerp", "memory")
    copy.dataProvider().addAttributes(list(layer.fields()))
    copy.updateFields()
    features = []
    for source in layer.getFeatures():
        if str(source[field]).strip() in excluded:
            continue
        feature = QgsFeature(copy.fields())
        feature.setAttributes(source.attributes())
        feature.setGeometry(source.geometry())
        features.append(feature)
    if features and not copy.dataProvider().addFeatures(features)[0]:
        raise ValueError("De stationskeuzes konden niet worden toegepast.")
    copy.updateExtents()
    copy.setCustomProperty("LSNetontwerp/source_station_uri", layer.source())
    result = dict(parameters)
    result["STATIONS"] = copy
    return result


def show_retired_stations(rules, directory):
    project = QgsProject.instance()
    old_layers = [layer for layer in project.mapLayers().values()
                  if layer.customProperty("LSNetontwerp/retired_stations", False)]
    records = [(name, rule) for name, rule in rules.items() if rule.get("status") == "Te verwijderen"]
    if records:
        memory = QgsVectorLayer("Point?crs=EPSG:28992", "Stations te verwijderen", "memory")
        memory.dataProvider().addAttributes([QgsField("Station", QVariant.String),
                                           QgsField("Status", QVariant.String), QgsField("KVA", QVariant.Double)])
        memory.updateFields()
        features = []
        for name, rule in records:
            feature = QgsFeature(memory.fields())
            feature.setAttributes([name, "Te verwijderen", rule["kva"]])
            feature.setGeometry(QgsGeometry.fromWkt(f"POINT({rule['x']} {rule['y']})"))
            features.append(feature)
        memory.dataProvider().addFeatures(features)
        memory.updateExtents()
        path = Path(directory) / f"stations_uitfaseren_{uuid4().hex[:12]}.gpkg"
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "stations_uitfaseren"
        result = QgsVectorFileWriter.writeAsVectorFormatV3(memory, str(path), project.transformContext(), options)
        if result[0] != QgsVectorFileWriter.NoError:
            raise ValueError(f"Uitfasering opslaan mislukt: {result[1]}")
        layer = QgsVectorLayer(f"{path}|layername=stations_uitfaseren", "Stations te verwijderen", "ogr")
        if not layer.isValid():
            raise ValueError("De laag met te verwijderen stations kon niet worden geopend.")
        layer.setCustomProperty("LSNetontwerp/retired_stations", True)
        layer.renderer().setSymbol(QgsMarkerSymbol.createSimple({"name": "cross2", "color": "220,30,30,255", "size": "4"}))
        project.addMapLayer(layer)
        reference = next((item for item in project.mapLayers().values() if item.name() == "Stations ontwerp"), None)
        if reference is not None:
            from .project_presentation import place_layer_before
            place_layer_before(layer, reference, project)
    for layer in old_layers:
        project.removeMapLayer(layer.id())

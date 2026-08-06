from __future__ import annotations

import re

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsField,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterField,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
    QgsProject,
    QgsVectorDataProvider,
)


def parse_station_kva(value):
    values = re.findall(r"[-+]?\d+(?:[.,]\d+)?", str(value or "").strip())
    if not values:
        return None
    try:
        parsed = float(values[-1].replace(",", "."))
    except ValueError:
        return None
    return parsed if parsed > 0.0 else None


class StationsSelectieAlgorithm(QgsProcessingAlgorithm):
    """Persistently change or delete selected existing station records."""

    STATIONS = "STATIONS"
    STATIONSNAAM_VELD = "STATIONSNAAM_VELD"
    TRAFO_CAPACITEIT_VELD = "TRAFO_CAPACITEIT_VELD"
    MAX_STROOM_VELD = "MAX_STROOM_VELD"
    NIEUWE_CAPACITEIT_KVA = "NIEUWE_CAPACITEIT_KVA"
    VERWIJDEREN = "VERWIJDEREN"
    AANTAL = "AANTAL"

    def tr(self, text):
        return QCoreApplication.translate("LSNetontwerp", text)

    def createInstance(self):
        return StationsSelectieAlgorithm()

    def name(self):
        return "bestaande_stations_selectie"

    def displayName(self):
        return self.tr("Bestaande stations aanpassen/verwijderen (selectie)")

    def group(self):
        return self.tr("LS Netontwerp")

    def groupId(self):
        return "ls_netontwerp"

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    @classmethod
    def _default_layer(cls):
        project = QgsProject.instance()
        if project is None:
            return None
        ordered = list(project.layerTreeRoot().layerOrder())
        if not ordered:
            ordered = list(project.mapLayers().values())
        candidates = []
        for order, layer in enumerate(ordered):
            if not hasattr(layer, "fields"):
                continue
            field_names = {field.name().casefold() for field in layer.fields()}
            has_source_fields = (
                "trafo_power" in field_names and "station" in field_names
            )
            is_review = bool(
                layer.customProperty("LSNetontwerp/review_station_layer", False)
            )
            if has_source_fields or is_review:
                candidates.append(
                    (
                        -int(is_review) * 10,
                        -int(layer.selectedFeatureCount() > 0),
                        order,
                        layer,
                    )
                )
        return min(candidates, key=lambda item: item[:3])[3] if candidates else None

    def preprocessParameters(self, parameters):
        prepared = dict(super().preprocessParameters(parameters))
        if prepared.get(self.STATIONS) in (None, ""):
            layer = self._default_layer()
            if layer is not None:
                prepared[self.STATIONS] = layer.id()
        return prepared

    def initAlgorithm(self, config=None):
        default_layer = self._default_layer()
        layer_parameter = QgsProcessingParameterVectorLayer(
            self.STATIONS,
            self.tr("Bestaande stations (gebruik huidige selectie)"),
            [QgsProcessing.TypeVectorPoint],
        )
        if default_layer is not None:
            layer_parameter.setDefaultValue(default_layer.id())
        self.addParameter(layer_parameter)
        for key, label, default in (
            (self.STATIONSNAAM_VELD, "Kolom stationsnaam", "Station"),
            (
                self.TRAFO_CAPACITEIT_VELD,
                "Kolom trafocapaciteit",
                "trafo_power",
            ),
            (self.MAX_STROOM_VELD, "Kolom maximale ontwerpstroom", "Max_A"),
        ):
            parameter = QgsProcessingParameterField(
                key,
                self.tr(label),
                parentLayerParameterName=self.STATIONS,
                type=QgsProcessingParameterField.Any,
                defaultValue=default,
            )
            self.addParameter(parameter)
        selected = list(default_layer.selectedFeatures()) if default_layer else []
        selected_capacity = None
        if default_layer is not None:
            field_name = str(
                default_layer.customProperty(
                    "LSNetontwerp/station_capacity_field", "trafo_power"
                )
            )
            field_index = default_layer.fields().lookupField(field_name)
            if field_index >= 0:
                values = [
                    parse_station_kva(feature[field_index]) for feature in selected
                ]
                values = [value for value in values if value is not None]
                if values:
                    selected_capacity = max(values)
        self.addParameter(
            QgsProcessingParameterNumber(
                self.NIEUWE_CAPACITEIT_KVA,
                self.tr("Nieuwe trafocapaciteit (kVA)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=selected_capacity or 630.0,
                minValue=0.001,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.VERWIJDEREN,
                self.tr("Geselecteerde stations definitief verwijderen"),
                defaultValue=False,
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                self.AANTAL, self.tr("Aantal aangepaste of verwijderde stations")
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsVectorLayer(parameters, self.STATIONS, context)
        if layer is None or not layer.isValid():
            raise QgsProcessingException("Kies de bestaande stationslaag")
        selected_ids = [int(value) for value in layer.selectedFeatureIds()]
        if not selected_ids:
            raise QgsProcessingException(
                "Selecteer eerst één of meer bestaande stations op de kaart"
            )
        if layer.isEditable():
            raise QgsProcessingException(
                "De stationslaag staat al in bewerkingsmodus. Sla die bewerkingen eerst op."
            )
        provider = layer.dataProvider()
        deleting = self.parameterAsBool(parameters, self.VERWIJDEREN, context)
        if deleting:
            if not provider.capabilities() & QgsVectorDataProvider.DeleteFeatures:
                raise QgsProcessingException("De stationslaag ondersteunt verwijderen niet")
            if not provider.deleteFeatures(selected_ids):
                raise QgsProcessingException(
                    "De geselecteerde stations konden niet worden verwijderd"
                )
            action = "verwijderd"
        else:
            name_field = self.parameterAsString(
                parameters, self.STATIONSNAAM_VELD, context
            )
            capacity_field = self.parameterAsString(
                parameters, self.TRAFO_CAPACITEIT_VELD, context
            )
            max_field = self.parameterAsString(
                parameters, self.MAX_STROOM_VELD, context
            )
            indices = {
                "naam": layer.fields().lookupField(name_field),
                "capaciteit": layer.fields().lookupField(capacity_field),
                "max": layer.fields().lookupField(max_field),
            }
            missing = [name for name, index in indices.items() if index < 0]
            if missing:
                raise QgsProcessingException(
                    "De stationslaag mist gekozen kolom(men): " + ", ".join(missing)
                )
            capacity = self.parameterAsDouble(
                parameters, self.NIEUWE_CAPACITEIT_KVA, context
            )
            if capacity <= 0.0:
                raise QgsProcessingException("Trafocapaciteit moet positief zijn")
            maximum_current = float(capacity) / 0.23 / 3.0
            capacity_is_numeric = layer.fields()[indices["capaciteit"]].isNumeric()
            capacity_value = float(capacity) if capacity_is_numeric else f"{capacity:g}"
            changes = {
                feature_id: {
                    indices["capaciteit"]: capacity_value,
                    indices["max"]: maximum_current,
                }
                for feature_id in selected_ids
            }
            if not provider.capabilities() & QgsVectorDataProvider.ChangeAttributeValues:
                raise QgsProcessingException("De stationslaag is niet schrijfbaar")
            if not provider.changeAttributeValues(changes):
                raise QgsProcessingException(
                    "De trafocapaciteit kon niet worden opgeslagen"
                )
            action = (
                f"ingesteld op {capacity:g} kVA; Max_A = "
                f"{maximum_current:.1f} A"
            )
        layer.updateFields()
        layer.removeSelection()
        layer.triggerRepaint()
        project = QgsProject.instance()
        project.setDirty(True)
        if project.fileName():
            project.write()
        feedback.pushInfo(f"{len(selected_ids)} station(s) {action}.")
        return {self.AANTAL: len(selected_ids)}

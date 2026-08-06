from __future__ import annotations

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputNumber,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
    QgsProject,
    QgsVectorDataProvider,
)


class HoogsteWaardenSelectieAlgorithm(QgsProcessingAlgorithm):
    """Persistently change Hoogste Trafo/Kabel for selected connections."""

    AANSLUITINGEN = "AANSLUITINGEN"
    WIJZIG_TRAFO = "WIJZIG_TRAFO"
    HOOGSTE_TRAFO = "HOOGSTE_TRAFO"
    WIJZIG_KABEL = "WIJZIG_KABEL"
    HOOGSTE_KABEL = "HOOGSTE_KABEL"
    AANTAL = "AANTAL"

    def tr(self, text):
        return QCoreApplication.translate("LSNetontwerp", text)

    def createInstance(self):
        return HoogsteWaardenSelectieAlgorithm()

    def name(self):
        return "hoogste_trafo_kabel_selectie"

    def displayName(self):
        return self.tr("Hoogste trafo en kabel aanpassen (selectie)")

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
            if {"hoogste trafo", "hoogste kabel"}.issubset(field_names):
                candidates.append(
                    (
                        int(layer.customProperty("LSNetontwerp/review_current_layer", 0))
                        * -10,
                        -int(layer.selectedFeatureCount() > 0),
                        order,
                        layer,
                    )
                )
        return min(candidates, key=lambda item: item[:3])[3] if candidates else None

    def preprocessParameters(self, parameters):
        prepared = dict(super().preprocessParameters(parameters))
        if prepared.get(self.AANSLUITINGEN) in (None, ""):
            layer = self._default_layer()
            if layer is not None:
                prepared[self.AANSLUITINGEN] = layer.id()
        return prepared

    def initAlgorithm(self, config=None):
        default_layer = self._default_layer()
        layer_parameter = QgsProcessingParameterVectorLayer(
            self.AANSLUITINGEN,
            self.tr("LS-aansluitingen (gebruik huidige selectie)"),
            [QgsProcessing.TypeVectorPoint],
        )
        if default_layer is not None:
            layer_parameter.setDefaultValue(default_layer.id())
        self.addParameter(layer_parameter)

        selected = list(default_layer.selectedFeatures()) if default_layer else []

        def selected_default(field_name, fallback):
            values = []
            for feature in selected:
                try:
                    value = float(feature[field_name])
                except (KeyError, TypeError, ValueError):
                    continue
                values.append(value)
            return max(values) if values else fallback

        self.addParameter(
            QgsProcessingParameterBoolean(
                self.WIJZIG_TRAFO,
                self.tr("Hoogste Trafo aanpassen"),
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.HOOGSTE_TRAFO,
                self.tr("Nieuwe Hoogste Trafo (A)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=selected_default("Hoogste Trafo", 0.0),
                minValue=0.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.WIJZIG_KABEL,
                self.tr("Hoogste Kabel aanpassen"),
                defaultValue=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.HOOGSTE_KABEL,
                self.tr("Nieuwe Hoogste Kabel (A)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=selected_default("Hoogste Kabel", 0.0),
                minValue=0.0,
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                self.AANTAL, self.tr("Aantal aangepaste aansluitingen")
            )
        )

    def processAlgorithm(self, parameters, context, feedback):
        layer = self.parameterAsVectorLayer(parameters, self.AANSLUITINGEN, context)
        if layer is None or not layer.isValid():
            raise QgsProcessingException("Kies de ontwerpstroomlaag uit het werkproject")
        selected_ids = list(layer.selectedFeatureIds())
        if not selected_ids:
            raise QgsProcessingException(
                "Selecteer eerst één of meer LS-aansluitingen op de kaart"
            )
        if layer.isEditable():
            raise QgsProcessingException(
                "De laag staat al in bewerkingsmodus. Sla die bewerkingen eerst op."
            )
        trafo_index = layer.fields().lookupField("Hoogste Trafo")
        cable_index = layer.fields().lookupField("Hoogste Kabel")
        if trafo_index < 0 or cable_index < 0:
            raise QgsProcessingException(
                "De gekozen laag mist Hoogste Trafo en/of Hoogste Kabel"
            )
        change_trafo = self.parameterAsBool(parameters, self.WIJZIG_TRAFO, context)
        change_cable = self.parameterAsBool(parameters, self.WIJZIG_KABEL, context)
        if not change_trafo and not change_cable:
            raise QgsProcessingException("Kies ten minste één waarde om aan te passen")
        trafo_value = self.parameterAsDouble(parameters, self.HOOGSTE_TRAFO, context)
        cable_value = self.parameterAsDouble(parameters, self.HOOGSTE_KABEL, context)
        changes = {}
        for feature_id in selected_ids:
            fields = {}
            if change_trafo:
                fields[trafo_index] = float(trafo_value)
            if change_cable:
                fields[cable_index] = float(cable_value)
            changes[int(feature_id)] = fields
        provider = layer.dataProvider()
        if not provider.capabilities() & QgsVectorDataProvider.ChangeAttributeValues:
            raise QgsProcessingException("De ontwerpstroomlaag is niet schrijfbaar")
        if not provider.changeAttributeValues(changes):
            raise QgsProcessingException("De geselecteerde waarden konden niet worden opgeslagen")
        layer.updateFields()
        layer.triggerRepaint()
        project = QgsProject.instance()
        project.setDirty(True)
        if project.fileName():
            project.write()
        feedback.pushInfo(
            f"{len(selected_ids)} aansluiting(en) blijvend aangepast; "
            f"Hoogste Trafo={'ongewijzigd' if not change_trafo else f'{trafo_value:.3f} A'}, "
            f"Hoogste Kabel={'ongewijzigd' if not change_cable else f'{cable_value:.3f} A'}."
        )
        return {self.AANTAL: len(selected_ids)}

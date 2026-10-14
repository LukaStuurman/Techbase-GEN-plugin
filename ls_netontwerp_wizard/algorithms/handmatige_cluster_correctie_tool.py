from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

from qgis.PyQt.QtCore import QCoreApplication, QVariant
from qgis.core import (
    QgsCategorizedSymbolRenderer,
    QgsFeature,
    QgsApplication,
    QgsField,
    QgsFields,
    QgsGeometry,
    QgsLayoutItemAttributeTable,
    QgsLayoutItemLegend,
    QgsLayoutItemMap,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputFile,
    QgsProcessingOutputNumber,
    QgsProcessingOutputString,
    QgsProcessingParameterBoolean,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterString,
    QgsProcessingParameterVectorLayer,
    QgsProject,
    QgsRendererCategory,
    QgsVectorDataProvider,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsWkbTypes,
)


class HandmatigeClusterCorrectieAlgorithm(QgsProcessingAlgorithm):
    """Move selected connections and rebuild every dependent cluster layer."""

    AANSLUITINGEN = "AANSLUITINGEN"
    STATIONS = "STATIONS"
    GEBIEDEN = "GEBIEDEN"
    KABELROUTES = "KABELROUTES"
    SLEUVEN = "SLEUVEN"
    PLANGEBIED = "PLANGEBIED"
    HELE_BRONCLUSTER_VERWIJDEREN = "HELE_BRONCLUSTER_VERWIJDEREN"
    ALLE_ROUTES_VERVERSEN = "ALLE_ROUTES_VERVERSEN"
    ALLEEN_GESELECTEERDE_ROUTES = "ALLEEN_GESELECTEERDE_ROUTES"
    ROUTE_CLUSTERS = "ROUTE_CLUSTERS"
    ALLES_TOESTAAN = "ALLES_TOESTAAN"
    CONTROLE_MAX_ONTWERPSTROOM = "CONTROLE_MAX_ONTWERPSTROOM"
    CONTROLE_MAX_KABELLENGTE = "CONTROLE_MAX_KABELLENGTE"
    CONTROLE_ROUTES_ANDERE_CLUSTERS = "CONTROLE_ROUTES_ANDERE_CLUSTERS"
    CONTROLE_GEDEELDE_ROUTES_VERTAKKINGEN = (
        "CONTROLE_GEDEELDE_ROUTES_VERTAKKINGEN"
    )
    MAX_ROUTE_M = "MAX_ROUTE_M"
    KNOOP_TOLERANTIE_M = "KNOOP_TOLERANTIE_M"
    BACKUPMAP = "BACKUPMAP"

    AANSLUITINGEN_UIT = "AANSLUITINGEN_UIT"
    STATIONS_UIT = "STATIONS_UIT"
    GEBIEDEN_UIT = "GEBIEDEN_UIT"
    KABELROUTES_UIT = "KABELROUTES_UIT"
    BACKUP_GPKG = "BACKUP_GPKG"
    RESULTAAT_GPKG = "RESULTAAT_GPKG"
    VERPLAATST_AANTAL = "VERPLAATST_AANTAL"
    DOELSTATION = "DOELSTATION"
    BIJGEWERKTE_LAGEN = "BIJGEWERKTE_LAGEN"

    def tr(self, text):
        return QCoreApplication.translate("HandmatigeClusterCorrectie", text)

    def createInstance(self):
        return HandmatigeClusterCorrectieAlgorithm()

    def name(self):
        return "handmatige_clustercorrectie_selectie"

    def displayName(self):
        return self.tr("Handmatige clustercorrectie (selectie naar station)")

    def group(self):
        return self.tr("Netontwerp")

    def groupId(self):
        return "netontwerp"

    def flags(self):
        # The algorithm changes layers which are owned by the open project.
        # QGIS/OGR providers must not be mutated from a Processing task thread.
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def shortHelpString(self):
        return self.tr(
            """
Verplaatst geselecteerde LS-aansluitingen naar precies één geselecteerd
doelstation en past de bestaande resultaatlagen rechtstreeks aan.

Werkwijze:
1. Selecteer in 'Aansluitingen geclusterd' alle aansluitingen die samen moeten
   verhuizen. Selecteer bij voorkeur een volledige kabeltak of een volledig
   gebouw.
2. Selecteer in 'Stations ontwerp' precies één doelstation.
3. Kies de vier resultaatlagen, 'Sleuven geknipt/genood' en indien aanwezig
   'Plangebied'. Start de tool. De gekozen resultaatlagen worden na alle
   controles in dezelfde bestanden aangepast; er worden dus geen dubbele
   kaartlagen toegevoegd.

Met 'Hele broncluster samenvoegen en verwijderen' hoeft slechts één aansluiting
uit de broncluster geselecteerd te zijn. Alle aansluitingen uit die cluster
verhuizen dan naar het doelstation; het oude station, gebied en kabelrouterecord
worden verwijderd. 'ALLES TOESTAAN' schakelt de vier veiligheidscontroles als
één hoofdschakelaar uit.

De tool rekent de exclusieve kabelroutes en aaneengesloten clustergebieden
opnieuw uit. Met een plangebied worden sleuven en nieuwe clustergrenzen daar
hard op begrensd; aansluitingen buiten het plangebied worden geweigerd. Ook
Cluster, Stat_type, Stat_KVA, Max_A, Clust_A, Benut_pct,
Route_m en Snap_m bij aansluitingen en alle belasting-, aantal-, capaciteits-,
benuttings- en routestatistieken bij stations, gebieden en kabelroutes worden
bijgewerkt.

Met 'Alle clusterroutes verversen zonder aansluitingen te verplaatsen' is geen
kaartselectie nodig. Alle bestaande Cluster-toewijzingen blijven dan gelijk,
maar de kortste exclusieve routes worden volledig opnieuw gezocht. Zo kan een
later toegevoegde en genode sleuf een langere bestaande route vervangen.

Voor de bronlagen worden gewijzigd maakt de tool een GeoPackage-back-up en een
GeoPackage met het nieuwe resultaat. De correctie wordt geweigerd als de
stationcapaciteit wordt overschreden, een route langer wordt dan de ingestelde
grens, clusters kabeldelen zouden delen of de selectie geen volledige
kabelverbonden tak vormt. Bij zo'n melding blijven de bronlagen ongewijzigd.

De vier veiligheidscontroles staan standaard afzonderlijk aan. Per uitvoering
kunnen de controles op maximale ontwerpstroom, maximale kabellengte, routes
door/over andere clusters en gedeelde kabelroutes/onvolledige vertakkingen
onafhankelijk worden uitgezet. Technische basiscontroles op geldige lagen, CRS,
bronvelden, geometrie en een bruikbaar kabelnet blijven altijd actief.

De zes invoerlagen worden automatisch op hun vaste laagnaam ingevuld. Als
dezelfde namen meerdere keren voorkomen, kiest de tool bij voorkeur de zes
blijvende lagen uit hetzelfde GeoPackage boven tijdelijke of losse lagen.

De bestaande projectlagen verschijnen bewust niet opnieuw als vectoruitvoer in
het resultatenscherm. Daardoor kan na een uitvoering veilig op 'Terug' worden
geklikt en kan de tool opnieuw worden gestart. Alleen de back-up,
resultaatkopie en samenvatting worden als uitvoer gemeld.

Sla eventuele open bewerkingen in deze lagen eerst op. Gebruik bij voorkeur de
uitvoerlaag 'Sleuven geknipt/genood' van de clustering; zet de knooptolerantie
dan op 0 meter.
"""
        ).strip()

    @classmethod
    def _project_layer_defaults(cls):
        """Find the five matching result layers, preferably from one GPKG."""
        expected_names = {
            cls.AANSLUITINGEN: "aansluitingen geclusterd",
            cls.STATIONS: "stations ontwerp",
            cls.GEBIEDEN: "clustergebieden",
            cls.KABELROUTES: "kabelroutes per cluster",
            cls.SLEUVEN: "sleuven geknipt/genood",
            cls.PLANGEBIED: "plangebied",
        }
        project = QgsProject.instance()
        if project is None:
            return {}
        project_layers = list(project.layerTreeRoot().layerOrder())
        if not project_layers:
            project_layers = list(project.mapLayers().values())

        records = []
        for order, layer in enumerate(project_layers):
            folded_name = layer.name().strip().casefold()
            parameter_name = next(
                (
                    key
                    for key, expected in expected_names.items()
                    if folded_name == expected
                ),
                None,
            )
            if parameter_name is None:
                continue
            source_text = layer.source().split("|", 1)[0]
            source_path = Path(source_text)
            if source_path.suffix.casefold() == ".gpkg":
                source_group = str(source_path.resolve()).casefold()
                is_geopackage = True
            elif source_path.suffix:
                source_group = str(source_path.resolve().parent).casefold()
                is_geopackage = False
            else:
                source_group = source_text.casefold()
                is_geopackage = False
            records.append(
                {
                    "parameter": parameter_name,
                    "layer": layer,
                    "group": source_group,
                    "temporary": bool(layer.isTemporary()),
                    "geopackage": is_geopackage,
                    "order": order,
                }
            )
        if not records:
            return {}

        group_scores = {}
        for record in records:
            score = group_scores.setdefault(
                record["group"],
                {
                    "parameters": set(),
                    "persistent": 0,
                    "geopackage": 0,
                    "first_order": record["order"],
                },
            )
            score["parameters"].add(record["parameter"])
            score["persistent"] += int(not record["temporary"])
            score["geopackage"] += int(record["geopackage"])
            score["first_order"] = min(score["first_order"], record["order"])
        best_group = max(
            group_scores,
            key=lambda group: (
                len(group_scores[group]["parameters"]),
                group_scores[group]["persistent"],
                group_scores[group]["geopackage"],
                -group_scores[group]["first_order"],
            ),
        )

        defaults = {}
        for parameter_name in expected_names:
            candidates = [
                record
                for record in records
                if record["parameter"] == parameter_name
                and record["group"] == best_group
            ]
            if not candidates:
                candidates = [
                    record
                    for record in records
                    if record["parameter"] == parameter_name
                ]
            if candidates:
                selected = min(
                    candidates,
                    key=lambda record: (
                        record["temporary"],
                        not record["geopackage"],
                        record["order"],
                    ),
                )
                defaults[parameter_name] = selected["layer"].id()
        return defaults

    def preprocessParameters(self, parameters):
        prepared = dict(super().preprocessParameters(parameters))
        defaults = self._project_layer_defaults()
        for parameter_name, layer_id in defaults.items():
            if prepared.get(parameter_name) in (None, ""):
                prepared[parameter_name] = layer_id
        return prepared

    def initAlgorithm(self, config=None):
        layer_defaults = self._project_layer_defaults()
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.AANSLUITINGEN,
                self.tr("Aansluitingen geclusterd (selecteer te verplaatsen punten)"),
                [QgsProcessing.TypeVectorPoint],
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.STATIONS,
                self.tr("Stations ontwerp (selecteer precies één doelstation)"),
                [QgsProcessing.TypeVectorPoint],
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.GEBIEDEN,
                self.tr("Clustergebieden"),
                [QgsProcessing.TypeVectorPolygon],
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.KABELROUTES,
                self.tr("Kabelroutes per cluster"),
                [QgsProcessing.TypeVectorLine],
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.SLEUVEN,
                self.tr("Sleuven geknipt/genood"),
                [QgsProcessing.TypeVectorLine],
            )
        )
        self.addParameter(
            QgsProcessingParameterVectorLayer(
                self.PLANGEBIED,
                self.tr("Plangebied (optioneel; automatisch gekozen op naam)"),
                [QgsProcessing.TypeVectorPolygon],
                optional=True,
            )
        )
        for parameter_name, layer_id in layer_defaults.items():
            parameter = self.parameterDefinition(parameter_name)
            if parameter is not None:
                parameter.setDefaultValue(layer_id)
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.HELE_BRONCLUSTER_VERWIJDEREN,
                self.tr(
                    "Hele broncluster samenvoegen en verwijderen "
                    "(selecteer minimaal één aansluiting uit de broncluster)"
                ),
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ALLE_ROUTES_VERVERSEN,
                self.tr(
                    "Alle clusterroutes verversen zonder aansluitingen te verplaatsen"
                ),
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ALLEEN_GESELECTEERDE_ROUTES,
                self.tr(
                    "Alleen geselecteerde routes/stations verversen"
                ),
                defaultValue=False,
            )
        )
        self.addParameter(
            QgsProcessingParameterString(
                self.ROUTE_CLUSTERS,
                self.tr(
                    "Extra clusternamen voor routeverversing (komma-gescheiden)"
                ),
                defaultValue="",
                optional=True,
            )
        )
        self.addParameter(
            QgsProcessingParameterBoolean(
                self.ALLES_TOESTAAN,
                self.tr("ALLES TOESTAAN: alle vier veiligheidscontroles uitschakelen"),
                defaultValue=False,
            )
        )
        safety_parameters = (
            (
                self.CONTROLE_MAX_ONTWERPSTROOM,
                "Maximale ontwerpstroom van het station bewaken",
            ),
            (
                self.CONTROLE_MAX_KABELLENGTE,
                "Maximale kabellengte bewaken",
            ),
            (
                self.CONTROLE_ROUTES_ANDERE_CLUSTERS,
                "Routes door/over andere clusters blokkeren",
            ),
            (
                self.CONTROLE_GEDEELDE_ROUTES_VERTAKKINGEN,
                "Gedeelde kabelroutes en onvolledige vertakkingen blokkeren",
            ),
        )
        for parameter_name, description in safety_parameters:
            self.addParameter(
                QgsProcessingParameterBoolean(
                    parameter_name,
                    self.tr(description),
                    defaultValue=True,
                )
            )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.MAX_ROUTE_M,
                self.tr("Maximale kabelroute station-aansluiting (m)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=850.0,
                minValue=1.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterNumber(
                self.KNOOP_TOLERANTIE_M,
                self.tr("Knooptolerantie (0 bij reeds geknipte/genode sleuven)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=0.0,
                minValue=0.0,
                maxValue=25.0,
            )
        )
        self.addParameter(
            QgsProcessingParameterFolderDestination(
                self.BACKUPMAP,
                self.tr("Map voor back-up en resultaatkopie"),
                defaultValue=QgsProcessing.TEMPORARY_OUTPUT,
            )
        )

        self.addOutput(
            QgsProcessingOutputFile(self.BACKUP_GPKG, self.tr("Back-up vóór correctie"))
        )
        self.addOutput(
            QgsProcessingOutputFile(
                self.RESULTAAT_GPKG,
                self.tr("Resultaatkopie na correctie"),
            )
        )
        self.addOutput(
            QgsProcessingOutputNumber(
                self.VERPLAATST_AANTAL,
                self.tr("Aantal verplaatste aansluitingen"),
            )
        )
        self.addOutput(
            QgsProcessingOutputString(self.DOELSTATION, self.tr("Doelstation"))
        )
        self.addOutput(
            QgsProcessingOutputString(
                self.BIJGEWERKTE_LAGEN,
                self.tr("Rechtstreeks bijgewerkte projectlagen"),
            )
        )

    @staticmethod
    def _worker_paths():
        library_dir = Path(__file__).resolve().parent / "laagspanning_clustering_lib"
        runner_path = library_dir / "handmatige_correctie_runner.py"
        engine_path = library_dir / "maak_clustering_engine.py"
        for required_path in (runner_path, engine_path):
            if not required_path.exists():
                raise QgsProcessingException(
                    f"Onderdeel van de rekenkern ontbreekt: {required_path}"
                )
        return runner_path

    @staticmethod
    def _python_command():
        """Return a QGIS Python command, also from embedded QGIS Desktop."""
        executable = Path(sys.executable)
        if "python" in executable.stem.casefold():
            return [str(executable)]

        candidates = []
        osgeo_root = os.environ.get("OSGEO4W_ROOT")
        if osgeo_root:
            candidates.append(Path(osgeo_root) / "bin" / "python-qgis.bat")
        prefix = Path(QgsApplication.prefixPath())
        if len(prefix.parents) >= 2:
            candidates.append(prefix.parents[1] / "bin" / "python-qgis.bat")
        for candidate in candidates:
            if candidate.exists():
                return [str(candidate)]
        raise QgsProcessingException(
            "De aparte QGIS-Pythonrekenomgeving is niet gevonden."
        )

    @staticmethod
    def _validate_fields(layer, required, description):
        existing = {field.name().casefold() for field in layer.fields()}
        missing = [name for name in required if name.casefold() not in existing]
        if missing:
            raise QgsProcessingException(
                f"{description} mist verplichte velden: {', '.join(missing)}"
            )

    @staticmethod
    def _write_layer_snapshot(layer, path, layer_name, context):
        fields = QgsFields(layer.fields())
        if fields.indexFromName("__src_fid") >= 0:
            raise QgsProcessingException(
                f"Laag {layer.name()} bevat al het tijdelijke veld __src_fid"
            )
        fields.append(QgsField("__src_fid", QVariant.LongLong))
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = layer_name
        options.fileEncoding = "UTF-8"
        if Path(path).exists():
            # Reuse one temporary GeoPackage for every worker input. This
            # avoids repeatedly creating and opening six separate databases.
            options.actionOnExistingFile = (
                QgsVectorFileWriter.CreateOrOverwriteLayer
            )
        writer = QgsVectorFileWriter.create(
            str(path),
            fields,
            layer.wkbType(),
            layer.crs(),
            context.transformContext(),
            options,
        )
        if writer is None or writer.hasError() != QgsVectorFileWriter.NoError:
            message = "onbekende schrijffout" if writer is None else writer.errorMessage()
            raise QgsProcessingException(
                f"Tijdelijke kopie van {layer.name()} mislukt: {message}"
            )
        try:
            for feature in layer.getFeatures():
                output_feature = QgsFeature(fields)
                output_feature.setGeometry(feature.geometry())
                output_feature.setAttributes(
                    [*feature.attributes(), int(feature.id())]
                )
                if not writer.addFeature(output_feature):
                    raise QgsProcessingException(
                        f"Tijdelijke kopie van {layer.name()} is onvolledig"
                    )
        finally:
            del writer

    def _apply_result_layer(
        self,
        layer,
        result_path,
        result_layer_name,
        change_geometry=False,
        delete_missing=False,
        preserve_empty_geometry=False,
    ):
        if layer.isEditable():
            raise QgsProcessingException(
                f"Laag '{layer.name()}' staat nog in bewerkingsmodus. "
                "Sla de bewerkingen op en start de correctie opnieuw."
            )
        provider = layer.dataProvider()
        selected_ids = list(layer.selectedFeatureIds())
        capabilities = provider.capabilities()
        if not capabilities & QgsVectorDataProvider.ChangeAttributeValues:
            raise QgsProcessingException(
                f"Laag '{layer.name()}' ondersteunt geen attribuutwijzigingen."
            )
        if change_geometry and not capabilities & QgsVectorDataProvider.ChangeGeometries:
            raise QgsProcessingException(
                f"Laag '{layer.name()}' ondersteunt geen geometriewijzigingen."
            )
        if delete_missing and not capabilities & QgsVectorDataProvider.DeleteFeatures:
            raise QgsProcessingException(
                f"Laag '{layer.name()}' ondersteunt het verwijderen van een cluster niet."
            )

        field_lookup = {
            field.name().casefold(): index
            for index, field in enumerate(layer.fields())
        }
        primary_key_fields = set(provider.pkAttributeIndexes())
        result_layer = QgsVectorLayer(
            f"{result_path}|layername={result_layer_name}",
            f"tijdelijk_{result_layer_name}",
            "ogr",
        )
        if not result_layer.isValid():
            raise QgsProcessingException(
                f"Resultaatlaag '{result_layer_name}' kan niet worden gelezen."
            )
        source_fid_index = result_layer.fields().lookupField("Bron_FID")
        if source_fid_index < 0:
            raise QgsProcessingException(
                f"Resultaatlaag '{result_layer_name}' mist veld Bron_FID."
            )
        result_fields = {
            field.name().casefold(): index
            for index, field in enumerate(result_layer.fields())
            if field.name().casefold() != "bron_fid"
        }
        common_fields = [
            (field_index, result_fields[field_name])
            for field_name, field_index in field_lookup.items()
            if field_name in result_fields and field_index not in primary_key_fields
            and layer.fields().fieldOrigin(field_index) == QgsFields.OriginProvider
        ]
        attribute_changes = {}
        geometry_changes = {}
        result_source_ids = set()
        for result_feature in result_layer.getFeatures():
            feature_id = int(result_feature.attribute(source_fid_index))
            result_source_ids.add(feature_id)
            attribute_changes[feature_id] = {
                field_index: result_feature.attribute(result_field_index)
                for field_index, result_field_index in common_fields
            }
            if change_geometry:
                qgis_geometry = QgsGeometry(result_feature.geometry())
                if preserve_empty_geometry and (
                    qgis_geometry.isNull() or qgis_geometry.isEmpty()
                ):
                    # Never erase a visible saved route because a recalculation
                    # unexpectedly returned zero line parts.
                    continue
                if not qgis_geometry.isNull() and not qgis_geometry.isEmpty():
                    if (
                        QgsWkbTypes.isMultiType(layer.wkbType())
                        and not QgsWkbTypes.isMultiType(qgis_geometry.wkbType())
                    ):
                        qgis_geometry.convertToMultiType()
                geometry_changes[feature_id] = qgis_geometry

        if delete_missing:
            delete_ids = {
                int(feature.id())
                for feature in layer.getFeatures()
                if int(feature.id()) not in result_source_ids
            }
            if delete_ids and not provider.deleteFeatures(sorted(delete_ids)):
                provider_error = provider.lastError() or "; ".join(
                    str(error) for error in provider.errors()
                )
                raise QgsProcessingException(
                    f"Verwijderen van de broncluster uit '{layer.name()}' is mislukt. "
                    f"Gebruik de gemaakte back-up om te herstellen. {provider_error}"
                )
            selected_ids = [value for value in selected_ids if value not in delete_ids]

        if attribute_changes and not provider.changeAttributeValues(attribute_changes):
            provider_error = provider.lastError() or "; ".join(
                str(error) for error in provider.errors()
            )
            raise QgsProcessingException(
                f"Bijwerken van attributen in '{layer.name()}' is mislukt. "
                f"Gebruik de gemaakte back-up om te herstellen. {provider_error}"
            )
        if (
            change_geometry
            and geometry_changes
            and not provider.changeGeometryValues(geometry_changes)
        ):
            provider_error = provider.lastError() or "; ".join(
                str(error) for error in provider.errors()
            )
            raise QgsProcessingException(
                f"Bijwerken van geometrie in '{layer.name()}' is mislukt. "
                f"Gebruik de gemaakte back-up om te herstellen. {provider_error}"
            )
        # Release the OGR update handle before a sibling layer in the same
        # GeoPackage is changed. Unlike layer.reload(), forceReload() does not
        # rebuild the entire layer or disturb the user's selection.
        provider.forceReload()
        layer.selectByIds(selected_ids)
        layer.updateExtents()
        layer.triggerRepaint()

    @staticmethod
    def _ensure_integer_field(layer, field_name):
        index = layer.fields().lookupField(field_name)
        if index >= 0 and layer.fields().fieldOrigin(index) != QgsFields.OriginExpression:
            return
        provider = layer.dataProvider()
        if not provider.capabilities() & QgsVectorDataProvider.AddAttributes:
            raise QgsProcessingException(
                f"Laag '{layer.name()}' kan veld {field_name} niet toevoegen."
            )
        if not provider.addAttributes([QgsField(field_name, QVariant.Int)]):
            raise QgsProcessingException(
                f"Veld {field_name} kon niet aan '{layer.name()}' worden toegevoegd."
            )
        if index >= 0:
            layer.removeExpressionField(index)
        layer.updateFields()

    @staticmethod
    def _refresh_project_layout_after_correction(
        connections_layer, stations_layer, areas_layer, routes_layer
    ):
        """Synchronize the one-layer layout styles, legend and station table."""
        project = QgsProject.instance()
        station_rows = sorted(
            stations_layer.getFeatures(),
            key=lambda feature: (
                int(feature["Volgnummer"] or 0)
                if stations_layer.fields().lookupField("Volgnummer") >= 0
                else 0,
                str(feature["Cluster"] or ""),
            ),
        )
        valid_clusters = [str(feature["Cluster"]).strip() for feature in station_rows]
        valid_set = set(valid_clusters)
        direct_layer_ids = {
            connections_layer.id(),
            stations_layer.id(),
            areas_layer.id(),
            routes_layer.id(),
        }
        for layer in project.mapLayers().values():
            if layer.id() not in direct_layer_ids:
                continue
            renderer = layer.renderer()
            if not isinstance(renderer, QgsCategorizedSymbolRenderer):
                continue
            if str(renderer.classAttribute()).strip('"').casefold() != "cluster":
                continue
            categories_by_value = {
                str(category.value()).strip(): category
                for category in renderer.categories()
            }
            refreshed_categories = []
            for cluster_name in valid_clusters:
                category = categories_by_value.get(cluster_name)
                if category is None or cluster_name not in valid_set:
                    continue
                refreshed_categories.append(
                    QgsRendererCategory(
                        category.value(),
                        category.symbol().clone(),
                        category.label(),
                        category.renderState(),
                    )
                )
            layer.setRenderer(
                QgsCategorizedSymbolRenderer(
                    renderer.classAttribute(), refreshed_categories
                )
            )
            layer.triggerRepaint()

        for layout in project.layoutManager().printLayouts():
            for multi_frame in layout.multiFrames():
                if isinstance(multi_frame, QgsLayoutItemAttributeTable):
                    multi_frame.refresh()
            for item in layout.items():
                if isinstance(item, QgsLayoutItemLegend):
                    item.updateLegend()
                    item.refresh()
                elif isinstance(item, QgsLayoutItemMap):
                    item.refresh()
            layout.refresh()
        project.setDirty(True)

    def processAlgorithm(self, parameters, context, feedback):
        connections_layer = self.parameterAsVectorLayer(
            parameters, self.AANSLUITINGEN, context
        )
        stations_layer = self.parameterAsVectorLayer(
            parameters, self.STATIONS, context
        )
        areas_layer = self.parameterAsVectorLayer(parameters, self.GEBIEDEN, context)
        routes_layer = self.parameterAsVectorLayer(
            parameters, self.KABELROUTES, context
        )
        cables_layer = self.parameterAsVectorLayer(parameters, self.SLEUVEN, context)
        plan_layer = self.parameterAsVectorLayer(parameters, self.PLANGEBIED, context)
        layers = [
            connections_layer,
            stations_layer,
            areas_layer,
            routes_layer,
            cables_layer,
        ]
        if any(layer is None or not layer.isValid() for layer in layers):
            raise QgsProcessingException("Een of meer invoerlagen zijn ongeldig.")
        if any(not layer.crs().isValid() for layer in layers):
            raise QgsProcessingException("Alle invoerlagen moeten een geldige CRS hebben.")
        if plan_layer is not None and (
            not plan_layer.isValid() or not plan_layer.crs().isValid()
        ):
            raise QgsProcessingException("De plangebiedlaag of de CRS daarvan is ongeldig.")

        selected_connection_ids = {
            int(value) for value in connections_layer.selectedFeatureIds()
        }
        selected_station_ids = [
            int(value) for value in stations_layer.selectedFeatureIds()
        ]
        refresh_all_routes = self.parameterAsBool(
            parameters, self.ALLE_ROUTES_VERVERSEN, context
        )
        if not refresh_all_routes and not selected_connection_ids:
            raise QgsProcessingException(
                "Selecteer eerst één of meer aansluitingen in de kaart."
            )
        if not refresh_all_routes and len(selected_station_ids) != 1:
            raise QgsProcessingException(
                "Selecteer in de stationslaag precies één doelstation."
            )
        if refresh_all_routes:
            first_station = next(stations_layer.getFeatures(), None)
            if first_station is None:
                raise QgsProcessingException("De stationslaag bevat geen stations.")
            selected_station_ids = [int(first_station.id())]
        refresh_selected_only = self.parameterAsBool(
            parameters, self.ALLEEN_GESELECTEERDE_ROUTES, context
        )
        entered_refresh_clusters = {
            value.strip()
            for value in self.parameterAsString(
                parameters, self.ROUTE_CLUSTERS, context
            ).split(",")
            if value.strip()
        }
        if refresh_all_routes and refresh_selected_only:
            route_cluster_field = routes_layer.fields().lookupField("Cluster")
            station_cluster_field = stations_layer.fields().lookupField("Cluster")
            if route_cluster_field < 0 or station_cluster_field < 0:
                raise QgsProcessingException(
                    "Kabelroutes en stations moeten een Cluster-kolom bevatten."
                )
            entered_refresh_clusters.update(
                str(feature.attribute(route_cluster_field)).strip()
                for feature in routes_layer.getSelectedFeatures()
                if str(feature.attribute(route_cluster_field)).strip()
            )
            entered_refresh_clusters.update(
                str(feature.attribute(station_cluster_field)).strip()
                for feature in stations_layer.getSelectedFeatures()
                if str(feature.attribute(station_cluster_field)).strip()
            )
            if not entered_refresh_clusters:
                raise QgsProcessingException(
                    "Selecteer eerst één of meer kabelroutes of stations om alleen "
                    "die clusterroutes te verversen."
                )

        self._validate_fields(
            connections_layer,
            (
                "Cluster",
                "Ontwerp_A",
                "Stat_type",
                "Stat_KVA",
                "Max_A",
                "Clust_A",
                "Benut_pct",
                "Route_m",
                "Snap_m",
            ),
            "Aansluitingenlaag",
        )
        summary_fields = (
            "Cluster",
            "Type",
            "KVA",
            "Max_A",
            "Belast_A",
            "Benut_pct",
            "Aantal",
            "Gem_route",
            "Max_route",
            "Route_km",
        )
        self._validate_fields(stations_layer, summary_fields, "Stationslaag")
        self._validate_fields(areas_layer, summary_fields, "Gebiedenlaag")
        self._validate_fields(routes_layer, summary_fields, "Kabelroutelaag")

        for layer in (connections_layer, stations_layer, areas_layer, routes_layer):
            if layer.isEditable():
                raise QgsProcessingException(
                    f"Laag '{layer.name()}' staat nog in bewerkingsmodus. "
                    "Sla de bewerkingen eerst op."
                )

        max_route_m = self.parameterAsDouble(parameters, self.MAX_ROUTE_M, context)
        remove_source_clusters = self.parameterAsBool(
            parameters, self.HELE_BRONCLUSTER_VERWIJDEREN, context
        )
        allow_all = self.parameterAsBool(parameters, self.ALLES_TOESTAAN, context)
        safety_checks = {
            "check_station_capacity": self.parameterAsBool(
                parameters, self.CONTROLE_MAX_ONTWERPSTROOM, context
            ),
            "check_max_route": self.parameterAsBool(
                parameters, self.CONTROLE_MAX_KABELLENGTE, context
            ),
            "block_other_cluster_routes": self.parameterAsBool(
                parameters, self.CONTROLE_ROUTES_ANDERE_CLUSTERS, context
            ),
            "check_shared_routes_and_branches": self.parameterAsBool(
                parameters,
                self.CONTROLE_GEDEELDE_ROUTES_VERTAKKINGEN,
                context,
            ),
        }
        if allow_all:
            safety_checks = {key: False for key in safety_checks}
            feedback.pushWarning(
                "ALLES TOESTAAN is actief: capaciteit, maximale route, routes door "
                "andere clusters en gedeelde routes/vertakkingen worden niet geblokkeerd."
            )
        node_tolerance_m = self.parameterAsDouble(
            parameters, self.KNOOP_TOLERANTIE_M, context
        )
        output_folder = Path(
            self.parameterAsString(parameters, self.BACKUPMAP, context)
        )
        output_folder.mkdir(parents=True, exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = output_folder / f"cluster_backup_{timestamp}.gpkg"
        result_path = output_folder / f"cluster_correctie_{timestamp}.gpkg"

        with tempfile.TemporaryDirectory(prefix="qgis_handmatige_clustercorrectie_") as temp:
            temp_dir = Path(temp)
            layer_specs = [
                ("aansluitingen", connections_layer),
                ("stations", stations_layer),
                ("gebieden", areas_layer),
                ("routes", routes_layer),
                ("sleuven", cables_layer),
            ]
            if plan_layer is not None:
                layer_specs.append(("plangebied", plan_layer))
            snapshots = {}
            feedback.setProgress(2)
            snapshot_path = temp_dir / "rekeninvoer.gpkg"
            for layer_name, layer in layer_specs:
                self._write_layer_snapshot(
                    layer, snapshot_path, layer_name, context
                )
                snapshots[layer_name] = {
                    "path": str(snapshot_path),
                    "layer": layer_name,
                }
            feedback.setProgress(12)

            summary_path = temp_dir / "samenvatting.json"
            config_path = temp_dir / "opdracht.json"
            config_path.write_text(
                json.dumps(
                    {
                        "inputs": snapshots,
                        "selected_source_fids": sorted(selected_connection_ids),
                        "target_station_source_fid": selected_station_ids[0],
                        "remove_source_clusters": remove_source_clusters,
                        "refresh_all_routes": refresh_all_routes,
                        "refresh_cluster_names": sorted(
                            entered_refresh_clusters
                            if refresh_selected_only
                            else []
                        ),
                        "allow_all": allow_all,
                        "max_route_m": max_route_m,
                        **safety_checks,
                        "node_tolerance_m": node_tolerance_m,
                        "backup_path": str(backup_path),
                        "result_path": str(result_path),
                        "summary_path": str(summary_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            feedback.pushInfo(
                "Netwerkberekening wordt in een aparte rekenomgeving uitgevoerd..."
            )
            disabled_checks = [
                label
                for key, label in (
                    ("check_station_capacity", "maximale ontwerpstroom"),
                    ("check_max_route", "maximale kabellengte"),
                    (
                        "block_other_cluster_routes",
                        "routes door/over andere clusters",
                    ),
                    (
                        "check_shared_routes_and_branches",
                        "gedeelde kabelroutes en onvolledige vertakkingen",
                    ),
                )
                if not safety_checks[key]
            ]
            if disabled_checks:
                feedback.pushWarning(
                    "WAARSCHUWING: uitgeschakelde veiligheidscontroles: "
                    + ", ".join(disabled_checks)
                    + "."
                )
            command = [
                *self._python_command(),
                "-u",
                str(self._worker_paths()),
                str(config_path),
            ]
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=(
                    subprocess.CREATE_NO_WINDOW
                    if os.name == "nt" and hasattr(subprocess, "CREATE_NO_WINDOW")
                    else 0
                ),
            )

            output_queue: Queue[tuple[str, str]] = Queue()

            def drain_stream(stream, channel):
                try:
                    for line in iter(stream.readline, ""):
                        output_queue.put((channel, line.rstrip("\r\n")))
                finally:
                    stream.close()

            stdout_thread = Thread(
                target=drain_stream,
                args=(process.stdout, "stdout"),
                daemon=True,
            )
            stderr_thread = Thread(
                target=drain_stream,
                args=(process.stderr, "stderr"),
                daemon=True,
            )
            stdout_thread.start()
            stderr_thread.start()
            stderr_lines = []
            phase_progress = {
                "Invoerlagen in de rekenomgeving lezen": 18,
                "Kabelnet opnieuw knippen en noden": 30,
                "Bestaand geknipt/genood kabelnet": 30,
                "Kabelroutes voor de aangepaste clusters": 48,
                "Alle kortste clusterroutes opnieuw berekenen": 48,
                "Aaneengesloten clustergebieden opnieuw opbouwen": 67,
                "Resultaat en back-up naar GeoPackage schrijven": 82,
            }

            def publish_available_output():
                while True:
                    try:
                        channel, line = output_queue.get_nowait()
                    except Empty:
                        break
                    if not line:
                        continue
                    if channel == "stderr":
                        stderr_lines.append(line)
                        feedback.pushWarning(line)
                    else:
                        feedback.pushInfo(line)
                    for marker, percent in phase_progress.items():
                        if marker in line:
                            feedback.setProgress(percent)

            while process.poll() is None:
                publish_available_output()
                if feedback.isCanceled():
                    process.terminate()
                    try:
                        process.wait(timeout=5.0)
                    except subprocess.TimeoutExpired:
                        process.kill()
                    raise QgsProcessingException("Handmatige correctie geannuleerd.")
                # Provider changes happen on QGIS' main thread. Keep the modal
                # dialog responsive while the isolated worker calculates.
                QCoreApplication.processEvents()
                try:
                    process.wait(timeout=0.10)
                except subprocess.TimeoutExpired:
                    pass
            stdout_thread.join(timeout=2.0)
            stderr_thread.join(timeout=2.0)
            publish_available_output()
            if process.returncode != 0 or not summary_path.exists():
                detail = stderr_lines[-1] if stderr_lines else (
                    f"rekenproces eindigde met code {process.returncode}"
                )
                raise QgsProcessingException(
                    f"Handmatige clustercorrectie is niet mogelijk: {detail}"
                )
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

        # All calculations and both recovery files exist before source mutation.
        feedback.setProgress(88)
        for numbered_layer in (stations_layer, areas_layer, routes_layer):
            self._ensure_integer_field(numbered_layer, "Volgnummer")
        self._apply_result_layer(
            connections_layer, result_path, "aansluitingen_geclusterd"
        )
        self._apply_result_layer(
            stations_layer,
            result_path,
            "stations_ontwerp",
            delete_missing=remove_source_clusters,
        )
        self._apply_result_layer(
            areas_layer,
            result_path,
            "clustergebieden",
            change_geometry=True,
            delete_missing=remove_source_clusters,
        )
        self._apply_result_layer(
            routes_layer,
            result_path,
            "cluster_kabelroutes",
            change_geometry=True,
            delete_missing=remove_source_clusters,
            preserve_empty_geometry=True,
        )
        self._refresh_project_layout_after_correction(
            connections_layer,
            stations_layer,
            areas_layer,
            routes_layer,
        )
        feedback.setProgress(100)

        if refresh_all_routes:
            refreshed_clusters = summary.get("refreshed_clusters", [])
            feedback.pushInfo(
                (
                    "Geselecteerde clusterroutes zijn opnieuw als kortste "
                    "exclusieve kabelpaden opgebouwd ("
                    + ", ".join(refreshed_clusters)
                    + ")."
                    if refresh_selected_only
                    else "Alle clusterroutes zijn opnieuw als kortste exclusieve "
                    "kabelpaden opgebouwd."
                )
                + " Langste route: "
                f"{summary['maximum_route_m']:.1f} m."
            )
        else:
            feedback.pushInfo(
                f"{summary['moved_count']} aansluiting(en) verplaatst naar "
                f"{summary['target_cluster']}. Doelbelasting: "
                f"{summary['target_load_a']:.1f} / "
                f"{summary['target_capacity_a']:.1f} A. Langste route: "
                f"{summary['maximum_route_m']:.1f} m."
            )
        removed_clusters = summary.get("removed_source_clusters", [])
        if removed_clusters:
            feedback.pushInfo(
                "Verwijderde broncluster(s): " + ", ".join(removed_clusters) + "."
            )
        preserved_routes = summary.get("preserved_route_clusters", [])
        if preserved_routes:
            feedback.pushWarning(
                "Geen nieuwe volledige/zichtbare sleufroute gevonden voor: "
                + ", ".join(preserved_routes)
                + ". De vorige route en Route_m zijn daarom behouden. "
                "Controleer de sleufverbinding en ververs deze routes daarna opnieuw."
            )
        if summary.get("used_forced_direct_routes", False):
            feedback.pushWarning(
                "ALLES TOESTAAN heeft één of meer directe correctieroutes gebruikt "
                "omdat geen volledige kabelroute beschikbaar was."
            )
        applied_checks = summary.get("safety_checks", safety_checks)
        feedback.pushInfo(
            "Veiligheidscontroles: ontwerpstroom={}; kabellengte={}; "
            "andere clusters={}; gedeelde routes/vertakkingen={}.".format(
                "aan" if applied_checks.get("check_station_capacity", True) else "uit",
                "aan" if applied_checks.get("check_max_route", True) else "uit",
                "aan"
                if applied_checks.get("block_other_cluster_routes", True)
                else "uit",
                "aan"
                if applied_checks.get("check_shared_routes_and_branches", True)
                else "uit",
            )
        )
        return {
            self.BACKUP_GPKG: str(backup_path),
            self.RESULTAAT_GPKG: str(result_path),
            self.VERPLAATST_AANTAL: int(summary["moved_count"]),
            self.DOELSTATION: (
                "(toewijzingen ongewijzigd)"
                if refresh_all_routes
                else str(summary["target_cluster"])
            ),
            self.BIJGEWERKTE_LAGEN: (
                "Aansluitingen geclusterd; Stations ontwerp; Clustergebieden; "
                "Kabelroutes per cluster"
            ),
        }

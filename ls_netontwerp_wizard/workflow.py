from __future__ import annotations

import importlib.util
import json
import os
import re
from datetime import datetime
from pathlib import Path

from qgis.PyQt.QtCore import QVariant
from qgis.PyQt.QtGui import QColor, QFont
from qgis.core import (
    Qgis,
    QgsCategorizedSymbolRenderer,
    QgsCoordinateReferenceSystem,
    QgsCoordinateTransform,
    QgsFillSymbol,
    QgsFeature,
    QgsFeatureRequest,
    QgsField,
    QgsGeometry,
    QgsLineSymbol,
    QgsMarkerSymbol,
    QgsPalLayerSettings,
    QgsProcessingContext,
    QgsProcessingException,
    QgsProcessingFeedback,
    QgsProject,
    QgsRasterLayer,
    QgsRectangle,
    QgsReferencedRectangle,
    QgsRendererCategory,
    QgsRuleBasedRenderer,
    QgsSingleSymbolRenderer,
    QgsVectorFileWriter,
    QgsVectorLayer,
    QgsVectorLayerSimpleLabeling,
    QgsVectorDataProvider,
    QgsTextBufferSettings,
    QgsTextFormat,
)

from .station_name_csv import load_station_name_lookup, normalize_asset_id
from .station_symbology import color_connections_by_station
from .project_presentation import PRESENTATION_VERSION, use_layer_tree_order, show_connection_legend


PLUGIN_ROOT = Path(__file__).resolve().parent
ALGORITHM_ROOT = PLUGIN_ROOT / "algorithms"


ALGORITHMS = {
    "import": (
        "GEN XML naar alles in QGIS 45 Relatie-ID.py",
        "ImportSmallworldLayersWithCSV_V45_RelationIds",
    ),
    "housing": (
        "TypeWoning classificatie met overige panden 6.py",
        "WoningTyperingSortedAlgorithm",
    ),
    "current": (
        "Ontwersptroom TRAFO, KABEL & OPWEK voor XML KADER 2026 V5.py",
        "OntwerpstroomSpatial",
    ),
    "clustering": (
        "laagspanning_clustering_tool.py",
        "LaagspanningClusteringAlgorithm",
    ),
}


class StageFeedback(QgsProcessingFeedback):
    def __init__(self, callback, start, end, title):
        super().__init__()
        self.callback = callback
        self.start = float(start)
        self.end = float(end)
        self.title = title

    def setProgress(self, progress):
        mapped = self.start + (self.end - self.start) * float(progress) / 100.0
        self.callback(mapped, self.title)

    def pushInfo(self, info):
        text = str(info).strip()
        if text:
            self.callback(self.start, f"{self.title}: {text}")

    def pushWarning(self, warning):
        self.callback(self.start, f"{self.title}: waarschuwing: {warning}")

    def reportError(self, error, fatalError=False):
        self.callback(self.start, f"{self.title}: {error}")
        super().reportError(error, fatalError)


class WorkflowRunner:
    def __init__(self, values, progress_callback):
        self.v = values
        self.progress = progress_callback
        self.context = QgsProcessingContext()
        self.context.setProject(QgsProject.instance())

    def _configure_cpu_threads(self):
        logical = max(1, os.cpu_count() or 1)
        if self.v.get("auto_cpu_threads", True):
            threads = max(1, logical - 1)
        else:
            threads = max(1, int(self.v.get("cpu_threads", 1)))
        threads = min(threads, logical, 64)
        self.v["effective_cpu_threads"] = threads
        # These are read by HiGHS/SciPy, BLAS and the bundled clustering engine.
        os.environ["LS_NETONTWERP_THREADS"] = str(threads)
        os.environ["OMP_NUM_THREADS"] = str(threads)
        os.environ["OPENBLAS_NUM_THREADS"] = str(threads)
        os.environ["MKL_NUM_THREADS"] = str(threads)
        os.environ["NUMEXPR_NUM_THREADS"] = str(threads)
        self.progress(
            0,
            f"CPU-versnelling: {threads} van {logical} logische processors gebruiken",
        )
        return threads

    def _algorithm(self, key):
        filename, class_name = ALGORITHMS[key]
        path = ALGORITHM_ROOT / filename
        module_name = f"ls_netontwerp_{key}_{abs(hash(str(path)))}"
        spec = importlib.util.spec_from_file_location(module_name, path)
        if spec is None or spec.loader is None:
            raise QgsProcessingException(f"Kan algoritme niet laden: {path}")
        module = importlib.util.module_from_spec(spec)
        spec.loader.exec_module(module)
        algorithm = getattr(module, class_name)()
        algorithm.initAlgorithm()
        return algorithm

    def _run_algorithm(self, key, parameters, start, end, title):
        self.progress(start, title)
        feedback = StageFeedback(self.progress, start, end, title)
        if key == "clustering":
            from .station_policy import apply_input_policy
            parameters = apply_input_policy(parameters)
        result = self._algorithm(key).processAlgorithm(
            parameters, self.context, feedback
        )
        self.progress(end, f"{title} gereed")
        return result

    @staticmethod
    def _layer(gpkg, layer_name):
        return f"{gpkg}|layername={layer_name}"

    @staticmethod
    def _unique_result_dir(parent):
        parent = Path(parent)
        parent.mkdir(parents=True, exist_ok=True)
        preferred = parent / "LS_netontwerp_resultaat"
        if not preferred.exists():
            preferred.mkdir()
            return preferred
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        result = parent / f"LS_netontwerp_resultaat_{timestamp}"
        result.mkdir()
        return result

    def _write_plan(self, input_path, output_path):
        layer = QgsVectorLayer(str(input_path), "plangebied", "ogr")
        if not layer.isValid():
            raise QgsProcessingException(
                f"Het plangebied kon niet worden geopend: {input_path}"
            )
        if layer.crs().isValid() is False:
            fallback = QgsCoordinateReferenceSystem(self.v["plan_source_crs"])
            if not fallback.isValid():
                raise QgsProcessingException(
                    "Het plangebied heeft geen CRS en de Advanced bron-CRS is ongeldig"
                )
            layer.setCrs(fallback)
        target_crs = QgsCoordinateReferenceSystem("EPSG:28992")
        options = QgsVectorFileWriter.SaveVectorOptions()
        options.driverName = "GPKG"
        options.layerName = "plangebied"
        options.actionOnExistingFile = QgsVectorFileWriter.CreateOrOverwriteFile
        writer = QgsVectorFileWriter.create(
            str(output_path),
            layer.fields(),
            layer.wkbType(),
            target_crs,
            QgsProject.instance().transformContext(),
            options,
        )
        if writer is None or writer.hasError() != QgsVectorFileWriter.NoError:
            message = writer.errorMessage() if writer is not None else "geen writer"
            raise QgsProcessingException(
                f"Plangebied schrijven mislukt: {message}"
            )
        coordinate_transform = None
        if layer.crs() != target_crs:
            coordinate_transform = QgsCoordinateTransform(
                layer.crs(), target_crs, QgsProject.instance()
            )
        for source_feature in layer.getFeatures():
            output_feature = QgsFeature(source_feature)
            if coordinate_transform is not None and source_feature.hasGeometry():
                geometry = QgsGeometry(source_feature.geometry())
                geometry.transform(coordinate_transform)
                output_feature.setGeometry(geometry)
            if not writer.addFeature(output_feature):
                message = writer.errorMessage() or "feature kon niet worden geschreven"
                del writer
                raise QgsProcessingException(
                    f"Plangebied schrijven mislukt: {message}"
                )
        del writer
        uri = self._layer(output_path, "plangebied")
        result_layer = QgsVectorLayer(uri, "plangebied", "ogr")
        if not result_layer.isValid() or result_layer.featureCount() == 0:
            raise QgsProcessingException("Het geconverteerde plangebied is leeg")
        return result_layer, uri

    def _validate_layer(self, uri, label):
        layer = QgsVectorLayer(uri, label, "ogr")
        if not layer.isValid():
            raise QgsProcessingException(
                f"Laag '{label}' is niet gevonden. Controleer Advanced > Lagen.\n{uri}"
            )
        return uri

    @staticmethod
    def _apply_station_names_from_csv(layer, values):
        csv_path = str(values.get("station_names_csv", "") or "").strip()
        if not csv_path:
            return None
        if layer.isEditable():
            raise QgsProcessingException("Sla bestaande bewerkingen in de aansluitingenlaag eerst op.")
        lookup, csv_summary = load_station_name_lookup(
            csv_path, values.get("station_name_csv_field", "")
        )

        def compact(value):
            return "".join(
                character.casefold()
                for character in str(value)
                if character.isalnum()
            )

        key_index = next(
            (
                index
                for index, field in enumerate(layer.fields())
                if compact(field.name()) in {"masterassetid", "masterassetidentifier"}
            ),
            -1,
        )
        if key_index < 0:
            raise QgsProcessingException(
                "De laag 'LS-aansluitingen ontwerpstroom' bevat geen "
                "Master Asset ID-kolom om de CSV aan te koppelen."
            )

        station_index = layer.fields().lookupField("Station")
        if not layer.startEditing():
            raise QgsProcessingException(
                "De ontwerpstroomlaag kon niet worden bewerkt om de "
                "stationsnaamkolom toe te voegen."
            )
        if station_index < 0:
            if not layer.addAttribute(QgsField("Station", QVariant.String)):
                layer.rollBack()
                raise QgsProcessingException(
                    "De kolom 'Station' kon niet aan de ontwerpstroomlaag worden toegevoegd."
                )
            layer.updateFields()
            station_index = layer.fields().lookupField("Station")

        changes = {}
        matched_count = 0
        layer_feature_count = 0
        for feature in layer.getFeatures():
            layer_feature_count += 1
            asset_id = normalize_asset_id(feature[key_index])
            station_name = lookup.get(asset_id, "")
            if station_name:
                matched_count += 1
                changes[feature.id()] = {station_index: station_name}

        if not matched_count:
            layer.rollBack()
            raise QgsProcessingException(
                "Geen aansluitingen konden via Master Asset ID aan de CSV worden "
                "gekoppeld. Controleer of de CSV en de GEN-export bij elkaar horen."
            )
        for feature_id, attributes in changes.items():
            if not layer.changeAttributeValues(feature_id, attributes):
                layer.rollBack()
                raise QgsProcessingException(
                    f"Stationsnaam bij aansluiting {feature_id} kon niet worden opgeslagen."
                )
        if not layer.commitChanges():
            errors = "; ".join(layer.commitErrors())
            layer.rollBack()
            raise QgsProcessingException(
                "De stationsnamen konden niet naar de ontwerpstroomlaag worden "
                f"geschreven{': ' + errors if errors else '.'}"
            )
        color_connections_by_station(layer)
        layer.triggerRepaint()
        return {
            **csv_summary,
            "matched": matched_count,
            "unmatched": max(0, layer_feature_count - matched_count),
            "layer_features": layer_feature_count,
            "target_name_field": "Station",
        }

    @staticmethod
    def _project_layer_by_source(uri):
        wanted = str(uri).replace("\\", "/").casefold()
        for layer in QgsProject.instance().mapLayers().values():
            if layer.source().replace("\\", "/").casefold() == wanted:
                return layer
        return None

    def _add_project_layer(self, uri, name, visible=True):
        project = QgsProject.instance()
        layer = self._project_layer_by_source(uri)
        if layer is None:
            layer = QgsVectorLayer(str(uri), name, "ogr")
            if not layer.isValid():
                raise QgsProcessingException(
                    f"Werkprojectlaag '{name}' kon niet worden geopend: {uri}"
                )
            project.addMapLayer(layer)
        layer.setName(name)
        layer.setCustomProperty("LSNetontwerp/workflow_layer", True)
        layer.setScaleBasedVisibility(False)
        node = project.layerTreeRoot().findLayer(layer.id())
        if node is not None:
            node.setItemVisibilityChecked(bool(visible))
        return layer

    @staticmethod
    def _style_plan_area(layer):
        """Toon het plangebied alleen als duidelijke rode begrenzing."""
        symbol = QgsFillSymbol.createSimple(
            {
                "style": "no",
                "color": "255,255,255,0",
                "outline_style": "solid",
                "outline_color": "255,0,0,255",
                "outline_width": "1",
            }
        )
        try:
            symbol.setOutputUnit(Qgis.RenderUnit.Millimeters)
        except (AttributeError, TypeError):
            pass
        layer.renderer().setSymbol(symbol)
        layer.setOpacity(1.0)
        layer.setScaleBasedVisibility(False)
        layer.setCustomProperty("LSNetontwerp/plan_layer", True)
        layer.triggerRepaint()

    @staticmethod
    def _style_woningtypes(layer, field_name):
        field_index = layer.fields().lookupField(field_name)
        if field_index < 0:
            raise QgsProcessingException(
                f"Woningtypenlaag mist de gekozen kolom '{field_name}'"
            )
        configured = (
            ("vrijstaande woning", "Vrijstaande woning", "139,0,0,190"),
            ("twee-onder-een-kap", "Twee-onder-een-kap", "142,201,240,190"),
            ("appartement", "Appartement", "255,153,204,190"),
            ("tussenwoning/geschakeld", "Rijtjeswoning", "144,238,144,190"),
            ("hoekwoning", "Hoekwoning", "0,100,0,190"),
            ("", "Overige panden", "217,217,217,170"),
        )
        categories = []
        for value, label, color in configured:
            symbol = QgsFillSymbol.createSimple(
                {
                    "color": color,
                    "outline_color": "51,51,51,210",
                    "outline_width": "0.15",
                }
            )
            try:
                symbol.setOutputUnit(Qgis.RenderUnit.Millimeters)
            except (AttributeError, TypeError):
                pass
            categories.append(QgsRendererCategory(value, symbol, label))
        layer.setRenderer(QgsCategorizedSymbolRenderer(field_name, categories))
        layer.setScaleBasedVisibility(False)
        layer.triggerRepaint()

    @staticmethod
    def _style_function_cables(layer, field_name, enabled_words):
        field_index = layer.fields().lookupField(field_name)
        if field_index < 0:
            raise QgsProcessingException(
                f"Kabellaag '{layer.name()}' mist de gekozen kolom '{field_name}'"
            )
        values = sorted(
            layer.uniqueValues(field_index),
            key=lambda value: str(value or "").casefold(),
        )
        palette = (
            "31,119,180,255",
            "255,127,14,255",
            "44,160,44,255",
            "214,39,40,255",
            "148,103,189,255",
            "140,86,75,255",
            "227,119,194,255",
            "127,127,127,255",
            "188,189,34,255",
            "23,190,207,255",
        )
        words = [
            word.strip().casefold()
            for word in str(enabled_words or "LS").replace(";", ",").split(",")
            if word.strip()
        ] or ["ls"]
        categories = []
        enabled_states = []
        for index, value in enumerate(values):
            text = str(value or "").strip()
            symbol = QgsLineSymbol.createSimple(
                {"color": palette[index % len(palette)], "width": "0.65"}
            )
            try:
                symbol.setOutputUnit(Qgis.RenderUnit.Millimeters)
            except (AttributeError, TypeError):
                pass
            categories.append(
                QgsRendererCategory(value, symbol, text or "(leeg/NULL)")
            )
            enabled_states.append(
                any(word in text.casefold() for word in words)
            )
        renderer = QgsCategorizedSymbolRenderer(field_name, categories)
        for index, enabled in enumerate(enabled_states):
            renderer.updateCategoryRenderState(index, enabled)
        layer.setRenderer(renderer)
        layer.setScaleBasedVisibility(False)
        layer.triggerRepaint()

    @staticmethod
    def _set_step_one_layer_visibility(visible_layers):
        project = QgsProject.instance()
        visible_ids = {layer.id() for layer in visible_layers if layer is not None}
        for layer in project.mapLayers().values():
            if layer.id() not in visible_ids and not layer.customProperty("LSNetontwerp/workflow_layer", False):
                continue
            layer.setScaleBasedVisibility(False)
            node = project.layerTreeRoot().findLayer(layer.id())
            if node is not None:
                node.setItemVisibilityChecked(layer.id() in visible_ids)

    @staticmethod
    def _set_step_one_render_order(foreground_layers, osm_layer):
        """Use the visible layer list, with OSM at the bottom, for map order."""
        use_layer_tree_order(foreground=foreground_layers, background=(osm_layer,))

    @staticmethod
    def _style_review_connections(layer):
        symbol = QgsMarkerSymbol.createSimple(
            {
                "name": "circle",
                "color": "102,194,165,235",
                "outline_color": "35,35,35,255",
                "outline_width": "1",
                "size": "17",
            }
        )
        try:
            symbol.setOutputUnit(Qgis.RenderUnit.Pixels)
            symbol.setSizeUnit(Qgis.RenderUnit.Pixels)
            symbol_layer = symbol.symbolLayer(0)
            symbol_layer.setSizeUnit(Qgis.RenderUnit.Pixels)
            symbol_layer.setStrokeWidthUnit(Qgis.RenderUnit.Pixels)
        except (AttributeError, TypeError):
            pass
        station_coloring = bool(layer.customProperty("LSNetontwerp/station_coloring", False))
        layer.setRenderer(QgsSingleSymbolRenderer(symbol))

        labels = QgsPalLayerSettings()
        labels.fieldName = 'format_number("Hoogste Trafo", 1)'
        labels.isExpression = True
        labels.enabled = True
        labels.displayAll = True
        labels.scaleVisibility = False
        labels.placement = Qgis.LabelPlacement.OverPoint
        text_format = QgsTextFormat()
        font = QFont("Arial", 7)
        font.setBold(True)
        text_format.setFont(font)
        text_format.setSize(10)
        try:
            text_format.setSizeUnit(Qgis.RenderUnit.Pixels)
        except (AttributeError, TypeError):
            pass
        text_format.setColor(QColor(20, 20, 20))
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setSize(1.5)
        try:
            buffer.setSizeUnit(Qgis.RenderUnit.Pixels)
        except (AttributeError, TypeError):
            pass
        buffer.setColor(QColor(255, 255, 255))
        text_format.setBuffer(buffer)
        labels.setFormat(text_format)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(labels))
        layer.setLabelsEnabled(True)
        layer.setCustomProperty("LSNetontwerp/review_current_layer", True)
        if station_coloring:
            color_connections_by_station(layer)
        else:
            show_connection_legend(layer)
        layer.triggerRepaint()

    @staticmethod
    def _parse_station_kva(value):
        """Parse the last positive number, matching the clustering engine."""
        values = re.findall(r"[-+]?\d+(?:[.,]\d+)?", str(value or "").strip())
        if not values:
            return None
        try:
            parsed = float(values[-1].replace(",", "."))
        except ValueError:
            return None
        return parsed if parsed > 0.0 else None

    @classmethod
    def _ensure_station_max_current(
        cls, layer, capacity_field="trafo_power", max_field="Max_A"
    ):
        """Persist Max_A so the review map and editor use one exact value."""
        capacity_index = layer.fields().lookupField(capacity_field)
        if capacity_index < 0:
            raise QgsProcessingException(
                f"De stationslaag mist de trafocapaciteitskolom '{capacity_field}'"
            )
        max_index = layer.fields().lookupField(max_field)
        provider = layer.dataProvider()
        if max_index < 0:
            if not provider.capabilities() & QgsVectorDataProvider.AddAttributes:
                raise QgsProcessingException(
                    f"De stationslaag kan het berekende veld '{max_field}' niet toevoegen"
                )
            if not provider.addAttributes([QgsField(max_field, QVariant.Double)]):
                raise QgsProcessingException(
                    f"Het berekende stationsveld '{max_field}' kon niet worden toegevoegd"
                )
            layer.updateFields()
            max_index = layer.fields().lookupField(max_field)
        changes = {}
        for feature in layer.getFeatures():
            capacity = cls._parse_station_kva(feature[capacity_index])
            maximum_current = (
                float(capacity) / 0.23 / 3.0 if capacity is not None else None
            )
            changes[int(feature.id())] = {max_index: maximum_current}
        if changes and not provider.changeAttributeValues(changes):
            raise QgsProcessingException(
                "De maximale ontwerpstroom van de stations kon niet worden opgeslagen"
            )
        layer.updateFields()
        layer.setCustomProperty("LSNetontwerp/review_station_layer", True)
        return max_field

    @staticmethod
    def _style_review_stations(
        layer,
        station_name_field="Station",
        capacity_field="trafo_power",
        max_field="Max_A",
    ):
        """Keep every imported station visible, including unknown capacities."""
        symbol = QgsMarkerSymbol.createSimple(
            {
                "name": "square",
                "color": "227,26,28,255",
                "outline_color": "0,0,0,255",
                "outline_width": "0.5",
                "size": "5.0",
            }
        )
        planned_symbol = QgsMarkerSymbol.createSimple(
            {
                "name": "square",
                "color": "255,215,0,255",
                "outline_color": "0,0,0,255",
                "outline_width": "0.5",
                "size": "5.0",
            }
        )
        try:
            for marker in (symbol, planned_symbol):
                marker.setOutputUnit(Qgis.RenderUnit.Millimeters)
                marker.setSizeUnit(Qgis.RenderUnit.Millimeters)
                marker.symbolLayer(0).setSizeUnit(Qgis.RenderUnit.Millimeters)
                marker.symbolLayer(0).setStrokeWidthUnit(Qgis.RenderUnit.Millimeters)
        except (AttributeError, TypeError):
            pass
        escaped_name = station_name_field.replace('"', '""')
        escaped_max = max_field.replace('"', '""')
        root_rule = QgsRuleBasedRenderer.Rule(None)
        station_rule = QgsRuleBasedRenderer.Rule(symbol)
        station_rule.setLabel("Bestaand station met naam en geldige capaciteit")
        station_rule.setFilterExpression(
            f'length(trim(coalesce("{escaped_name}", \'\'))) > 0 '
            f'AND "{escaped_max}" IS NOT NULL AND "{escaped_max}" > 0'
        )
        root_rule.appendChild(station_rule)
        planned_rule = QgsRuleBasedRenderer.Rule(planned_symbol)
        planned_rule.setLabel("Gepland station zonder naam en met geldige capaciteit")
        planned_rule.setFilterExpression(
            f'length(trim(coalesce("{escaped_name}", \'\'))) = 0 '
            f'AND "{escaped_max}" IS NOT NULL AND "{escaped_max}" > 0'
        )
        root_rule.appendChild(planned_rule)
        for named, color, legend in (
            (True, "255,140,0,255", "Bestaand station — capaciteit onbekend"),
            (False, "160,160,160,255", "Station zonder naam — capaciteit onbekend"),
        ):
            unknown_symbol = symbol.clone()
            unknown_symbol.setColor(QColor(*[int(v) for v in color.split(',')]))
            unknown_rule = QgsRuleBasedRenderer.Rule(unknown_symbol)
            unknown_rule.setLabel(legend)
            unknown_rule.setFilterExpression(
                f'length(trim(coalesce("{escaped_name}", \'\'))) {">" if named else "="} 0 '
                f'AND ("{escaped_max}" IS NULL OR "{escaped_max}" <= 0)'
            )
            root_rule.appendChild(unknown_rule)
        layer.setRenderer(QgsRuleBasedRenderer(root_rule))

        labels = QgsPalLayerSettings()
        labels.fieldName = (
            f'CASE WHEN "{escaped_max}" IS NOT NULL AND "{escaped_max}" > 0 THEN '
            f'concat(CASE WHEN length(trim(coalesce("{escaped_name}", \'\'))) > 0 '
            f'THEN concat(trim("{escaped_name}"), \'\\n\') '
            f'ELSE \'Gepland station\\n\' END, \'Max_A: \', '
            f'format_number("{escaped_max}", 0), \' A\') ELSE '
            f'concat(CASE WHEN length(trim(coalesce("{escaped_name}", \'\'))) > 0 '
            f'THEN trim("{escaped_name}") ELSE \'Station zonder naam\' END, '
            f'\'\\nCapaciteit onbekend\') END'
        )
        labels.isExpression = True
        labels.enabled = True
        labels.displayAll = True
        labels.scaleVisibility = False
        labels.priority = 10
        labels.obstacle = False
        labels.zIndex = 100.0
        try:
            placement = labels.placementSettings()
            placement.setAllowDegradedPlacement(True)
            placement.setOverlapHandling(
                Qgis.LabelOverlapHandling.AllowOverlapAtNoCost
            )
            labels.setPlacementSettings(placement)
        except (AttributeError, TypeError):
            pass
        text_format = QgsTextFormat()
        font = QFont("Arial", 8)
        font.setBold(True)
        text_format.setFont(font)
        text_format.setSize(8.0)
        try:
            text_format.setSizeUnit(Qgis.RenderUnit.Points)
        except (AttributeError, TypeError):
            pass
        buffer = QgsTextBufferSettings()
        buffer.setEnabled(True)
        buffer.setSize(0.65)
        try:
            buffer.setSizeUnit(Qgis.RenderUnit.Millimeters)
        except (AttributeError, TypeError):
            pass
        buffer.setColor(QColor(255, 255, 255))
        text_format.setBuffer(buffer)
        labels.setFormat(text_format)
        layer.setLabeling(QgsVectorLayerSimpleLabeling(labels))
        layer.setLabelsEnabled(True)
        layer.setScaleBasedVisibility(False)
        layer.setCustomProperty("LSNetontwerp/review_station_layer", True)
        layer.setCustomProperty(
            "LSNetontwerp/station_name_field", station_name_field
        )
        layer.setCustomProperty(
            "LSNetontwerp/station_capacity_field", capacity_field
        )
        layer.setCustomProperty("LSNetontwerp/station_max_field", max_field)
        layer.triggerRepaint()

    def _initialize_work_project(self, result_dir):
        project = QgsProject.instance()
        project.clear()
        project.setCrs(QgsCoordinateReferenceSystem("EPSG:28992"))
        project_path = Path(result_dir) / "LS_netontwerp_werkproject.qgz"
        project.setFileName(str(project_path))
        project.setPresetHomePath(".")
        try:
            project.setFilePathStorage(Qgis.FilePathType.Relative)
        except (AttributeError, TypeError):
            pass
        osm_uri = (
            "type=xyz&url=https://tile.openstreetmap.org/"
            "{z}/{x}/{y}.png&zmin=0&zmax=19"
        )
        osm = QgsRasterLayer(osm_uri, "OpenStreetMap", "wms")
        if osm.isValid():
            osm.setScaleBasedVisibility(False)
            osm.setCustomProperty("LSNetontwerp/osm_layer", True)
            project.addMapLayer(osm)
        project.writeEntry("LSNetontwerp", "fase", "initialiseren")
        if not project.write(str(project_path)):
            raise QgsProcessingException(
                "Het QGIS-werkproject kon aan het begin niet worden geschreven"
            )
        self.progress(1, f"Nieuw QGIS-werkproject gemaakt: {project_path.name}")
        return project_path

    @staticmethod
    def _write_state(state):
        state_file = Path(state["result_dir"]) / "ls_netontwerp_workflow.json"
        state["state_file"] = str(state_file)
        state_file.write_text(
            json.dumps(state, ensure_ascii=False, indent=2), encoding="utf-8"
        )
        project = QgsProject.instance()
        project.writeEntry("LSNetontwerp", "state_file", str(state_file))
        project.writeEntry("LSNetontwerp", "fase", state["status"])
        if "station_rules" in state:
            project.writeEntry("LSNetontwerp", "station_rules", json.dumps(state["station_rules"], ensure_ascii=False))
        project.write()
        return state

    def prepare(self):
        cpu_threads = self._configure_cpu_threads()
        result_dir = self._unique_result_dir(self.v["output"])
        import_gpkg = result_dir / "01_gen_import.gpkg"
        plan_gpkg = result_dir / "02_plangebied.gpkg"
        housing_gpkg = result_dir / "03_woningtypen.gpkg"
        points_gpkg = result_dir / "04_ls_aansluitingen.gpkg"
        clustering_dir = result_dir / "05_clustering"
        work_project = self._initialize_work_project(result_dir)

        self._run_algorithm(
            "import",
            {
                "INPUT_XML": self.v["xml"],
                "INPUT_CABLE_DATA_EXCEL": self.v["excel"],
                "SHEET_NAME_CABLE": self.v["sheet_cable"],
                "SHEET_NAME_JOINT": self.v["sheet_joint"],
                "SHEET_NAME_CONN_CABLE": self.v["sheet_connection"],
                "OUTPUT_GPKG": str(import_gpkg),
                "GROUP_NAME": "LS Netontwerp import",
            },
            0,
            18,
            "GEN XML en Excel importeren",
        )
        import_source = str(import_gpkg).replace("\\", "/").casefold()
        for layer in QgsProject.instance().mapLayers().values():
            if layer.source().replace("\\", "/").casefold().startswith(import_source):
                layer.setCustomProperty("LSNetontwerp/workflow_layer", True)
        source_layers = {}
        for layer_key, display_name, visible in (
            ("layer_main_cables", "Laagspanningskabels (bron)", True),
            ("layer_connection_cables", "Aansluitkabels (bron)", True),
            ("layer_stations", "Bestaande stations (bron)", False),
            ("layer_flat_cabinets", "Flatkasten (bron)", False),
            ("layer_station_enclosures", "Stationomtrekken (bron)", False),
            ("layer_distribution_cabinets", "Verdeelkasten (bron)", False),
        ):
            source_layers[layer_key] = self._add_project_layer(
                self._validate_layer(
                    self._layer(import_gpkg, self.v[layer_key]), display_name
                ),
                display_name,
                visible,
            )
        self._style_function_cables(
            source_layers["layer_main_cables"],
            self.v["field_main_function"],
            self.v["main_function_words"],
        )
        self._style_function_cables(
            source_layers["layer_connection_cables"],
            self.v["field_connection_function"],
            self.v["connection_function_words"],
        )
        station_review_layer = source_layers["layer_stations"]
        station_max_field = self._ensure_station_max_current(
            station_review_layer,
            self.v["field_station_capacity"],
        )
        self._style_review_stations(
            station_review_layer,
            self.v["field_station_name"],
            self.v["field_station_capacity"],
            station_max_field,
        )
        QgsProject.instance().write()

        plan_layer = plan_project_layer = None
        if self.v.get("plan"):
            self.progress(18, "Plangebied naar GeoPackage omzetten")
            plan_layer, plan_uri = self._write_plan(self.v["plan"], plan_gpkg)
            plan_project_layer = self._add_project_layer(plan_uri, "Plangebied", True)
            self._style_plan_area(plan_project_layer)
            self.progress(22, "Plangebied gereed")
        else:
            self.progress(22, "Geen plangebied: aansluitingen bepalen de BAG-omvang")

        point_source = self._validate_layer(
            self._layer(import_gpkg, self.v["layer_points"]),
            self.v["layer_points"],
        )
        point_extent_layer = QgsVectorLayer(
            point_source, "LS-aansluitingen voor BAG-omvang", "ogr"
        )
        if not point_extent_layer.isValid() or point_extent_layer.featureCount() == 0:
            raise QgsProcessingException(
                "Geen LS-aansluitingen gevonden; de BAG-omvang kan niet worden bepaald"
            )
        target_crs = (
            plan_layer.crs() if plan_layer is not None
            else QgsCoordinateReferenceSystem("EPSG:28992")
        )
        if not point_extent_layer.crs().isValid():
            raise QgsProcessingException("De LS-aansluitingenlaag heeft geen geldig CRS")
        if plan_layer is None:
            housing_rectangle = QgsRectangle(point_extent_layer.extent())
            if point_extent_layer.crs() != target_crs:
                to_target = QgsCoordinateTransform(
                    point_extent_layer.crs(), target_crs, QgsProject.instance()
                )
                housing_rectangle = to_target.transformBoundingBox(housing_rectangle)
            if max(housing_rectangle.width(), housing_rectangle.height()) > 100000:
                raise QgsProcessingException(
                    "De aansluitingen liggen meer dan 100 km uiteen. "
                    "Controleer de coördinaten of kies een plangebied om de BAG-opvraag te begrenzen."
                )
        else:
            housing_rectangle = QgsRectangle(plan_layer.extent())
            # Gebruik niet rechtstreeks layer.extent(): één corrupte of verkeerd
            # geprojecteerde aansluiting kan anders een BAG-opvraag van heel
            # Europa veroorzaken. Neem alleen aansluitingen uit de ruime,
            # plausibele omgeving van het plangebied mee.
            maximum_plan_dimension = max(
                housing_rectangle.width(), housing_rectangle.height()
            )
            search_margin = max(
                1000.0, min(10000.0, maximum_plan_dimension * 2.0)
            )
            plausible_rectangle = QgsRectangle(housing_rectangle)
            plausible_rectangle.grow(search_margin)
            point_to_plan = None
            request_rectangle = QgsRectangle(plausible_rectangle)
            if point_extent_layer.crs() != plan_layer.crs():
                point_to_plan = QgsCoordinateTransform(
                    point_extent_layer.crs(),
                    plan_layer.crs(),
                    QgsProject.instance(),
                )
                plan_to_point = QgsCoordinateTransform(
                    plan_layer.crs(),
                    point_extent_layer.crs(),
                    QgsProject.instance(),
                )
                request_rectangle = plan_to_point.transformBoundingBox(
                    request_rectangle
                )
            request = QgsFeatureRequest().setFilterRect(request_rectangle)
            for point_feature in point_extent_layer.getFeatures(request):
                geometry = QgsGeometry(point_feature.geometry())
                if geometry.isEmpty():
                    continue
                if point_to_plan is not None:
                    geometry.transform(point_to_plan)
                point_rectangle = geometry.boundingBox()
                if plausible_rectangle.intersects(point_rectangle):
                    housing_rectangle.combineExtentWith(point_rectangle)
        # Neem ook volledige pandcontouren mee wanneer een aansluiting of de
        # plangrens vlak langs de gevel ligt.
        housing_rectangle.grow(25.0)
        housing_extent = QgsReferencedRectangle(housing_rectangle, target_crs)

        housing_layer_name = housing_gpkg.stem
        housing_uri = self._layer(housing_gpkg, housing_layer_name)
        self._run_algorithm(
            "housing",
            {
                "FETCH_MODE": 0,
                "PROCESSING_EXTENT": housing_extent,
                "TILE_SIZE": 10000,
                "BUFFER": 0.2,
                "USE_3DBAG_LOD22": self.v["use_3dbag"],
                "USE_MT": True,
                "CORES": cpu_threads,
                "OUTPUT": str(housing_gpkg),
            },
            22,
            42,
            "BAG/3DBAG-woningtypen bepalen",
        )
        housing_project_layer = self._add_project_layer(
            housing_uri, "Woningtypen BAG/3DBAG", True
        )
        self._style_woningtypes(
            housing_project_layer, self.v["field_building_type"]
        )

        housing_source = self._validate_layer(housing_uri, "woningtypen")
        points_layer_name = points_gpkg.stem
        points_uri = self._layer(points_gpkg, points_layer_name)
        self._run_algorithm(
            "current",
            {
                "INPUT_LAYER": point_source,
                "INPUT_PANDEN": housing_source,
                "FLD_DOORLAAT": self.v["field_passthrough"],
                "FLD_GEBRUIK": self.v["field_usage"],
                "FLD_GAS": self.v["field_gas"],
                "FLD_WONINGTYPE": self.v["field_building_type"],
                "FLD_BOUWJAAR": self.v["field_build_year"],
                "VAL_KADER": {"3.0": 0, "3.1": 1, "2.0": 2}.get(
                    str(self.v.get("design_framework", "3.0")), 0
                ),
                "VAL_1FASE_EXCEPTION": self.v["one_phase_exception"],
                "VAL_APPARTEMENT_ZONDER_DOORLAAT": self.v["default_apartment"],
                "VAL_BOUWJAAR_GRENS": self.v["building_year_limit"],
                "VAL_LIMIT_FASE": self.v["phase_limit"],
                "VAL_LIMIT_AMP": self.v["amp_limit"],
                "MAT_WOONHUIS": self.v["matrix_woonhuis"],
                "MAT_WOONHUIS_2022": self.v["matrix_woonhuis_2022"],
                "MAT_WOONHUIS_KABEL": self.v["matrix_woonhuis_kabel"],
                "MAT_WOONHUIS_KABEL_2022": self.v[
                    "matrix_woonhuis_kabel_2022"
                ],
                "MAT_WOONHUIS_OPWEK": self.v["matrix_woonhuis_opwek"],
                "MAT_WOONHUIS_OPWEK_KABEL": self.v[
                    "matrix_woonhuis_opwek_kabel"
                ],
                "VAL_OPWEK_ZERO_IDS": self.v["opwek_zero_ids"],
                "VAL_OPWEK_ZERO_TEXT": self.v["opwek_zero_text"],
                "MAT_AMP": self.v["matrix_amp"],
                "MAT_TYPE": self.v["matrix_type"],
                "MAT_STRAAT": self.v["matrix_straat"],
                "MAT_LAAD": self.v["matrix_laad"],
                "MAT_LAAD_KABEL": self.v["matrix_laad_kabel"],
                "MAT_GAS": self.v["matrix_gas"],
                "MAT_GAS_KABEL": self.v["matrix_gas_kabel"],
                "MAT_REGEX": self.v["matrix_regex"],
                "MAT_KEYWORDS": self.v["matrix_keywords"],
                "VAL_FALLBACK_LAAD": self.v["fallback_laad"],
                "OUTPUT": str(points_gpkg),
            },
            42,
            55,
            "Ontwerpstroom berekenen",
        )

        review_layer = self._add_project_layer(
            self._validate_layer(points_uri, "LS-aansluitingen ontwerpstroom"),
            "LS-aansluitingen ontwerpstroom",
            True,
        )
        required_review_fields = ("Hoogste Trafo", "Hoogste Kabel")
        missing_review_fields = [
            field_name
            for field_name in required_review_fields
            if review_layer.fields().lookupField(field_name) < 0
        ]
        if missing_review_fields:
            raise QgsProcessingException(
                "De ontwerpstroomlaag mist: " + ", ".join(missing_review_fields)
            )
        self._style_review_connections(review_layer)
        osm_layer = next(
            (
                layer
                for layer in QgsProject.instance().mapLayers().values()
                if bool(layer.customProperty("LSNetontwerp/osm_layer", False))
            ),
            None,
        )
        self._set_step_one_layer_visibility(
            (
                osm_layer,
                housing_project_layer,
                review_layer,
                station_review_layer,
                source_layers["layer_connection_cables"],
                source_layers["layer_main_cables"],
                plan_project_layer,
            )
        )
        self._set_step_one_render_order(
            (
                station_review_layer,
                review_layer,
                plan_project_layer,
                source_layers["layer_connection_cables"],
                source_layers["layer_main_cables"],
                housing_project_layer,
            ),
            osm_layer,
        )
        QgsProject.instance().writeEntry(
            "LSNetontwerp", "presentation_version", PRESENTATION_VERSION
        )
        state = {
            "version": 1,
            "status": "ontwerpstroom_controleren",
            "values": dict(self.v),
            "effective_cpu_threads": cpu_threads,
            "result_dir": str(result_dir),
            "work_project": str(work_project),
            "import_gpkg": str(import_gpkg),
            "plan_gpkg": str(plan_gpkg) if plan_layer is not None else "",
            "housing_gpkg": str(housing_gpkg),
            "points_gpkg": str(points_gpkg),
            "points_layer": points_layer_name,
            "clustering_dir": str(clustering_dir),
        }
        self.progress(
            55,
            "Controlefase: controleer aansluitingen, woningtypen en bestaande stations",
        )
        return self._write_state(state)

    def cluster(self, state):
        if not state:
            raise QgsProcessingException("Er is geen voorbereide ontwerpstroomfase")
        from .batch_editing import station_rules
        state["station_rules"] = station_rules() or state.get("station_rules", {})
        QgsProject.instance().writeEntry("LSNetontwerp", "station_rules", json.dumps(state["station_rules"], ensure_ascii=False))
        self.v = dict(state["values"])
        cpu_threads = self._configure_cpu_threads()
        result_dir = Path(state["result_dir"])
        import_gpkg = Path(state["import_gpkg"])
        plan_gpkg = state.get("plan_gpkg", "")
        points_gpkg = Path(state["points_gpkg"])
        points_layer_name = state.get("points_layer", points_gpkg.stem)
        points_uri = self._layer(points_gpkg, points_layer_name)
        plan_uri = self._layer(plan_gpkg, "plangebied") if plan_gpkg else None
        housing_gpkg = Path(state["housing_gpkg"]) if state.get("housing_gpkg") else None
        housing_uri = (
            self._layer(housing_gpkg, housing_gpkg.stem)
            if housing_gpkg is not None and housing_gpkg.is_file()
            else None
        )
        clustering_dir = Path(state["clustering_dir"])

        review_layer = self._project_layer_by_source(points_uri)
        if review_layer is not None and review_layer.isEditable():
            if not review_layer.commitChanges():
                raise QgsProcessingException(
                    "Open bewerkingen in de ontwerpstroomlaag konden niet worden opgeslagen"
                )
        if housing_uri is not None:
            housing_layer = self._project_layer_by_source(housing_uri)
            if housing_layer is not None and housing_layer.isEditable():
                if not housing_layer.commitChanges():
                    raise QgsProcessingException(
                        "Open bewerkingen in de BAG-woningtypenlaag konden niet worden opgeslagen"
                    )
        state["status"] = "clustering_bezig"
        self._write_state(state)

        if state.get("station_rules") and self.v.get("open_project", True):
            from .station_policy import show_retired_stations
            show_retired_stations(state["station_rules"], clustering_dir)
            QgsProject.instance().write()

        def imported(name, label):
            return self._validate_layer(self._layer(import_gpkg, name), label)

        from .network_repair import merged_cables
        routing_cables = merged_cables(imported(self.v['layer_main_cables'],'LS-kabels'),
                                      state.get('repair_trenches',''),self.v['field_main_function'])

        clustering_result = self._run_algorithm(
            "clustering",
            {
                "AANSLUITINGEN": self._validate_layer(points_uri, "LS-aansluitingen"),
                "ONTWERPSTROOM_VELD": self.v.get("field_design_current", "Hoogste Trafo"),
                "MULTISTORY_VELD": self.v["field_multistory"],
                "FLATKASTEN": imported(self.v["layer_flat_cabinets"], "flatkasten") if self.v.get("use_flat_cabinets", True) else None,
                "FLATKAST_ID_VELD": self.v["field_flat_id"],
                "BAG_API_URL": self.v["bag_api_url"],
                "BAG_PANDEN": (
                    self._validate_layer(housing_uri, "BAG-woningtypen")
                    if housing_uri else None
                ),
                "KABELS": routing_cables,
                "LS_FUNCTION_VELD": self.v["field_main_function"],
                "LS_FUNCTION_WOORDEN": self.v["main_function_words"],
                "AANSLUITKABELS": imported(
                    self.v["layer_connection_cables"], "aansluitkabels"
                ),
                "AANSLUIT_FUNCTION_VELD": self.v["field_connection_function"],
                "AANSLUIT_FUNCTION_WOORDEN": self.v["connection_function_words"],
                "SLEUVEN_NODEN": self.v["node_trenches"],
                "KNOOP_TOLERANTIE_M": self.v["node_tolerance"],
                "REKEN_THREADS": cpu_threads,
                "SCHRIJF_SHAPEFILES": self.v["write_shapefiles"],
                "STATIONS": imported(self.v["layer_stations"], "stations"),
                "STATION_NAAM_VELD": self.v["field_station_name"],
                "STATION_CAPACITEIT_VELD": self.v["field_station_capacity"],
                "STATIONOMTREKKEN": imported(
                    self.v["layer_station_enclosures"], "stationomtrekken"
                ),
                "STATIONOMTREK_NAAM_VELD": self.v["field_enclosure_station"],
                "VERDEELKASTEN": imported(
                    self.v["layer_distribution_cabinets"], "verdeelkasten"
                ),
                "PLANGEBIED": plan_uri,
                "ALLEEN_BINNEN_PLANGEBIED": bool(plan_uri) and self.v["only_plan"],
                "KABELROUTES_BUITEN_PLANGEBIED": self.v.get("allow_external_routes", False),
                "AUTOMATISCH_AANTAL": self.v["automatic_stations"],
                "AANTAL_NIEUWE": self.v["manual_station_count"],
                "NIEUW_KVA": self.v["new_station_kva"],
                "VOORKEUR_BENUTTING": self.v["target_utilization"],
                "MAX_ROUTE_M": self.v["max_route"],
                "UITVOERMAP": str(clustering_dir),
            },
            55,
            98,
            "Kabelverbonden clustering berekenen",
        )

        project = Path(clustering_result.get("QGIS_PROJECT", ""))
        if not project.exists():
            raise QgsProcessingException("De clustering schreef geen geldig QGIS-project")
        if self.v["open_project"]:
            self.progress(99, "QGIS-project openen")
            if not QgsProject.instance().read(str(project)):
                raise QgsProcessingException(
                    "Het resultaat is gereed, maar het QGIS-project kon niet worden geopend"
                )

        self.progress(100, "Volledig LS-netontwerp gereed")
        warning_path = clustering_dir / "clustering_waarschuwingen.json"
        warnings = json.loads(warning_path.read_text(encoding="utf-8")) if warning_path.exists() else []
        state["status"] = "gereed"
        state["warnings"] = warnings
        state["final_project"] = str(project)
        self._write_state(state)
        return {
            "result_dir": str(result_dir),
            "project": str(project),
            "geopackage": clustering_result.get("GEOPACKAGE", ""),
            "pdf": clustering_result.get("CONTROLEKAART_PDF", ""),
            "png": clustering_result.get("CONTROLEKAART", ""),
            "warnings": warnings,
        }

    def recover_project(self, state):
        """Rebuild project/layout from completed outputs without recalculating clusters."""
        output_dir = Path(state["clustering_dir"])
        gpkg = output_dir / "clustering_ontwerp.gpkg"
        if not gpkg.exists() or not (output_dir / "cluster_overzicht.csv").exists():
            raise QgsProcessingException("Er is nog geen berekende clustering om een project van te herstellen.")
        algorithm = self._algorithm("clustering")
        project_runner = ALGORITHM_ROOT / "laagspanning_clustering_lib" / "qgis_project_runner.py"
        manifest = output_dir / "scope_invoer.json"
        if not manifest.exists() and state.get("points_gpkg"):
            scope_context = {
                "points_uri": self._layer(state["points_gpkg"], state.get("points_layer", Path(state["points_gpkg"]).stem)),
                "current_field": state["values"].get("field_design_current", "Hoogste Trafo"),
                "station_csv": state["values"].get("station_names_csv", ""),
                "station_csv_field": state["values"].get("station_name_csv_field", "SourceFile"),
            }
            if state.get("import_gpkg") and state["values"].get("layer_stations"):
                scope_context["stations_uri"] = self._layer(state["import_gpkg"], state["values"]["layer_stations"])
                scope_context["station_field"] = state["values"].get("field_station_name", "Station")
            manifest.write_text(json.dumps(scope_context, ensure_ascii=False, indent=2), encoding="utf-8")
        self.progress(10, "Berekende clustering openen voor projectherstel")
        feedback = StageFeedback(self.progress, 10, 95, "QGIS-project herstellen")
        project_path, _layout_path = algorithm._create_qgis_project_with_retries(project_runner, output_dir, gpkg, feedback)
        state["status"] = "gereed"
        state["final_project"] = str(project_path)
        if state["values"].get("open_project", True):
            if not QgsProject.instance().read(str(project_path)):
                raise QgsProcessingException("Het project is hersteld, maar kon niet worden geopend.")
        self._write_state(state)
        self.progress(100, "QGIS-project en printlayout hersteld")
        return project_path

    def run(self):
        """Backward-compatible uninterrupted run for tests and automation."""
        return self.cluster(self.prepare())

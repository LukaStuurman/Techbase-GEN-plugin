from __future__ import annotations

import json
import os
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path
from queue import Empty, Queue
from threading import Thread

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsFeature,
    QgsLayoutItemMap,
    QgsProcessing,
    QgsProcessingAlgorithm,
    QgsProcessingException,
    QgsProcessingOutputFile,
    QgsProcessingOutputNumber,
    QgsProcessingParameterFolderDestination,
    QgsProcessingParameterNumber,
    QgsProcessingParameterVectorLayer,
    QgsProject,
    QgsVectorDataProvider,
    QgsVectorLayer,
    QgsWkbTypes,
)

from .handmatige_cluster_correctie_tool import HandmatigeClusterCorrectieAlgorithm


class SleufRouteToevoegenAlgorithm(QgsProcessingAlgorithm):
    """Add drawn linework to the persistent noded trench network."""

    SLEUVEN = "SLEUVEN"
    NIEUWE_SLEUF = "NIEUWE_SLEUF"
    AANSLUITINGEN = "AANSLUITINGEN"
    STATIONS = "STATIONS"
    PLANGEBIED = "PLANGEBIED"
    KNOOP_TOLERANTIE_M = "KNOOP_TOLERANTIE_M"
    BACKUPMAP = "BACKUPMAP"
    BACKUP_GPKG = "BACKUP_GPKG"
    RESULTAAT_GPKG = "RESULTAAT_GPKG"
    AANTAL_DELEN = "AANTAL_DELEN"

    def tr(self, text):
        return QCoreApplication.translate("SleufRouteToevoegen", text)

    def createInstance(self):
        return SleufRouteToevoegenAlgorithm()

    def name(self):
        return "sleufroute_toevoegen_en_noden"

    def displayName(self):
        return self.tr("Nieuwe sleufroute toevoegen en netwerk knippen/noden")

    def group(self):
        return self.tr("Netontwerp")

    def groupId(self):
        return "netontwerp"

    def flags(self):
        return super().flags() | QgsProcessingAlgorithm.FlagNoThreading

    def shortHelpString(self):
        return self.tr(
            "Voegt een getekende lijn blijvend toe aan Sleuven geknipt/genood. "
            "Alleen bestaande sleufdelen die de nieuwe lijn raken of binnen de "
            "tolerantie liggen worden opnieuw geknipt/genood; de overige delen "
            "blijven exact behouden. Bij een zeer grote wijziging schakelt de tool "
            "automatisch over op volledig noden. Er wordt eerst een "
            "GeoPackage-back-up gemaakt."
        )

    def initAlgorithm(self, config=None):
        defaults = HandmatigeClusterCorrectieAlgorithm._project_layer_defaults()
        for name, label, geometry_type in (
            (self.SLEUVEN, "Sleuven geknipt/genood", QgsProcessing.TypeVectorLine),
            (self.NIEUWE_SLEUF, "Nieuw getekende sleufroute", QgsProcessing.TypeVectorLine),
            (self.AANSLUITINGEN, "Aansluitingen geclusterd", QgsProcessing.TypeVectorPoint),
            (self.STATIONS, "Stations ontwerp", QgsProcessing.TypeVectorPoint),
        ):
            parameter = QgsProcessingParameterVectorLayer(
                name, self.tr(label), [geometry_type]
            )
            default_key = {
                self.SLEUVEN: HandmatigeClusterCorrectieAlgorithm.SLEUVEN,
                self.AANSLUITINGEN: HandmatigeClusterCorrectieAlgorithm.AANSLUITINGEN,
                self.STATIONS: HandmatigeClusterCorrectieAlgorithm.STATIONS,
            }.get(name)
            if default_key and defaults.get(default_key):
                parameter.setDefaultValue(defaults[default_key])
            self.addParameter(parameter)
        plan_parameter = QgsProcessingParameterVectorLayer(
            self.PLANGEBIED,
            self.tr("Plangebied (optioneel)"),
            [QgsProcessing.TypeVectorPolygon],
            optional=True,
        )
        if defaults.get(HandmatigeClusterCorrectieAlgorithm.PLANGEBIED):
            plan_parameter.setDefaultValue(
                defaults[HandmatigeClusterCorrectieAlgorithm.PLANGEBIED]
            )
        self.addParameter(plan_parameter)
        self.addParameter(
            QgsProcessingParameterNumber(
                self.KNOOP_TOLERANTIE_M,
                self.tr("Tolerantie voor kleine T-aansluitingspleten (m)"),
                type=QgsProcessingParameterNumber.Double,
                defaultValue=1.0,
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
        self.addOutput(QgsProcessingOutputFile(self.BACKUP_GPKG, "Back-up sleuvennet"))
        self.addOutput(QgsProcessingOutputFile(self.RESULTAAT_GPKG, "Resultaatkopie"))
        self.addOutput(QgsProcessingOutputNumber(self.AANTAL_DELEN, "Aantal genode delen"))

    @staticmethod
    def _replace_line_layer(layer, result_path):
        if layer.isEditable():
            raise QgsProcessingException(
                f"Laag '{layer.name()}' staat nog in bewerkingsmodus."
            )
        provider = layer.dataProvider()
        needed = QgsVectorDataProvider.DeleteFeatures | QgsVectorDataProvider.AddFeatures
        if provider.capabilities() & needed != needed:
            raise QgsProcessingException(
                f"Laag '{layer.name()}' kan niet rechtstreeks worden vervangen."
            )
        result = QgsVectorLayer(
            f"{result_path}|layername=sleuven_genood", "genood_resultaat", "ogr"
        )
        if not result.isValid():
            raise QgsProcessingException("Het genode resultaat kan niet worden gelezen.")
        source_fields = {field.name().casefold(): i for i, field in enumerate(result.fields())}
        primary_keys = set(provider.pkAttributeIndexes())
        new_features = []
        for source in result.getFeatures():
            feature = QgsFeature(layer.fields())
            geometry = source.geometry()
            if QgsWkbTypes.isMultiType(layer.wkbType()) and not QgsWkbTypes.isMultiType(geometry.wkbType()):
                geometry.convertToMultiType()
            feature.setGeometry(geometry)
            attributes = []
            for index, field in enumerate(layer.fields()):
                source_index = source_fields.get(field.name().casefold())
                attributes.append(
                    None
                    if index in primary_keys or source_index is None
                    else source.attribute(source_index)
                )
            feature.setAttributes(attributes)
            new_features.append(feature)
        if not layer.startEditing():
            raise QgsProcessingException(f"Bewerken van '{layer.name()}' kon niet starten.")
        try:
            if not layer.deleteFeatures([feature.id() for feature in layer.getFeatures()]):
                raise QgsProcessingException("Oude sleufdelen konden niet worden verwijderd.")
            if new_features and not layer.addFeatures(new_features):
                raise QgsProcessingException("Nieuwe genode sleufdelen konden niet worden toegevoegd.")
            if not layer.commitChanges():
                raise QgsProcessingException("Opslaan van het genode sleuvennet is mislukt.")
        except Exception:
            layer.rollBack()
            raise
        provider.forceReload()
        layer.updateExtents()
        layer.triggerRepaint()

    def processAlgorithm(self, parameters, context, feedback):
        layers = {
            "sleuven": self.parameterAsVectorLayer(parameters, self.SLEUVEN, context),
            "nieuwe_sleuf": self.parameterAsVectorLayer(parameters, self.NIEUWE_SLEUF, context),
            "aansluitingen": self.parameterAsVectorLayer(parameters, self.AANSLUITINGEN, context),
            "stations": self.parameterAsVectorLayer(parameters, self.STATIONS, context),
            "plangebied": self.parameterAsVectorLayer(parameters, self.PLANGEBIED, context),
        }
        required = ("sleuven", "nieuwe_sleuf", "aansluitingen", "stations")
        if any(layers[name] is None or not layers[name].isValid() for name in required):
            raise QgsProcessingException("Een of meer verplichte netwerklagen zijn ongeldig.")
        if any(not layers[name].crs().isValid() for name in required):
            raise QgsProcessingException("Alle netwerklagen moeten een geldige CRS hebben.")
        if layers["nieuwe_sleuf"].featureCount() < 1:
            raise QgsProcessingException("De nieuw getekende sleuflaag is leeg.")
        if layers["sleuven"].isEditable():
            raise QgsProcessingException("Sla open bewerkingen in de sleuvenlaag eerst op.")

        output_folder = Path(self.parameterAsString(parameters, self.BACKUPMAP, context))
        output_folder.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
        backup_path = output_folder / f"sleuven_backup_{stamp}.gpkg"
        result_path = output_folder / f"sleuven_genood_{stamp}.gpkg"
        with tempfile.TemporaryDirectory(prefix="qgis_sleufroute_") as temporary:
            temporary_path = Path(temporary)
            snapshots = {}
            snapshot_path = temporary_path / "rekeninvoer.gpkg"
            for name, layer in layers.items():
                if layer is None:
                    continue
                HandmatigeClusterCorrectieAlgorithm._write_layer_snapshot(
                    layer, snapshot_path, name, context
                )
                snapshots[name] = {
                    "path": str(snapshot_path),
                    "layer": name,
                }
            summary_path = temporary_path / "samenvatting.json"
            config_path = temporary_path / "opdracht.json"
            config_path.write_text(
                json.dumps(
                    {
                        "inputs": snapshots,
                        "node_tolerance_m": self.parameterAsDouble(
                            parameters, self.KNOOP_TOLERANTIE_M, context
                        ),
                        "backup_path": str(backup_path),
                        "result_path": str(result_path),
                        "summary_path": str(summary_path),
                    },
                    ensure_ascii=False,
                    indent=2,
                ),
                encoding="utf-8",
            )
            runner = (
                Path(__file__).resolve().parent
                / "laagspanning_clustering_lib"
                / "netwerk_onderhoud_runner.py"
            )
            command = [
                *HandmatigeClusterCorrectieAlgorithm._python_command(),
                "-u",
                str(runner),
                str(config_path),
            ]
            process = subprocess.Popen(
                command,
                stdout=subprocess.PIPE,
                stderr=subprocess.PIPE,
                text=True,
                encoding="utf-8",
                errors="replace",
                creationflags=(subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0),
            )
            queue = Queue()
            errors = []

            def drain(stream, channel):
                try:
                    for line in iter(stream.readline, ""):
                        queue.put((channel, line.rstrip()))
                finally:
                    stream.close()

            threads = [
                Thread(target=drain, args=(process.stdout, "out"), daemon=True),
                Thread(target=drain, args=(process.stderr, "err"), daemon=True),
            ]
            for thread in threads:
                thread.start()
            while process.poll() is None:
                while True:
                    try:
                        channel, line = queue.get_nowait()
                    except Empty:
                        break
                    if line:
                        (errors.append(line) if channel == "err" else feedback.pushInfo(line))
                if feedback.isCanceled():
                    process.terminate()
                    raise QgsProcessingException("Sleufbewerking geannuleerd.")
                QCoreApplication.processEvents()
                try:
                    process.wait(timeout=0.1)
                except subprocess.TimeoutExpired:
                    pass
            for thread in threads:
                thread.join(timeout=2.0)
            while True:
                try:
                    channel, line = queue.get_nowait()
                except Empty:
                    break
                if line:
                    (errors.append(line) if channel == "err" else feedback.pushInfo(line))
            if process.returncode != 0 or not summary_path.exists():
                raise QgsProcessingException(
                    "Nieuwe sleuf kon niet worden genood: "
                    + (errors[-1] if errors else f"rekenprocescode {process.returncode}")
                )
            summary = json.loads(summary_path.read_text(encoding="utf-8"))

        self._replace_line_layer(layers["sleuven"], result_path)
        project = QgsProject.instance()
        for layout in project.layoutManager().printLayouts():
            for item in layout.items():
                if isinstance(item, QgsLayoutItemMap):
                    item.refresh()
            layout.refresh()
        project.setDirty(True)
        feedback.setProgress(100)
        if summary.get("used_local_noding", False):
            feedback.pushInfo(
                "Snelle lokale netwerkupdate gebruikt: alleen "
                f"{int(summary.get('affected_existing_parts', 0)):,} geraakt(e) "
                "bestaand(e) sleufdeel/delen zijn opnieuw genood."
            )
        feedback.pushInfo(
            f"Nieuwe sleuf verwerkt; netwerk bevat {summary['noded_part_count']:,} genode delen."
        )
        return {
            self.BACKUP_GPKG: str(backup_path),
            self.RESULTAAT_GPKG: str(result_path),
            self.AANTAL_DELEN: int(summary["noded_part_count"]),
        }

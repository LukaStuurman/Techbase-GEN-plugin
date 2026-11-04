"""UI-side batch I/O. Calculations run on snapshots, never live QGIS layers."""
import json
import subprocess
import tempfile
from datetime import datetime
from pathlib import Path

from qgis.PyQt.QtCore import QCoreApplication
from qgis.core import (
    QgsFeature, QgsFields, QgsGeometry, QgsProcessingContext, QgsProject,
    QgsTransaction, QgsVectorLayer, QgsWkbTypes,
)

from .algorithms.handmatige_cluster_correctie_tool import HandmatigeClusterCorrectieAlgorithm
from .algorithms.laagspanning_clustering_tool import LaagspanningClusteringAlgorithm

NAMES = {"connections": "aansluitingen_geclusterd", "stations": "stations_ontwerp",
         "areas": "clustergebieden", "routes": "cluster_kabelroutes", "cables": "sleuven_genood"}
RULES_PROPERTY = "LSNetontwerp/station_rules"


def station_rules():
    project = QgsProject.instance()
    try:
        value, _ = project.readEntry("LSNetontwerp", "station_rules", "{}")
        result = json.loads(value)
        if result:
            return result
        filename, _ = project.readEntry("LSNetontwerp", "state_file", "")
        if filename and Path(filename).exists():
            return json.loads(Path(filename).read_text(encoding="utf-8")).get("station_rules", {})
    except (ValueError, TypeError, OSError):
        pass
    return {}


def save_station_rules(rules):
    project = QgsProject.instance()
    project.writeEntry("LSNetontwerp", "station_rules", json.dumps(rules, ensure_ascii=False))
    filename, _ = project.readEntry("LSNetontwerp", "state_file", "")
    if filename and Path(filename).exists():
        data = json.loads(Path(filename).read_text(encoding="utf-8"))
        data["station_rules"] = rules
        Path(filename).write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
    project.setDirty(True)


def apply_snapshot(layers, path):
    """Apply the four tables in one SQLite transaction, retaining original FIDs.

    QGIS' OGR provider does not expose a shared QgsTransaction for GeoPackage.
    The database transaction provides rollback across all dependent tables.
    """
    import sqlite3
    import struct

    keys = ("connections", "stations", "areas", "routes")
    if any(layers[key].isEditable() for key in keys):
        raise ValueError("Sla bestaande laagbewerkingen eerst op.")
    paths = {str(Path(layers[key].source().split("|", 1)[0]).resolve()).casefold() for key in keys}
    if len(paths) != 1 or not next(iter(paths)).endswith(".gpkg"):
        raise ValueError("Gebruik de resultaatlagen uit hetzelfde cluster-GeoPackage.")
    database = layers["connections"].source().split("|", 1)[0]
    tables = {}
    for key in keys:
        parts = layers[key].source().split("|")
        tables[key] = next((part.split("=",1)[1] for part in parts if part.startswith("layername=")), NAMES[key])
        layers[key].dataProvider().forceReload()

    def quote(name):
        return '"' + str(name).replace('"', '""') + '"'

    def geometry(blob):
        if blob is None:
            return QgsGeometry()
        data = bytes(blob)
        if data[:2] == b"GP":
            envelope = (data[3] >> 1) & 7
            count = {0: 0, 1: 4, 2: 6, 3: 6, 4: 8}.get(envelope)
            if count is None:
                raise ValueError("Ongeldige GeoPackage-geometrie.")
            data = data[8+8*count:]
        result = QgsGeometry()
        result.fromWkb(data)
        return result

    connection = sqlite3.connect(database, timeout=20)
    try:
        # Spatial index triggers use these standard GeoPackage functions.
        connection.create_function("ST_IsEmpty", 1, lambda blob: int(blob is None or geometry(blob).isEmpty()))
        for name, getter in (("ST_MinX", "xMinimum"), ("ST_MaxX", "xMaximum"),
                             ("ST_MinY", "yMinimum"), ("ST_MaxY", "yMaximum")):
            connection.create_function(name, 1, lambda blob, getter=getter: None if blob is None else getattr(geometry(blob).boundingBox(), getter)())
        connection.create_function("ST_SRID", 1, lambda blob: struct.unpack("<i" if bytes(blob)[3]&1 else ">i", bytes(blob)[4:8])[0] if blob else None)
        connection.execute("ATTACH DATABASE ? AS batch", (str(Path(path).resolve()),))
        connection.execute("BEGIN IMMEDIATE")
        for key in keys:
            table = tables[key]
            source = NAMES[key]
            target_columns = connection.execute(f"PRAGMA main.table_info({quote(table)})").fetchall()
            source_columns = {row[1] for row in connection.execute(f"PRAGMA batch.table_info({quote(source)})")}
            primary = [row[1] for row in target_columns if row[5]]
            if len(primary) != 1 or "Bron_FID" not in source_columns:
                raise ValueError(f"De oorspronkelijke objectnummers ontbreken in {source}.")
            primary = primary[0]
            target_geometry = connection.execute("SELECT column_name,srs_id FROM main.gpkg_geometry_columns WHERE table_name=?", (table,)).fetchone()
            source_geometry = connection.execute("SELECT column_name,srs_id FROM batch.gpkg_geometry_columns WHERE table_name=?", (source,)).fetchone()
            if not target_geometry or not source_geometry or target_geometry[1] != source_geometry[1]:
                raise ValueError(f"Het coördinatenstelsel van {source} is veranderd.")
            columns = [(row[1], row[1]) for row in target_columns if row[1] != primary and row[1] in source_columns and row[1] != target_geometry[0]]
            columns.append((target_geometry[0], source_geometry[0]))
            target_sql = 'main.'+quote(table)
            source_sql = 'batch.'+quote(source)
            connection.execute(f"DELETE FROM {target_sql} WHERE {quote(primary)} NOT IN (SELECT Bron_FID FROM {source_sql})")
            updates = ','.join(f'{quote(target)}=s.{quote(origin)}' for target,origin in columns)
            changed = ' OR '.join(f't.{quote(target)} IS NOT s.{quote(origin)}' for target,origin in columns)
            connection.execute(f"UPDATE {target_sql} AS t SET {updates} FROM {source_sql} AS s WHERE t.{quote(primary)}=s.Bron_FID AND ({changed})")
            target_fields = ','.join([quote(primary), *(quote(target) for target,_ in columns)])
            source_fields = ','.join(['s.Bron_FID', *(f's.{quote(origin)}' for _,origin in columns)])
            connection.execute(f"INSERT INTO {target_sql} ({target_fields}) SELECT {source_fields} FROM {source_sql} AS s WHERE NOT EXISTS (SELECT 1 FROM {target_sql} AS t WHERE t.{quote(primary)}=s.Bron_FID)")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.close()
        for key in keys:
            layer = layers[key]
            layer.dataProvider().forceReload()
            layer.updateExtents()
            layer.triggerRepaint()


def run_batch(layers, operations, directory, maximum_route, preview, feedback, rules=None):
    from .cluster_management import fingerprint
    if not operations:
        raise ValueError("De wachtrij is leeg.")
    if any(layer.isEditable() for layer in layers.values() if layer is not None):
        raise ValueError("Sla bestaande bewerkingen in de invoerlagen eerst op.")
    before = fingerprint(layers)
    directory = Path(directory)
    directory.mkdir(parents=True, exist_ok=True)
    token = datetime.now().strftime("%Y%m%d_%H%M%S_%f")
    backup = directory / f"sessie_backup_{token}.gpkg"
    result = directory / f"sessie_resultaat_{token}.gpkg"
    with tempfile.TemporaryDirectory(prefix="ls_cluster_sessie_") as temp:
        temp = Path(temp)
        snapshot = temp / "invoer.gpkg"
        inputs = {}
        context = QgsProcessingContext()
        context.setProject(QgsProject.instance())
        for name, layer in layers.items():
            if layer is None:
                continue
            HandmatigeClusterCorrectieAlgorithm._write_layer_snapshot(layer, snapshot, name, context)
            inputs[name] = {"path": str(snapshot), "layer": name}
        config = {"inputs": inputs, "operations": operations, "max_route_m": maximum_route,
                  "preview": preview, "station_rules": rules or {}, "backup_path": str(backup),
                  "result_path": str(result), "summary_path": str(temp / "summary.json")}
        config_path = temp / "opdracht.json"
        config_path.write_text(json.dumps(config, ensure_ascii=False), encoding="utf-8")
        runner = Path(__file__).parent / "algorithms/laagspanning_clustering_lib/batch_correction_runner.py"
        with (temp / "proces.log").open("w", encoding="utf-8") as log:
            process = subprocess.Popen(
                [*LaagspanningClusteringAlgorithm._qgis_python_command(), "-u", str(runner), str(config_path)],
                env=LaagspanningClusteringAlgorithm._qgis_python_environment(),
                stdout=log, stderr=log,
                creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0),
            )
            try:
                while process.poll() is None:
                    QCoreApplication.processEvents()
                    if feedback.isCanceled():
                        process.terminate()
                        try:
                            process.wait(timeout=5)
                        except subprocess.TimeoutExpired:
                            process.kill()
                            process.wait()
                        raise ValueError("Bewerking geannuleerd; het ontwerp is niet gewijzigd.")
                    try:
                        process.wait(timeout=.05)
                    except subprocess.TimeoutExpired:
                        pass
            finally:
                if process.poll() is None:
                    process.kill()
                    process.wait()
        text = (temp / "proces.log").read_text(encoding="utf-8", errors="replace")
        persistent_log = directory / f"sessie_{token}.log"
        persistent_log.write_text(text, encoding="utf-8")
        if process.returncode != 0 or not Path(config["summary_path"]).exists():
            lines = text.strip().splitlines()
            raise ValueError((lines[-1] if lines else "Het rekenproces stopte onverwacht.") + f" Log: {persistent_log}")
        summary = json.loads(Path(config["summary_path"]).read_text(encoding="utf-8"))
    if not preview:
        if feedback.isCanceled():
            raise ValueError("Bewerking geannuleerd; het ontwerp is niet gewijzigd.")
        if fingerprint(layers) != before:
            raise ValueError("Het ontwerp is tijdens de berekening aangepast. Het resultaat is niet toegepast.")
        if rules is not None and rules != station_rules():
            raise ValueError("De stationskeuzes zijn tijdens de berekening aangepast. Het resultaat is niet toegepast.")
        apply_snapshot(layers, result)
    return summary, str(backup), str(result)

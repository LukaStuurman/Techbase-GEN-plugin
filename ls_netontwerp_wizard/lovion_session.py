"""Persistent station queue and reversible Master Asset ID assignments."""
import copy
import csv
import json
from pathlib import Path
import re
import uuid

from qgis.core import QgsCoordinateTransform, QgsFeatureRequest, QgsGeometry, QgsProject, QgsVariantUtils

from .connection_sources import _begin, _ensure_fields, text_value
from .station_name_csv import normalize_asset_id, find_master_asset_id_column
from .station_symbology import color_connections_by_station

STATE_KEY = "LSNetontwerp/lovion_extraction"
DONE = {"done", "planned"}


def station_numbers(text):
    values, seen = [], set()
    for part in re.split(r"[,;\t\r\n]+", str(text)):
        value = part.strip()
        if not value:
            continue
        if any(char in value for char in '\\/:*?"<>|'):
            raise ValueError(f"Ongeldig stationsnummer: {value}")
        if value.casefold() not in seen:
            seen.add(value.casefold())
            values.append(value)
    return values


def selected_station_numbers(layer, field):
    if layer is None or layer.fields().lookupField(field) < 0:
        raise ValueError("Kies de stationslaag en de kolom met stationsnummers.")
    features = list(layer.selectedFeatures())
    if not features:
        raise ValueError("Selecteer eerst stations op de kaart.")
    return station_numbers("\n".join(text_value(feature, field) for feature in features))


def stations_in_plan(stations, field, plan):
    if stations is None or plan is None or stations.fields().lookupField(field) < 0:
        raise ValueError("Kies een stationslaag, stationsnummerkolom en plangebied.")
    areas = list(plan.selectedFeatures()) or list(plan.getFeatures())
    if not areas:
        raise ValueError("Het plangebied bevat geen objecten.")
    transform = QgsCoordinateTransform(plan.crs(), stations.crs(), QgsProject.instance())
    ids = set()
    for area in areas:
        if not area.hasGeometry():
            continue
        geometry = QgsGeometry(area.geometry())
        geometry.transform(transform)
        for station in stations.getFeatures(QgsFeatureRequest().setFilterRect(geometry.boundingBox())):
            if station.hasGeometry() and geometry.intersects(station.geometry()):
                ids.add(station.id())
    stations.selectByIds(sorted(ids))
    if not ids:
        return []
    return selected_station_numbers(stations, field)


def verified_report(report_path, requested):
    """Only accept complete transformer sets whose CSV counts and identity agree."""
    path = Path(report_path)
    report = json.loads(path.read_text(encoding="utf-8-sig"))
    if set(report.get("RequestedStations", [])) != set(requested):
        raise ValueError("Het LOVION-resultaat hoort niet bij deze stationsronde.")
    rows = []
    if path.with_suffix(".csv").exists():
        with path.with_suffix(".csv").open(encoding="utf-8-sig", newline="") as handle:
            rows = list(csv.DictReader(handle))
    groups, offset = {}, 0
    for record in report.get("Records", []):
        station = record["Station"]
        if station not in requested:
            raise ValueError("Het LOVION-rapport bevat een niet-aangevraagd station.")
        count = int(record["ImportedCount"])
        if count < 0 or count != int(record["ExpectedCount"]):
            raise ValueError(f"De aantallen voor station {station} zijn niet geverifieerd.")
        batch = rows[offset:offset + count]
        offset += count
        if len(batch) != count or any(row.get("SourceFile") != station for row in batch):
            raise ValueError("De LOVION-export en het stationsrapport komen niet overeen.")
        outcome = record.get("Outcome")
        if outcome == "planned":
            if count or record.get("Status") != "gepland":
                raise ValueError("Een geplande trafo bevat ongeldige aansluitingen.")
        elif outcome != "imported" or record.get("Status") != "in bedrijf":
            raise ValueError("Een trafostatus is niet geverifieerd.")
        ids = []
        for row in batch:
            column = find_master_asset_id_column(list(row))
            asset = normalize_asset_id(row.get(column, ""))
            if not asset:
                raise ValueError("Een LOVION-aansluiting mist Master Asset ID.")
            ids.append(asset)
        if len(set(ids)) != len(ids):
            raise ValueError("Een LOVION-batch bevat dubbele aansluitingen.")
        groups.setdefault(station, []).append((record, ids))
    if len(rows) != int(report.get("ImportedRows", -1)) or len(rows) < offset:
        raise ValueError("De LOVION-export is onvolledig.")
    result = {}
    manual = set(report.get("ManualStations", []))
    for station in requested:
        records = groups.get(station, [])
        counts = {int(record["TransformerCount"]) for record, _ in records}
        indexes = [int(record["Transformer"]) for record, _ in records]
        complete = (len(counts) == 1 and next(iter(counts), 0) > 0
                    and sorted(indexes) == list(range(1, next(iter(counts), 0) + 1)))
        if station in manual:
            state = "manual"
        elif complete:
            state = "done" if any(record["Outcome"] == "imported" for record, _ in records) else "planned"
        else:
            state = "error" if report.get("Error") else "pending"
        assets = sorted({asset for _, ids in records for asset in ids}) if state in DONE else []
        result[station] = {"status": state, "assets": assets, "rows": sum(len(ids) for _, ids in records),
                           "note": report.get("Error", "") if state == "error" else "",
                           "planned": sum(record["Outcome"] == "planned" for record, _ in records)}
    return result


class LovionSession:
    def __init__(self, layer):
        if layer is None or not layer.isValid():
            raise ValueError("Kies een geldige ontwerpstroomlaag.")
        self.layer = layer
        try:
            self.data = json.loads(str(layer.customProperty(STATE_KEY, "{}")))
        except (ValueError, TypeError):
            self.data = {}
        if (not isinstance(self.data, dict) or self.data.get("version") != 1
                or not isinstance(self.data.get("stations"), dict)
                or not isinstance(self.data.get("assignments"), dict)):
            self.data = {"version": 1, "id": uuid.uuid4().hex, "stations": {}, "assignments": {}}

    def save(self):
        self.layer.setCustomProperty(STATE_KEY, json.dumps(self.data))
        project = QgsProject.instance()
        project.setDirty(True)
        if project.fileName():
            project.write()

    def add(self, numbers):
        existing = {key.casefold() for key in self.data["stations"]}
        count = 0
        for number in numbers:
            if number.casefold() not in existing:
                self.data["stations"][number] = {"status": "pending", "assets": [], "rows": 0, "matched": 0}
                existing.add(number.casefold())
                count += 1
        self.save()
        return count

    def pending(self):
        return [number for number, entry in self.data["stations"].items() if entry["status"] not in DONE]

    def apply_report(self, path, requested):
        data = copy.deepcopy(self.data)
        result = verified_report(path, requested)
        for number, entry in result.items():
            if number not in data["stations"]:
                raise ValueError("De stationslijst is gewijzigd tijdens de ronde.")
            # A failed retry does not discard previously verified assignments.
            if entry["status"] not in DONE:
                entry["assets"] = data["stations"][number].get("assets", [])
            data["stations"][number].update(entry)
        data["last_report"] = str(path)
        self._apply(data, {number for number, entry in result.items() if entry["status"] in DONE})
        return result

    def remove(self, numbers):
        data = copy.deepcopy(self.data)
        for number in numbers:
            data["stations"].pop(number, None)
        self._apply(data)

    def retry(self, numbers):
        for number in numbers:
            self.data["stations"][number]["status"] = "pending"
        self.save()

    def reset(self):
        data = copy.deepcopy(self.data)
        data["stations"] = {}
        data["id"] = uuid.uuid4().hex
        data.pop("last_report", None)
        self._apply(data)

    def _apply(self, data, refresh_stations=()):
        if self.layer.isEditable():
            raise ValueError("Sla de laagbewerkingen eerst op voordat je de stationskoppeling wijzigt.")
        lookup = {}
        for station, entry in data["stations"].items():
            for asset in entry.get("assets", []):
                if asset in lookup and lookup[asset] != station:
                    raise ValueError(f"Master Asset ID {asset} is bij {lookup[asset]} én {station} gevonden. Verwijder de onjuiste stationskeuze.")
                lookup[asset] = station
        key = find_master_asset_id_column([field.name() for field in self.layer.fields()])
        if key is None:
            raise ValueError("De ontwerpstroomlaag mist Master Asset ID.")
        previous = data["assignments"]
        changes, assignments = {}, {}
        matched = {number: 0 for number in data["stations"]}
        for feature in self.layer.getFeatures():
            asset = normalize_asset_id(feature[key])
            fid = str(feature.id())
            old = previous.get(fid)
            if old and old["asset"] != asset:
                old = None
            station = lookup.get(asset)
            current = feature["Station"] if feature.fields().lookupField("Station") >= 0 else None
            current = None if QgsVariantUtils.isNull(current) else str(current)
            if station is not None:
                if old and old["assigned"] == station and current != station and station not in refresh_stations:
                    # Queue operations and unrelated rounds preserve a user's
                    # manual reassignment. An explicit retry can replace it.
                    assignments[fid] = old
                    continue
                original = old["original"] if old and current == old["assigned"] else current
                assignments[fid] = {"asset": asset, "original": original, "assigned": station}
                changes[feature.id()] = station
                matched[station] += 1
            elif old and current == old["assigned"]:
                changes[feature.id()] = old["original"]
        if changes:
            _begin(self.layer)
            try:
                _ensure_fields(self.layer, ["Station"])
                index = self.layer.fields().lookupField("Station")
                for fid, value in changes.items():
                    if not self.layer.changeAttributeValue(fid, index, value):
                        raise ValueError("De stationskoppeling kon niet worden opgeslagen.")
                if not self.layer.commitChanges():
                    raise ValueError("De stationskoppeling kon niet worden opgeslagen.")
            except Exception:
                self.layer.rollBack()
                raise
        for station in data["stations"]:
            data["stations"][station]["matched"] = matched[station]
        data["assignments"] = assignments
        self.data = data
        if self.layer.fields().lookupField("Station") >= 0:
            color_connections_by_station(self.layer)
        self.layer.triggerRepaint()
        self.save()
